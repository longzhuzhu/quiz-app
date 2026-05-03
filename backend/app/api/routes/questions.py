"""Questions API 路由 - 题目 CRUD、分页"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.user import User
from app.schemas.question import QuestionCreateRequest, QuestionUpdateRequest
from app.services.ai_service import (
    clear_question_explanation,
    clear_question_translation,
    sanitize_options_for_storage,
)

router = APIRouter()


def question_to_dict(q: Question, include_answer: bool = True) -> dict:
    """题目序列化（与 Flask 版本保持一致）

    options 字段：PostgreSQL JSONB 存储为列表/字典，直接返回。
    Flask 版本使用 json.loads(q.options) 解析 JSON 字符串，
    FastAPI 版本 JSONB 存储直接为 Python 对象，无需 json.loads。
    """
    options = q.options
    if isinstance(options, str):
        options = json.loads(options)

    d = {
        "id": q.id,
        "bank_id": q.bank_id,
        "question_type": q.question_type,
        "content": q.content,
        "content_zh": q.content_zh,
        "options": options,
        "order_index": q.order_index,
        "explanation": q.explanation,
        "explanation_zh": q.explanation_zh,
        "created_at": q.created_at.isoformat(),
    }
    if include_answer:
        d["correct_answer"] = q.correct_answer
    return d


@router.get("/banks/{bank_id}/questions")
def list_questions(
    bank_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * per_page
    query = db.query(Question).filter_by(bank_id=bank_id).order_by(Question.order_index)
    total = query.count()
    questions = query.offset(offset).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if total > 0 else 0

    return {
        "questions": [question_to_dict(q) for q in questions],
        "total": total,
        "page": page,
        "pages": pages,
    }


@router.post("/", status_code=201)
def create_question(
    data: QuestionCreateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = Question(
        bank_id=data.bank_id,
        question_type=data.question_type,
        content=data.content,
        options=data.options,  # JSONB 直接存储列表
        correct_answer=data.correct_answer,
    )
    db.add(q)

    bank = db.get(QuestionBank, data.bank_id)
    if bank:
        bank.question_count = db.query(Question).filter_by(bank_id=bank.id).count() + 1

    db.commit()
    db.refresh(q)
    return question_to_dict(q)


@router.put("/{question_id}")
def update_question(
    question_id: int,
    data: QuestionUpdateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")

    if data.content is not None:
        if data.content != q.content:
            clear_question_translation(db, q)
            clear_question_explanation(db, q)
        q.content = data.content

    if data.options is not None:
        sanitized_updated = sanitize_options_for_storage(data.options)
        current_options = q.options
        if isinstance(current_options, str):
            current_options = json.loads(current_options)
        sanitized_current = sanitize_options_for_storage(current_options)
        if sanitized_updated != sanitized_current:
            clear_question_translation(db, q)
            clear_question_explanation(db, q)
            q.options = sanitized_updated  # JSONB 直接存储

    if data.correct_answer is not None:
        if data.correct_answer != q.correct_answer:
            clear_question_explanation(db, q)
        q.correct_answer = data.correct_answer

    if data.question_type is not None:
        if data.question_type != q.question_type:
            clear_question_explanation(db, q)
        q.question_type = data.question_type

    db.commit()
    db.refresh(q)
    return question_to_dict(q)


@router.delete("/{question_id}")
def delete_question(
    question_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")

    bank = db.get(QuestionBank, q.bank_id)
    db.delete(q)
    if bank:
        bank.question_count = max(0, bank.question_count - 1)
    db.commit()
    return {"message": "题目已删除"}
