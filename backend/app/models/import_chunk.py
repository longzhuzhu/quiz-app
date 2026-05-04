"""SQLAlchemy 2.x 数据模型 - ImportChunk"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImportChunk(Base):
    __tablename__ = "import_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_jobs.id"), nullable=False
    )

    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    llm_request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    llm_response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    issues_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # 关系
    import_job = relationship("ImportJob")

    __table_args__ = (
        Index("idx_import_chunks_job_id", "import_job_id"),
        Index("idx_import_chunks_status", "status"),
        Index("idx_import_chunks_hash", "chunk_hash"),
    )
