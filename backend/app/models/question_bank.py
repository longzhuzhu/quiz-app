"""SQLAlchemy 2.x 数据模型 - QuestionBank"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id"), nullable=False, index=True
    )

    # 关系
    exam = relationship("Exam", back_populates="banks")
    questions = relationship(
        "Question", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
    sessions = relationship("QuizSession", back_populates="bank")
    word_frequencies = relationship(
        "BankWordFrequency", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
    word_progress_entries = relationship(
        "UserBankWordProgress", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
    word_exclusions = relationship(
        "BankWordExclusion", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
