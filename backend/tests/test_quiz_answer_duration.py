"""首次成功提交耗时通过公开答题 API 保存，改答不改写。"""

import json
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes.quiz import router  # noqa: E402
from app.api.routes.wrong import router as wrong_router  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import Exam, Question, QuestionBank, QuizSession, User, WrongAnswer  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def quiz_api(tmp_path, request):
    schema = None
    base_engine = None
    if getattr(request, "param", None) == "postgresql":
        if not settings.DATABASE_URL.startswith("postgresql"):
            pytest.skip("并发首次提交需要 PostgreSQL 行锁语义")
        base_engine = create_engine(settings.DATABASE_URL)
        schema = "duration_test_" + uuid.uuid4().hex
        with base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(settings.DATABASE_URL).update_query_dict({"options": f"-csearch_path={schema}"})
        engine = create_engine(url)
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'quiz.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="timer", email="timer@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="timer", name="Timer", short_name="T")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="计时题库", question_count=2)
        db.add(bank)
        db.flush()
        question = Question(
            bank_id=bank.id, question_type="single", content="Q1",
            options=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}],
            correct_answer="A", order_index=1,
        )
        db.add(question)
        db.flush()
        session = QuizSession(
            user_id=user.id, bank_id=bank.id, mode="sequential",
            total_questions=1, question_ids=json.dumps([question.id]),
        )
        db.add(session)
        db.commit()
        ids = SimpleNamespace(user=user.id, exam=exam.id, bank=bank.id,
                              question=question.id, session=session.id)

    def get_test_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/quiz")
    app.include_router(wrong_router, prefix="/api/wrong")
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        client.headers.update({
            "Authorization": f"Bearer {create_access_token(str(ids.user))}",
            "X-Exam-Slug": "timer",
        })
        yield SimpleNamespace(client=client, ids=ids, sessions=sessions)
    engine.dispose()
    if base_engine is not None:
        with base_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        base_engine.dispose()


def _submit(api, **extra):
    return api.client.post("/api/quiz/answer", json={
        "session_id": api.ids.session, "question_id": api.ids.question,
        "user_answer": "A", **extra,
    })


def _answers(api):
    response = api.client.get(f"/api/quiz/session/{api.ids.session}")
    assert response.status_code == 200
    return response.json()["answers"]


def test_first_submission_duration_is_retrievable(quiz_api):
    response = _submit(quiz_api, answer_duration_ms=12345)
    assert response.status_code == 200
    assert _answers(quiz_api)[0]["answer_duration_ms"] == 12345


def test_redo_returns_and_preserves_first_duration(quiz_api):
    assert _submit(quiz_api, answer_duration_ms=12345).status_code == 200
    response = _submit(quiz_api, user_answer="B", answer_duration_ms=99999)
    assert response.status_code == 200
    assert response.json()["answer_duration_ms"] == 12345
    answer = _answers(quiz_api)[0]
    assert answer["answer_duration_ms"] == 12345
    assert answer["user_answer"] == "B"


@pytest.mark.parametrize("duration", [None, 0, 9_007_199_254_740_991])
def test_unknown_zero_and_maximum_durations_are_preserved_on_redo(quiz_api, duration):
    assert _submit(quiz_api, answer_duration_ms=duration).status_code == 200
    assert _submit(quiz_api, answer_duration_ms=23456).status_code == 200
    assert _answers(quiz_api)[0]["answer_duration_ms"] == duration


def test_old_client_without_duration_keeps_unknown_on_future_redo(quiz_api):
    assert _submit(quiz_api).status_code == 200
    response = _submit(quiz_api, answer_duration_ms=23456)
    assert response.status_code == 200
    assert response.json()["answer_duration_ms"] is None
    assert _answers(quiz_api)[0]["answer_duration_ms"] is None


@pytest.mark.parametrize("duration", [-1, 1.5, True, "1000", 9_007_199_254_740_992])
def test_invalid_duration_rejects_submission_without_recording_answer(quiz_api, duration):
    assert _submit(quiz_api, answer_duration_ms=duration).status_code == 422
    assert _answers(quiz_api) == []


@pytest.mark.parametrize("mode", ["sequential", "random", "exam", "topic", "wrong_practice"])
def test_all_mode_start_paths_save_duration_without_leaking_exam_answers(quiz_api, mode):
    if mode == "wrong_practice":
        with quiz_api.sessions() as db:
            db.add(WrongAnswer(user_id=quiz_api.ids.user, question_id=quiz_api.ids.question))
            db.commit()
        start = quiz_api.client.post("/api/wrong/practice", json={"bank_id": quiz_api.ids.bank})
    else:
        start = quiz_api.client.post("/api/quiz/start", json={"bank_id": quiz_api.ids.bank, "mode": mode})
    assert start.status_code == 200
    quiz_api.ids.session = start.json()["session"]["id"]
    response = _submit(quiz_api, answer_duration_ms=12000)
    assert response.status_code == 200
    assert response.json()["answer_duration_ms"] == 12000
    assert _answers(quiz_api)[0]["answer_duration_ms"] == 12000
    if mode == "exam":
        assert response.json()["submitted"] is True
        assert "correct_answer" not in response.json()
        assert "correct_answer" not in _answers(quiz_api)[0]


