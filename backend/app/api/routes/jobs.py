"""Jobs API 路由 - 后台任务管理"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_exam_context
from app.core.database import get_db
from app.models.background_job import BackgroundJob
from app.models.exam import Exam
from app.models.user import User
from app.schemas.job import JobCreateRequest
from app.services.exam_service import get_bank_in_exam_or_404
from app.services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JobServiceError,
    build_scope_key,
    create_or_reuse_job,
    serialize_job,
)

router = APIRouter()

VALID_JOB_TYPES = {
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
}


def _parse_bank_id(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or not normalized.isdigit():
            return None
        return int(normalized)
    return None


def _build_payload(job_type: str, source: dict, db: Session, exam: Exam) -> tuple[dict, HTTPException | None]:
    payload: dict = {}
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        bank_id = _parse_bank_id(source.get("bank_id"))
        if bank_id is None:
            return {}, HTTPException(status_code=400, detail="bank_id 必须为整数")
        bank = get_bank_in_exam_or_404(db, bank_id, exam)
        payload["bank_id"] = bank.id
    return payload, None


@router.post("")
def create_job(
    data: JobCreateRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    job_type = data.job_type
    if job_type not in VALID_JOB_TYPES:
        raise HTTPException(status_code=400, detail="不支持的任务类型")

    payload, payload_error = _build_payload(job_type, data.model_dump(), db, exam)
    if payload_error:
        raise payload_error

    try:
        result, job, message = create_or_reuse_job(db, job_type, payload, current_user.id)
    except JobServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return {
        "result": result,
        "job": serialize_job(job) if job else None,
        "message": message,
    }


@router.get("/active")
def get_active_job(
    job_type: str = Query(...),
    bank_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    if job_type not in VALID_JOB_TYPES:
        raise HTTPException(status_code=400, detail="不支持的任务类型")

    payload, payload_error = _build_payload(job_type, {"bank_id": bank_id}, db, exam)
    if payload_error:
        raise payload_error

    scope_key = build_scope_key(job_type, payload)
    job = db.query(BackgroundJob).filter(
        BackgroundJob.active_scope_key == scope_key,
        BackgroundJob.created_by == current_user.id,
    ).order_by(BackgroundJob.id.desc()).first()
    return {"job": serialize_job(job) if job else None}


@router.get("/{job_id}")
def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(BackgroundJob, job_id)
    if not job or job.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": serialize_job(job)}
