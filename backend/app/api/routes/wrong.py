"""Wrong API 路由 - 错题本（列表/练习/标记掌握/统计）"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.question import Question
from app.models.quiz import QuizSession, QuizAnswer
from app.models.wrong import WrongAnswer, UserQuestionStat
from app.models.user import User
from app.schemas.wrong import WrongPracticeRequest

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


@router.get("/")
def list_wrong(
    bank_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id

    query = db.query(WrongAnswer).filter_by(user_id=user_id, is_resolved=False)
    if bank_id:
        query = query.join(Question).filter(Question.bank_id == bank_id)

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
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    bank_id = data.bank_id

    query = db.query(WrongAnswer).filter_by(user_id=user_id, is_resolved=False)
    if bank_id:
        query = query.join(Question).filter(Question.bank_id == bank_id)

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
            "total_questions": len(questions),
        },
        "questions": questions_out,
    }


@router.put("/{wrong_id}/resolve")
def resolve_wrong(
    wrong_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    wrong = db.get(WrongAnswer, wrong_id)
    if not wrong:
        raise HTTPException(status_code=404, detail="错题记录不存在")
    if wrong.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")
    wrong.is_resolved = True
    db.commit()
    return {"message": "已标记为掌握"}


@router.get("/stats")
def wrong_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    total = db.query(WrongAnswer).filter_by(user_id=user_id, is_resolved=False).count()
    resolved = db.query(WrongAnswer).filter_by(user_id=user_id, is_resolved=True).count()
    return {"unresolved": total, "resolved": resolved, "total": total + resolved}
