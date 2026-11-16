"""SQLAlchemy 2.x 数据模型 - QuestionBank"""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id"), nullable=False, index=True
    )

    # 平台副本的只读来源标识；两者同时为空表示自建库。
    # 来源操作（发布/下架/删除账号）都不级联删除个人副本，因此外键用 RESTRICT。
    source_platform_bank_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_platform_release_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # 关系
    exam = relationship("Exam", back_populates="banks")
    questions = relationship(
        "Question", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
    sessions = relationship("QuizSession", back_populates="bank")
    word_frequencies = relationship(
        "BankWordFrequency", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
    word_progress_entries = relationship(
        "UserBankWordProgress", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )
    word_exclusions = relationship(
        "BankWordExclusion", back_populates="bank", lazy="dynamic", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # 自建库两者都为空；平台副本两者必须同时存在。
        CheckConstraint(
            "(source_platform_bank_id IS NULL) = (source_platform_release_id IS NULL)",
            name="ck_question_banks_source_pair",
        ),
        # 同一项目对同一平台来源最多保留一份副本；自建库的空来源不受限制。
        UniqueConstraint(
            "exam_id", "source_platform_bank_id", name="uq_question_banks_exam_platform_source"
        ),
        # 组合外键保证记录的发布版本确实属于该来源，不能拼凑来源与版本。
        ForeignKeyConstraint(
            ["source_platform_bank_id"],
            ["platform_banks.id"],
            name="fk_question_banks_platform_bank",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_platform_release_id", "source_platform_bank_id"],
            ["platform_bank_releases.id", "platform_bank_releases.platform_bank_id"],
            name="fk_question_banks_platform_release",
            ondelete="RESTRICT",
        ),
    )
