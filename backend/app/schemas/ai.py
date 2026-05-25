"""Pydantic schemas - AI"""

from pydantic import BaseModel, Field


class AITranslateRequest(BaseModel):
    question_id: int


class AITranslateBatchRequest(BaseModel):
    bank_id: int | None = None


class AIExplainRequest(BaseModel):
    question_id: int


class AIPrewarmRequest(BaseModel):
    session_id: int
    question_ids: list[int] = Field(min_length=1, max_length=2)


class AITranslateResponse(BaseModel):
    content_zh: str | None = None
    options_zh: list[dict] = Field(default_factory=list)
    cached: bool = False


class AIExplainResponse(BaseModel):
    explanation: str | None = None
    explanation_zh: str | None = None
    cached: bool = False


class AITranslateBatchResponse(BaseModel):
    success: int
    errors: int
    total: int
