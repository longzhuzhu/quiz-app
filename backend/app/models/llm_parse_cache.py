"""SQLAlchemy 2.x 数据模型 - LlmParseCache"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LlmParseCache(Base):
    __tablename__ = "llm_parse_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_llm_parse_cache_chunk_hash", "chunk_hash"),
    )
