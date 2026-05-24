"""Questions API 路由 - 题目 CRUD、分页"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_exam_context
from app.core.database import get_db
from app.models.exam import Exam
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizAnswer
from app.models.wrong import UserQuestionStat, WrongAnswer
from app.schemas.question import QuestionCreateRequest, QuestionUpdateRequest
from app.services.ai_service import (
    clear_question_explanation,
    clear_question_translation,
    sanitize_options_for_storage,
)
from app.services.exam_service import get_bank_in_exam_or_404, get_question_in_exam_or_404

router = APIRouter()


def question_to_dict(q: Question, include_answer: bool = True) -> dict:
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
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    get_bank_in_exam_or_404(db, bank_id, exam)
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


@router.post("", status_code=201)
def create_question(
    data: QuestionCreateRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank = get_bank_in_exam_or_404(db, data.bank_id, exam)
    q = Question(
        bank_id=bank.id,
        question_type=data.question_type,
        content=data.content,
        options=data.options,
        correct_answer=data.correct_answer,
    )
    db.add(q)
    db.flush()
    bank.question_count = db.query(Question).filter_by(bank_id=bank.id).count()

    db.commit()
    db.refresh(q)
    return question_to_dict(q)


@router.put("/{question_id}")
def update_question(
    question_id: int,
    data: QuestionUpdateRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    q = get_question_in_exam_or_404(db, question_id, exam)

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
            q.options = sanitized_updated

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
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    q = get_question_in_exam_or_404(db, question_id, exam)
    bank = db.get(QuestionBank, q.bank_id)
    db.query(QuizAnswer).filter_by(question_id=q.id).delete(synchronize_session=False)
    db.query(WrongAnswer).filter_by(question_id=q.id).delete(synchronize_session=False)
    db.query(UserQuestionStat).filter_by(question_id=q.id).delete(synchronize_session=False)
    db.delete(q)
    if bank:
        bank.question_count = max(0, db.query(Question).filter_by(bank_id=bank.id).count() - 1)
    db.commit()
    return {"message": "题目已删除"}
