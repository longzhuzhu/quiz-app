"""Pydantic schemas - Import Review（第一阶段预留）"""

from pydantic import BaseModel


class ImportReviewAcceptRequest(BaseModel):
    content: str | None = None
    options: list[dict] | None = None
    correct_answer: list[str] | None = None
    explanation: str | None = None
