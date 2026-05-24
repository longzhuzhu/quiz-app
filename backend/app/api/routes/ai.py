"""AI API 路由 - AI 翻译（单题/批量）、AI 解析"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_exam_context
from app.core.database import get_db
from app.models.exam import Exam
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.schemas.ai import AIExplainRequest, AITranslateBatchRequest, AITranslateRequest
from app.services.ai_service import (
    build_question_explanation_payload,
    build_question_translation_payload,
    explain_question,
    has_question_explanation,
    has_question_translation,
    translate_question,
)
from app.services.exam_service import get_bank_in_exam_or_404, get_question_in_exam_or_404

router = APIRouter()


@router.post("/translate")
def translate(
    data: AITranslateRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    question = get_question_in_exam_or_404(db, data.question_id, exam)

    if has_question_translation(question):
        return {
            **build_question_translation_payload(question),
            "cached": True,
        }

    try:
        result = translate_question(db, question)
        return {**result, "cached": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"翻译失败: {str(e)}")


@router.post("/translate/batch")
def translate_batch(
    data: AITranslateBatchRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    get_bank_in_exam_or_404(db, data.bank_id, exam)
    questions = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(
            QuestionBank.exam_id == exam.id,
            Question.bank_id == data.bank_id,
            Question.content_zh.is_(None),
        )
        .all()
    )

    success = 0
    errors = 0
    for q in questions:
        try:
            translate_question(db, q)
            success += 1
        except Exception:
            errors += 1

    return {"success": success, "errors": errors, "total": len(questions)}


@router.post("/explain")
def explain(
    data: AIExplainRequest,
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    question = get_question_in_exam_or_404(db, data.question_id, exam)

    if has_question_explanation(question):
        return {
            **build_question_explanation_payload(question),
            "cached": True,
        }

    try:
        result = explain_question(db, question)
        return {**result, "cached": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
