"""SQLAlchemy 2.x 数据模型 - ExamTopic（考点）"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

TOPIC_LEVEL_DOMAIN = 1
TOPIC_LEVEL_COMPETENCY = 2


class ExamTopic(Base):
    """考试大纲中的考点，两层：level 1 为域，level 2 为其下的能力项。

    题目只关联 level 2；域的题目集合由其子考点并集得出。
    """

    __tablename__ = "exam_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("exam_topics.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    short_name_zh: Mapped[str] = mapped_column(String(40), nullable=False)
    blueprint_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blueprint_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 表现指标原文，只用于拼装 AI 打标 prompt，不作为可选考点暴露
    indicators_en: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    exam = relationship("Exam", back_populates="topics")
    parent = relationship("ExamTopic", back_populates="children", remote_side=[id])
    children = relationship(
        "ExamTopic", back_populates="parent", cascade="all, delete-orphan"
    )
    question_links = relationship(
        "QuestionTopic", back_populates="topic", lazy="dynamic", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("exam_id", "code", name="uq_exam_topics_exam_code"),
        Index("idx_exam_topics_exam_level_order", "exam_id", "level", "order_index"),
    )
