"""Pydantic schemas - Import Review"""

from pydantic import BaseModel, Field


class ReviewItemResponse(BaseModel):
    id: int
    import_job_id: int
    parsed_question_id: int
    review_type: str | None = None
    severity: str | None = None
    before_json: dict | None = None
    after_json: dict | None = None
    status: str = "pending"
    reviewer_id: int | None = None
    reviewed_at: str | None = None
    parsed_question: dict | None = None
    chunk_text: str | None = None


class ReviewItemListResponse(BaseModel):
    items: list[ReviewItemResponse]


class ReviewAcceptResponse(BaseModel):
    question_id: int | None = None
    message: str


class ReviewSkipResponse(BaseModel):
    message: str


class ReviewReparseResponse(BaseModel):
    background_job_id: int | None = None
    status: str
    message: str
