"""Pydantic schemas - LLM Parse（第一阶段预留）"""

from pydantic import BaseModel, Field
from typing import Literal


class ParsedOption(BaseModel):
    label: str
    text: str


class ParsedQuestion(BaseModel):
    source_question_no: str | None = None
    question_type: Literal["single", "multiple", "truefalse", "unknown"] = "single"
    scenario: str | None = None
    content: str
    options: list[ParsedOption]
    correct_answer: list[str] = Field(default_factory=list)
    explanation: str = ""
    references: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: list[str | dict] = Field(default_factory=list)


class LlmParseResult(BaseModel):
    questions: list[ParsedQuestion]
    chunk_issues: list[str | dict] = Field(default_factory=list)
