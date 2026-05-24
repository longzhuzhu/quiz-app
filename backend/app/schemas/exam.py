"""Pydantic schemas - Exam"""

from pydantic import BaseModel, Field


class ExamCreateRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    short_name: str = Field(..., min_length=1, max_length=30)
    description: str | None = None
    icon: str | None = None
    locale: str = "en-US"
    sort_order: int = 0
    ai_profile_mode: str = "default"
    copy_ai_profile_from: str | None = None
    ai_profile: dict | None = None


class ExamUpdateRequest(BaseModel):
    slug: str | None = Field(None, min_length=1, max_length=50)
    name: str | None = Field(None, min_length=1, max_length=100)
    short_name: str | None = Field(None, min_length=1, max_length=30)
    description: str | None = None
    icon: str | None = None
    locale: str | None = None
    sort_order: int | None = None
    ai_profile: dict | None = None


class ActiveExamRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=50)
