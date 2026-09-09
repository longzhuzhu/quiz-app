"""练习日记录与练习热力图查询。

练习日按作答当时客户端给出的本地自然日冻结，不从 QuizAnswer.answered_at 回放。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.practice import PracticeDayQuestion

logger = logging.getLogger(__name__)

HEATMAP_WEEKS = 53


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
