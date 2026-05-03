"""AI API 路由 - AI 翻译（单题/批量）、AI 解析"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.question import Question
from app.models.user import User
from app.schemas.ai import AITranslateRequest, AITranslateBatchRequest, AIExplainRequest
from app.services.ai_service import (
    build_question_explanation_payload,
    build_question_translation_payload,
    explain_question,
    has_question_explanation,
    has_question_translation,
    translate_question,
)

router = APIRouter()


@router.post("/translate")
def translate(
    data: AITranslateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question = db.get(Question, data.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

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
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank_id = data.bank_id
    questions = db.query(Question).filter_by(bank_id=bank_id).filter(
        Question.content_zh.is_(None)
    ).all()

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question = db.get(Question, data.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

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
