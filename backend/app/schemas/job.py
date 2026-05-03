"""Pydantic schemas - Jobs"""

from pydantic import BaseModel


class JobCreateRequest(BaseModel):
    job_type: str
    bank_id: int | None = None


class JobResponse(BaseModel):
    id: int
    job_type: str
    scope_key: str
    status: str
    attempt_count: int
    max_attempts: int
    progress_total: int
    progress_done: int
    success_count: int
    skipped_count: int
    last_error: str | None
    status_message: str | None
    payload: dict = {}
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    next_run_at: str | None = None
    heartbeat_at: str | None = None
    lease_until: str | None = None

    model_config = {"from_attributes": True}


class JobCreateResponse(BaseModel):
    result: str
    job: JobResponse | None = None
    message: str


class JobGetResponse(BaseModel):
    job: JobResponse | None
