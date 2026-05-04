"""SQLAlchemy 2.x 数据模型 - ImportParsedQuestion"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImportParsedQuestion(Base):
    __tablename__ = "import_parsed_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_jobs.id"), nullable=False
    )
    chunk_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_chunks.id"), nullable=True
    )

    source_question_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    scenario_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    correct_answer: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    source_evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    llm_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    final_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    issues_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duplicate_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    import_status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")

    imported_question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # 关系
    import_job = relationship("ImportJob")
    chunk = relationship("ImportChunk")

    __table_args__ = (
        Index("idx_import_parsed_questions_job_id", "import_job_id"),
        Index("idx_import_parsed_questions_review_status", "review_status"),
        Index("idx_import_parsed_questions_import_status", "import_status"),
    )
