"""Pydantic schemas - Import Job"""

from pydantic import BaseModel, Field


class ImportJobCreateResponse(BaseModel):
    import_job_id: int
    background_job_id: int
    status: str


class ImportJobResponse(BaseModel):
    id: int
    bank_id: int
    background_job_id: int | None = None
    file_name: str
    file_type: str
    status: str
    total_pages: int = 0
    total_chunks: int = 0
    parsed_questions: int = 0
    imported_questions: int = 0
    review_questions: int = 0
    failed_chunks: int = 0
    summary: dict | None = None
    error_message: str | None = None
    created_by: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    background_job: dict | None = None


class ImportJobListResponse(BaseModel):
    jobs: list[ImportJobResponse]


class ImportChunkResponse(BaseModel):
    id: int
    import_job_id: int
    chunk_no: int
    start_page: int | None = None
    end_page: int | None = None
    chunk_text: str
    status: str
    issues: dict | None = None
    created_at: str | None = None


class ImportChunkListResponse(BaseModel):
    chunks: list[ImportChunkResponse]


class ParsedQuestionResponse(BaseModel):
    id: int
    import_job_id: int
    chunk_id: int | None = None
    source_question_no: str | None = None
    question_type: str | None = None
    scenario_text: str | None = None
    content: str
    options: list[dict] = Field(default_factory=list)
    correct_answer: list[str] = Field(default_factory=list)
    explanation: str | None = None
    llm_confidence: float | None = None
    final_confidence: float | None = None
    issues: dict | None = None
    review_status: str = "pending"
    import_status: str = "waiting"
    imported_question_id: int | None = None


class ParsedQuestionListResponse(BaseModel):
    questions: list[ParsedQuestionResponse]
