"""SQLAlchemy 2.x 数据模型 - QuizSession, QuizAnswer"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # sequential/random/exam/wrong_practice
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    question_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: 题目 ID 列表
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    user = relationship("User", back_populates="quiz_sessions")
    bank = relationship("QuestionBank", back_populates="sessions")
    answers = relationship(
        "QuizAnswer", back_populates="session", lazy="dynamic", cascade="all, delete-orphan"
    )


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quiz_sessions.id"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    user_answer: Mapped[str] = mapped_column(String(20), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    session = relationship("QuizSession", back_populates="answers")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("session_id", "question_id"),
    )
