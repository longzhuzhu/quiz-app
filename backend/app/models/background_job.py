"""SQLAlchemy 2.x 数据模型 - BackgroundJob"""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    subject_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    active_scope_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 平台导入/重解析没有个人项目归属；创建者只是审计署名，平台任务允许为空。
    platform_bank_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_banks.id"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    creator = relationship("User", back_populates="background_jobs")
    platform_bank = relationship("PlatformBank")

    __table_args__ = (
        # 平台任务可以没有作者；个人后台任务仍必须有作者。
        CheckConstraint(
            "platform_bank_id IS NOT NULL OR created_by IS NOT NULL",
            name="ck_background_jobs_platform_author",
        ),
        UniqueConstraint("active_scope_key", name="uq_background_jobs_active_scope_key"),
        Index("idx_background_jobs_status_next_run", "status", "next_run_at"),
        Index("idx_background_jobs_status_lease", "status", "lease_until"),
        Index("idx_background_jobs_type_created_at", "job_type", "created_at"),
        Index("idx_background_jobs_platform_bank", "platform_bank_id", "status"),
    )
