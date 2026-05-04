"""Pydantic schemas - QuestionBank"""

from datetime import datetime

from pydantic import BaseModel, Field


class BankResponse(BaseModel):
    """题库响应格式（与 Flask 版本保持一致）"""
    id: int
    name: str
    description: str | None
    source_filename: str | None
    question_count: int
    created_at: str

    model_config = {"from_attributes": True}


class BankCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""


class BankUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
