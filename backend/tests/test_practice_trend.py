"""练习趋势图：滚动正确率快照写入、30 日展开、清历史归零。"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
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
    PracticeAccuracyDay,
    PracticeDayQuestion,
    Question,
    QuestionBank,
    QuizAnswer,
    QuizSession,
    User,
)
from app.services.practice_service import (  # noqa: E402
    TREND_DAYS,
    clear_practice_days,
    recent_accuracy_for,
    record_accuracy_snapshot,
    record_question_touch,
    trend_for,
)


UTC_TODAY = date(2026, 9, 10)
YESTERDAY = UTC_TODAY - timedelta(days=1)
TWO_DAYS_AGO = UTC_TODAY - timedelta(days=2)


def _session_factory(autoflush=True):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=autoflush)()


def _seed(db, question_count=3):
    user = User(username="carol", email="carol@example.com", password_hash="hash")
    db.add(user)
    db.flush()
    exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="库", question_count=question_count, exam_id=exam.id)
    db.add(bank)
    db.flush()
    questions = []
    for index in range(question_count):
        question = Question(
            bank_id=bank.id,
            question_type="single",
            content=f"Q{index + 1}",
            options=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}],
            correct_answer="A",
            order_index=index + 1,
        )
        questions.append(question)
    db.add_all(questions)
    db.flush()
    return user, exam, bank, questions


def _open_session(db, user, bank, questions):
    quiz_session = QuizSession(
        user_id=user.id,
        bank_id=bank.id,
        mode="sequential",
        total_questions=len(questions),
        question_ids="[" + ",".join(str(q.id) for q in questions) + "]",
    )
    db.add(quiz_session)
    db.flush()
    return quiz_session


def _answer(db, quiz_session, question, is_correct, answered_at=None):
    existing = (
        db.query(QuizAnswer)
        .filter_by(session_id=quiz_session.id, question_id=question.id)
        .first()
    )
    if existing:
        existing.user_answer = "A" if is_correct else "B"
        existing.is_correct = is_correct
        existing.answered_at = answered_at or datetime.now(timezone.utc)
        return existing
    row = QuizAnswer(
        session_id=quiz_session.id,
        question_id=question.id,
        user_answer="A" if is_correct else "B",
        is_correct=is_correct,
        answered_at=answered_at or datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def _snapshot(db, user_id, exam_id, local_date):
    return (
        db.query(PracticeAccuracyDay)
        .filter_by(user_id=user_id, exam_id=exam_id, local_date=local_date)
        .one_or_none()
    )


def test_recent_accuracy_for_matches_last_n_existing_answers():
    db = _session_factory()
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)
    _answer(db, quiz_session, questions[0], True)
    _answer(db, quiz_session, questions[1], True)
    _answer(db, quiz_session, questions[2], False)
    db.commit()

    stats = recent_accuracy_for(db, user.id, exam.id, limit=100)
    assert stats["total"] == 3
    assert stats["correct"] == 2
    assert stats["accuracy"] == 66.7
    assert stats["limit"] == 100


def test_valid_local_date_writes_snapshot_and_same_day_updates_only_that_day():
    db = _session_factory()
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)

    _answer(db, quiz_session, questions[0], True)
    _answer(db, quiz_session, questions[1], False)
    assert record_accuracy_snapshot(
        db, user.id, exam.id, YESTERDAY, utc_today=YESTERDAY
    ) is True
    db.commit()

    yesterday = _snapshot(db, user.id, exam.id, YESTERDAY)
    assert yesterday is not None
    assert yesterday.accuracy == 50.0
    assert yesterday.sample_size == 2

    _answer(db, quiz_session, questions[2], True)
    assert record_accuracy_snapshot(
        db, user.id, exam.id, UTC_TODAY, utc_today=UTC_TODAY
    ) is True
    db.commit()

    _answer(db, quiz_session, questions[1], True)
    assert record_accuracy_snapshot(
        db, user.id, exam.id, UTC_TODAY, utc_today=UTC_TODAY
    ) is True
    db.commit()

    yesterday = _snapshot(db, user.id, exam.id, YESTERDAY)
    today = _snapshot(db, user.id, exam.id, UTC_TODAY)
    assert yesterday.accuracy == 50.0
    assert yesterday.sample_size == 2
    assert today.accuracy == 100.0
    assert today.sample_size == 3
    assert db.query(PracticeAccuracyDay).count() == 2


def test_cross_day_reanswer_does_not_rewrite_yesterday_snapshot():
    db = _session_factory()
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)

    _answer(db, quiz_session, questions[0], True)
    _answer(db, quiz_session, questions[1], False)
    record_accuracy_snapshot(db, user.id, exam.id, YESTERDAY, utc_today=YESTERDAY)
    db.commit()

    _answer(db, quiz_session, questions[1], True)
    record_accuracy_snapshot(db, user.id, exam.id, UTC_TODAY, utc_today=UTC_TODAY)
    db.commit()

    yesterday = _snapshot(db, user.id, exam.id, YESTERDAY)
    today = _snapshot(db, user.id, exam.id, UTC_TODAY)
    assert yesterday.accuracy == 50.0
    assert yesterday.sample_size == 2
    assert today.accuracy == 100.0
    assert today.sample_size == 2


def test_invalid_or_missing_local_date_does_not_write_snapshot():
    db = _session_factory()
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)
    _answer(db, quiz_session, questions[0], True)

    assert record_accuracy_snapshot(db, user.id, exam.id, None, utc_today=UTC_TODAY) is False
    assert record_accuracy_snapshot(db, user.id, exam.id, "nope", utc_today=UTC_TODAY) is False
    assert record_accuracy_snapshot(
        db, user.id, exam.id, UTC_TODAY - timedelta(days=2), utc_today=UTC_TODAY
    ) is False
    db.commit()
    assert db.query(PracticeAccuracyDay).count() == 0


def test_snapshot_not_written_when_no_answers():
    db = _session_factory()
    user, exam, _bank, _questions = _seed(db)
    assert record_accuracy_snapshot(db, user.id, exam.id, UTC_TODAY, utc_today=UTC_TODAY) is False
    db.commit()
    assert db.query(PracticeAccuracyDay).count() == 0


def test_trend_for_returns_30_dense_days_with_null_accuracy_when_no_snapshot():
    db = _session_factory()
    user, exam, _bank, questions = _seed(db)
    record_question_touch(db, user.id, exam.id, questions[0].id, UTC_TODAY, utc_today=UTC_TODAY)
    db.commit()

    trend = trend_for(db, user.id, exam.id, UTC_TODAY)
    assert trend["today"] == "2026-09-10"
    assert len(trend["days"]) == TREND_DAYS
    assert trend["days"][0]["date"] == "2026-08-12"
    assert trend["days"][-1]["date"] == "2026-09-10"
    assert all(day["date"] for day in trend["days"])
    rest_days = [day for day in trend["days"] if day["date"] != "2026-09-10"]
    assert all(day["count"] == 0 for day in rest_days)
    assert all(day["accuracy"] is None for day in rest_days)
    assert all(day["sample_size"] == 0 for day in rest_days)
    today = trend["days"][-1]
    assert today["count"] == 1
    assert today["accuracy"] is None
    assert today["sample_size"] == 0


def test_trend_carries_forward_after_snapshot_and_today_uses_live_accuracy():
    db = _session_factory()
    user, exam, bank, questions = _seed(db, question_count=4)
    quiz_session = _open_session(db, user, bank, questions)

    _answer(db, quiz_session, questions[0], True)
    _answer(db, quiz_session, questions[1], False)
    record_question_touch(db, user.id, exam.id, questions[0].id, TWO_DAYS_AGO, utc_today=TWO_DAYS_AGO)
    record_question_touch(db, user.id, exam.id, questions[1].id, TWO_DAYS_AGO, utc_today=TWO_DAYS_AGO)
    record_accuracy_snapshot(db, user.id, exam.id, TWO_DAYS_AGO, utc_today=TWO_DAYS_AGO)
    db.commit()

    _answer(db, quiz_session, questions[2], True)
    _answer(db, quiz_session, questions[3], True)
    db.commit()

    live = recent_accuracy_for(db, user.id, exam.id, limit=100)
    assert live["total"] == 4
    assert live["accuracy"] == 75.0

    trend = trend_for(db, user.id, exam.id, UTC_TODAY)
    by_date = {day["date"]: day for day in trend["days"]}

    assert by_date["2026-08-12"]["accuracy"] is None
    assert by_date["2026-08-12"]["count"] == 0
    assert by_date["2026-09-08"]["count"] == 2
    assert by_date["2026-09-08"]["accuracy"] == 50.0
    assert by_date["2026-09-08"]["sample_size"] == 2
    assert by_date["2026-09-09"]["count"] == 0
    assert by_date["2026-09-09"]["accuracy"] == 50.0
    assert by_date["2026-09-09"]["sample_size"] == 2
    assert by_date["2026-09-10"]["count"] == 0
    assert by_date["2026-09-10"]["accuracy"] == live["accuracy"]
    assert by_date["2026-09-10"]["sample_size"] == live["total"]


def test_trend_carries_snapshot_from_before_window():
    db = _session_factory()
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)
    _answer(db, quiz_session, questions[0], True)
    _answer(db, quiz_session, questions[1], False)
    before_window = UTC_TODAY - timedelta(days=40)
    assert record_accuracy_snapshot(
        db, user.id, exam.id, before_window, utc_today=before_window
    ) is True
    db.commit()

    trend = trend_for(db, user.id, exam.id, UTC_TODAY)
    by_date = {day["date"]: day for day in trend["days"]}
    assert by_date["2026-08-12"]["accuracy"] == 50.0
    assert by_date["2026-08-12"]["count"] == 0
    assert by_date["2026-08-12"]["sample_size"] == 2
    assert by_date["2026-09-09"]["accuracy"] == 50.0
    assert by_date["2026-09-09"]["sample_size"] == 2
    live = recent_accuracy_for(db, user.id, exam.id, limit=100)
    assert by_date["2026-09-10"]["accuracy"] == live["accuracy"]
    assert by_date["2026-09-10"]["sample_size"] == live["total"]


def test_clear_practice_days_empties_trend_snapshots():
    db = _session_factory()
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)
    _answer(db, quiz_session, questions[0], True)
    record_question_touch(db, user.id, exam.id, questions[0].id, UTC_TODAY, utc_today=UTC_TODAY)
    record_accuracy_snapshot(db, user.id, exam.id, UTC_TODAY, utc_today=UTC_TODAY)
    db.commit()

    db.delete(quiz_session)
    clear_practice_days(db, user.id, exam.id)
    db.commit()

    assert db.query(PracticeAccuracyDay).count() == 0
    assert db.query(PracticeDayQuestion).count() == 0
    trend = trend_for(db, user.id, exam.id, UTC_TODAY)
    assert all(day["count"] == 0 for day in trend["days"])
    assert all(day["accuracy"] is None for day in trend["days"])


def test_snapshot_insert_does_not_rollback_pending_answer():
    db = _session_factory(autoflush=False)
    user, exam, bank, questions = _seed(db)
    quiz_session = _open_session(db, user, bank, questions)
    answer = QuizAnswer(
        session_id=quiz_session.id,
        question_id=questions[0].id,
        user_answer="A",
        is_correct=True,
    )
    db.add(answer)
    assert record_accuracy_snapshot(
        db, user.id, exam.id, UTC_TODAY, utc_today=UTC_TODAY
    ) is True
    db.commit()

    db.refresh(answer)
    assert answer.is_correct is True
    assert _snapshot(db, user.id, exam.id, UTC_TODAY).sample_size == 1
