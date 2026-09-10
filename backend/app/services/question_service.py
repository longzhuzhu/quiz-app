"""题目正确答案更正与本场重判。"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.exam import Exam
from app.models.question import Question
from app.models.quiz import QuizAnswer, QuizSession
from app.services.ai_service import clear_question_explanation
from app.services.answer_keys import (
    answers_equivalent,
    format_answer_keys,
    option_keys_from,
    resolve_answer_keys,
)
from app.services.practice_service import record_accuracy_snapshot


def validate_correct_answer_keys(correct_answer: str, question: Question) -> str:
    """Validate option keys and return the canonical stored form (`B` / `A,C`)."""
    option_keys = option_keys_from(question)
    resolved, unknown = resolve_answer_keys(correct_answer, option_keys)
    if unknown:
        raise ValueError(f"选项 {', '.join(unknown)} 不属于该题")
    if not resolved:
        raise ValueError("正确答案不能为空")
    question_type = getattr(question, "question_type", None) or "single"
    if question_type in ("single", "truefalse") and len(resolved) != 1:
        raise ValueError("单选题和判断题必须恰好有一个正确答案")
    if question_type == "multiple" and len(resolved) < 1:
        raise ValueError("多选题至少需要一个正确答案")
    return format_answer_keys(resolved)


def apply_session_regrade(session: QuizSession, quiz_answer: QuizAnswer, new_correct_answer: str) -> bool:
    """Regrade one stored attempt against the new correct answer. Does not touch WrongAnswer."""
    new_is_correct = answers_equivalent(quiz_answer.user_answer, new_correct_answer)
    old_is_correct = bool(quiz_answer.is_correct)
    quiz_answer.is_correct = new_is_correct
    if (not old_is_correct) and new_is_correct:
        session.correct_count += 1
    elif old_is_correct and (not new_is_correct):
        session.correct_count = max(session.correct_count - 1, 0)
    return new_is_correct


def _session_in_exam_or_404(db: Session, session_id: int, exam: Exam) -> QuizSession:
    session = db.get(QuizSession, session_id)
    if session is None or not session.bank or session.bank.exam_id != exam.id:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    if session.user_id != exam.owner_id:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    return session


def _current_session_is_correct(db: Session, question_id: int, session: QuizSession | None) -> bool | None:
    if session is None:
        return None
    existing = (
        db.query(QuizAnswer)
        .filter_by(session_id=session.id, question_id=question_id)
        .first()
    )
    if existing is None:
        return None
    return existing.is_correct


def update_question_correct_answer(
    db: Session,
    question: Question,
    exam: Exam,
    *,
    correct_answer: str,
    session_id: int | None,
    local_date: str | None = None,
) -> dict:
    """Update Question.correct_answer and optionally regrade the current session only.

    Same transaction: write the answer, clear explanation if changed, regrade this
    session's QuizAnswer.is_correct + session.correct_count. Does not touch
    WrongAnswer / UserQuestionStat / answered_count. Does not call /quiz/answer.
    """
    formatted = validate_correct_answer_keys(correct_answer, question)
    session = _session_in_exam_or_404(db, session_id, exam) if session_id is not None else None

    if answers_equivalent(question.correct_answer, formatted):
        return {
            "correct_answer": question.correct_answer,
            "is_correct": _current_session_is_correct(db, question.id, session),
            "explanation": question.explanation,
            "explanation_zh": question.explanation_zh,
        }

    question.correct_answer = formatted
    clear_question_explanation(db, question)

    is_correct: bool | None = None
    if session is not None:
        existing = (
            db.query(QuizAnswer)
            .filter_by(session_id=session.id, question_id=question.id)
            .first()
        )
        if existing is not None:
            is_correct = apply_session_regrade(session, existing, formatted)
            if local_date is not None:
                record_accuracy_snapshot(
                    db,
                    user_id=session.user_id,
                    exam_id=exam.id,
                    local_date=local_date,
                )

    db.commit()
    return {
        "correct_answer": question.correct_answer,
        "is_correct": is_correct,
        "explanation": question.explanation,
        "explanation_zh": question.explanation_zh,
    }
