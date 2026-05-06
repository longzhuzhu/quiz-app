"""Quiz API 路由 - 答题会话（开始/答题/结束/历史/详情）"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.question import Question
from app.models.quiz import QuizSession, QuizAnswer
from app.models.wrong import WrongAnswer, UserQuestionStat
from app.models.user import User
from app.schemas.quiz import QuizStartRequest, QuizAnswerRequest, QuizFinishRequest

router = APIRouter()


def _get_user_question_counts(user_id: int, question_ids: list[int], db: Session) -> dict:
    if not question_ids:
        return {}
    stats = db.query(UserQuestionStat).filter(
        UserQuestionStat.user_id == user_id,
        UserQuestionStat.question_id.in_(question_ids),
    ).all()
    return {item.question_id: item.answer_count for item in stats}


def _upsert_user_question_stat(user_id: int, question_id: int, db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows_updated = db.query(UserQuestionStat).filter_by(
        user_id=user_id, question_id=question_id
    ).update({
        UserQuestionStat.answer_count: UserQuestionStat.answer_count + 1,
        UserQuestionStat.last_answered_at: now,
    }, synchronize_session=False)
    if rows_updated:
        result = db.query(UserQuestionStat.answer_count).filter_by(
            user_id=user_id, question_id=question_id
        ).scalar()
        return result or 0

    stat = UserQuestionStat(
        user_id=user_id,
        question_id=question_id,
        answer_count=1,
        first_answered_at=now,
        last_answered_at=now,
    )
    # 使用 savepoint 处理并发插入
    nested = db.begin_nested()
    try:
        db.add(stat)
        db.flush()
        nested.commit()
        return stat.answer_count
    except IntegrityError:
        nested.rollback()
        db.query(UserQuestionStat).filter_by(
            user_id=user_id, question_id=question_id
        ).update({
            UserQuestionStat.answer_count: UserQuestionStat.answer_count + 1,
            UserQuestionStat.last_answered_at: now,
        }, synchronize_session=False)
        result = db.query(UserQuestionStat.answer_count).filter_by(
            user_id=user_id, question_id=question_id
        ).scalar()
        return result or 0


def _load_options(question: Question) -> list | dict:
    """加载题目选项，兼容 JSONB 和 JSON 字符串格式"""
    options = question.options
    if isinstance(options, str):
        return json.loads(options)
    return options


@router.post("/start")
def start_quiz(
    data: QuizStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    bank_id = data.bank_id
    mode = data.mode
    question_count = data.question_count
    is_exam = mode == "exam"

    query = db.query(Question).filter_by(bank_id=bank_id)
    if mode in ("random", "exam"):
        query = query.order_by(func.random())
    else:
        query = query.order_by(Question.order_index)

    if question_count:
        query = query.limit(question_count)

    questions = query.all()
    if not questions:
        raise HTTPException(status_code=400, detail="该题库没有题目")

    session = QuizSession(
        user_id=user_id,
        bank_id=bank_id,
        mode=mode,
        total_questions=len(questions),
        question_ids=json.dumps([q.id for q in questions]),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    question_ids = [q.id for q in questions]
    counts = _get_user_question_counts(user_id, question_ids, db)

    questions_out = []
    for q in questions:
        question_data = {
            "id": q.id,
            "question_type": q.question_type,
            "content": q.content,
            "content_zh": q.content_zh,
            "options": _load_options(q),
            "user_answer_count": counts.get(q.id, 0),
        }
        if not is_exam:
            question_data["explanation"] = q.explanation
            question_data["explanation_zh"] = q.explanation_zh
        questions_out.append(question_data)

    return {
        "session": {
            "id": session.id,
            "bank_id": session.bank_id,
            "mode": session.mode,
            "total_questions": session.total_questions,
        },
        "questions": questions_out,
    }


@router.post("/answer")
def submit_answer(
    data: QuizAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    session_id = data.session_id
    question_id = data.question_id
    user_answer = data.user_answer

    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")
    if session.is_completed:
        raise HTTPException(status_code=400, detail="答题已结束")

    session_question_ids = json.loads(session.question_ids) if session.question_ids else []
    if question_id not in session_question_ids:
        raise HTTPException(status_code=400, detail="题目不属于当前答题会话")

    existing = db.query(QuizAnswer).filter_by(
        session_id=session_id, question_id=question_id
    ).first()

    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    is_correct = user_answer.strip().upper() == question.correct_answer.strip().upper()

    counted_as_new_attempt = False
    stat = db.query(UserQuestionStat).filter_by(user_id=user_id, question_id=question_id).first()
    user_answer_count = stat.answer_count if stat else 0

    if existing:
        old_is_correct = existing.is_correct
        existing.user_answer = user_answer
        existing.is_correct = is_correct
        existing.answered_at = datetime.now(timezone.utc)

        # answered_count 保持不变，仅按正确性变化修正 correct_count
        if (not old_is_correct) and is_correct:
            session.correct_count += 1
        elif old_is_correct and (not is_correct):
            session.correct_count = max(session.correct_count - 1, 0)
    else:
        answer = QuizAnswer(
            session_id=session_id,
            question_id=question_id,
            user_answer=user_answer,
            is_correct=is_correct,
        )
        db.add(answer)

        session.answered_count += 1
        if is_correct:
            session.correct_count += 1

        user_answer_count = _upsert_user_question_stat(user_id, question_id, db)
        counted_as_new_attempt = True

    if not is_correct:
        # 自动收集错题
        wrong = db.query(WrongAnswer).filter_by(
            user_id=user_id, question_id=question_id
        ).first()
        if wrong:
            wrong.wrong_count += 1
            wrong.last_wrong_at = datetime.now(timezone.utc)
            wrong.is_resolved = False
        else:
            wrong = WrongAnswer(user_id=user_id, question_id=question_id)
            db.add(wrong)

    db.commit()

    # 模拟考试模式不返回正确答案和解析
    if session.mode == "exam":
        return {
            "submitted": True,
            "user_answer_count": user_answer_count,
            "counted_as_new_attempt": counted_as_new_attempt,
        }

    return {
        "is_correct": is_correct,
        "correct_answer": question.correct_answer,
        "explanation": question.explanation,
        "explanation_zh": question.explanation_zh,
        "user_answer_count": user_answer_count,
        "counted_as_new_attempt": counted_as_new_attempt,
    }


@router.post("/finish")
def finish_quiz(
    data: QuizFinishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    session = db.get(QuizSession, data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")

    session.is_completed = True
    session.completed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "session": {
            "id": session.id,
            "total_questions": session.total_questions,
            "answered_count": session.answered_count,
            "correct_count": session.correct_count,
            "is_completed": True,
            "accuracy": round(session.correct_count / max(session.answered_count, 1) * 100, 1),
        }
    }


@router.get("/history")
def history(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    offset = (page - 1) * per_page
    query = db.query(QuizSession).filter_by(user_id=user_id).order_by(QuizSession.created_at.desc())
    total = query.count()
    sessions = query.offset(offset).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if total > 0 else 0

    result = []
    for s in sessions:
        bank_name = s.bank.name if s.bank else ""
        result.append({
            "id": s.id,
            "bank_id": s.bank_id,
            "bank_name": bank_name,
            "mode": s.mode,
            "total_questions": s.total_questions,
            "answered_count": s.answered_count,
            "correct_count": s.correct_count,
            "is_completed": s.is_completed,
            "accuracy": round(s.correct_count / max(s.answered_count, 1) * 100, 1),
            "created_at": s.created_at.isoformat(),
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        })

    return {
        "items": result,
        "total": total,
        "page": page,
        "pages": pages,
    }


@router.delete("/history")
def clear_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    sessions = db.query(QuizSession).filter_by(user_id=user_id).all()
    for s in sessions:
        db.delete(s)
    db.commit()
    return {"message": "已清空答题历史"}


@router.get("/recent-accuracy")
def recent_accuracy(
    limit: int = Query(100, ge=10, le=500, description="统计最近答题数"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    # 子查询：按答题时间降序取最近 limit 条记录
    sub = (
        db.query(QuizAnswer.id, QuizAnswer.is_correct)
        .join(QuizSession, QuizAnswer.session_id == QuizSession.id)
        .filter(
            QuizSession.user_id == user_id,
            QuizAnswer.answered_at.isnot(None),
            QuizAnswer.is_correct.isnot(None),
        )
        .order_by(QuizAnswer.answered_at.desc(), QuizAnswer.id.desc())
        .limit(limit)
        .subquery()
    )
    # 条件聚合：一次查询同时算 total 和 correct
    total, correct = db.query(
        func.count(),
        func.count().filter(sub.c.is_correct.is_(True)),
    ).select_from(sub).one()
    total = total or 0
    correct = correct or 0
    accuracy = round(correct / max(total, 1) * 100, 1)

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "limit": limit,
    }


@router.get("/session/{session_id}")
def session_detail(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")
    is_exam = session.mode == "exam"

    answers = db.query(QuizAnswer).filter_by(session_id=session_id).all()
    answers_out = []
    for a in answers:
        q = a.question
        answer_data = {
            "question_id": a.question_id,
            "question_content": q.content,
            "question_content_zh": q.content_zh,
            "question_type": q.question_type,
            "options": _load_options(q),
            "user_answer": a.user_answer,
        }
        if not is_exam:
            answer_data["is_correct"] = a.is_correct
            answer_data["correct_answer"] = q.correct_answer
            answer_data["explanation"] = q.explanation
            answer_data["explanation_zh"] = q.explanation_zh
        answers_out.append(answer_data)

    # 未完成的会话返回完整题目列表，用于页面刷新后恢复答题
    questions_out = []
    if not session.is_completed and session.question_ids:
        q_ids = json.loads(session.question_ids)
        counts = _get_user_question_counts(user_id, q_ids, db)
        answered_ids = {a.question_id for a in answers}
        all_questions = db.query(Question).filter(Question.id.in_(q_ids)).all()
        q_map = {q.id: q for q in all_questions}
        for qid in q_ids:
            q = q_map.get(qid)
            if q:
                question_data = {
                    "id": q.id,
                    "question_type": q.question_type,
                    "content": q.content,
                    "content_zh": q.content_zh,
                    "options": _load_options(q),
                    "answered": qid in answered_ids,
                    "user_answer_count": counts.get(q.id, 0),
                }
                if not is_exam:
                    question_data["explanation"] = q.explanation
                    question_data["explanation_zh"] = q.explanation_zh
                questions_out.append(question_data)

    result = {
        "session": {
            "id": session.id,
            "bank_id": session.bank_id,
            "bank_name": session.bank.name if session.bank else "",
            "mode": session.mode,
            "total_questions": session.total_questions,
            "answered_count": session.answered_count,
            "correct_count": session.correct_count,
            "is_completed": session.is_completed,
            "accuracy": round(session.correct_count / max(session.answered_count, 1) * 100, 1),
            "created_at": session.created_at.isoformat(),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
        "answers": answers_out,
    }
    if questions_out:
        result["questions"] = questions_out
    return result
