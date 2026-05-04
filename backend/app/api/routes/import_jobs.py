"""Import Jobs API 路由 - 导入任务查询、Chunk 列表、解析题目列表"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.import_chunk import ImportChunk
from app.models.import_job import ImportJob
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.user import User
from app.services.smart_import_service import (
    serialize_chunk,
    serialize_import_job,
    serialize_parsed_question,
)

router = APIRouter()


@router.get("")
def list_import_jobs(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    bank_id: int | None = Query(None),
    status: str | None = Query(None),
):
    """列出所有导入任务（管理员）"""
    query = db.query(ImportJob).order_by(ImportJob.created_at.desc())

    if bank_id is not None:
        query = query.filter_by(bank_id=bank_id)
    if status is not None:
        query = query.filter_by(status=status)

    jobs = query.all()
    return {"jobs": [serialize_import_job(j) for j in jobs]}


@router.get("/{job_id}")
def get_import_job(
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """获取导入任务详情"""
    import_job = db.get(ImportJob, job_id)
    if not import_job:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return serialize_import_job(import_job)


@router.get("/{job_id}/chunks")
def list_chunks(
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """获取导入任务的 Chunk 列表"""
    import_job = db.get(ImportJob, job_id)
    if not import_job:
        raise HTTPException(status_code=404, detail="导入任务不存在")

    chunks = (
        db.query(ImportChunk)
        .filter_by(import_job_id=job_id)
        .order_by(ImportChunk.chunk_no.asc())
        .all()
    )
    return {"chunks": [serialize_chunk(c) for c in chunks]}


@router.get("/{job_id}/parsed-questions")
def list_parsed_questions(
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    review_status: str | None = Query(None),
):
    """获取导入任务的解析题目列表"""
    import_job = db.get(ImportJob, job_id)
    if not import_job:
        raise HTTPException(status_code=404, detail="导入任务不存在")

    query = (
        db.query(ImportParsedQuestion)
        .filter_by(import_job_id=job_id)
        .order_by(ImportParsedQuestion.id.asc())
    )
    if review_status:
        query = query.filter_by(review_status=review_status)

    questions = query.all()
    return {"questions": [serialize_parsed_question(q) for q in questions]}
