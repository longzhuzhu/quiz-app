"""Admin Bank API 路由 - 管理员只读题库查看"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.api.routes.questions import question_to_dict
from app.core.database import get_db
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.user import User

router = APIRouter()


@router.get("/{bank_id}/questions")
def list_admin_bank_questions(
    bank_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = db.get(QuestionBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    offset = (page - 1) * per_page
    query = db.query(Question).filter_by(bank_id=bank_id).order_by(Question.order_index)
    total = query.count()
    questions = query.offset(offset).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return {
        "questions": [question_to_dict(question) for question in questions],
        "total": total,
        "page": page,
        "pages": pages,
    }
