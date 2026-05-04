"""SQLAlchemy 2.x 数据模型 - ImportJob"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False
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

    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    background_job = relationship("BackgroundJob")
    creator = relationship("User")

    __table_args__ = (
        Index("idx_import_jobs_bank_id", "bank_id"),
        Index("idx_import_jobs_status", "status"),
        Index("idx_import_jobs_file_hash", "file_hash"),
    )
