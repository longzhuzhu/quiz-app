"""解析接口契约端到端验收：真实 API + 真实 worker + 隔离 PostgreSQL。

只替换上游模型 HTTP，其余链路（认证、任务入队、worker 领取、槽位限流、
结果落库、接口读取）全部真实执行。用于锁定本次三项变更的对外契约：

    AC-1  /api/ai/explanations 不再返回 has_legacy_explanation。
    AC-2  单次模型调用收到 120s 超时（配置默认值），而非旧默认 60s。
    AC-3  解析任务领取后的租约覆盖两次 120s 调用的最坏耗时。
    AC-4  多模型并行执行，峰值并发可超过旧的全站上限 3。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.routes import ai, settings as settings_routes  # noqa: E402
from app.core.config import settings as runtime_settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import Exam, Question, QuestionBank, User  # noqa: E402
from app.services.settings_service import set_encrypted_ai_api_key, set_key  # noqa: E402
from app.workers import job_worker  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402

MODELS = ["model-a", "model-b", "model-c", "model-d"]


@pytest.fixture(scope="module")
def postgres():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def api(postgres, monkeypatch):
    monkeypatch.setattr(runtime_settings, "JWT_SECRET_KEY", "verify-jwt")
    monkeypatch.setattr(runtime_settings, "SECRET_KEY", "verify-encryption")
    monkeypatch.setattr(runtime_settings, "SYSTEM_SETTINGS_ENCRYPTION_KEY", None)
    with postgres.begin() as connection:
        names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        owner = User(username="verify-owner", email="verify@example.invalid", password_hash="unused", is_admin=True)
        db.add(owner)
        db.flush()
        exam = Exam(owner_id=owner.id, slug="verify", name="Verify", short_name="Verify")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Verify Bank")
        db.add(bank)
        db.flush()
        questions = [
            Question(
                bank_id=bank.id, question_type="single", order_index=n,
                content=f"Which control is MOST effective? {n}",
                options=[{"key": key, "text": f"Option {key}"} for key in "ABCD"],
                correct_answer="D",
            ) for n in range(3)
        ]
        db.add_all(questions)
        db.flush()
        set_key(db, "ai_api_base_url", "https://8.8.8.8")
        set_encrypted_ai_api_key(db, "verify-token")
        set_key(db, "ai_explain_models", json.dumps([{"model_id": m, "reasoning_effort": None} for m in MODELS]))
        db.commit()
        owner_id = owner.id
        question_ids = [q.id for q in questions]

    app = FastAPI()
    app.include_router(ai.router, prefix="/api/ai")
    app.include_router(settings_routes.router, prefix="/api/settings")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(job_worker, "SessionLocal", sessions)
    with TestClient(app, headers={
        "Authorization": f"Bearer {create_access_token(str(owner_id))}",
        "X-Exam-Slug": "verify",
    }) as client:
        yield type("Api", (), {
            "client": client, "sessions": sessions, "ids": question_ids,
        })


def _analysis(answer: str) -> dict:
    return {
        "judged_answer": answer,
        "stem_breakdown": {
            "qualifier": "MOST", "role": "隐私工程师", "scenario": "比较数据保护措施",
            "constraint": "选择最有效的措施", "asked": "哪项措施最有效",
        },
        "explanation": "The measure reduces exposure across the whole lifecycle.",
        "explanation_zh": "该措施在整个数据生命周期内减少暴露面。它同时覆盖了存储和传输两个环节。",
        "distractors": [
            {"key": key, "type": "范围过窄", "reason": "只覆盖数据处理的单个环节，无法满足题干整体限制"}
            for key in "ABC"
        ],
    }


# ─── AC-1 ────────────────────────────────────────────────────────────


def test_explanations_response_has_no_legacy_field(api):
    """历史解析展示移除后，接口不再暴露 has_legacy_explanation。"""
    payload = api.client.get("/api/ai/explanations", params={"question_id": api.ids[0]}).json()
    assert "has_legacy_explanation" not in payload
    # 其余契约保持不变
    assert set(payload) == {"question_id", "correct_answer", "input_fingerprint", "models"}
    assert [m["model_id"] for m in payload["models"]] == MODELS


# ─── AC-2 / AC-3 / AC-4 ──────────────────────────────────────────────


def test_explanation_calls_use_configured_timeout_and_parallelism(api, monkeypatch):
    """真实 worker 执行：超时取配置值、并发突破旧上限、租约覆盖最坏耗时。"""
    observed = {"timeouts": [], "active": 0, "peak": 0, "lease_until": None}
    lock = threading.Lock()

    def model_http(url, *, json: dict, **kwargs):
        with lock:
            observed["timeouts"].append(kwargs.get("timeout"))
            observed["active"] += 1
            observed["peak"] = max(observed["peak"], observed["active"])
        try:
            time.sleep(0.3)
            content = json_module.dumps(_analysis("D"), ensure_ascii=False)
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        finally:
            with lock:
                observed["active"] -= 1

    json_module = json
    monkeypatch.setattr(httpx, "post", model_http)

    qid = api.ids[0]
    for model_id in MODELS:
        assert api.client.post("/api/ai/explain", json={"question_id": qid, "model_id": model_id}).status_code == 202

    # 租约只在任务 running 期间存在，完成即被置空；须在消费过程中采样。
    stop_sampling = threading.Event()

    def sample_lease():
        while not stop_sampling.is_set():
            with api.sessions() as db:
                row = db.execute(text(
                    "SELECT lease_until, heartbeat_at FROM background_jobs "
                    "WHERE job_type='ai_explanation' AND status='running' ORDER BY id LIMIT 1"
                )).first()
            if row is not None:
                with lock:
                    observed["lease_until"] = row[0]
                    observed["claimed_anchor"] = row[1]
                return
            time.sleep(0.02)

    claimed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # 真实 worker 用多个线程消费；单线程循环只能串行执行，测不出并发。
    def drain():
        while job_worker.process_one_job():
            pass

    sampler = threading.Thread(target=sample_lease, daemon=True)
    sampler.start()
    threads = [threading.Thread(target=drain) for _ in range(len(MODELS))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    stop_sampling.set()
    sampler.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads), "worker 线程未在期限内结束"

    payload = api.client.get("/api/ai/explanations", params={"question_id": qid}).json()
    assert all(m["result"] is not None for m in payload["models"]), "全部模型应完成解析"

    # AC-2：每次调用都使用配置的 120s，而非 call_ai_api 的 60s 默认值
    assert observed["timeouts"], "未观察到任何模型调用"
    assert set(observed["timeouts"]) == {runtime_settings.AI_EXPLANATION_TIMEOUT_SECONDS}
    assert runtime_settings.AI_EXPLANATION_TIMEOUT_SECONDS == 120.0

    # AC-4：并发峰值超过旧的全站槽位上限 3
    assert observed["peak"] > 3, f"峰值并发仅 {observed['peak']}，未突破旧上限 3"

    # AC-3：领取时写入的租约覆盖「超时 × 2」的最坏耗时
    assert observed["lease_until"] is not None, "未采样到运行中任务的租约"
    anchor = observed.get("claimed_anchor") or claimed_at
    worst_case = 2 * runtime_settings.AI_EXPLANATION_TIMEOUT_SECONDS
    lease_seconds = (observed["lease_until"] - anchor).total_seconds()
    assert lease_seconds > worst_case, (
        f"租约 {lease_seconds:.0f}s 未覆盖最坏耗时 {worst_case:.0f}s，任务会被误判中断"
    )
