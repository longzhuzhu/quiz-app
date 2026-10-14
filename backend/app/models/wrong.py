"""SQLAlchemy 2.x 数据模型 - WrongAnswer, UserQuestionStat"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# 连对达标阈值：一道错题连续答对达到此值即标记为已掌握，退出错题本。
# 放在模型层是因为它属于数据语义，判分链路与错题接口都要引用。
MASTERY_CORRECT_STREAK = 2


class WrongAnswer(Base):
    __tablename__ = "wrong_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    wrong_count: Mapped[int] = mapped_column(Integer, default=1)
    last_wrong_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    # 连对次数：连续答对的计数，达到 MASTERY_CORRECT_STREAK 即自动掌握。
    # 任何一次答错（含本场改答到错）都归零；只有该场首次成功提交的答对才加一，
    # 模拟考试既不加入也不归零。server_default 让存量行取 0 而非 NULL，避免参与算术时被污染。
    correct_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # 最近一次错误答案：该题最近一次成功提交的错误选择，后来答对也不覆写；
    # 为空表示没有可靠的错误作答证据（旧数据或仅由旧路径写入）。
    last_wrong_answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 产生上一次错误答案的答题会话，用于排除尚未结束的模拟考试证据
    last_wrong_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 关系
    user = relationship("User", back_populates="wrong_answers")
    question = relationship("Question")

    __table_args__ = (
        UniqueConstraint("user_id", "question_id"),
    )


class UserQuestionStat(Base):
    __tablename__ = "user_question_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    answer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # 关系
    user = relationship("User", back_populates="question_stats")
    question = relationship("Question", back_populates="user_stats")

    __table_args__ = (
        UniqueConstraint("user_id", "question_id"),
        Index("idx_user_question_stats_lookup", "user_id", "question_id"),
    )
