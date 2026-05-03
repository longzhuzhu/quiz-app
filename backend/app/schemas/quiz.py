"""Pydantic schemas - Quiz"""

from datetime import datetime

from pydantic import BaseModel, Field


class QuizStartRequest(BaseModel):
    bank_id: int
    mode: str = "sequential"
    question_count: int | None = None


class QuizAnswerRequest(BaseModel):
    session_id: int
    question_id: int
    user_answer: str


class QuizFinishRequest(BaseModel):
    session_id: int


class QuizQuestionOut(BaseModel):
    id: int
    question_type: str
    content: str
    content_zh: str | None = None
    options: list[dict] = Field(default_factory=list)
    explanation: str | None = None
    explanation_zh: str | None = None
    user_answer_count: int = 0
    answered: bool | None = None  # 仅 session_detail 未完成会话时使用


class QuizSessionOut(BaseModel):
    id: int
    bank_id: int
    bank_name: str | None = None
    mode: str
    total_questions: int
    answered_count: int = 0
    correct_count: int = 0
    is_completed: bool = False
    accuracy: float | None = None
    created_at: str | None = None
    completed_at: str | None = None


class QuizStartResponse(BaseModel):
    session: QuizSessionOut
    questions: list[QuizQuestionOut]


class QuizAnswerResponse(BaseModel):
    is_correct: bool | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    explanation_zh: str | None = None
    user_answer_count: int = 0
    counted_as_new_attempt: bool = False
    submitted: bool | None = None  # exam 模式


class QuizFinishResponse(BaseModel):
    session: QuizSessionOut


class QuizSessionDetailResponse(BaseModel):
    session: QuizSessionOut
    answers: list[dict] = Field(default_factory=list)
    questions: list[QuizQuestionOut] | None = None


class HistoryItemOut(BaseModel):
    id: int
    bank_id: int
    bank_name: str
    mode: str
    total_questions: int
    answered_count: int
    correct_count: int
    is_completed: bool
    accuracy: float
    created_at: str
    completed_at: str | None


class HistoryListResponse(BaseModel):
    items: list[HistoryItemOut]
    total: int
    page: int
    pages: int
