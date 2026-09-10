"""练习日记录、滚动正确率快照与练习热力图 / 练习趋势图查询。

练习日与滚动正确率按作答当时客户端给出的本地自然日冻结，
不从 QuizAnswer.answered_at 回放（ADR-0005 / ADR-0006）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.practice import PracticeAccuracyDay, PracticeDayQuestion
from app.models.question_bank import QuestionBank
from app.models.quiz import QuizAnswer, QuizSession

logger = logging.getLogger(__name__)

HEATMAP_WEEKS = 53
TREND_DAYS = 30
ACCURACY_LIMIT = 100


def coerce_local_date(value) -> date | None:
    """把请求里的本地日收成 date；缺省或非法返回 None，不抛错。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_acceptable_local_date(local_date: date, utc_today: date) -> bool:
    """相对 UTC 今天 ±1 天（含边界），吸收时区与时钟偏差。"""
    return abs((local_date - utc_today).days) <= 1


def heatmap_window_start(today: date, weeks: int = HEATMAP_WEEKS) -> date:
    """周一为起点、覆盖 weeks 列、最后一列含 today 的窗口起始日。"""
    last_monday = today - timedelta(days=today.weekday())
    return last_monday - timedelta(weeks=weeks - 1)


def compute_current_streak(practice_dates: set[date], today: date) -> int:
    """当前连续练习日。今天未练但昨天是练习日时，从昨天往过去计（宽限）。"""
    if today in practice_dates:
        cursor = today
    elif (today - timedelta(days=1)) in practice_dates:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in practice_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def record_question_touch(
    db: Session,
    user_id: int,
    exam_id: int,
    question_id: int,
    local_date,
    utc_today: date | None = None,
) -> bool:
    """幂等记下「该用户、该考试项目、该本地日、该题」。

    缺省/非法/超出 ±1 天窗口：不写，返回 False。
    唯一冲突视为已记过，返回 True。
    其它写入异常吞掉并打日志，返回 False，不向上抛。
    """
    parsed = coerce_local_date(local_date)
    if parsed is None:
        return False
    if utc_today is None:
        utc_today = datetime.now(timezone.utc).date()
    if not is_acceptable_local_date(parsed, utc_today):
        return False

    already = (
        db.query(PracticeDayQuestion.id)
        .filter_by(
            user_id=user_id,
            exam_id=exam_id,
            local_date=parsed,
            question_id=question_id,
        )
        .first()
    )
    if already:
        return True

    # 先落盘同一事务里的答题写入，避免练习日 savepoint 回滚时把改答一起撤掉
    db.flush()

    nested = db.begin_nested()
    try:
        db.add(
            PracticeDayQuestion(
                user_id=user_id,
                exam_id=exam_id,
                local_date=parsed,
                question_id=question_id,
            )
        )
        db.flush()
        nested.commit()
        return True
    except IntegrityError:
        nested.rollback()
        return True
    except Exception:
        nested.rollback()
        logger.exception(
            "记录练习日失败 user_id=%s exam_id=%s question_id=%s local_date=%s",
            user_id,
            exam_id,
            question_id,
            parsed,
        )
        return False


def recent_accuracy_for(
    db: Session,
    user_id: int,
    exam_id: int,
    limit: int = ACCURACY_LIMIT,
) -> dict:
    """当前考试项目最近 N 条仍存在作答记录的正确率（与四格卡片同一口径）。"""
    sub = (
        db.query(QuizAnswer.id, QuizAnswer.is_correct)
        .join(QuizSession, QuizAnswer.session_id == QuizSession.id)
        .join(QuestionBank, QuizSession.bank_id == QuestionBank.id)
        .filter(
            QuizSession.user_id == user_id,
            QuestionBank.exam_id == exam_id,
            QuizAnswer.answered_at.isnot(None),
            QuizAnswer.is_correct.isnot(None),
        )
        .order_by(QuizAnswer.answered_at.desc(), QuizAnswer.id.desc())
        .limit(limit)
        .subquery()
    )
    total, correct = (
        db.query(
            func.count(),
            func.count().filter(sub.c.is_correct.is_(True)),
        )
        .select_from(sub)
        .one()
    )
    total = total or 0
    correct = correct or 0
    accuracy = round(correct / max(total, 1) * 100, 1)
    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "limit": limit,
    }


