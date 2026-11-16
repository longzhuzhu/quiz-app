"""Pydantic schemas - 平台题库管理与目录"""

from pydantic import BaseModel, Field


class PlatformBankCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class PlatformBankUpdateRequest(BaseModel):
    """草稿元数据修改；来源与版本等只读字段不接受写入"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class PlatformDraftQuestionCreateRequest(BaseModel):
    question_type: str
    content: str
    content_zh: str | None = None
    options: list[dict]
    correct_answer: str
    source_topics: list | None = None


class PlatformDraftQuestionUpdateRequest(BaseModel):
    """草稿题修订；未提供的字段保持不变"""

    question_type: str | None = None
    content: str | None = None
    content_zh: str | None = None
    options: list[dict] | None = None
    correct_answer: str | None = None
    source_topics: list | None = None


class PlatformAdoptResponse(BaseModel):
    bank_id: int
    platform_bank_id: str
    release_id: str
    published_version: int
    created: bool
