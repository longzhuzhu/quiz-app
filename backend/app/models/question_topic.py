"""SQLAlchemy 2.x 数据模型 - QuestionTopic（题目与考点的多对多关联）"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

TOPIC_SOURCE_AI = "ai"
TOPIC_SOURCE_MANUAL = "manual"


class QuestionTopic(Base):
    """一道题目与一个考点的关联。

    source 区分来源：批量打标只重建 "ai" 的关联，"manual" 的人工修正不受重跑影响。
    """

    __tablename__ = "question_topics"

    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exam_topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False, default=TOPIC_SOURCE_AI)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    question = relationship("Question", back_populates="topic_links")
    topic = relationship("ExamTopic", back_populates="question_links")

    __table_args__ = (
        Index("idx_question_topics_topic_question", "topic_id", "question_id"),
    )
