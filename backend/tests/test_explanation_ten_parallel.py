"""10 并发实测：验证槽位、线程与连接池在满载配置下协同工作。

与契约测试不同，这里把 10 个解析任务同时排入队列，用 10 个 worker 线程消费，
观测真实峰值并发是否达到满载值。这是「支持 10 并发」的直接证据。

覆盖：
    TC-1  10 个解析任务并行执行，峰值并发达到 10（而非受旧上限 3 限制）。
    TC-2  满载 10 并发时连接池不耗尽，所有任务成功完成。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.routes import ai  # noqa: E402
from app.core.config import settings as runtime_settings  # noqa: E402
from app.core.database import Base, engine as shared_engine, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import Exam, Question, QuestionBank, User  # noqa: E402
from app.services.settings_service import set_encrypted_ai_api_key, set_key  # noqa: E402
from app.workers import job_worker  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402

PARALLEL = 10
# 单题模型列表上限为 5（schemas/settings.py:39），因此用 2 道题 × 5 个模型
# 才能填满 10 个槽位 —— 这正是 10 并发的真实场景：多题（或多用户）同时在途。
MODELS = [f"model-{n}" for n in range(1, 6)]
QUESTIONS = 2


@pytest.fixture(scope="module")
def postgres():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def api(postgres, monkeypatch):
    monkeypatch.setattr(runtime_settings, "JWT_SECRET_KEY", "ten-parallel-jwt")
    monkeypatch.setattr(runtime_settings, "SECRET_KEY", "ten-parallel-encryption")
    monkeypatch.setattr(runtime_settings, "SYSTEM_SETTINGS_ENCRYPTION_KEY", None)
    # 满载配置：10 个槽位
    monkeypatch.setattr(runtime_settings, "AI_EXPLANATION_CONCURRENCY", PARALLEL)
    with postgres.begin() as connection:
        names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    sessions = sessionmaker(bind=postgres)
    with sessions() as db:
        owner = User(username="ten-parallel-owner", email="ten@example.invalid", password_hash="unused", is_admin=True)
        db.add(owner)
        db.flush()
        exam = Exam(owner_id=owner.id, slug="ten", name="Ten", short_name="Ten")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Ten Bank")
        db.add(bank)
        db.flush()
        questions = [
            Question(
                bank_id=bank.id, question_type="single", order_index=n,
                content=f"Which control is MOST effective? {n}",
                options=[{"key": key, "text": f"Option {key}"} for key in "ABCD"],
                correct_answer="D",
            ) for n in range(QUESTIONS)
        ]
        db.add_all(questions)
        db.flush()
        set_key(db, "ai_api_base_url", "https://8.8.8.8")
        set_encrypted_ai_api_key(db, "ten-parallel-token")
        set_key(db, "ai_explain_models", json.dumps([{"model_id": m, "reasoning_effort": None} for m in MODELS]))
        db.commit()
        owner_id = owner.id
        question_ids = [q.id for q in questions]

    app = FastAPI()
    app.include_router(ai.router, prefix="/api/ai")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(job_worker, "SessionLocal", sessions)
    with TestClient(app, headers={
        "Authorization": f"Bearer {create_access_token(str(owner_id))}",
        "X-Exam-Slug": "ten",
    }) as client:
        yield type("Api", (), {"client": client, "sessions": sessions, "qids": question_ids})


def _analysis() -> str:
    return json.dumps({
        "judged_answer": "D",
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
    }, ensure_ascii=False)


def test_ten_explanations_run_in_parallel_without_pool_exhaustion(api, monkeypatch):
    """10 个解析任务并发执行，峰值达到 10 且全部成功。"""
    observed = {"active": 0, "peak": 0, "completed": 0, "errors": []}
    lock = threading.Lock()

    def model_http(url, *, json: dict, **kwargs):
        with lock:
            observed["active"] += 1
            observed["peak"] = max(observed["peak"], observed["active"])
        try:
            # 保持足够长的重叠窗口，使 10 个任务能同时在途。
            time.sleep(0.8)
            with lock:
                observed["completed"] += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": _analysis()}}]})
        finally:
            with lock:
                observed["active"] -= 1

    monkeypatch.setattr(httpx, "post", model_http)

    for question_id in api.qids:
        for model_id in MODELS:
            response = api.client.post("/api/ai/explain", json={"question_id": question_id, "model_id": model_id})
            assert response.status_code == 202, response.text

    def drain():
        try:
            while job_worker.process_one_job():
                pass
        except Exception as exc:  # 连接池耗尽会在此暴露
            with lock:
                observed["errors"].append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=drain) for _ in range(PARALLEL)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "worker 线程未在期限内结束"

    # TC-2：无连接池耗尽或槽位争用异常
    assert not observed["errors"], f"并发执行出现异常：{observed['errors']}"
    assert observed["completed"] == PARALLEL, f"仅 {observed['completed']}/{PARALLEL} 个模型完成调用"

    # TC-1：峰值并发达到满载值
    assert observed["peak"] == PARALLEL, f"峰值并发 {observed['peak']}，未达到 {PARALLEL}"

    for question_id in api.qids:
        payload = api.client.get("/api/ai/explanations", params={"question_id": question_id}).json()
        assert all(m["result"] is not None for m in payload["models"]), "全部模型应完成解析"


def test_production_pool_capacity_covers_full_load():
    """生产连接池上限覆盖「worker 线程数 + 解析槽位数」，满载不阻塞。"""
    capacity = shared_engine.pool.size() + shared_engine.pool._max_overflow
    required = job_worker.DEFAULT_CONCURRENCY + runtime_settings.AI_EXPLANATION_CONCURRENCY
    assert capacity >= required, f"连接池上限 {capacity} 不足以支撑 {required} 条并发连接"
