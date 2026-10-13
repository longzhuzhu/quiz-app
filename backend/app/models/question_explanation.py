"""每题、每模型的最近成功解析；与正在执行的任务分离。"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuestionExplanation(Base):
    __tablename__ = "question_explanations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str] = mapped_column(String(255))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    judged_answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_zh: Mapped[str] = mapped_column(Text)
    analysis: Mapped[dict] = mapped_column(JSONB)
    generation_id: Mapped[int] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("question_id", "model_id", name="uq_question_explanations_model"),)
