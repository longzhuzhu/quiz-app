"""SQLAlchemy 2.x 数据模型 - VectorIndex（预留，Phase 3 启用 pgvector）

本阶段仅建表，不使用 embedding 列。
Phase 3 迁移将添加 pgvector 扩展和 embedding VECTOR(1536) 列。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VectorIndex(Base):
    __tablename__ = "vector_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    vector_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(128), nullable=False)
    bank_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=True
    )

    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # embedding VECTOR(1536) — Phase 3 迁移添加

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_vector_index_type", "vector_type"),
        Index("idx_vector_index_bank_id", "bank_id"),
    )
