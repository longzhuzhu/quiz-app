"""Pydantic schemas - Wrong Answer"""

from typing import Optional

from pydantic import BaseModel, Field


class WrongPracticeRequest(BaseModel):
    bank_id: int | None = None
    # 题量上限；为空表示取全部未掌握错题。小于 1 的非法值由路由层手写校验返回 400，
    # 不用 Field(ge=1) 是因为框架的校验失败响应是 422 + detail 数组，前端取不到文案。
    question_count: int | None = None


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
