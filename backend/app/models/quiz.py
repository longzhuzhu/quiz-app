"""SQLAlchemy 2.x 数据模型 - QuizSession, QuizAnswer"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from app.core.db_types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class QuizSession(Base):
    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("question_banks.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # sequential/random/exam/wrong_practice/topic
    # 仅 mode="topic" 使用：指向所练的一级考点；为空表示练未分类题目
    topic_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("exam_topics.id", ondelete="SET NULL"), nullable=True
    )
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    question_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: 题目 ID 列表
    # 本场题目快照，与 question_ids 同序；只含判分依据（题干/选项/题型/当场正确答案），
    # 不含翻译与 AI 解析。为空表示迁移前的旧会话，不做回填。
    question_snapshot: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    # 完成时冻结的各题最终作答与判定，键为字符串题号；显式 null 表示该题未答。
    # 未完成会话为 NULL；题目被删除后仍可读出该题判定。
    final_answers: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    user = relationship("User", back_populates="quiz_sessions")
    bank = relationship("QuestionBank", back_populates="sessions")
    topic = relationship("ExamTopic")
    answers = relationship(
        "QuizAnswer", back_populates="session", lazy="dynamic", cascade="all, delete-orphan"
    )


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quiz_sessions.id"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    user_answer: Mapped[str] = mapped_column(String(20), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 本次页面内首次成功提交的耗时；缺省/旧记录为未知，改答不覆盖。
    answer_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # 关系
    session = relationship("QuizSession", back_populates="answers")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("session_id", "question_id"),
    )
