import sys
from datetime import datetime, timezone, timedelta
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
from app.models import Exam, Question, QuestionBank, QuizAnswer, QuizSession, User  # noqa: E402
from app.api.routes.quiz import history  # noqa: E402


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    return TestingSessionLocal()


def _seed_user_exam_bank(db):
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="hash",
    )
    db.add(user)
    db.flush()

    exam = Exam(
        owner_id=user.id,
        slug="cipt",
        name="CIPT",
        short_name="CIPT",
    )
    db.add(exam)
    db.flush()

    older_bank = QuestionBank(name="较早题库", question_count=1, exam_id=exam.id)
    newer_bank = QuestionBank(name="较新题库", question_count=1, exam_id=exam.id)
    db.add_all([older_bank, newer_bank])
    db.flush()

    question = Question(
        bank_id=older_bank.id,
        question_type="single",
        content="Question 1",
        options=[{"key": "A", "text": "A"}],
        correct_answer="A",
        order_index=1,
    )
    db.add(question)
    db.flush()
    return user, exam, older_bank, newer_bank, question


def test_history_orders_incomplete_sessions_by_recent_answer_activity():
    db = _session_factory()
    user, exam, older_bank, newer_bank, question = _seed_user_exam_bank(db)
    base_time = datetime(2026, 9, 7, tzinfo=timezone.utc)

    older_created_recently_answered = QuizSession(
        user_id=user.id,
        bank_id=older_bank.id,
        mode="sequential",
        total_questions=1,
        answered_count=1,
        correct_count=1,
        is_completed=False,
        question_ids=f"[{question.id}]",
        created_at=base_time,
    )
    newer_created_not_answered = QuizSession(
        user_id=user.id,
        bank_id=newer_bank.id,
        mode="sequential",
        total_questions=1,
        answered_count=0,
        correct_count=0,
        is_completed=False,
        question_ids="[]",
        created_at=base_time + timedelta(minutes=10),
    )
    db.add_all([older_created_recently_answered, newer_created_not_answered])
    db.flush()

    db.add(QuizAnswer(
        session_id=older_created_recently_answered.id,
        question_id=question.id,
        user_answer="A",
        is_correct=True,
        answered_at=base_time + timedelta(minutes=20),
    ))
    db.commit()

    result = history(page=1, per_page=10, current_user=user, exam=exam, db=db)

    assert result["items"][0]["id"] == older_created_recently_answered.id
    assert result["items"][0]["bank_name"] == "较早题库"


def test_history_uses_created_at_for_sessions_without_answers():
    db = _session_factory()
    user, exam, older_bank, newer_bank, question = _seed_user_exam_bank(db)
    base_time = datetime(2026, 9, 7, tzinfo=timezone.utc)

    older_session = QuizSession(
        user_id=user.id,
        bank_id=older_bank.id,
        mode="sequential",
        total_questions=1,
        question_ids=f"[{question.id}]",
        created_at=base_time,
    )
    newer_session = QuizSession(
        user_id=user.id,
        bank_id=newer_bank.id,
        mode="sequential",
        total_questions=1,
        question_ids="[]",
        created_at=base_time + timedelta(minutes=10),
    )
    db.add_all([older_session, newer_session])
    db.commit()

    result = history(page=1, per_page=10, current_user=user, exam=exam, db=db)

    assert result["items"][0]["id"] == newer_session.id
    assert result["items"][0]["bank_name"] == "较新题库"
