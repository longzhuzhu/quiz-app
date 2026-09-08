"""Pydantic schemas - Question"""

from datetime import datetime

from pydantic import BaseModel, Field


class QuestionResponse(BaseModel):
    """题目响应格式。

    options 字段返回原始列表（前端已按列表使用），
    correct_answer 仅在包含答案时返回。
    """
    id: int
    bank_id: int
    question_type: str
    content: str
    content_zh: str | None = None
    options: list[dict] = Field(default_factory=list)
    order_index: int = 0
    explanation: str | None = None
    explanation_zh: str | None = None
    created_at: str
    correct_answer: str | None = None  # 可选，列表时不包含
    topics: list[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]
    total: int
    page: int
    pages: int


class QuestionCreateRequest(BaseModel):
    bank_id: int
    question_type: str
    content: str
    options: list[dict]
    correct_answer: str


class QuestionUpdateRequest(BaseModel):
    content: str | None = None
    options: list[dict] | None = None
    correct_answer: str | None = None
    question_type: str | None = None
    # 人工设定的考点，整份替换；写入后不会被批量打标覆盖
    topic_ids: list[int] | None = None
