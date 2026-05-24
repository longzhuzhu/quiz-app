"""SQLAlchemy 2.x 数据模型 - Exam"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_name: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-US")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    importer_profile: Mapped[str] = mapped_column(String(50), nullable=False, default="examtopics-pdf")
    ai_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quiz_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner = relationship("User", back_populates="owned_exams", foreign_keys=[owner_id])
    banks = relationship("QuestionBank", back_populates="exam", lazy="dynamic")
    vocabularies = relationship("Vocabulary", back_populates="exam", lazy="dynamic")

    __table_args__ = (
        UniqueConstraint("owner_id", "slug", name="uq_exams_owner_slug"),
        Index("ix_exams_owner_sort", "owner_id", "sort_order"),
    )
