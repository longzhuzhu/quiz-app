"""练习日写入：本地日校验、同日幂等、跨日改答不偷走。"""

from __future__ import annotations

import sys
from datetime import date, timedelta
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
    PracticeDayQuestion,
    Question,
    QuestionBank,
    QuizAnswer,
    QuizSession,
    User,
)
from app.schemas.quiz import QuizAnswerRequest  # noqa: E402
from app.services.practice_service import (  # noqa: E402
    clear_practice_days,
    coerce_local_date,
    heatmap_for,
    is_acceptable_local_date,
    record_question_touch,
)


UTC_TODAY = date(2026, 9, 9)


def _session_factory(autoflush=True):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=autoflush)()


def _seed(db):
    user = User(username="alice", email="alice@example.com", password_hash="hash")
    db.add(user)
    db.flush()
    exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="库", question_count=2, exam_id=exam.id)
    db.add(bank)
    db.flush()
    q1 = Question(
        bank_id=bank.id,
        question_type="single",
        content="Q1",
        options=[{"key": "A", "text": "A"}],
        correct_answer="A",
        order_index=1,
    )
    q2 = Question(
        bank_id=bank.id,
        question_type="single",
        content="Q2",
        options=[{"key": "A", "text": "A"}],
        correct_answer="A",
        order_index=2,
    )
    db.add_all([q1, q2])
    db.flush()
    return user, exam, bank, q1, q2


def _day_count(db, user_id, exam_id, local_date):
    return (
        db.query(PracticeDayQuestion)
        .filter_by(user_id=user_id, exam_id=exam_id, local_date=local_date)
        .count()
    )


def test_coerce_local_date_rejects_missing_and_illegal():
    assert coerce_local_date(None) is None
    assert coerce_local_date("") is None
    assert coerce_local_date("not-a-date") is None
    assert coerce_local_date("2026/09/09") is None
    assert coerce_local_date("2026-09-09") == date(2026, 9, 9)
    assert coerce_local_date(date(2026, 9, 9)) == date(2026, 9, 9)


def test_local_date_window_accepts_plus_minus_one_utc_day():
    assert is_acceptable_local_date(UTC_TODAY, UTC_TODAY) is True
    assert is_acceptable_local_date(UTC_TODAY - timedelta(days=1), UTC_TODAY) is True
    assert is_acceptable_local_date(UTC_TODAY + timedelta(days=1), UTC_TODAY) is True
    assert is_acceptable_local_date(UTC_TODAY - timedelta(days=2), UTC_TODAY) is False
    assert is_acceptable_local_date(UTC_TODAY + timedelta(days=2), UTC_TODAY) is False


def test_invalid_local_date_on_answer_request_does_not_raise():
    data = QuizAnswerRequest(
        session_id=1,
        question_id=1,
        user_answer="A",
        local_date="not-a-date",
    )
    assert data.local_date is None

    missing = QuizAnswerRequest(session_id=1, question_id=1, user_answer="A")
    assert missing.local_date is None


def test_missing_or_illegal_date_does_not_write_practice_day():
    db = _session_factory()
    user, exam, _bank, q1, _q2 = _seed(db)

    assert record_question_touch(db, user.id, exam.id, q1.id, None, utc_today=UTC_TODAY) is False
    assert record_question_touch(db, user.id, exam.id, q1.id, "nope", utc_today=UTC_TODAY) is False
    assert record_question_touch(
        db, user.id, exam.id, q1.id, date(2026, 9, 7), utc_today=UTC_TODAY
    ) is False
    db.commit()
    assert db.query(PracticeDayQuestion).count() == 0


def test_same_question_same_day_second_touch_does_not_increase_count():
    db = _session_factory()
    user, exam, _bank, q1, _q2 = _seed(db)

    assert record_question_touch(db, user.id, exam.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY) is True
    assert record_question_touch(db, user.id, exam.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY) is True
    db.commit()

    assert _day_count(db, user.id, exam.id, UTC_TODAY) == 1
    heatmap = heatmap_for(db, user.id, exam.id, UTC_TODAY)
    assert heatmap["days"] == [{"date": "2026-09-09", "count": 1}]


