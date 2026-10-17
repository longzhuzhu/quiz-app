"""Wrong API 路由 - 错题本（列表/练习/标记掌握/统计）"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

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
from app.services.explanation_service import input_fingerprint, summaries_for_questions
from app.services.quiz_snapshot_service import snapshot_entries
from app.services.settings_service import get_wrong_mastery_correct_streak

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

    wrongs = query.options(joinedload(WrongAnswer.question)).order_by(WrongAnswer.last_wrong_at.desc()).all()
    summaries = summaries_for_questions(db, [w.question for w in wrongs], exam.id)
    result = []
    for w in wrongs:
        q = w.question
        result.append({
            "id": w.id,
            "question_id": w.question_id,
            "wrong_count": w.wrong_count,
            "correct_streak": w.correct_streak,
            "last_wrong_at": w.last_wrong_at.isoformat(),
            "question": {
                "id": q.id,
                "bank_id": q.bank_id,
                "question_type": q.question_type,
                "content": q.content,
                "content_zh": q.content_zh,
                "options": _load_options(q),
                "correct_answer": q.correct_answer,
                "ai_explanations": summaries.get(q.id, []),
                "ai_input_fingerprint": input_fingerprint(q),
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

    # 非法题量在此手写校验而非用 Pydantic ge=1：框架对校验失败返回 422 且 detail 为数组，
    # 前端读不到可读文案，也偏离本接口既有的 400 契约。
    if data.question_count is not None and data.question_count < 1:
        raise HTTPException(status_code=400, detail="题目数量必须大于 0")

    query = _wrong_query(db, user_id, exam).filter(WrongAnswer.is_resolved.is_(False))
    if bank_id:
        get_bank_in_exam_or_404(db, bank_id, exam)
        query = query.filter(Question.bank_id == bank_id)

    # 每次开始都重新洗牌，避免固定顺序让用户形成位置记忆；
    # 超量请求静默截断，因为错题数会随练习实时减少，硬失败会让「填 20 只剩 18」变成错误。
    wrongs = query.order_by(func.random()).all()
    if data.question_count:
        wrongs = wrongs[: data.question_count]
    if not wrongs:
        raise HTTPException(status_code=400, detail="没有错题")

    question_ids = [w.question_id for w in wrongs]
    questions = db.query(Question).filter(Question.id.in_(question_ids)).all()
    question_map = {q.id: q for q in questions}
    ordered_questions = [question_map[qid] for qid in question_ids if qid in question_map]
    counts = _get_user_question_counts(user_id, question_ids, db)

    # 错题练习可跨题库，逐题下发题库归属；必须在 commit 前用一次列查询建立映射，
    # 否则 commit 过期后逐题访问 ORM 关系会触发 N+1。
    bank_rows = (
        db.query(Question.id, QuestionBank.id, QuestionBank.name)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(Question.id.in_(question_ids))
        .all()
    )
    banks_by_question_id = {
        question_id: (question_bank_id, bank_name)
        for question_id, question_bank_id, bank_name in bank_rows
    }
    # 归属映射在 commit 前定型：commit 后 ORM 属性过期，循环里再读 q.bank_id 会逐题触发查询
    question_banks = {
        q.id: banks_by_question_id.get(q.id, (q.bank_id, "")) for q in ordered_questions
    }

    first_bank_id = bank_id or ordered_questions[0].bank_id
    session = QuizSession(
        user_id=user_id,
        bank_id=first_bank_id,
        mode="wrong_practice",
        total_questions=len(ordered_questions),
        question_ids=json.dumps(question_ids),
        # 错题会话可跨题库，快照逐题取各自题库内容，不能只查 first_bank_id
        question_snapshot=snapshot_entries(ordered_questions),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    questions_out = []
    summaries = summaries_for_questions(db, ordered_questions, exam.id)
    for q in ordered_questions:
        question_bank_id, question_bank_name = question_banks[q.id]
        questions_out.append({
            "id": q.id,
            "bank_id": question_bank_id,
            "bank_name": question_bank_name,
            "question_type": q.question_type,
            "content": q.content,
            "content_zh": q.content_zh,
            "options": _load_options(q),
            "explanation": q.explanation,
            "explanation_zh": q.explanation_zh,
            "user_answer_count": counts.get(q.id, 0),
            "ai_explanations": summaries.get(q.id, []),
            "ai_input_fingerprint": input_fingerprint(q),
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
    # 手动掌握与自动掌握必须落到同一状态，否则「手动掌握后答错再答对一次」
    # 会因残留计数而立刻自动掌握，与自动路径行为不一致。
    wrong.correct_streak = 0
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
    return {
        "unresolved": total,
        "resolved": resolved,
        "total": total + resolved,
        "mastery_correct_streak": get_wrong_mastery_correct_streak(db),
    }
