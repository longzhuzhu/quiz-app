"""提交答案不得被练习正确率快照的共享行锁卡住。

practice_accuracy_days 按 (user_id, exam_id, local_date) 唯一。
每次带 local_date 的提交都会更新同一行；若该行被其它事务锁住且
PostgreSQL lock_timeout=0，提交会一直等到锁释放——实测 8s 锁 → 提交约 8s。
答题主路径必须先提交作答，不能跟这块共享热点绑在同一段等待上。
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.api.routes.quiz import submit_answer  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.exam import Exam  # noqa: E402
from app.services.exam_service import delete_exam_data  # noqa: E402
from app.models.practice import PracticeAccuracyDay, PracticeDayQuestion  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.question_bank import QuestionBank  # noqa: E402
from app.models.quiz import QuizAnswer, QuizSession  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.quiz import QuizAnswerRequest  # noqa: E402


pytestmark = pytest.mark.skipif(
    "postgresql" not in (settings.DATABASE_URL or ""),
    reason="需要真实 PostgreSQL 才能复现行锁等待",
)

HOLD_SECONDS = 2.0
SUBMIT_BUDGET_SECONDS = 0.8


def _seed(db):
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"locklat_{suffix}",
        email=f"locklat_{suffix}@example.com",
        password_hash="hash",
    )
    db.add(user)
    db.flush()
    exam = Exam(owner_id=user.id, slug=f"locklat-{suffix}", name="LockLat", short_name="LL")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="库", question_count=1, exam_id=exam.id)
    db.add(bank)
    db.flush()
    question = Question(
        bank_id=bank.id,
        question_type="single",
        content="Q1",
        options=[{"key": "A", "text": "A"}, {"key": "B", "text": "B"}],
        correct_answer="A",
        order_index=1,
    )
    db.add(question)
    db.flush()
    session = QuizSession(
        user_id=user.id,
        bank_id=bank.id,
        mode="sequential",
        total_questions=1,
        question_ids=json.dumps([question.id]),
    )
    db.add(session)
    db.flush()
    today = datetime.now(timezone.utc).date()
    db.add(
        PracticeAccuracyDay(
            user_id=user.id,
            exam_id=exam.id,
            local_date=today,
            accuracy=50.0,
            sample_size=2,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.refresh(user)
    db.refresh(exam)
    db.refresh(question)
    db.refresh(session)
    return user, exam, question, session, today


def _cleanup(user_id: int) -> None:
    db = SessionLocal()
    try:
        for exam in db.query(Exam).filter_by(owner_id=user_id).all():
            delete_exam_data(db, exam)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _hold_accuracy_row(user_id: int, exam_id: int, local_date: date, started: threading.Event):
    holder = SessionLocal()
    try:
        holder.execute(
            text(
                "UPDATE practice_accuracy_days "
                "SET sample_size = sample_size "
                "WHERE user_id = :u AND exam_id = :e AND local_date = :d"
            ),
            {"u": user_id, "e": exam_id, "d": local_date},
        )
        started.set()
        holder.execute(text("SELECT pg_sleep(:s)"), {"s": HOLD_SECONDS})
        holder.commit()
    finally:
        holder.close()


def test_submit_answer_does_not_block_on_accuracy_day_row_lock():
    setup = SessionLocal()
    user = exam = question = session = today = None
    try:
        user, exam, question, session, today = _seed(setup)
    finally:
        setup.close()

    started = threading.Event()
    holder = threading.Thread(
        target=_hold_accuracy_row,
        args=(user.id, exam.id, today, started),
        daemon=True,
    )
    submit_db = SessionLocal()
    try:
        holder.start()
        assert started.wait(timeout=2.0)

        payload = QuizAnswerRequest(
            session_id=session.id,
            question_id=question.id,
            user_answer="A",
            local_date=today.isoformat(),
        )
        t0 = time.perf_counter()
        result = submit_answer(payload, current_user=user, exam=exam, db=submit_db)
        elapsed = time.perf_counter() - t0

        assert result["is_correct"] is True
        assert elapsed < SUBMIT_BUDGET_SECONDS, (
            f"提交被 practice_accuracy_days 行锁卡住 {elapsed:.3f}s，"
            f"预算 {SUBMIT_BUDGET_SECONDS}s（锁持有 {HOLD_SECONDS}s）"
        )

        verify = SessionLocal()
        try:
            answer = (
                verify.query(QuizAnswer)
                .filter_by(session_id=session.id, question_id=question.id)
                .one()
            )
            assert answer.user_answer == "A"
            assert answer.is_correct is True
        finally:
            verify.close()
    finally:
        submit_db.close()
        holder.join(timeout=HOLD_SECONDS + 2)
        _cleanup(user.id)


def test_submit_answer_still_writes_practice_stats_without_lock():
    setup = SessionLocal()
    user = exam = question = session = today = None
    try:
        user, exam, question, session, today = _seed(setup)
    finally:
        setup.close()

    submit_db = SessionLocal()
    try:
        payload = QuizAnswerRequest(
            session_id=session.id,
            question_id=question.id,
            user_answer="A",
            local_date=today.isoformat(),
        )
        result = submit_answer(payload, current_user=user, exam=exam, db=submit_db)
        assert result["is_correct"] is True
    finally:
        submit_db.close()

    verify = SessionLocal()
    try:
        touch = (
            verify.query(PracticeDayQuestion)
            .filter_by(user_id=user.id, exam_id=exam.id, local_date=today, question_id=question.id)
            .one_or_none()
        )
        assert touch is not None
        snapshot = (
            verify.query(PracticeAccuracyDay)
            .filter_by(user_id=user.id, exam_id=exam.id, local_date=today)
            .one()
        )
        assert snapshot.sample_size >= 1
        assert snapshot.accuracy == 100.0
    finally:
        verify.close()
        _cleanup(user.id)
