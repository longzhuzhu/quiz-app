"""SQLAlchemy 2.x 数据模型 - 练习日事实与滚动正确率按日快照"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PracticeDayQuestion(Base):
    """某用户在某考试项目的某个本地日动过的一道题。

    当日作答量 = 同一 (user_id, exam_id, local_date) 下的行数。
    练习日 = 该日行数 ≥ 1。同题同日再提交由唯一约束保证幂等。
    """

    __tablename__ = "practice_day_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exam_id",
            "local_date",
            "question_id",
            name="uq_practice_day_questions_user_exam_date_question",
        ),
        Index(
            "idx_practice_day_questions_user_exam_date",
            "user_id",
            "exam_id",
            "local_date",
        ),
    )


class PracticeAccuracyDay(Base):
    """某用户在某考试项目某个本地日冻结的滚动正确率。

    提交当时写入，只更新该本地日，不从 QuizAnswer.answered_at 回放（ADR-0006）。
    """

    __tablename__ = "practice_accuracy_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exam_id",
            "local_date",
            name="uq_practice_accuracy_days_user_exam_date",
        ),
        Index(
            "idx_practice_accuracy_days_user_exam_date",
            "user_id",
            "exam_id",
            "local_date",
        ),
    )