def record_accuracy_snapshot(
    db: Session,
    user_id: int,
    exam_id: int,
    local_date,
    utc_today: date | None = None,
    limit: int = ACCURACY_LIMIT,
) -> bool:
    """把当时的滚动正确率写入该本地日一行；只更新该日。

    缺省/非法/超出 ±1 天窗口：不写，返回 False。
    写入异常吞掉并打日志，返回 False，不向上抛。
    """
    parsed = coerce_local_date(local_date)
    if parsed is None:
        return False
    if utc_today is None:
        utc_today = datetime.now(timezone.utc).date()
    if not is_acceptable_local_date(parsed, utc_today):
        return False

    try:
        # 先落盘同一事务里的答题写入，再算现势正确率
        db.flush()
        stats = recent_accuracy_for(db, user_id, exam_id, limit=limit)
        if stats["total"] <= 0:
            return False
        now = datetime.now(timezone.utc)

        existing = (
            db.query(PracticeAccuracyDay)
            .filter_by(user_id=user_id, exam_id=exam_id, local_date=parsed)
            .first()
        )
        if existing:
            existing.accuracy = stats["accuracy"]
            existing.sample_size = stats["total"]
            existing.updated_at = now
            return True

        nested = db.begin_nested()
        try:
            db.add(
                PracticeAccuracyDay(
                    user_id=user_id,
                    exam_id=exam_id,
                    local_date=parsed,
                    accuracy=stats["accuracy"],
                    sample_size=stats["total"],
                    updated_at=now,
                )
            )
            db.flush()
            nested.commit()
            return True
        except IntegrityError:
            nested.rollback()
            row = (
                db.query(PracticeAccuracyDay)
                .filter_by(user_id=user_id, exam_id=exam_id, local_date=parsed)
                .first()
            )
            if row:
                row.accuracy = stats["accuracy"]
                row.sample_size = stats["total"]
                row.updated_at = now
            return True
        except Exception:
            nested.rollback()
            logger.exception(
                "记录滚动正确率快照失败 user_id=%s exam_id=%s local_date=%s",
                user_id,
                exam_id,
                parsed,
            )
            return False
    except Exception:
        logger.exception(
            "记录滚动正确率快照失败 user_id=%s exam_id=%s local_date=%s",
            user_id,
            exam_id,
            parsed,
        )
        return False


def trend_for(db: Session, user_id: int, exam_id: int, today: date) -> dict:
    """近 30 个本地日的密集序列：当日作答量 + 展开后的滚动正确率。"""
    window_start = today - timedelta(days=TREND_DAYS - 1)

    count_rows = (
        db.query(PracticeDayQuestion.local_date, func.count())
        .filter(
            PracticeDayQuestion.user_id == user_id,
            PracticeDayQuestion.exam_id == exam_id,
            PracticeDayQuestion.local_date >= window_start,
            PracticeDayQuestion.local_date <= today,
        )
        .group_by(PracticeDayQuestion.local_date)
        .all()
    )
    counts_by_date = {_as_date(local_date): int(count) for local_date, count in count_rows}

    snapshot_rows = (
        db.query(PracticeAccuracyDay)
        .filter(
            PracticeAccuracyDay.user_id == user_id,
            PracticeAccuracyDay.exam_id == exam_id,
            PracticeAccuracyDay.local_date >= window_start,
            PracticeAccuracyDay.local_date <= today,
        )
        .all()
    )
    snapshots = {_as_date(row.local_date): row for row in snapshot_rows}

    seed = (
        db.query(PracticeAccuracyDay)
        .filter(
            PracticeAccuracyDay.user_id == user_id,
            PracticeAccuracyDay.exam_id == exam_id,
            PracticeAccuracyDay.local_date < window_start,
        )
        .order_by(PracticeAccuracyDay.local_date.desc())
        .first()
    )

    live = recent_accuracy_for(db, user_id, exam_id, limit=ACCURACY_LIMIT)

    days = []
    last_accuracy = seed.accuracy if seed is not None else None
    last_sample_size = seed.sample_size if seed is not None else 0
    for offset in range(TREND_DAYS):
        local_date = window_start + timedelta(days=offset)
        count = counts_by_date.get(local_date, 0)
        snapshot = snapshots.get(local_date)
        if snapshot is not None:
            last_accuracy = snapshot.accuracy
            last_sample_size = snapshot.sample_size
            accuracy = snapshot.accuracy
            sample_size = snapshot.sample_size
        elif last_accuracy is not None:
            accuracy = last_accuracy
            sample_size = last_sample_size
        else:
            accuracy = None
            sample_size = 0

        if local_date == today:
            if live["total"] > 0:
                accuracy = live["accuracy"]
                sample_size = live["total"]
            else:
                accuracy = None
                sample_size = 0

        days.append({
            "date": local_date.isoformat(),
            "count": count,
            "accuracy": accuracy,
            "sample_size": sample_size,
        })

    return {
        "today": today.isoformat(),
        "days": days,
    }


def heatmap_for(db: Session, user_id: int, exam_id: int, today: date) -> dict:
    """稀疏返回窗口内有作答的日期及当日作答量，以及当前连续练习日。"""
    rows = (
        db.query(PracticeDayQuestion.local_date, func.count())
        .filter(
            PracticeDayQuestion.user_id == user_id,
            PracticeDayQuestion.exam_id == exam_id,
            PracticeDayQuestion.local_date <= today,
        )
        .group_by(PracticeDayQuestion.local_date)
        .all()
    )
    counts_by_date = {_as_date(local_date): int(count) for local_date, count in rows}
    window_start = heatmap_window_start(today)
    days = [
        {"date": local_date.isoformat(), "count": count}
        for local_date, count in sorted(counts_by_date.items())
        if count > 0 and window_start <= local_date <= today
    ]
    return {
        "today": today.isoformat(),
        "current_streak": compute_current_streak(set(counts_by_date), today),
        "days": days,
    }


def clear_practice_days(db: Session, user_id: int, exam_id: int) -> None:
    db.query(PracticeDayQuestion).filter_by(
        user_id=user_id, exam_id=exam_id
    ).delete(synchronize_session=False)
    db.query(PracticeAccuracyDay).filter_by(
        user_id=user_id, exam_id=exam_id
    ).delete(synchronize_session=False)
