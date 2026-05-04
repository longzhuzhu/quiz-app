"""SQLAlchemy 2.x 数据模型 - User"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    quiz_sessions = relationship("QuizSession", back_populates="user", lazy="dynamic")
    wrong_answers = relationship("WrongAnswer", back_populates="user", lazy="dynamic")
    question_stats = relationship(
        "UserQuestionStat", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )
    vocabularies = relationship("Vocabulary", back_populates="user", lazy="dynamic")
    vocab_progress_entries = relationship(
        "UserVocabProgress", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )
    bank_word_progress_entries = relationship(
        "UserBankWordProgress", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )
    created_word_exclusions = relationship(
        "BankWordExclusion", back_populates="creator", lazy="dynamic"
    )
    background_jobs = relationship(
        "BackgroundJob", back_populates="creator", lazy="dynamic"
    )
