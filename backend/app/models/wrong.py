"""SQLAlchemy 2.x 数据模型 - WrongAnswer, UserQuestionStat"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WrongAnswer(Base):
    __tablename__ = "wrong_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    wrong_count: Mapped[int] = mapped_column(Integer, default=1)
    last_wrong_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    # 关系
    user = relationship("User", back_populates="wrong_answers")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("user_id", "question_id"),
    )


class UserQuestionStat(Base):
    __tablename__ = "user_question_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # 关系
    user = relationship("User", back_populates="question_stats")
    question = relationship("Question", back_populates="user_stats")

    __table_args__ = (
        UniqueConstraint("user_id", "question_id"),
        Index("idx_user_question_stats_lookup", "user_id", "question_id"),
    )
