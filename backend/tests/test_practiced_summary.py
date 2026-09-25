"""已刷题目统计：无作答为 0、跨会话/改答去重、考试项目隔离、清空历史归零。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"


from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    Exam,
    Question,
    QuestionBank,
    QuizAnswer,
    QuizSession,
    User,
)
from app.api.routes.quiz import clear_history, practiced_summary  # noqa: E402


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_user(db):
    user = User(username="alice", email="alice@example.com", password_hash="hash")
    db.add(user)
    db.flush()
    return user


def _seed_exam_with_question(db, user, slug, content="Q1"):
    exam = Exam(owner_id=user.id, slug=slug, name=slug.upper(), short_name=slug.upper())
    db.add(exam)
    db.flush()
    bank = QuestionBank(name=f"{slug} 库", question_count=1, exam_id=exam.id)
    db.add(bank)
    db.flush()
    question = Question(
        bank_id=bank.id,
        question_type="single",
        content=content,
        options=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}],
        correct_answer="A",
        order_index=1,
    )
    db.add(question)
    db.flush()
    return exam, bank, question


def _add_session_with_answer(db, user, bank, question, user_answer="A"):
    quiz_session = QuizSession(
        user_id=user.id,
        bank_id=bank.id,
        mode="sequential",
        total_questions=1,
        question_ids=f"[{question.id}]",
    )
    db.add(quiz_session)
    db.flush()
    db.add(QuizAnswer(
        session_id=quiz_session.id,
        question_id=question.id,
        user_answer=user_answer,
        is_correct=user_answer == question.correct_answer,
    ))
    db.flush()
    return quiz_session


def test_no_answers_returns_zero():
    db = _session_factory()
    user = _seed_user(db)
    exam, _bank, _question = _seed_exam_with_question(db, user, "cipt")
    db.commit()

    assert practiced_summary(current_user=user, exam=exam, db=db) == {"practiced_questions": 0}


def test_same_question_across_sessions_and_reanswer_counts_once():
    db = _session_factory()
    user = _seed_user(db)
    exam, bank, question = _seed_exam_with_question(db, user, "cipt")
    first = _add_session_with_answer(db, user, bank, question)
    second = _add_session_with_answer(db, user, bank, question)
    db.commit()

    # 同会话改答只更新原行（submit_answer 行为），不产生新的作答记录
    answer = db.query(QuizAnswer).filter_by(session_id=first.id, question_id=question.id).one()
    answer.user_answer = "B"
    answer.is_correct = False
    db.commit()

    assert practiced_summary(current_user=user, exam=exam, db=db) == {"practiced_questions": 1}


def test_answers_in_other_exam_do_not_count():
    db = _session_factory()
    user = _seed_user(db)
    cipt, _cipt_bank, _cipt_question = _seed_exam_with_question(db, user, "cipt")
    other, other_bank, other_question = _seed_exam_with_question(db, user, "other", content="Other Q")
    _add_session_with_answer(db, user, other_bank, other_question)
    db.commit()

    assert practiced_summary(current_user=user, exam=cipt, db=db) == {"practiced_questions": 0}
    assert practiced_summary(current_user=user, exam=other, db=db) == {"practiced_questions": 1}


def test_clear_history_resets_practiced_to_zero():
    db = _session_factory()
    user = _seed_user(db)
    exam, bank, question = _seed_exam_with_question(db, user, "cipt")
    _add_session_with_answer(db, user, bank, question)
    db.commit()
    assert practiced_summary(current_user=user, exam=exam, db=db) == {"practiced_questions": 1}

    clear_history(current_user=user, exam=exam, db=db)
    db.commit()

    assert practiced_summary(current_user=user, exam=exam, db=db) == {"practiced_questions": 0}
