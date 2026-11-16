"""SQLAlchemy 2.x 数据模型 - ImportJob"""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from app.core.db_types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 双目标：个人题库或平台来源，恰有一个非空（DB CHECK 强制）。
    bank_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=True
    )
    platform_bank_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_banks.id"), nullable=True
    )
    background_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("background_jobs.id"), nullable=True
    )

    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    config_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # 关系
    bank = relationship("QuestionBank")
    platform_bank = relationship("PlatformBank")
    background_job = relationship("BackgroundJob")
    creator = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "(bank_id IS NULL) <> (platform_bank_id IS NULL)",
            name="ck_import_jobs_single_target",
        ),
        Index("idx_import_jobs_bank_id", "bank_id"),
        Index("idx_import_jobs_platform_bank_id", "platform_bank_id"),
        Index("idx_import_jobs_status", "status"),
        Index("idx_import_jobs_file_hash", "file_hash"),
    )
