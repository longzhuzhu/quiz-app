"""答题会话本场题目快照、完成冻结与最近一次错误答案。

覆盖：
- /quiz/start 各模式与 /wrong/practice 都写快照，元素与 question_ids 同序
- 跨题库错题会话逐题取各自题库内容
- 未完成会话 final_answers 为 NULL；完成时冻结，未答题显式 null
- 完成后改题干/选项/正确答案、删除题目都不影响快照与冻结判定
- 进行中更正答案同步当前会话快照，其他会话不动
- 旧会话（question_snapshot=NULL）不被回填
- 答错记录最近一次错误答案，后来答对不覆写
- 012 迁移在真实 PostgreSQL（isolated_postgres，不碰业务库）上可 upgrade / downgrade
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.questions import router as questions_router  # noqa: E402
from app.api.routes.quiz import router  # noqa: E402
from app.api.routes.wrong import router as wrong_router  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models import (  # noqa: E402
    Exam,
    ExamTopic,
    Question,
    QuestionBank,
    QuestionTopic,
    QuizAnswer,
    QuizSession,
    User,
    WrongAnswer,
)
from app.models.exam_topic import TOPIC_LEVEL_COMPETENCY  # noqa: E402
from app.services.quiz_snapshot_service import sync_snapshot_correct_answer  # noqa: E402
from postgres_support import isolated_postgres  # noqa: E402

SNAPSHOT_FIELDS = {"question_id", "question_type", "content", "options", "correct_answer"}


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def quiz_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'snapshot.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="snap", email="snap@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        exam = Exam(owner_id=user.id, slug="snap", name="Snap", short_name="S")
        db.add(exam)
        db.flush()
        bank = QuestionBank(exam_id=exam.id, name="主库", question_count=3)
        other_bank = QuestionBank(exam_id=exam.id, name="副库", question_count=1)
        db.add_all([bank, other_bank])
        db.flush()
        questions = [
            Question(
                bank_id=bank.id, question_type="single", content=f"Q{index}",
                options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
                correct_answer="A", order_index=index,
            )
            for index in range(1, 4)
        ]
        other_question = Question(
            bank_id=other_bank.id, question_type="single", content="跨库题",
            options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            correct_answer="B", order_index=1,
        )
        db.add_all(questions + [other_question])
        db.commit()
        ids = SimpleNamespace(
            user=user.id, exam=exam.id, bank=bank.id, other_bank=other_bank.id,
            questions=[q.id for q in questions], other_question=other_question.id,
        )

    def get_test_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/quiz")
    app.include_router(wrong_router, prefix="/api/wrong")
    app.include_router(questions_router, prefix="/api/questions")
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        client.headers.update({
            "Authorization": f"Bearer {create_access_token(str(ids.user))}",
            "X-Exam-Slug": "snap",
        })
        yield SimpleNamespace(client=client, ids=ids, sessions=sessions)
    engine.dispose()


def _start(api, **body):
    body.setdefault("bank_id", api.ids.bank)
    return api.client.post("/api/quiz/start", json=body)


def _answer(api, session_id, question_id, user_answer):
    return api.client.post("/api/quiz/answer", json={
        "session_id": session_id, "question_id": question_id, "user_answer": user_answer,
    })


def _load_session(api, session_id) -> QuizSession:
    with api.sessions() as db:
        session = db.get(QuizSession, session_id)
        db.expunge(session)
        return session


def _snapshot(api, session_id):
    return _load_session(api, session_id).question_snapshot


def _finish_and_read(api, session_id):
    assert api.client.post("/api/quiz/finish", json={"session_id": session_id}).status_code == 200
    return _load_session(api, session_id).final_answers


@pytest.mark.parametrize("mode", ["sequential", "random", "exam", "topic"])
def test_every_start_mode_writes_snapshot_aligned_with_question_ids(quiz_api, mode):
    body = {"mode": mode}
    if mode == "topic":
        body["topic_id"] = None  # 未分类专项
    start = _start(quiz_api, **body)
    assert start.status_code == 200
    session_id = start.json()["session"]["id"]

    session = _load_session(quiz_api, session_id)
    question_ids = json.loads(session.question_ids)
    snapshot = session.question_snapshot

    assert [entry["question_id"] for entry in snapshot] == question_ids
    for entry in snapshot:
        assert set(entry) == SNAPSHOT_FIELDS
        assert isinstance(entry["options"], list)
        assert entry["question_type"] == "single"
        assert entry["correct_answer"] == "A"
        assert entry["content"]
    assert session.final_answers is None  # 未完成会话不写冻结


def test_topic_scope_writes_snapshot_of_selected_topic_questions(quiz_api):
    with quiz_api.sessions() as db:
        topic = ExamTopic(
            exam_id=quiz_api.ids.exam, level=TOPIC_LEVEL_COMPETENCY, code="I.A",
            name_en="Privacy", name_zh="隐私", short_name_zh="隐私",
            source_version="test",
        )
        db.add(topic)
        db.flush()
        db.add(QuestionTopic(
            question_id=quiz_api.ids.questions[1], topic_id=topic.id, source="manual",
        ))
        db.commit()
        topic_id = topic.id

    start = _start(quiz_api, mode="topic", topic_id=topic_id)
    assert start.status_code == 200
    session = _load_session(quiz_api, start.json()["session"]["id"])

    assert json.loads(session.question_ids) == [quiz_api.ids.questions[1]]
    assert [entry["question_id"] for entry in session.question_snapshot] == [quiz_api.ids.questions[1]]
    assert session.question_snapshot[0]["content"] == "Q2"


def test_finish_session_without_question_ids_leaves_freeze_empty(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    with quiz_api.sessions() as db:
        db.get(QuizSession, session_id).question_ids = None
        db.commit()

    response = quiz_api.client.post("/api/quiz/finish", json={"session_id": session_id})
    assert response.status_code == 200
    assert _load_session(quiz_api, session_id).final_answers is None


def test_wrong_practice_snapshot_across_banks_uses_each_question_content(quiz_api):
    with quiz_api.sessions() as db:
        db.add_all([
            WrongAnswer(user_id=quiz_api.ids.user, question_id=quiz_api.ids.questions[0]),
            WrongAnswer(user_id=quiz_api.ids.user, question_id=quiz_api.ids.other_question),
        ])
        db.commit()

    start = quiz_api.client.post("/api/wrong/practice", json={})
    assert start.status_code == 200
    session = _load_session(quiz_api, start.json()["session"]["id"])

    snapshot = session.question_snapshot
    assert [entry["question_id"] for entry in snapshot] == json.loads(session.question_ids)
    assert len(snapshot) == 2

    with quiz_api.sessions() as db:
        assert db.get(Question, quiz_api.ids.questions[0]).bank_id == quiz_api.ids.bank
        assert db.get(Question, quiz_api.ids.other_question).bank_id == quiz_api.ids.other_bank
        assert db.get(Question, quiz_api.ids.questions[0]).content == "Q1"

    by_id = {entry["question_id"]: entry for entry in snapshot}
    assert by_id[quiz_api.ids.other_question]["content"] == "跨库题"
    assert by_id[quiz_api.ids.other_question]["correct_answer"] == "B"
    assert by_id[quiz_api.ids.questions[0]]["content"] == "Q1"


def test_finish_freezes_answers_with_explicit_null_for_unanswered(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    first, second, third = quiz_api.ids.questions
    assert _answer(quiz_api, session_id, first, "A").status_code == 200
    assert _answer(quiz_api, session_id, second, "B").status_code == 200

    frozen = _finish_and_read(quiz_api, session_id)

    assert frozen[str(first)] == {"user_answer": "A", "is_correct": True}
    assert frozen[str(second)] == {"user_answer": "B", "is_correct": False}
    assert frozen[str(third)] is None


def test_completed_session_snapshot_survives_question_edits(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    first = quiz_api.ids.questions[0]
    assert _answer(quiz_api, session_id, first, "B").status_code == 200
    frozen = _finish_and_read(quiz_api, session_id)
    before = _snapshot(quiz_api, session_id)

    response = quiz_api.client.put(f"/api/questions/{first}", json={
        "content": "题干已改",
        "options": [{"key": "A", "text": "改后甲"}, {"key": "B", "text": "改后乙"}],
        "correct_answer": "B",
    })
    assert response.status_code == 200

    session = _load_session(quiz_api, session_id)
    assert session.question_snapshot == before
    assert next(e for e in session.question_snapshot if e["question_id"] == first)["correct_answer"] == "A"
    assert next(e for e in session.question_snapshot if e["question_id"] == first)["content"] == "Q1"
    assert session.final_answers == frozen
    assert session.final_answers[str(first)]["is_correct"] is False


def test_deleted_question_keeps_frozen_verdict_readable(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    first = quiz_api.ids.questions[0]
    assert _answer(quiz_api, session_id, first, "B").status_code == 200
    frozen = _finish_and_read(quiz_api, session_id)

    assert quiz_api.client.delete(f"/api/questions/{first}").status_code == 200

    with quiz_api.sessions() as db:
        assert db.get(Question, first) is None
    session = _load_session(quiz_api, session_id)
    assert session.final_answers == frozen
    assert session.final_answers[str(first)] == {"user_answer": "B", "is_correct": False}


def test_repeated_finish_keeps_frozen_answers(quiz_api):
    """重复结束（双击或重试）不得重算冻结：删题后重算会把判定改写成未答。"""
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    first = quiz_api.ids.questions[0]
    assert _answer(quiz_api, session_id, first, "B").status_code == 200
    frozen = _finish_and_read(quiz_api, session_id)
    completed_at = _load_session(quiz_api, session_id).completed_at

    assert quiz_api.client.delete(f"/api/questions/{first}").status_code == 200
    assert quiz_api.client.post(
        "/api/quiz/finish", json={"session_id": session_id}
    ).status_code == 200

    session = _load_session(quiz_api, session_id)
    assert session.final_answers == frozen
    assert session.final_answers[str(first)] == {"user_answer": "B", "is_correct": False}
    assert session.completed_at == completed_at


def test_correct_answer_rejected_on_completed_session(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    question_id = quiz_api.ids.questions[0]
    assert _answer(quiz_api, session_id, question_id, "A").status_code == 200
    frozen = _finish_and_read(quiz_api, session_id)
    snapshot_before = _snapshot(quiz_api, session_id)

    response = quiz_api.client.put(f"/api/questions/{question_id}/correct-answer", json={
        "correct_answer": "B", "session_id": session_id,
    })
    assert response.status_code == 400

    session = _load_session(quiz_api, session_id)
    assert session.question_snapshot == snapshot_before
    assert session.final_answers == frozen
    assert session.correct_count == 1
    with quiz_api.sessions() as db:
        answer = db.query(QuizAnswer).filter_by(
            session_id=session_id, question_id=question_id
        ).one()
        assert answer.is_correct is True
        assert db.get(Question, question_id).correct_answer == "A"


def test_active_correction_updates_only_current_session_snapshot(quiz_api):
    first_session = _start(quiz_api, mode="sequential").json()["session"]["id"]
    second_session = _start(quiz_api, mode="sequential").json()["session"]["id"]
    question_id = quiz_api.ids.questions[0]

    response = quiz_api.client.put(f"/api/questions/{question_id}/correct-answer", json={
        "correct_answer": "B", "session_id": first_session,
    })
    assert response.status_code == 200

    current = {e["question_id"]: e for e in _snapshot(quiz_api, first_session)}
    other = {e["question_id"]: e for e in _snapshot(quiz_api, second_session)}
    assert current[question_id]["correct_answer"] == "B"
    assert other[question_id]["correct_answer"] == "A"


def test_sync_snapshot_tolerates_missing_or_malformed_entries():
    """快照条目缺失或非 dict 时不抛异常：缺 question_id 的条目原样保留，命中项更新。"""
    session = SimpleNamespace(question_snapshot=[
        None,
        "oops",
        {"content": "无题号"},
        {"question_id": 7, "correct_answer": "A"},
    ])

    sync_snapshot_correct_answer(session, 7, "B")

    assert session.question_snapshot[3] == {"question_id": 7, "correct_answer": "B"}
    assert session.question_snapshot[:3] == [None, "oops", {"content": "无题号"}]


def test_sync_snapshot_noop_without_snapshot():
    """旧会话（快照为 NULL）安全空转，不回填伪造快照。"""
    session = SimpleNamespace(question_snapshot=None)

    sync_snapshot_correct_answer(session, 7, "B")

    assert session.question_snapshot is None


def test_legacy_session_without_snapshot_is_not_backfilled(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    with quiz_api.sessions() as db:
        db.get(QuizSession, session_id).question_snapshot = None
        db.commit()

    assert _answer(quiz_api, session_id, quiz_api.ids.questions[0], "A").status_code == 200
    frozen = _finish_and_read(quiz_api, session_id)

    session = _load_session(quiz_api, session_id)
    assert session.question_snapshot is None  # 旧会话不被当前题库回填
    assert frozen[str(quiz_api.ids.questions[0])] == {"user_answer": "A", "is_correct": True}


def test_wrong_answer_keeps_last_wrong_choice_after_later_correct_redo(quiz_api):
    session_id = _start(quiz_api, mode="sequential").json()["session"]["id"]
    question_id = quiz_api.ids.questions[0]

    def read_wrong():
        with quiz_api.sessions() as db:
            return db.query(WrongAnswer).filter_by(
                user_id=quiz_api.ids.user, question_id=question_id
            ).one()

    assert _answer(quiz_api, session_id, question_id, "B").status_code == 200
    wrong = read_wrong()
    assert wrong.last_wrong_answer == "B"
    assert wrong.last_wrong_session_id == session_id

    assert _answer(quiz_api, session_id, question_id, "A").status_code == 200
    wrong = read_wrong()
    assert wrong.last_wrong_answer == "B"
    assert wrong.last_wrong_session_id == session_id
    assert wrong.is_resolved is False

    # 同题再次答错时才更新为最新错误选择
    assert _answer(quiz_api, session_id, question_id, "C").status_code == 200
    assert read_wrong().last_wrong_answer == "C"


@contextmanager
def _migration_database():
    """临时 PostgreSQL 上的专用 schema；不连接 backend/.env 里的业务库，也不留残留。"""
    with isolated_postgres() as engine:
        schema = "snapshot_migration_test"
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        try:
            yield engine
        finally:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_migration_012_upgrades_and_downgrades_on_postgres():
    new_columns = (
        "question_snapshot", "final_answers", "last_wrong_answer", "last_wrong_session_id"
    )
    schema = "snapshot_migration_test"
    with _migration_database() as engine:
        url = engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
        # alembic 把 -x url= 交给 configparser，URL 里的 % 需转义成 %% 否则插值报错
        url_string = url.render_as_string(hide_password=False).replace("%", "%%")

        def migrate(*args):
            # Alembic env 会重配置日志；隔离进程避免影响其他测试的日志捕获。
            subprocess.run(
                [sys.executable, "-m", "alembic", "-x", f"url={url_string}", *args],
                cwd=BACKEND_ROOT, check=True, capture_output=True, text=True,
            )

        def existing_columns():
            with engine.connect() as conn:
                return set(conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND column_name = ANY(:names)"
                    ),
                    {"schema": schema, "names": list(new_columns)},
                ).all())

        migrate("upgrade", "001")
        # 003 要求 owner 用户先存在；迁移跑在专用 schema 上，这里补最小的 admin 行。
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text(
                "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
                "VALUES (1, 'nianyu', 'nianyu@example.com', 'x', TRUE, NOW())"
            ))

        migrate("upgrade", "head")
        assert existing_columns() == {
            ("quiz_sessions", "question_snapshot"),
            ("quiz_sessions", "final_answers"),
            ("wrong_answers", "last_wrong_answer"),
            ("wrong_answers", "last_wrong_session_id"),
        }

        migrate("downgrade", "011")
        assert existing_columns() == set()
