"""SQLAlchemy 2.x 数据模型 - Question"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from app.core.db_types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False
    )
    question_type: Mapped[str] = mapped_column(String(20), nullable=False)  # single/multiple/truefalse
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSONType, nullable=False)  # JSON 存储（PostgreSQL 为 JSONB），兼容前端解析
    correct_answer: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    bank = relationship("QuestionBank", back_populates="questions")
    user_stats = relationship(
        "UserQuestionStat", back_populates="question", lazy="dynamic", cascade="all, delete-orphan"
    )
    topic_links = relationship(
        "QuestionTopic", back_populates="question", cascade="all, delete-orphan"
    )
