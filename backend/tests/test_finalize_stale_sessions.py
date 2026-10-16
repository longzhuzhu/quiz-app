"""陈旧会话结束脚本：dry-run/apply、冻结口径、归属校验与拒绝路径。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base
from app.models import Exam, Question, QuestionBank, QuizAnswer, QuizSession, User
from scripts.finalize_stale_sessions import FinalizeError, Scope, finalize_sessions, parse_sessions
from postgres_support import isolated_postgres


@pytest.fixture(scope="module")
def pg():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def db(pg):
    with pg.begin() as conn:
        names = ",".join('"' + name + '"' for name in Base.metadata.tables)
        conn.execute(text("TRUNCATE " + names + " RESTART IDENTITY CASCADE"))
    with Session(pg) as db:
        user = User(username="nianyu", email="nianyu@test.invalid", password_hash="test")
        other = User(username="other", email="other@test.invalid", password_hash="test")
        db.add_all([user, other])
        db.flush()
        exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
        foreign = Exam(owner_id=other.id, slug="cipt", name="Other", short_name="O")
        db.add_all([exam, foreign])
        db.flush()
        db.add_all([QuestionBank(id=13, exam_id=exam.id, name="官方题库"), QuestionBank(id=77, exam_id=foreign.id, name="外部题库")])
        db.flush()
        db.add_all([
            Question(bank_id=13, question_type="single", content="first", options=[{"key": "A", "text": "x"}, {"key": "B", "text": "y"}], correct_answer="A"),
            Question(bank_id=13, question_type="single", content="second", options=[{"key": "A", "text": "x"}, {"key": "B", "text": "y"}], correct_answer="A"),
        ])
        db.commit()
        yield db
        db.rollback()


def stale(db, ids, *, bank_id=13, user_id=1, snapshot=None, completed=False):
    session = QuizSession(
        user_id=user_id, bank_id=bank_id, mode="random", total_questions=len(ids),
        question_ids=json.dumps(ids), is_completed=completed, question_snapshot=snapshot,
    )
    db.add(session)
    db.commit()
    return session.id


def test_parse_sessions_rejects_ambiguous_input():
    assert parse_sessions("34,37,38,125") == (34, 37, 38, 125)
    for raw in ("", "34,", "34,34", "0", "-1", "34,abc"):
        with pytest.raises(FinalizeError, match="INVALID_SESSIONS"):
            parse_sessions(raw)


def test_dry_run_validates_without_writing(db):
    session_id = stale(db, [1, 2], snapshot=[{"question_id": 1}, {"question_id": 2}])
    db.add(QuizAnswer(session_id=session_id, question_id=1, user_answer="A", is_correct=True))
    db.commit()
    result = finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,))
    assert result.sessions[0].status == "would_finalize"
    assert (result.sessions[0].answers, result.sessions[0].frozen) == (1, 2)
    db.expire_all()
    session = db.get(QuizSession, session_id)
    assert session.is_completed is False and session.completed_at is None and session.final_answers is None


def test_apply_freezes_judgements_like_finish_endpoint(db):
    session_id = stale(db, [1, 2], snapshot=[{"question_id": 1}, {"question_id": 2}])
    db.add(QuizAnswer(session_id=session_id, question_id=1, user_answer="A", is_correct=True))
    db.commit()
    before = datetime.now(timezone.utc)
    result = finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,), apply=True)
    assert result.sessions[0].status == "finalized"
    db.expire_all()
    session = db.get(QuizSession, session_id)
    assert session.is_completed is True
    assert session.completed_at is not None and session.completed_at.replace(tzinfo=timezone.utc) >= before
    # 未答题显式写 None，键为字符串题号，与 finish 端点同口径。
    assert session.final_answers == {"1": {"user_answer": "A", "is_correct": True}, "2": None}


def test_completed_session_is_skipped_and_not_refrozen(db):
    session_id = stale(db, [1], snapshot=[{"question_id": 1}], completed=True)
    frozen = {"1": {"user_answer": "B", "is_correct": False}}
    session = db.get(QuizSession, session_id)
    session.final_answers = frozen
    db.commit()
    result = finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,), apply=True)
    assert result.sessions[0].status == "already_completed"
    db.expire_all()
    assert db.get(QuizSession, session_id).final_answers == frozen


@pytest.mark.parametrize("scope", [Scope("ghost", "cipt"), Scope("nianyu", "missing")])
def test_scope_must_resolve_before_any_write(db, scope):
    session_id = stale(db, [1], snapshot=[{"question_id": 1}])
    with pytest.raises(FinalizeError, match="OWNER_NOT_FOUND|EXAM_NOT_FOUND"):
        finalize_sessions(db, scope, (session_id,), apply=True)
    db.expire_all()
    assert db.get(QuizSession, session_id).is_completed is False


def test_same_slug_other_owner_is_a_different_exam(db):
    # 另一个 owner 也有同名 slug；归属按用户解析，不允许跨 owner 结束会话。
    session_id = stale(db, [1], bank_id=77, user_id=2, snapshot=[{"question_id": 1}])
    with pytest.raises(FinalizeError, match="SESSION_NOT_IN_SCOPE"):
        finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,), apply=True)
    assert db.get(QuizSession, session_id).is_completed is False


def test_foreign_exam_and_missing_session_are_rejected(db):
    outside = stale(db, [1], bank_id=77, user_id=2, snapshot=[{"question_id": 1}])
    own = stale(db, [1], snapshot=[{"question_id": 1}])
    with pytest.raises(FinalizeError, match="SESSION_NOT_IN_SCOPE"):
        finalize_sessions(db, Scope("nianyu", "cipt"), (own, outside), apply=True)
    with pytest.raises(FinalizeError, match="SESSION_NOT_FOUND"):
        finalize_sessions(db, Scope("nianyu", "cipt"), (999,))
    db.expire_all()
    # 整批在第一条写入前拒绝：合法会话也保持未完成。
    assert db.get(QuizSession, own).is_completed is False
    assert db.get(QuizSession, outside).is_completed is False


def test_snapshotless_session_refuses_to_freeze(db):
    session_id = stale(db, [1, 2])
    with pytest.raises(FinalizeError, match="MISSING_SESSION_SNAPSHOT"):
        finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,), apply=True)
    db.expire_all()
    assert db.get(QuizSession, session_id).is_completed is False


def test_valid_session_before_invalid_one_is_not_left_half_written(db):
    # 合法会话 ID 小于非法会话时，合法会话先被遍历；校验失败必须在第一个字段写入
    # 之前抛出，否则调用方捕获异常后提交（或复用会话）就会落库半批结束结果。
    own = stale(db, [1], snapshot=[{"question_id": 1}])
    outside = stale(db, [1], bank_id=77, snapshot=[{"question_id": 1}])
    assert own < outside
    with pytest.raises(FinalizeError, match="SESSION_NOT_IN_SCOPE"):
        finalize_sessions(db, Scope("nianyu", "cipt"), (own, outside), apply=True)
    assert db.get(QuizSession, own).is_completed is False
    assert db.get(QuizSession, own).completed_at is None
    assert db.get(QuizSession, own).final_answers is None


def test_malformed_question_ids_are_rejected(db):
    session_id = stale(db, [1])
    db.execute(text("UPDATE quiz_sessions SET question_ids = '{\"unknown\": 2}' WHERE id = :id"), {"id": session_id})
    db.commit()
    with pytest.raises(FinalizeError, match="UNKNOWN_SESSION_STRUCTURE"):
        finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,), apply=True)


def test_empty_question_list_finalizes_without_fabricated_freeze(db):
    session_id = stale(db, [])
    result = finalize_sessions(db, Scope("nianyu", "cipt"), (session_id,), apply=True)
    assert result.sessions[0].status == "finalized"
    db.expire_all()
    session = db.get(QuizSession, session_id)
    assert session.is_completed is True and session.final_answers is None


def test_cli_rejects_placeholder_url_and_bad_sessions_before_connecting(tmp_path):
    import os
    import subprocess
    cli = Path(__file__).resolve().parents[1] / "scripts" / "finalize_stale_sessions.py"
    # 拼接占位串，避免静态凭据扫描器把它当成真实配置。
    placeholder = "postgresql+psycopg://" + "user" + ":" + "pass" + "@localhost:5432/quiz"
    for sessions, expected in (
        ("34,34", "INVALID_SESSIONS"),
        ("34,abc", "INVALID_SESSIONS"),
        ("34", "EXPLICIT_POSTGRESQL_REQUIRED"),
    ):
        result = subprocess.run(
            [sys.executable, str(cli), "--sessions", sessions, "--apply"],
            env={**os.environ, "DATABASE_URL": placeholder},
            capture_output=True, text=True, timeout=30,
        )
        # 连接层拒绝也必须按固定分类回显，不能退化成 FINALIZE_OPERATION_FAILED。
        assert result.returncode == 2 and expected in result.stderr, result.stderr
