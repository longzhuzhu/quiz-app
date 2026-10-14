"""Quiz API 路由 - 答题会话（开始/答题/结束/历史/详情）"""

import json
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_exam_context
from app.core.database import get_db
from app.models.exam import Exam
from app.models.exam_topic import ExamTopic, TOPIC_LEVEL_COMPETENCY, TOPIC_LEVEL_DOMAIN
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizSession, QuizAnswer
from app.models.wrong import MASTERY_CORRECT_STREAK, WrongAnswer, UserQuestionStat
from app.models.user import User
from app.schemas.quiz import (
    QuizAnswerRequest,
    QuizFinishRequest,
    QuizRetryRequest,
    QuizStartRequest,
)
from app.services.exam_service import get_bank_in_exam_or_404
from app.services.explanation_service import input_fingerprint, summaries_for_questions
from app.services.practice_service import (
    clear_practice_days,
    heatmap_for,
    practiced_questions_for,
    recent_accuracy_for,
    record_accuracy_snapshot,
    record_question_touch,
    trend_for,
)
from app.services.quiz_snapshot_service import freeze_final_answers, snapshot_entries
from app.services.quiz_stats import session_stats
from app.services.topic_service import (
    list_question_ids_for_competency,
    list_question_ids_for_domain,
    list_unclassified_question_ids,
)

router = APIRouter()
logger = logging.getLogger(__name__)
PRACTICE_STATS_LOCK_TIMEOUT = "250ms"


def _record_practice_stats(
    db: Session,
    *,
    user_id: int,
    exam_id: int,
    question_id: int,
    local_date,
) -> None:
    """写入练习日与正确率快照。PostgreSQL 上遇到共享行锁时快速放弃，不拖住已提交的作答。"""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL lock_timeout = '{PRACTICE_STATS_LOCK_TIMEOUT}'"))
    record_question_touch(
        db,
        user_id=user_id,
        exam_id=exam_id,
        question_id=question_id,
        local_date=local_date,
    )
    record_accuracy_snapshot(
        db,
        user_id=user_id,
        exam_id=exam_id,
        local_date=local_date,
    )


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


def _question_payloads(
    db: Session,
    questions: list[Question],
    exam_id: int,
    *,
    is_exam: bool,
    counts: dict,
) -> list[dict]:
    """构造答题页题目 payload，供 /start、/retry 等入口共用。

    模拟考试不返回解析、缓存指纹与题面辅助字段。
    """
    summaries = summaries_for_questions(db, questions, exam_id) if not is_exam else {}
    payloads = []
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
            question_data["ai_explanations"] = summaries.get(q.id, [])
            question_data["ai_input_fingerprint"] = input_fingerprint(q)
            question_data["explanation"] = q.explanation
            question_data["explanation_zh"] = q.explanation_zh
        payloads.append(question_data)
    return payloads


def _ensure_session_in_exam(session: QuizSession, exam: Exam) -> None:
    if not session.bank or session.bank.exam_id != exam.id:
        raise HTTPException(status_code=404, detail="答题会话不存在")


def _resolve_topic_scope(
    db: Session, exam: Exam, bank: QuestionBank, topic_id: int | None
) -> tuple[ExamTopic | None, list[int]]:
    """解析专项练习的出题范围。

    topic_id 为空表示练未分类题目，此时不关联任何考点。
    """
    if topic_id is None:
        return None, list_unclassified_question_ids(db, bank.id)

    topic = db.get(ExamTopic, topic_id)
    if not topic or topic.exam_id != exam.id:
        raise HTTPException(status_code=404, detail="考点不存在")
    if topic.level == TOPIC_LEVEL_DOMAIN:
        return topic, list_question_ids_for_domain(db, bank.id, topic.id)
    if topic.level == TOPIC_LEVEL_COMPETENCY:
        return topic, list_question_ids_for_competency(db, bank.id, topic.id)
    raise HTTPException(status_code=404, detail="考点不存在")


def _snapshot_entries_by_question_id(session: QuizSession) -> dict[int, dict]:
    """本场快照按题号索引；旧会话（无快照）与非 dict 条目一并跳过。"""
    entries: dict[int, dict] = {}
    if isinstance(session.question_snapshot, list):
        for entry in session.question_snapshot:
            if not isinstance(entry, dict):
                continue
            question_id = entry.get("question_id")
            if isinstance(question_id, int) and question_id not in entries:
                entries[question_id] = entry
    return entries


