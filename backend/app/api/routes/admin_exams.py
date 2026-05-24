"""Admin Exam API 路由 - 管理员只读考试项目查看"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.exam import Exam
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.services.exam_service import serialize_exam

router = APIRouter()


def _bank_to_dict(bank: QuestionBank) -> dict:
    return {
        "id": bank.id,
        "exam_id": bank.exam_id,
        "name": bank.name,
        "description": bank.description,
        "source_filename": bank.source_filename,
        "question_count": bank.question_count,
        "created_at": bank.created_at.isoformat(),
    }


@router.get("")
def list_admin_exams(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    exams = db.query(Exam).order_by(Exam.created_at.desc()).all()
    return {"items": [serialize_exam(exam, db) for exam in exams]}


@router.get("/{exam_id}")
def get_admin_exam(
    exam_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="考试项目不存在")
    return serialize_exam(exam, db)


@router.get("/{exam_id}/banks")
def list_admin_exam_banks(
    exam_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="考试项目不存在")
    banks = db.query(QuestionBank).filter_by(exam_id=exam_id).order_by(QuestionBank.created_at.desc()).all()
    return {"items": [_bank_to_dict(bank) for bank in banks]}
