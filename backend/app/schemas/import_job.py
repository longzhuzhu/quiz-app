"""Pydantic schemas - Import Job（第一阶段预留，不实现完整链路）"""

from pydantic import BaseModel


class ImportJobCreateResponse(BaseModel):
    import_job_id: int
    background_job_id: int
    status: str
