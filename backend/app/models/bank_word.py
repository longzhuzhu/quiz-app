"""SQLAlchemy 2.x 数据模型 - BankWordFrequency, UserBankWordProgress, BankWordExclusion"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BankWordFrequency(Base):
    __tablename__ = "bank_word_frequencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    term_zh: Mapped[str | None] = mapped_column(String(200), nullable=True)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False)
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
    bank = relationship("QuestionBank", back_populates="word_frequencies")

    __table_args__ = (
        UniqueConstraint("bank_id", "term"),
        Index("idx_bank_word_frequency_bank_frequency", "bank_id", "frequency"),
    )


class UserBankWordProgress(Base):
    __tablename__ = "user_bank_word_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    is_mastered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    user = relationship("User", back_populates="bank_word_progress_entries")
    bank = relationship("QuestionBank", back_populates="word_progress_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "bank_id", "term"),
        Index("idx_user_bank_word_progress_lookup", "user_id", "bank_id", "term"),
    )


class BankWordExclusion(Base):
    __tablename__ = "bank_word_exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    bank = relationship("QuestionBank", back_populates="word_exclusions")
    creator = relationship("User", back_populates="created_word_exclusions")

    __table_args__ = (
        UniqueConstraint("bank_id", "term"),
        Index("idx_bank_word_exclusion_lookup", "bank_id", "term"),
    )
