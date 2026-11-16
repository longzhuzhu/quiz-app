"""SQLAlchemy 2.x 数据模型 - ImportParsedQuestion"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from app.core.db_types import JSONType
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
    options_json: Mapped[list] = mapped_column(JSONType, nullable=False)
    correct_answer: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_json: Mapped[list | None] = mapped_column(JSONType, nullable=True)

    source_evidence_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    llm_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    final_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    issues_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    duplicate_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    import_status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")

    # 个人目标题指针（普通整数，保持既有语义）。
    imported_question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 平台草稿题指针：草稿题被手工删除时 SET NULL，历史审计记录保留。
    imported_platform_question_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("platform_draft_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 平台任务「确实新增过题目」的历史证据；草稿题被删除后不清标记，
    # 因此新增计数不能退化为「当前草稿题指针数量」。
    inserted_new: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # 关系
    import_job = relationship("ImportJob")
    chunk = relationship("ImportChunk")
    platform_question = relationship("PlatformDraftQuestion")

    __table_args__ = (
        # 两个目标题指针不能同时有值：平台题 ID 不得写进个人题字段。
        CheckConstraint(
            "NOT (imported_question_id IS NOT NULL AND imported_platform_question_id IS NOT NULL)",
            name="ck_import_parsed_questions_single_pointer",
        ),
        Index("idx_import_parsed_questions_job_id", "import_job_id"),
        Index("idx_import_parsed_questions_review_status", "review_status"),
        Index("idx_import_parsed_questions_import_status", "import_status"),
        Index(
            "idx_import_parsed_questions_platform_question",
            "imported_platform_question_id",
        ),
    )
