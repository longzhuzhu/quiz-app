"""Pydantic schemas - Vocabulary"""

from pydantic import BaseModel, Field


class VocabItemResponse(BaseModel):
    id: int
    term: str
    definition: str | None = None
    term_zh: str | None = None
    definition_zh: str | None = None
    is_system: bool
    is_mastered: bool
    can_delete: bool
    can_mark_mastered: bool = True
    created_at: str


class VocabAddRequest(BaseModel):
    term: str
    definition: str = ""
    term_zh: str | None = None
    definition_zh: str | None = None
    auto_translate: bool = False


class VocabProgressUpdateRequest(BaseModel):
    is_mastered: bool


class FrequentProgressUpdateRequest(BaseModel):
    bank_id: int
    term: str
    is_mastered: bool


class VocabStatsResponse(BaseModel):
    personal: int
    exam_personal: int
    all: int


class BatchTranslateResponse(BaseModel):
    message: str
    translated: int
    remaining: int


class FrequentListResponse(BaseModel):
    bank: dict
    summary: dict
    pagination: dict
    items: list[dict]


class ImportIAPPResponse(BaseModel):
    message: str
    added: int
    skipped: int
    total_fetched: int
