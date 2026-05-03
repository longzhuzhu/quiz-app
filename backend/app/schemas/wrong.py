"""Pydantic schemas - Wrong Answer"""

from pydantic import BaseModel, Field


class WrongAnswerQuestionOut(BaseModel):
    id: int
    bank_id: int
    question_type: str
    content: str
    content_zh: str | None = None
    options: list[dict] = Field(default_factory=list)
    correct_answer: str
    explanation: str | None = None
    explanation_zh: str | None = None


class WrongAnswerOut(BaseModel):
    id: int
    question_id: int
    wrong_count: int
    last_wrong_at: str
    question: WrongAnswerQuestionOut


class WrongPracticeResponse(BaseModel):
    session: dict
    questions: list[dict]


class WrongStatsResponse(BaseModel):
    unresolved: int
    resolved: int
    total: int
