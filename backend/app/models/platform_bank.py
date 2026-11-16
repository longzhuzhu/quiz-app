"""SQLAlchemy 2.x 数据模型 - 平台题库来源、草稿题与发布版本

平台内容独立于任何个人考试项目：
- PlatformBank 只记录草稿元数据与目录可选用状态，创建者只是审计署名，不是所有者。
- PlatformDraftQuestion 只供管理员维护与导入适配写入，不进入个人题目表。
- PlatformBankRelease 保存不可变、完整的发布快照，个人副本只记录其来源与版本标识。
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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
from app.core.db_types import JSONType

# 快照结构版本：以后改变 payload 结构时递增，读取方据此拒绝未知版本。
PLATFORM_RELEASE_SCHEMA_VERSION = 1


def _uuid_str() -> str:
    return str(uuid4())


class PlatformBank(Base):
    """平台题库来源（不归属任何 Exam 或 User 工作空间）"""

    __tablename__ = "platform_banks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 目录是否对该来源开放选用；下架只置 false，不删快照与草稿。
    is_listed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # 审计署名字段：只是记录谁创建，不代表内容所有权，账号删除时解除署名。
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    creator = relationship("User")
    draft_questions = relationship(
        "PlatformDraftQuestion",
        back_populates="platform_bank",
        cascade="all, delete-orphan",
        order_by="PlatformDraftQuestion.order_index",
    )
    releases = relationship(
        "PlatformBankRelease",
        back_populates="platform_bank",
        order_by="PlatformBankRelease.version_number",
    )

    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_platform_banks_name_not_blank"),
        Index("idx_platform_banks_listed", "is_listed"),
    )


class PlatformDraftQuestion(Base):
    """平台草稿题：管理员与导入目标维护的可编辑内容，未发布前不影响目录"""

    __tablename__ = "platform_draft_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_bank_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("platform_banks.id", ondelete="CASCADE"),
        nullable=False,
    )

    question_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[list] = mapped_column(JSONType, nullable=False)
    correct_answer: Mapped[str] = mapped_column(String(20), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # D03：来源考点只是描述数据，不创建 ExamTopic / QuestionTopic，也没有跨项目外键。
    source_topics: Mapped[list | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    platform_bank = relationship("PlatformBank", back_populates="draft_questions")

    __table_args__ = (
        Index("idx_platform_draft_questions_bank", "platform_bank_id", "order_index"),
    )


class PlatformBankRelease(Base):
    """不可变发布版本：完整题面快照，个人副本只读引用"""

    __tablename__ = "platform_bank_releases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    platform_bank_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("platform_banks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 展示元数据与题目内容一起冻结，目录只读取这些列，不投影 payload。
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)

    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=PLATFORM_RELEASE_SCHEMA_VERSION
    )
    payload: Mapped[list] = mapped_column(JSONType, nullable=False)

    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    platform_bank = relationship("PlatformBank", back_populates="releases")

    __table_args__ = (
        UniqueConstraint(
            "platform_bank_id", "version_number", name="uq_platform_bank_releases_version"
        ),
        # 支持 QuestionBank 的组合外键，保证「副本记录的来源与版本确实匹配」。
        UniqueConstraint("id", "platform_bank_id", name="uq_platform_bank_releases_id_bank"),
        CheckConstraint("version_number > 0", name="ck_platform_bank_releases_version_positive"),
        CheckConstraint("question_count >= 0", name="ck_platform_bank_releases_count_non_negative"),
        Index("idx_platform_bank_releases_bank", "platform_bank_id", "version_number"),
    )
