"""Jobs API 路由 - 后台任务管理"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.background_job import BackgroundJob
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
    JobServiceError,
    build_scope_key,
    create_or_reuse_job,
    serialize_job,
)

router = APIRouter()

VALID_JOB_TYPES = {
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
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


def _build_payload(job_type: str, source: dict, db: Session) -> tuple[dict | None, HTTPException | None]:
    payload = {}
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        bank_id = _parse_bank_id(source.get("bank_id"))
        if bank_id is None:
            return None, HTTPException(status_code=400, detail="bank_id 必须为整数")
        bank = db.get(QuestionBank, bank_id)
        if not bank:
            return None, HTTPException(status_code=404, detail="题库不存在")
        payload["bank_id"] = bank_id
    return payload, None


@router.post("")
def create_job(
    data: dict,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    job_type = data.get("job_type")
    if job_type not in VALID_JOB_TYPES:
        raise HTTPException(status_code=400, detail="不支持的任务类型")

    payload, payload_error = _build_payload(job_type, data, db)
    if payload_error:
        raise payload_error

    try:
        result, job, message = create_or_reuse_job(job_type, payload, _admin.id, db)
    except JobServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    status_code = 201 if result == "created" else 200
    return {
        "result": result,
        "job": serialize_job(job) if job else None,
        "message": message,
    }


@router.get("/active")
def get_active_job(
    job_type: str = Query(...),
    bank_id: str | None = Query(None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if job_type not in VALID_JOB_TYPES:
        raise HTTPException(status_code=400, detail="不支持的任务类型")

    source = {"bank_id": bank_id}
    payload, payload_error = _build_payload(job_type, source, db)
    if payload_error:
        raise payload_error

    scope_key = build_scope_key(job_type, payload)
    job = db.query(BackgroundJob).filter_by(
        active_scope_key=scope_key
    ).order_by(BackgroundJob.id.desc()).first()
    return {"job": serialize_job(job) if job else None}


@router.get("/{job_id}")
def get_job(
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    job = db.get(BackgroundJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": serialize_job(job)}
