"""Wrong API 路由 - 错题本（列表/练习/标记掌握/统计）"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_exam_context
from app.core.database import get_db
from app.models.exam import Exam
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizSession
from app.models.user import User
from app.models.wrong import UserQuestionStat, WrongAnswer
from app.schemas.wrong import WrongPracticeRequest
from app.services.exam_service import get_bank_in_exam_or_404

router = APIRouter()


def _get_user_question_counts(user_id: int, question_ids: list[int], db: Session) -> dict:
    if not question_ids:
        return {}
    stats = db.query(UserQuestionStat).filter(
        UserQuestionStat.user_id == user_id,
        UserQuestionStat.question_id.in_(question_ids),
    ).all()
    return {item.question_id: item.answer_count for item in stats}


def _load_options(question: Question) -> list | dict:
    options = question.options
    if isinstance(options, str):
        return json.loads(options)
    return options


def _wrong_query(db: Session, user_id: int, exam: Exam):
    return (
        db.query(WrongAnswer)
        .join(Question, WrongAnswer.question_id == Question.id)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(WrongAnswer.user_id == user_id, QuestionBank.exam_id == exam.id)
    )


@router.get("")
def list_wrong(
    bank_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    query = _wrong_query(db, user_id, exam).filter(WrongAnswer.is_resolved.is_(False))
    if bank_id:
        get_bank_in_exam_or_404(db, bank_id, exam)
        query = query.filter(Question.bank_id == bank_id)

    wrongs = query.order_by(WrongAnswer.last_wrong_at.desc()).all()
    result = []
    for w in wrongs:
        q = w.question
        result.append({
            "id": w.id,
            "question_id": w.question_id,
            "wrong_count": w.wrong_count,
            "last_wrong_at": w.last_wrong_at.isoformat(),
            "question": {
                "id": q.id,
                "bank_id": q.bank_id,
                "question_type": q.question_type,
                "content": q.content,
                "content_zh": q.content_zh,
                "options": _load_options(q),
                "correct_answer": q.correct_answer,
                "explanation": q.explanation,
                "explanation_zh": q.explanation_zh,
            }
        })
    return result


@router.post("/practice")
def practice_wrong(
    data: WrongPracticeRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    bank_id = data.bank_id

    query = _wrong_query(db, user_id, exam).filter(WrongAnswer.is_resolved.is_(False))
    if bank_id:
        get_bank_in_exam_or_404(db, bank_id, exam)
        query = query.filter(Question.bank_id == bank_id)

    wrongs = query.all()
    if not wrongs:
        raise HTTPException(status_code=400, detail="没有错题")

    question_ids = [w.question_id for w in wrongs]
    questions = db.query(Question).filter(Question.id.in_(question_ids)).all()
    question_map = {q.id: q for q in questions}
    ordered_questions = [question_map[qid] for qid in question_ids if qid in question_map]
    counts = _get_user_question_counts(user_id, question_ids, db)

    first_bank_id = bank_id or ordered_questions[0].bank_id
    session = QuizSession(
        user_id=user_id,
        bank_id=first_bank_id,
        mode="wrong_practice",
        total_questions=len(ordered_questions),
        question_ids=json.dumps(question_ids),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    questions_out = []
    for q in ordered_questions:
        questions_out.append({
            "id": q.id,
            "question_type": q.question_type,
            "content": q.content,
            "content_zh": q.content_zh,
            "options": _load_options(q),
            "explanation": q.explanation,
            "explanation_zh": q.explanation_zh,
            "user_answer_count": counts.get(q.id, 0),
        })

    return {
        "session": {
            "id": session.id,
            "bank_id": first_bank_id,
            "mode": "wrong_practice",
            "total_questions": len(ordered_questions),
        },
        "questions": questions_out,
    }


@router.put("/{wrong_id}/resolve")
def resolve_wrong(
    wrong_id: int,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    wrong = _wrong_query(db, current_user.id, exam).filter(WrongAnswer.id == wrong_id).first()
    if not wrong:
        raise HTTPException(status_code=404, detail="错题记录不存在")
    wrong.is_resolved = True
    db.commit()
    return {"message": "已标记为掌握"}


@router.get("/stats")
def wrong_stats(
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    total = _wrong_query(db, user_id, exam).filter(WrongAnswer.is_resolved.is_(False)).count()
    resolved = _wrong_query(db, user_id, exam).filter(WrongAnswer.is_resolved.is_(True)).count()
    return {"unresolved": total, "resolved": resolved, "total": total + resolved}
