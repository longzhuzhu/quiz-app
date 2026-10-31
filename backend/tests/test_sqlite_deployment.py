"""SQLite 部署路径：真实迁移、锁互斥、任务生命周期与 HTTP 业务链路。

边界：
- 只使用临时文件库；不读取或连接 backend/.env 指向的业务数据库。
- 迁移通过显式 -x url= 子进程执行，不依赖应用当前配置。
- AI 调用使用桩，不发真实网络请求。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import Base, create_db_engine  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import (  # noqa: E402
    Exam,
    Question,
    QuestionBank,
    User,
)
from app.services import job_service  # noqa: E402
from app.services.import_execution import (  # noqa: E402
    ImportBusy,
    execution_for,
    release_import_execution,
    review_writer,
)
from app.models import BackgroundJob, ImportJob  # noqa: E402

QUESTION_OPTIONS = [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}]


def _alembic(database: Path, *args: str) -> subprocess.CompletedProcess:
    url = f"sqlite:///{database}"
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "AI_API_KEY": "",
        "JWT_SECRET_KEY": "sqlite-deployment-test",
        "SECRET_KEY": "sqlite-deployment-test",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }


# ─── 迁移 ────────────────────────────────────────────────────────────


def test_empty_sqlite_upgrades_to_head_with_orm_schema(tmp_path):
    database = tmp_path / "empty.db"
    result = _alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert _tables(database) == expected
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("013",)
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='questions'"
        ).fetchone()[0]
    assert "JSON NOT NULL" in ddl
    assert "JSONB" not in ddl


def test_sqlite_migration_downgrades_to_base_and_back(tmp_path):
    database = tmp_path / "roundtrip.db"
    assert _alembic(database, "upgrade", "head").returncode == 0
    result = _alembic(database, "downgrade", "base")
    assert result.returncode == 0, result.stderr
    assert _tables(database) == {"alembic_version"}
    assert _alembic(database, "upgrade", "head").returncode == 0


def test_non_empty_sqlite_003_still_requires_expected_owner(tmp_path):
    database = tmp_path / "owned.db"
    assert _alembic(database, "upgrade", "002").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
            "VALUES (1, 'someone', 's@example.invalid', 'x', 0, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO question_banks (id, name, question_count, created_at) "
            "VALUES (1, 'legacy', 0, '2026-01-01 00:00:00')"
        )
    result = _alembic(database, "upgrade", "head")
    assert result.returncode != 0
    assert "nianyu" in result.stderr


def test_non_empty_sqlite_003_backfills_legacy_rows_for_owner(tmp_path):
    database = tmp_path / "backfill.db"
    assert _alembic(database, "upgrade", "002").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
            "VALUES (1, 'nianyu', 'n@example.invalid', 'x', 1, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO question_banks (id, name, question_count, created_at) "
            "VALUES (1, 'legacy', 0, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO vocabularies (id, term, is_system, created_at) "
            "VALUES (1, 'privacy', 1, '2026-01-01 00:00:00')"
        )
    result = _alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT exam_id FROM question_banks").fetchone() == (1,)
        assert connection.execute(
            "SELECT user_id, exam_id, is_system FROM vocabularies"
        ).fetchone() == (1, 1, 0)
        assert connection.execute("SELECT owner_id, slug FROM exams").fetchone() == (1, "cipt")


# ─── 任务与锁 ────────────────────────────────────────────────────────


@pytest.fixture
def sqlite_env(tmp_path):
    database = tmp_path / "deploy.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        owner = User(username="owner", email="owner@example.invalid", password_hash="x")
        db.add(owner)
        db.flush()
        exam = Exam(owner_id=owner.id, slug="exam", name="Exam", short_name="E")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="Bank", question_count=1)
        db.add(bank)
        db.flush()
        question = Question(
            bank_id=bank.id, question_type="single", content="Which control?",
            options=QUESTION_OPTIONS, correct_answer="A",
        )
        db.add(question)
        db.commit()
        ids = {"owner": owner.id, "exam": exam.id, "bank": bank.id, "question": question.id}
    yield engine, sessions, ids
    engine.dispose()


def test_job_claim_and_recover_are_safe_on_sqlite(sqlite_env):
    engine, sessions, ids = sqlite_env
    with sessions() as db:
        queued = BackgroundJob(
            job_type="ai_prewarm", scope_key="claim", payload_json="{}",
            status="queued", created_by=ids["owner"],
        )
        db.add(queued)
        db.commit()
        queued_id = queued.id

    with sessions() as first, sessions() as second:
        claimed = job_service.try_claim_job_by_id(first, queued_id, worker_id="w1")
        assert claimed is not None
        assert job_service.try_claim_job_by_id(second, queued_id, worker_id="w2") is None

    with sessions() as db:
        job = db.get(BackgroundJob, queued_id)
        job.lease_until = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert job_service.recover_stale_jobs(db) == 1
        job = db.get(BackgroundJob, queued_id)
        assert job.status == "queued"
        assert job.lease_until is None


def test_import_lock_is_exclusive_between_sessions_on_sqlite(sqlite_env):
    engine, sessions, ids = sqlite_env
    with sessions() as db:
        import_job = ImportJob(
            bank_id=ids["bank"], file_name="f.pdf", file_path="unused",
            file_hash="a" * 64, file_type="pdf", config_json={}, created_by=ids["owner"],
        )
        db.add(import_job)
        db.commit()
        import_job_id = import_job.id

    holder = sessions()
    with review_writer(holder, import_job_id):
        contender = sessions()
        try:
            with pytest.raises(ImportBusy):
                with review_writer(contender, import_job_id):
                    pass
        finally:
            contender.close()
    with review_writer(sessions(), import_job_id):
        pass
    holder.close()


def test_import_execution_context_is_required_for_import_jobs(sqlite_env):
    engine, sessions, ids = sqlite_env
    with sessions() as db:
        import_job = ImportJob(
            bank_id=ids["bank"], file_name="f.pdf", file_path="unused",
            file_hash="b" * 64, file_type="pdf", config_json={}, created_by=ids["owner"],
        )
        db.add(import_job)
        db.flush()
        job = BackgroundJob(
            job_type="question_import_llm",
            scope_key=f"import_llm:{import_job.id}",
            payload_json=json.dumps({"import_job_id": import_job.id, "bank_id": ids["bank"]}),
            status="queued", created_by=ids["owner"],
        )
        db.add(job)
        db.flush()
        import_job.background_job_id = job.id
        db.commit()
        job_id, import_job_id = job.id, import_job.id

    holder = sessions()
    claimed = job_service.try_claim_job_by_id(holder, job_id, worker_id="w1")
    assert claimed is not None
    assert execution_for(holder) is not None

    contender = sessions()
    assert job_service.try_claim_job_by_id(contender, job_id, worker_id="w2") is None
    contender.close()
    release_import_execution(holder, claimed)
    holder.close()

    # 释放后可重新领取（先把任务放回 queued）。
    with sessions() as db:
        job = db.get(BackgroundJob, job_id)
        job.status = "queued"
        db.commit()
    with sessions() as db:
        reclaimed = job_service.try_claim_job_by_id(db, job_id, worker_id="w3")
        assert reclaimed is not None
        release_import_execution(db, reclaimed)


def test_worker_concurrency_is_clamped_on_sqlite(sqlite_env, monkeypatch):
    from app.workers import job_worker

    engine, _, _ = sqlite_env
    assert job_worker._effective_concurrency(10, engine) == 1


# ─── HTTP 业务链路 ───────────────────────────────────────────────────


@pytest.fixture
def sqlite_api(sqlite_env, monkeypatch):
    engine, sessions, ids = sqlite_env
    from app.api.routes.ai import router as ai_router
    from app.api.routes.quiz import router as quiz_router
    from app.api.routes.wrong import router as wrong_router
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(quiz_router, prefix="/api/quiz")
    app.include_router(wrong_router, prefix="/api/wrong")
    app.include_router(ai_router, prefix="/api/ai")

    from app.core.database import write_sessionmaker

    def database(request: Request):
        # 与生产一致：GET/HEAD/OPTIONS 用 deferred 读会话，其余用 IMMEDIATE 写会话。
        factory = sessionmaker(bind=engine) if request.method in {"GET", "HEAD", "OPTIONS"} else write_sessionmaker(engine)
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    headers = {
        "Authorization": f"Bearer {create_access_token(str(ids['owner']))}",
        "X-Exam-Slug": "exam",
    }
    with TestClient(app, headers=headers) as client:
        yield type("Api", (), {"client": client, "sessions": sessions, "ids": ids, "engine": engine})


def test_sqlite_quiz_answer_and_wrong_book_flow(sqlite_api):
    client, ids = sqlite_api.client, sqlite_api.ids
    started = client.post("/api/quiz/start", json={"bank_id": ids["bank"], "mode": "sequential"})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    assert started.json()["questions"][0]["options"] == QUESTION_OPTIONS

    wrong = client.post("/api/quiz/answer", json={
        "session_id": session_id, "question_id": ids["question"],
        "user_answer": "B", "local_date": datetime.now(timezone.utc).date().isoformat(),
    })
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["is_correct"] is False

    listed = client.get("/api/wrong")
    assert listed.status_code == 200
    assert [item["question_id"] for item in listed.json()] == [ids["question"]]

    corrected = client.post("/api/quiz/answer", json={
        "session_id": session_id, "question_id": ids["question"],
        "user_answer": "A", "local_date": datetime.now(timezone.utc).date().isoformat(),
    })
    assert corrected.status_code == 200
    assert corrected.json()["is_correct"] is True
    assert corrected.json()["counted_as_new_attempt"] is False

    finished = client.post("/api/quiz/finish", json={"session_id": session_id})
    assert finished.status_code == 200
    assert finished.json()["session"]["is_completed"] is True
    history = client.get("/api/quiz/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["is_completed"] is True


def test_sqlite_concurrent_answers_do_not_duplicate_rows(sqlite_api):
    """同一会话同一题的并发提交：唯一约束与写事务保证不重复插入。"""
    import threading

    client, ids = sqlite_api.client, sqlite_api.ids
    started = client.post("/api/quiz/start", json={"bank_id": ids["bank"], "mode": "sequential"})
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    today = datetime.now(timezone.utc).date().isoformat()
    results = []

    def submit():
        response = client.post("/api/quiz/answer", json={
            "session_id": session_id, "question_id": ids["question"],
            "user_answer": "A", "local_date": today,
        })
        results.append(response.status_code)

    threads = [threading.Thread(target=submit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert results == [200, 200, 200, 200], results
    with sqlite_api.sessions() as db:
        rows = db.execute(text("SELECT COUNT(*) FROM quiz_answers")).scalar()
    assert rows == 1


def test_sqlite_translation_does_not_hold_write_lock_across_network(sqlite_api, monkeypatch):
    """AI 联网前结束只读事务：网络期间另一个写事务仍能立即提交。

    若请求在 httpx 调用期间仍持有 SQLite 写锁，下面的独立写事务会等待
    busy_timeout 后报 database is locked。
    """
    from app.services import ai_service

    observed = {}

    class _Response:
        is_success = True
        status_code = 200
        reason_phrase = "OK"
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(
                {"content_zh": "哪个控制？",
                 "options_zh": [{"key": "A", "text_zh": "甲"}, {"key": "B", "text_zh": "乙"}]},
                ensure_ascii=False,
            )}}]}

    def fake_post(*args, **kwargs):
        from app.core.database import write_sessionmaker
        from app.models.system_setting import SystemSetting

        writer = write_sessionmaker(sqlite_api.engine)()
        try:
            writer.add(SystemSetting(key="network_side_effect", value="ok"))
            writer.commit()
            observed["committed"] = True
        finally:
            writer.close()
        return _Response()

    monkeypatch.setattr(
        ai_service, "get_effective_ai_settings",
        lambda *a, **k: {"api_key": "test-key", "base_url": "https://8.8.8.8", "model": "stub"},
    )
    monkeypatch.setattr(ai_service.httpx, "post", fake_post)
    response = sqlite_api.client.post("/api/ai/translate", json={"question_id": sqlite_api.ids["question"]})
    assert response.status_code == 200, response.text
    assert response.json()["content_zh"] == "哪个控制？"
    assert observed.get("committed") is True
    with sqlite_api.sessions() as db:
        assert db.execute(text("SELECT content_zh FROM questions")).scalar() == "哪个控制？"
        assert db.execute(
            text("SELECT value FROM system_settings WHERE key='network_side_effect'")
        ).scalar() == "ok"
