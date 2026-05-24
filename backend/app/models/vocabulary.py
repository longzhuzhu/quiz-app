"""SQLAlchemy 2.x 数据模型 - Vocabulary, UserVocabProgress"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Vocabulary(Base):
    __tablename__ = "vocabularies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    term_zh: Mapped[str | None] = mapped_column(String(200), nullable=True)
    definition_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # True=专业词汇, False=用户个人
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    exam_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("exams.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    user = relationship("User", back_populates="vocabularies")
    exam = relationship("Exam", back_populates="vocabularies")
    progress_entries = relationship(
        "UserVocabProgress", back_populates="vocabulary", lazy="dynamic", cascade="all, delete-orphan"
    )


class UserVocabProgress(Base):
    __tablename__ = "user_vocab_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    vocabulary_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vocabularies.id"), nullable=False
    )
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
    user = relationship("User", back_populates="vocab_progress_entries")
    vocabulary = relationship("Vocabulary", back_populates="progress_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "vocabulary_id"),
    )