def _review_verdict(
    answer: QuizAnswer | None,
    frozen_answers: dict | None,
    question_id: int,
    snapshot_present: bool,
) -> tuple[str | None, bool | None, str, bool]:
    """复盘单题状态：`status` 只由保存的 `is_correct` 决定。

    返回 `(user_answer, is_correct, status, status_unknown)`。缺失判定不得用布尔兜底
    当作错误（Issue #63 根因）；旧会话没有快照也没有作答记录时无法核实是未答还是记录
    已缺失，标为不可核实而不推断成错误或未答。
    """
    key = str(question_id)
    # 整列损坏（非 dict）时不把「键不存在」与「无法核实」混为一谈，统一走不可核实分支
    frozen_present = isinstance(frozen_answers, dict) and key in frozen_answers
    frozen = frozen_answers.get(key) if frozen_present else None

    if isinstance(frozen, dict):
        # 完成冻结副本优先：题目与作答记录都被删除后仍可读出当时判定。
        # 只有真正的 bool 才构成判定，缺失或非 bool 一律不推断成错误。
        if isinstance(frozen.get("is_correct"), bool):
            is_correct = frozen["is_correct"]
            return frozen.get("user_answer"), is_correct, ("correct" if is_correct else "wrong"), False
        # 冻结副本缺少可核实判定：保留已保存的选择，不推断成错误或未答
        return frozen.get("user_answer"), None, "unanswered", True
    if frozen_present:
        if frozen is None:
            # 显式 null 表示该题未答，与「键不存在」区分
            return None, None, "unanswered", False
        # 冻结副本条目损坏（既非 dict 也非显式 null）：不推断成任何状态
        return None, None, "unanswered", True
    if answer is not None:
        # QuizAnswer.is_correct 非空，只认保存值，不用布尔兜底把缺失当错误
        is_correct = bool(answer.is_correct)
        return answer.user_answer, is_correct, ("correct" if is_correct else "wrong"), False
    if snapshot_present:
        # 本场有快照且没有作答记录：确实是未答题
        return None, None, "unanswered", False
    return None, None, "unanswered", True


def _review_question_out(
    *,
    question_id: int,
    index: int,
    snapshot_entry: dict | None,
    question: Question | None,
    answer: QuizAnswer | None,
    frozen_answers: dict | None,
) -> dict:
    """构造复盘态单题：内容优先取本场快照，无快照时退回当前题库数据。"""
    if snapshot_entry is not None:
        question_type = snapshot_entry.get("question_type")
        content = snapshot_entry.get("content")
        options = snapshot_entry.get("options")
        correct_answer = snapshot_entry.get("correct_answer")
    else:
        question_type = question.question_type if question else None
        content = question.content if question else None
        options = _load_options(question) if question else None
        correct_answer = question.correct_answer if question else None

    user_answer, is_correct, status, status_unknown = _review_verdict(
        answer, frozen_answers, question_id, snapshot_entry is not None
    )
    return {
        "id": question_id,
        "index": index,
        "question_type": question_type,
        "content": content,
        "options": options,
        "user_answer": user_answer,
        "is_correct": is_correct,
        "correct_answer": correct_answer,
        "status": status,
        "status_unknown": status_unknown,
    }


def _compute_resume_index(question_ids: list[int], answers: list[QuizAnswer]) -> int:
    """根据最近一次答题位置计算未完成会话恢复索引。"""
    if not question_ids:
        return 0

    index_by_question_id = {qid: index for index, qid in enumerate(question_ids)}

    def answer_sort_key(answer: QuizAnswer) -> tuple[float, int]:
        answered_at = answer.answered_at
        if answered_at is None:
            answered_timestamp = 0.0
        else:
            if answered_at.tzinfo is None:
                answered_at = answered_at.replace(tzinfo=timezone.utc)
            answered_timestamp = answered_at.timestamp()
        return answered_timestamp, answer.id or 0

    ordered_answers = sorted(answers, key=answer_sort_key, reverse=True)
    for answer in ordered_answers:
        answered_index = index_by_question_id.get(answer.question_id)
        if answered_index is not None:
            return min(answered_index + 1, len(question_ids) - 1)

    return 0


