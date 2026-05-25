"""AI API 路由 - AI 翻译（单题/批量）、AI 解析"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_exam_context
from app.core.database import get_db
from app.models.exam import Exam
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizSession
from app.models.user import User
from app.schemas.ai import AIPrewarmRequest, AIExplainRequest, AITranslateBatchRequest, AITranslateRequest
from app.services.ai_service import (
    build_question_explanation_payload,
    build_question_translation_payload,
    explain_question,
    has_question_explanation,
    has_question_translation,
    translate_question,
)
from app.services.exam_service import get_bank_in_exam_or_404, get_question_in_exam_or_404
from app.services.job_service import JOB_TYPE_AI_PREWARM, JobServiceError, create_or_reuse_job
from app.services.settings_service import is_quiz_ai_prewarm_enabled

router = APIRouter()


@router.post("/prewarm")
def prewarm(
    data: AIPrewarmRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    session = db.get(QuizSession, data.session_id)
    if not session or not session.bank or session.bank.exam_id != exam.id:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限")
    if session.is_completed:
        return {"accepted": False}

    session_question_ids = json.loads(session.question_ids) if session.question_ids else []
    requested_ids = []
    for question_id in data.question_ids:
        if question_id not in session_question_ids:
            raise HTTPException(status_code=404, detail="题目不属于当前答题会话")
        if question_id not in requested_ids:
            requested_ids.append(question_id)

    questions = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(
            Question.id.in_(requested_ids),
            Question.bank_id == session.bank_id,
            QuestionBank.exam_id == exam.id,
        )
        .all()
    )
    question_by_id = {question.id: question for question in questions}
    if len(question_by_id) != len(requested_ids):
        raise HTTPException(status_code=404, detail="题目不存在")

    if not is_quiz_ai_prewarm_enabled(db):
        return {"accepted": False}

    for question_id in requested_ids:
        question = question_by_id[question_id]
        for artifact_type in ("translation", "explanation"):
            if artifact_type == "translation" and has_question_translation(question):
                continue
            if artifact_type == "explanation" and has_question_explanation(question):
                continue
            payload = {
                "artifact_type": artifact_type,
                "exam_id": exam.id,
                "question_id": question.id,
                "session_id": session.id,
            }
            try:
                create_or_reuse_job(db, JOB_TYPE_AI_PREWARM, payload, current_user.id)
            except JobServiceError as exc:
                if exc.status_code >= 500:
                    raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return {"accepted": True}


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
