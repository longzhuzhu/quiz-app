"""Import Jobs API 路由 - 导入任务查询、Chunk 列表、解析题目列表"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_exam_context
from app.core.database import get_db
from app.models.exam import Exam
from app.models.import_chunk import ImportChunk
from app.models.import_job import ImportJob
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.question_bank import QuestionBank
from app.services.exam_service import get_import_job_in_exam_or_404
from app.services.smart_import_service import (
    serialize_auto_handled_item,
    serialize_chunk,
    serialize_import_job,
    serialize_parsed_question,
)

router = APIRouter()


@router.get("")
def list_import_jobs(
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
    bank_id: int | None = Query(None),
    status: str | None = Query(None),
):
    query = (
        db.query(ImportJob)
        .join(QuestionBank, ImportJob.bank_id == QuestionBank.id)
        .filter(QuestionBank.exam_id == exam.id)
        .order_by(ImportJob.created_at.desc())
    )

    if bank_id is not None:
        query = query.filter(ImportJob.bank_id == bank_id)
    if status is not None:
        query = query.filter(ImportJob.status == status)

    jobs = query.all()
    return {"jobs": [serialize_import_job(j, db) for j in jobs]}


@router.get("/{job_id}")
def get_import_job(
    job_id: int,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    import_job = get_import_job_in_exam_or_404(db, job_id, exam)
    return serialize_import_job(import_job, db)


@router.get("/{job_id}/chunks")
def list_chunks(
    job_id: int,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    get_import_job_in_exam_or_404(db, job_id, exam)
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
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
    review_status: str | None = Query(None),
):
    get_import_job_in_exam_or_404(db, job_id, exam)
    query = (
        db.query(ImportParsedQuestion)
        .filter_by(import_job_id=job_id)
        .order_by(ImportParsedQuestion.id.asc())
    )
    if review_status:
        query = query.filter_by(review_status=review_status)

    questions = query.all()
    return {"questions": [serialize_parsed_question(q) for q in questions]}


@router.get("/{job_id}/auto-handled")
def list_auto_handled_items(
    job_id: int,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    get_import_job_in_exam_or_404(db, job_id, exam)
    items = (
        db.query(ImportParsedQuestion)
        .filter(ImportParsedQuestion.import_job_id == job_id)
        .filter(ImportParsedQuestion.review_status.in_(["auto_accepted", "auto_skipped"]))
        .order_by(ImportParsedQuestion.id.asc())
        .all()
    )
    return {
        "items": [serialize_auto_handled_item(item) for item in items],
        "total": len(items),
    }