def test_same_question_on_two_days_counts_once_each_day():
    db = _session_factory()
    user, exam, _bank, q1, q2 = _seed(db)
    monday = date(2026, 9, 7)
    tuesday = date(2026, 9, 8)

    record_question_touch(db, user.id, exam.id, q1.id, monday, utc_today=monday)
    record_question_touch(db, user.id, exam.id, q2.id, monday, utc_today=monday)
    # 周二改答周一那题：周一不减，周二该题 +1
    record_question_touch(db, user.id, exam.id, q1.id, tuesday, utc_today=tuesday)
    db.commit()

    assert _day_count(db, user.id, exam.id, monday) == 2
    assert _day_count(db, user.id, exam.id, tuesday) == 1

    heatmap = heatmap_for(db, user.id, exam.id, tuesday)
    by_date = {item["date"]: item["count"] for item in heatmap["days"]}
    assert by_date["2026-09-07"] == 2
    assert by_date["2026-09-08"] == 1


def test_clear_practice_days_empties_heatmap_for_that_exam():
    db = _session_factory()
    user, exam, _bank, q1, _q2 = _seed(db)
    record_question_touch(db, user.id, exam.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY)
    db.commit()

    clear_practice_days(db, user.id, exam.id)
    db.commit()

    heatmap = heatmap_for(db, user.id, exam.id, UTC_TODAY)
    assert heatmap["days"] == []
    assert heatmap["current_streak"] == 0


def test_same_day_retouch_does_not_rollback_pending_answer_update():
    """同题同日再次提交走唯一冲突时，不能把同一事务里的改答 flush 回滚掉。

    生产 Session 是 autoflush=False；练习日 upsert 若在 savepoint 内 flush 全部
    脏对象，唯一冲突回滚 savepoint 会把 QuizAnswer 的改答一并撤掉。
    """
    db = _session_factory(autoflush=False)
    user, exam, bank, q1, _q2 = _seed(db)
    quiz_session = QuizSession(
        user_id=user.id,
        bank_id=bank.id,
        mode="sequential",
        total_questions=1,
        question_ids=f"[{q1.id}]",
    )
    db.add(quiz_session)
    db.flush()
    answer = QuizAnswer(
        session_id=quiz_session.id,
        question_id=q1.id,
        user_answer="A",
        is_correct=True,
    )
    db.add(answer)
    db.flush()
    assert record_question_touch(db, user.id, exam.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY) is True
    db.commit()

    answer.user_answer = "B"
    answer.is_correct = False
    assert record_question_touch(db, user.id, exam.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY) is True
    db.commit()

    db.refresh(answer)
    assert answer.user_answer == "B"
    assert answer.is_correct is False
    assert _day_count(db, user.id, exam.id, UTC_TODAY) == 1


def test_heatmap_and_clear_are_scoped_to_one_exam():
    db = _session_factory()
    user, exam, _bank, q1, _q2 = _seed(db)
    other = Exam(owner_id=user.id, slug="other", name="Other", short_name="OT")
    db.add(other)
    db.flush()

    record_question_touch(db, user.id, exam.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY)
    record_question_touch(db, user.id, other.id, q1.id, UTC_TODAY, utc_today=UTC_TODAY)
    db.commit()

    mine = heatmap_for(db, user.id, exam.id, UTC_TODAY)
    theirs = heatmap_for(db, user.id, other.id, UTC_TODAY)
    assert mine["days"] == [{"date": "2026-09-09", "count": 1}]
    assert theirs["days"] == [{"date": "2026-09-09", "count": 1}]
    assert mine["current_streak"] == 1

    clear_practice_days(db, user.id, exam.id)
    db.commit()

    assert heatmap_for(db, user.id, exam.id, UTC_TODAY)["days"] == []
    assert heatmap_for(db, user.id, other.id, UTC_TODAY)["days"] == [
        {"date": "2026-09-09", "count": 1}
    ]