def test_separate_sessions_keep_independent_first_durations(quiz_api):
    assert _submit(quiz_api, answer_duration_ms=1000).status_code == 200
    first_session = quiz_api.ids.session
    start = quiz_api.client.post("/api/quiz/start", json={"bank_id": quiz_api.ids.bank})
    quiz_api.ids.session = start.json()["session"]["id"]
    assert _submit(quiz_api, answer_duration_ms=2000).status_code == 200
    assert _answers(quiz_api)[0]["answer_duration_ms"] == 2000
    quiz_api.ids.session = first_session
    assert _answers(quiz_api)[0]["answer_duration_ms"] == 1000


def test_rejected_foreign_question_does_not_save_duration(quiz_api):
    assert _submit(quiz_api, question_id=999999, answer_duration_ms=1000).status_code == 400
    assert _answers(quiz_api) == []


def test_completed_session_does_not_accept_duration(quiz_api):
    response = quiz_api.client.post("/api/quiz/finish", json={"session_id": quiz_api.ids.session})
    assert response.status_code == 200
    assert _submit(quiz_api, answer_duration_ms=1000).status_code == 400
    assert _answers(quiz_api) == []


def test_other_exam_cannot_submit_duration(quiz_api):
    with quiz_api.sessions() as db:
        db.add(Exam(owner_id=quiz_api.ids.user, slug="other", name="Other", short_name="O"))
        db.commit()
    quiz_api.client.headers["X-Exam-Slug"] = "other"
    assert _submit(quiz_api, answer_duration_ms=1000).status_code == 404
    quiz_api.client.headers["X-Exam-Slug"] = "timer"
    assert _answers(quiz_api) == []


def test_other_user_cannot_submit_duration(quiz_api):
    with quiz_api.sessions() as db:
        user = User(username="other", email="other@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(Exam(owner_id=user.id, slug="timer", name="Other", short_name="O"))
        db.commit()
        token = create_access_token(str(user.id))
    old_auth = quiz_api.client.headers["Authorization"]
    quiz_api.client.headers["Authorization"] = f"Bearer {token}"
    assert _submit(quiz_api, answer_duration_ms=1000).status_code == 404
    quiz_api.client.headers["Authorization"] = old_auth
    assert _answers(quiz_api) == []


@pytest.mark.parametrize("quiz_api", ["postgresql"], indirect=True)
def test_concurrent_retries_preserve_one_first_duration(quiz_api):
    # 外部事务暂时阻塞会话写入，确保多个公开请求确实重叠，而非依次完成。
    with quiz_api.sessions() as holder, ThreadPoolExecutor(max_workers=4) as pool:
        holder.execute(text("SELECT id FROM quiz_sessions WHERE id = :id FOR UPDATE"),
                       {"id": quiz_api.ids.session})
        pending = [pool.submit(_submit, quiz_api, answer_duration_ms=value)
                   for value in [1000, 2000, 3000, 4000]]
        time.sleep(0.3)
        holder.rollback()
        responses = [future.result() for future in pending]
    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    duration = _answers(quiz_api)[0]["answer_duration_ms"]
    assert duration in [1000, 2000, 3000, 4000]
    assert all(response.json()["answer_duration_ms"] == duration for response in responses)
    detail = quiz_api.client.get(f"/api/quiz/session/{quiz_api.ids.session}").json()
    assert detail["session"]["answered_count"] == 1


def test_migration_preserves_old_answers_without_inventing_duration(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE quiz_answers (id INTEGER PRIMARY KEY, user_answer VARCHAR(20))"))
        conn.execute(text("INSERT INTO quiz_answers VALUES (1, 'A')"))
    def migrate(*args):
        # Alembic env 会重配置日志；隔离进程避免禁用其他测试的日志捕获。
        subprocess.run(
            [sys.executable, "-m", "alembic", "-x", f"url={engine.url}", *args],
            cwd=Path(__file__).resolve().parents[1], check=True,
            capture_output=True, text=True,
        )

    migrate("stamp", "008")
    migrate("upgrade", "head")
    with engine.connect() as conn:
        answer = conn.execute(text("SELECT user_answer, answer_duration_ms FROM quiz_answers")).one()
        assert tuple(answer) == ("A", None)
    migrate("downgrade", "008")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT user_answer FROM quiz_answers")).scalar_one() == "A"
    engine.dispose()
