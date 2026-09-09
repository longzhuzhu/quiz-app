"""当前连续练习日：今天有练、昨天宽限、空窗为 0、中间断开。"""

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
from app.models import Exam, Question, QuestionBank, User  # noqa: E402
from app.services.practice_service import (  # noqa: E402
    compute_current_streak,
    heatmap_for,
    heatmap_window_start,
    record_question_touch,
)


TODAY = date(2026, 9, 9)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    user = User(username="bob", email="bob@example.com", password_hash="hash")
    db.add(user)
    db.flush()
    exam = Exam(owner_id=user.id, slug="cipt", name="CIPT", short_name="CIPT")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="库", question_count=1, exam_id=exam.id)
    db.add(bank)
    db.flush()
    question = Question(
        bank_id=bank.id,
        question_type="single",
        content="Q1",
        options=[{"key": "A", "text": "A"}],
        correct_answer="A",
        order_index=1,
    )
    db.add(question)
    db.flush()
    return user, exam, question


def test_streak_counts_from_today_when_today_practiced():
    dates = {TODAY - timedelta(days=i) for i in range(3)}
    assert compute_current_streak(dates, TODAY) == 3


def test_streak_grace_uses_yesterday_when_today_empty():
    dates = {TODAY - timedelta(days=1), TODAY - timedelta(days=2)}
    assert compute_current_streak(dates, TODAY) == 2


def test_streak_is_zero_when_yesterday_also_empty():
    dates = {TODAY - timedelta(days=2)}
    assert compute_current_streak(dates, TODAY) == 0
    assert compute_current_streak(set(), TODAY) == 0


def test_streak_breaks_on_a_missing_day():
    dates = {TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=3)}
    assert compute_current_streak(dates, TODAY) == 2


def test_heatmap_for_applies_grace_and_returns_sparse_days():
    db = _session_factory()
    user, exam, question = _seed(db)
    yesterday = TODAY - timedelta(days=1)
    two_days_ago = TODAY - timedelta(days=2)

    record_question_touch(db, user.id, exam.id, question.id, yesterday, utc_today=yesterday)
    record_question_touch(db, user.id, exam.id, question.id, two_days_ago, utc_today=two_days_ago)
    db.commit()

    result = heatmap_for(db, user.id, exam.id, TODAY)
    assert result["today"] == "2026-09-09"
    assert result["current_streak"] == 2
    assert result["days"] == [
        {"date": "2026-09-07", "count": 1},
        {"date": "2026-09-08", "count": 1},
    ]


def test_heatmap_window_starts_on_monday_covering_53_weeks():
    # 2026-09-09 是周三；最后一列周一是 2026-09-07；往前 52 周
    assert heatmap_window_start(TODAY) == date(2025, 9, 8)
    assert heatmap_window_start(TODAY).weekday() == 0