@router.post("/start")
def start_quiz(
    data: QuizStartRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    bank_id = data.bank_id
    mode = data.mode
    question_count = data.question_count
    is_exam = mode == "exam"
    bank = get_bank_in_exam_or_404(db, bank_id, exam)

    topic = None
    query = db.query(Question).filter_by(bank_id=bank.id)
    if mode == "topic":
        topic, topic_question_ids = _resolve_topic_scope(db, exam, bank, data.topic_id)
        if not topic_question_ids:
            raise HTTPException(status_code=400, detail="该考点下没有题目")
        query = query.filter(Question.id.in_(topic_question_ids)).order_by(func.random())
    elif mode in ("random", "exam"):
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
        topic_id=topic.id if topic else None,
        total_questions=len(questions),
        question_ids=json.dumps([q.id for q in questions]),
        question_snapshot=snapshot_entries(questions),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    question_ids = [q.id for q in questions]
    counts = _get_user_question_counts(user_id, question_ids, db)
    questions_out = _question_payloads(db, questions, exam.id, is_exam=is_exam, counts=counts)

    return {
        "session": {
            "id": session.id,
            "bank_id": session.bank_id,
            "mode": session.mode,
            "topic_short_name": topic.short_name_zh if topic else None,
            "total_questions": session.total_questions,
        },
        "questions": questions_out,
    }


@router.post("/retry")
def retry_quiz(
    data: QuizRetryRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    """从已完成的原会话按原题原序另开一场练习。

    复用全部原题 ID 与原顺序（含原场未答题），保留原模式与题数；「原题」指成员与顺序，
    不是恢复题库旧版本，新会话使用这些原题**当前**内容并建立自己的快照。任一原题不可用
    则整场失败，不创建部分会话。
    """
    user_id = current_user.id
    session = db.get(QuizSession, data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    _ensure_session_in_exam(session, exam)
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")
    if not session.is_completed:
        raise HTTPException(status_code=400, detail="答题会话尚未结束，不能重新开始")

    try:
        source_question_ids = json.loads(session.question_ids) if session.question_ids else []
    except (TypeError, ValueError):
        source_question_ids = []
    if (
        not isinstance(source_question_ids, list)
        or not source_question_ids
        # 列表里混入非整数时不能直接进 SQL，否则查询报错变成 500
        or not all(isinstance(qid, int) and not isinstance(qid, bool) for qid in source_question_ids)
    ):
        # 旧会话列表缺失或损坏时拒绝，不通过查询题库猜原范围
        raise HTTPException(status_code=400, detail="原会话缺少题目列表，无法重新开始")

    counts = _get_user_question_counts(user_id, source_question_ids, db)
    # 跨题库错题会话的题目分属不同题库，只限定考试项目，不能加 bank_id 过滤；
    # 查询返回顺序不可依赖，按原 question_ids 重建。
    # 行锁持有到本次提交：question_ids 存的是 JSON 而非外键，删除题目不会触发约束错误，
    # 若校验与创建之间被并发删除，新会话会带上一个已不存在的题。删除端已有行锁，同一把锁。
    rows = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(Question.id.in_(source_question_ids), QuestionBank.exam_id == exam.id)
        .with_for_update(of=Question)
        .all()
    )
    question_map = {q.id: q for q in rows}
    missing = [qid for qid in source_question_ids if qid not in question_map]
    if missing:
        # 整场失败：先全部校验再创建，不跳过、不补抽，也不留下部分会话
        listed = "、".join(str(qid) for qid in missing)
        raise HTTPException(
            status_code=400,
            detail=f"部分原题已不可用，无法重新开始（题目 ID: {listed}）",
        )
    questions = [question_map[qid] for qid in source_question_ids]

    # 保留仍有效的考点上下文。考点被删除时外键 ondelete="SET NULL"（models/quiz.py）
    # 已把原会话的 topic_id 置空，这里读到的是 None，**无法**反推「原考点已删除」——
    # 它与「练未分类题目」同形。所以不输出 topic_unavailable 这类标记：生产上恒为
    # False 的假信号比没有信号更糟。原题集合与顺序不受影响，照常创建。
    topic = db.get(ExamTopic, session.topic_id) if session.topic_id else None
    if topic is not None and topic.exam_id != exam.id:
        topic = None
    mode = session.mode
    is_exam = mode == "exam"

    new_session = QuizSession(
        user_id=user_id,
        bank_id=session.bank_id,  # 跨题库错题会话沿用原值，这里只是首个题库
        mode=mode,
        topic_id=topic.id if topic else None,
        total_questions=len(questions),
        question_ids=json.dumps(source_question_ids),
        question_snapshot=snapshot_entries(questions),
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    questions_out = _question_payloads(db, questions, exam.id, is_exam=is_exam, counts=counts)

    return {
        "session": {
            "id": new_session.id,
            "bank_id": new_session.bank_id,
            "mode": new_session.mode,
            "topic_short_name": topic.short_name_zh if topic else None,
            "total_questions": new_session.total_questions,
        },
        "questions": questions_out,
    }


@router.post("/answer")
def submit_answer(
    data: QuizAnswerRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    session_id = data.session_id
    question_id = data.question_id
    user_answer = data.user_answer

    # 同一会话的并发重试必须先看到首次答案，避免重复插入或覆盖首次耗时。
    # 锁只保持到作答提交，不延长到随后独立写入的练习统计事务。
    session = db.get(QuizSession, session_id, with_for_update=True)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    _ensure_session_in_exam(session, exam)
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

    question = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(Question.id == question_id, QuestionBank.exam_id == exam.id)
        .first()
    )
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
            answer_duration_ms=data.answer_duration_ms,
        )
        db.add(answer)

        session.answered_count += 1
        if is_correct:
            session.correct_count += 1

        user_answer_count = _upsert_user_question_stat(user_id, question_id, db)
        counted_as_new_attempt = True

    # 答错必然要读错题记录（写入或复活）；答对只在可能加一的两条路径上才需要读，
    # 其余路径不查——原实现的查询只存在于答错分支内，不能因为提到分支外就给
    # 每次正确作答都加一次往返（答题接口是延迟敏感路径）。
    wrong = None
    if (not is_correct) or (counted_as_new_attempt and session.mode != "exam"):
        wrong = db.query(WrongAnswer).filter_by(
            user_id=user_id, question_id=question_id
        ).first()

    if not is_correct:
        # 自动收集错题，并保留最近一次错误答案作为错误作答证据（后来答对不覆写）
        if wrong:
            wrong.wrong_count += 1
            wrong.last_wrong_at = datetime.now(timezone.utc)
            wrong.is_resolved = False
            wrong.last_wrong_answer = user_answer
            wrong.last_wrong_session_id = session_id
        else:
            wrong = WrongAnswer(
                user_id=user_id,
                question_id=question_id,
                last_wrong_answer=user_answer,
                last_wrong_session_id=session_id,
            )
            db.add(wrong)
        # 任何一次答错都清零连对，包含本场改答到错；不设限才能防「答对后改错再改回」刷连对。
        # 模拟考试例外：它不向用户展示对错，连对同样不参与，否则会出现
        # 「模拟考答错后连对归零，但用户看不到任何对错反馈」的静默逆转。
        if session.mode != "exam" and wrong.correct_streak:
            wrong.correct_streak = 0
    elif (
        wrong is not None
        # 模拟考试不向用户展示对错，静默改写掌握状态无法归因，故既不加入也不归零。
        and session.mode != "exam"
        # counted_as_new_attempt 等价于本场首次成功提交（下面 else 分支才置真）；
        # 限定它才能防止同场反复「答错→改成对」刷满连对。语义若变，此处需同步。
        and counted_as_new_attempt
    ):
        wrong.correct_streak += 1
        if wrong.correct_streak >= MASTERY_CORRECT_STREAK:
            wrong.is_resolved = True

    session_mode = session.mode
    answer_duration_ms = existing.answer_duration_ms if existing else answer.answer_duration_ms
    correct_answer = question.correct_answer
    explanation = question.explanation
    explanation_zh = question.explanation_zh
    db.commit()

    try:
        _record_practice_stats(
            db,
            user_id=user_id,
            exam_id=exam.id,
            question_id=question_id,
            local_date=data.local_date,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "练习统计写入跳过 session_id=%s question_id=%s err=%s",
            session_id,
            question_id,
            type(exc).__name__,
        )

    # 模拟考试模式不返回正确答案和解析
    if session_mode == "exam":
        return {
            "submitted": True,
            "answer_duration_ms": answer_duration_ms,
            "user_answer_count": user_answer_count,
            "counted_as_new_attempt": counted_as_new_attempt,
        }

    return {
        "is_correct": is_correct,
        "answer_duration_ms": answer_duration_ms,
        "correct_answer": correct_answer,
        "explanation": explanation,
        "explanation_zh": explanation_zh,
        "user_answer_count": user_answer_count,
        "counted_as_new_attempt": counted_as_new_attempt,
    }


@router.post("/finish")
def finish_quiz(
    data: QuizFinishRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    session = db.get(QuizSession, data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    _ensure_session_in_exam(session, exam)
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")

    # 完成冻结只做一次：重复结束（双击或重试）不得重算，否则原题被删后
    # QuizAnswer 已清空，重算会把冻结判定改写成未答。已完成但缺冻结的旧会话
    # 同样不在此回填，由复盘接口走兼容分支。
    if not session.is_completed:
        session.is_completed = True
        session.completed_at = datetime.now(timezone.utc)
        session_question_ids = json.loads(session.question_ids) if session.question_ids else []
        if session_question_ids:
            answers = db.query(QuizAnswer).filter_by(session_id=session.id).all()
            session.final_answers = freeze_final_answers(session_question_ids, answers)
        db.commit()

    stats = session_stats(
        total=session.total_questions,
        answered=session.answered_count,
        correct=session.correct_count,
        mode=session.mode,
    )
    return {
        "session": {
            "id": session.id,
            "total_questions": session.total_questions,
            "answered_count": session.answered_count,
            "correct_count": session.correct_count,
            "is_completed": True,
            **stats,
        }
    }


@router.get("/history")
def history(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    offset = (page - 1) * per_page
    last_answered = (
        db.query(
            QuizAnswer.session_id.label("session_id"),
            func.max(QuizAnswer.answered_at).label("last_answered_at"),
        )
        .group_by(QuizAnswer.session_id)
        .subquery()
    )
    query = (
        db.query(QuizSession)
        .join(QuestionBank, QuizSession.bank_id == QuestionBank.id)
        .outerjoin(last_answered, QuizSession.id == last_answered.c.session_id)
        # bank / topic 都是多对一，预加载避免逐行序列化时按会话数发懒加载查询
        .options(joinedload(QuizSession.bank), joinedload(QuizSession.topic))
        .filter(QuizSession.user_id == user_id, QuestionBank.exam_id == exam.id)
        .order_by(
            func.coalesce(last_answered.c.last_answered_at, QuizSession.created_at).desc(),
            QuizSession.id.desc(),
        )
    )
    total = query.count()
    sessions = query.offset(offset).limit(per_page).all()
    pages = (total + per_page - 1) // per_page if total > 0 else 0

    result = []
    for s in sessions:
        bank_name = s.bank.name if s.bank else ""
        stats = session_stats(
            total=s.total_questions,
            answered=s.answered_count,
            correct=s.correct_count,
            mode=s.mode,
        )
        result.append({
            "id": s.id,
            "bank_id": s.bank_id,
            "bank_name": bank_name,
            "mode": s.mode,
            "topic_short_name": s.topic.short_name_zh if s.topic else None,
            "total_questions": s.total_questions,
            "answered_count": s.answered_count,
            "correct_count": s.correct_count,
            "is_completed": s.is_completed,
            **stats,
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
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    sessions = (
        db.query(QuizSession)
        .join(QuestionBank, QuizSession.bank_id == QuestionBank.id)
        .filter(QuizSession.user_id == user_id, QuestionBank.exam_id == exam.id)
        .all()
    )
    for s in sessions:
        db.delete(s)
    clear_practice_days(db, user_id, exam.id)
    db.commit()
    return {"message": "已清空答题历史"}


@router.get("/recent-accuracy")
def recent_accuracy(
    limit: int = Query(100, ge=10, le=500, description="统计最近答题数"),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    return recent_accuracy_for(db, current_user.id, exam.id, limit=limit)


@router.get("/practiced-summary")
def practiced_summary(
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    return {"practiced_questions": practiced_questions_for(db, current_user.id, exam.id)}


@router.get("/practice-heatmap")
def practice_heatmap(
    today: date = Query(..., description="浏览器本地今天 YYYY-MM-DD"),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    return heatmap_for(db, current_user.id, exam.id, today)


@router.get("/practice-trend")
def practice_trend(
    today: date = Query(..., description="浏览器本地今天 YYYY-MM-DD"),
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    return trend_for(db, current_user.id, exam.id, today)


@router.get("/session/{session_id}")
def session_detail(
    session_id: int,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    session = db.get(QuizSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="答题会话不存在")
    _ensure_session_in_exam(session, exam)
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权限")
    is_exam = session.mode == "exam"
    # 完成态才释放答案与对错：模拟考试结束前继续隐藏，复盘解锁以服务端完成态为准
    released = session.is_completed
    has_snapshot = bool(session.question_snapshot)

    answers = db.query(QuizAnswer).filter_by(session_id=session_id).all()
    session_question_ids = json.loads(session.question_ids) if session.question_ids else []
    resume_index = _compute_resume_index(session_question_ids, answers)

    answers_out = []
    if not released:
        # `answers` 只服务未完成会话的续答恢复（答题页刷新依赖它，见 QuizView.restoreSessionState）。
        # 已完成会话的复盘以 `questions` 为准：两套列表的题号口径不一致，同时输出会让消费方
        # 按数组下标编号而与原场题号错位，因此完成态不再输出这个过渡字段。
        for a in answers:
            q = a.question
            answer_data = {
                "question_id": a.question_id,
                "question_content": q.content,
                "question_content_zh": q.content_zh,
                "question_type": q.question_type,
                "options": _load_options(q),
                "user_answer": a.user_answer,
                "answer_duration_ms": a.answer_duration_ms,
            }
            if not is_exam:
                answer_data["is_correct"] = a.is_correct
                answer_data["correct_answer"] = q.correct_answer
                answer_data["explanation"] = q.explanation
                answer_data["explanation_zh"] = q.explanation_zh
            answers_out.append(answer_data)

    questions_out = []
    if released:
        # 复盘态：按 question_ids 原场顺序返回完整题目，含始终未答的题；
        # 内容优先取本场快照，无快照的旧会话才退回当前题库数据
        snapshot_by_id = _snapshot_entries_by_question_id(session)
        answer_by_question_id = {a.question_id: a for a in answers}
        existing_questions = (
            {q.id: q for q in db.query(Question).filter(Question.id.in_(session_question_ids)).all()}
            if session_question_ids
            else {}
        )
        for index, question_id in enumerate(session_question_ids):
            questions_out.append(_review_question_out(
                question_id=question_id,
                index=index + 1,
                snapshot_entry=snapshot_by_id.get(question_id),
                question=existing_questions.get(question_id),
                answer=answer_by_question_id.get(question_id),
                frozen_answers=session.final_answers,
            ))
    elif session_question_ids:
        # 未完成的会话返回完整题目列表，用于页面刷新后恢复答题
        q_ids = session_question_ids
        counts = _get_user_question_counts(user_id, q_ids, db)
        answered_ids = {a.question_id for a in answers}
        all_questions = db.query(Question).filter(Question.id.in_(q_ids)).all()
        summaries = summaries_for_questions(db, all_questions, exam.id) if not is_exam else {}
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
                    question_data["ai_explanations"] = summaries.get(q.id, [])
                    question_data["ai_input_fingerprint"] = input_fingerprint(q)
                    question_data["explanation"] = q.explanation
                    question_data["explanation_zh"] = q.explanation_zh
                questions_out.append(question_data)

    session_out = {
        "id": session.id,
        "bank_id": session.bank_id,
        "bank_name": session.bank.name if session.bank else "",
        "mode": session.mode,
        "topic_short_name": session.topic.short_name_zh if session.topic else None,
        "total_questions": session.total_questions,
        "answered_count": session.answered_count,
        "correct_count": session.correct_count,
        "is_completed": session.is_completed,
        "resume_index": resume_index,
        "created_at": session.created_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }
    if released:
        # 完成态按快照统计，不受题库后续编辑影响
        session_out.update(
            session_stats(
                total=session.total_questions,
                answered=session.answered_count,
                correct=session.correct_count,
                mode=session.mode,
            )
        )
        session_out["has_snapshot"] = has_snapshot
    else:
        # 进行中的模拟考试不得暴露可推导成绩的统计
        if not is_exam:
            session_out["accuracy"] = session_stats(
                total=session.total_questions,
                answered=session.answered_count,
                correct=session.correct_count,
                mode=session.mode,
            )["accuracy"]

    # 已完成会话只给复盘结构：不再附带按作答记录顺序排列的 `answers`
    result = {"session": session_out} if released else {"session": session_out, "answers": answers_out}
    if released or questions_out:
        result["questions"] = questions_out
    return result
