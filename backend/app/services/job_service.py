"""任务服务 - 后台任务生命周期管理（适配 FastAPI + SQLAlchemy 2.x）

- 所有函数显式接收 db: Session 参数
- 使用 SQLAlchemy 2.x select()/update() 风格
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import is_sqlite_bind
from app.core.db_locks import (
    EXPLANATION_SLOT_NAMESPACE,
    LockBackendUnavailable,
    backend_lock_held,
    engine_for_session,
    release_backend_lock,
    try_backend_lock,
)

from app.models.background_job import BackgroundJob
from app.models.bank_word import BankWordExclusion, BankWordFrequency
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.services.ai_service import has_question_explanation, has_question_translation
from app.services.import_service import TOP_FREQUENT_TERMS_LIMIT
from app.services.topic_tagging_service import list_untagged_question_ids

if TYPE_CHECKING:
    from app.services.import_execution import ImportExecution

JOB_TYPE_AI_PREWARM = "ai_prewarm"
JOB_TYPE_AI_EXPLANATION = "ai_explanation"
JOB_TYPE_BANK_FREQUENT_TRANSLATE = "bank_frequent_translate"
JOB_TYPE_QUESTION_IMPORT_LLM = "question_import_llm"
JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE = "question_import_llm_reparse"
JOB_TYPE_QUESTION_TOPIC_TAG = "question_topic_tag"
ACTIVE_STATUSES = {"queued", "running"}
DEFAULT_JOB_LEASE_SECONDS = 180
DEFAULT_REQUEUE_DELAY_SECONDS = 15
# 解析任务执行期间不续约，租约须覆盖「单次调用超时 × 2（含格式纠正重试）」的最坏耗时：
# 默认 120s × 2 = 240s，取 360s 留余量。否则租约先过期，recover_stale_jobs 会把
# 仍在进行的解析判为「执行已中断」。
EXPLANATION_JOB_LEASE_SECONDS = 360


def _acquire_explanation_slot(db: Session):
    """获取解析并发槽；PostgreSQL 用 advisory lock，SQLite 用同机文件锁。"""
    engine = engine_for_session(db)
    for slot in range(settings.AI_EXPLANATION_CONCURRENCY):
        handle = try_backend_lock(engine, EXPLANATION_SLOT_NAMESPACE, slot)
        if handle is not None:
            return handle, slot
    return None


def release_explanation_slot(job: BackgroundJob | None) -> None:
    reservation = getattr(job, "_explanation_slot", None)
    if reservation is None:
        return
    handle, slot = reservation
    try:
        release_backend_lock(handle, EXPLANATION_SLOT_NAMESPACE, slot)
    finally:
        setattr(job, "_explanation_slot", None)


class JobServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def text_missing(value) -> bool:
    return value is None or not str(value).strip()


def vocabulary_needs_translation(word) -> bool:
    if text_missing(word.term_zh):
        return True
    if word.definition and text_missing(word.definition_zh):
        return True
    return False


def build_scope_key(job_type: str, payload: dict) -> str:
    if job_type == JOB_TYPE_AI_EXPLANATION:
        from app.services.explanation_service import explanation_scope
        return explanation_scope(payload["exam_id"], payload["question_id"], payload["model_id"], payload["input_fingerprint"])
    if job_type == JOB_TYPE_AI_PREWARM:
        return f"ai_prewarm:{payload['exam_id']}:{payload['question_id']}:{payload['artifact_type']}"
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return f"bank_frequent:{payload['bank_id']}"
    if job_type == JOB_TYPE_QUESTION_IMPORT_LLM:
        return f"import_llm:{payload.get('import_job_id', 'unknown')}"
    if job_type == JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE:
        return f"import_reparse:{payload.get('chunk_id', 'unknown')}"
    if job_type == JOB_TYPE_QUESTION_TOPIC_TAG:
        return f"topic_tag:{payload['bank_id']}"
    raise ValueError(f"不支持的任务类型: {job_type}")


def list_bank_frequent_terms(db: Session, bank_id: int) -> list:
    """列出题库的高频词（排除被排除的词）"""
    excluded_terms = {
        row.term
        for row in db.query(BankWordExclusion).filter_by(bank_id=bank_id).all()
    }
    query = db.query(BankWordFrequency).filter_by(bank_id=bank_id)
    if excluded_terms:
        query = query.filter(~BankWordFrequency.term.in_(excluded_terms))
    return query.order_by(
        BankWordFrequency.frequency.desc(),
        BankWordFrequency.term.asc(),
    ).limit(TOP_FREQUENT_TERMS_LIMIT).all()


def count_pending_items(db: Session, job_type: str, payload: dict) -> int:
    if job_type == JOB_TYPE_AI_EXPLANATION:
        return 1
    if job_type == JOB_TYPE_AI_PREWARM:
        question = db.get(Question, payload["question_id"])
        if not question:
            raise JobServiceError("题目不存在", status_code=404)
        artifact_type = payload["artifact_type"]
        if artifact_type == "translation":
            return 0 if has_question_translation(question) else 1
        if artifact_type == "explanation":
            return 0 if has_question_explanation(question) else 1
        raise ValueError(f"不支持的预热产物类型: {artifact_type}")

    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        bank_id = payload["bank_id"]
        bank = db.get(QuestionBank, bank_id)
        if not bank:
            raise JobServiceError("题库不存在", status_code=404)

        items = list_bank_frequent_terms(db, bank_id)
        return sum(1 for item in items if text_missing(item.term_zh))

    if job_type in (JOB_TYPE_QUESTION_IMPORT_LLM, JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE):
        # 智能导入任务始终需要执行
        return 1

    if job_type == JOB_TYPE_QUESTION_TOPIC_TAG:
        bank_id = payload["bank_id"]
        bank = db.get(QuestionBank, bank_id)
        if not bank:
            raise JobServiceError("题库不存在", status_code=404)
        return len(list_untagged_question_ids(db, bank_id))

    raise ValueError(f"不支持的任务类型: {job_type}")


def deserialize_job_payload(job: BackgroundJob) -> dict:
    if not job.payload_json:
        return {}
    try:
        return json.loads(job.payload_json)
    except json.JSONDecodeError:
        return {}


def serialize_job(job: BackgroundJob | None) -> dict | None:
    if job is None:
        return None
    payload = deserialize_job_payload(job)
    return {
        "id": job.id,
        "job_type": job.job_type,
        "scope_key": job.scope_key,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "progress_total": job.progress_total,
        "progress_done": job.progress_done,
        "success_count": job.success_count,
        "skipped_count": job.skipped_count,
        "last_error": job.last_error,
        "status_message": job.status_message,
        "payload": payload,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "lease_until": job.lease_until.isoformat() if job.lease_until else None,
    }


def create_or_reuse_job(
    db: Session,
    job_type: str,
    payload: dict,
    created_by: int,
) -> tuple[str, BackgroundJob | None, str]:
    """创建或复用后台任务，返回 (result, job, message)"""
    scope_key = build_scope_key(job_type, payload)
    existing = (
        db.query(BackgroundJob)
        .filter_by(active_scope_key=scope_key)
        .order_by(BackgroundJob.id.desc())
        .first()
    )
    if existing:
        return "existing", existing, "已有后台任务正在执行"

    pending_total = count_pending_items(db, job_type, payload)
    if pending_total <= 0:
        return "no_work", None, "当前没有待处理数据"

    job = BackgroundJob(
        job_type=job_type,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="queued",
        progress_total=pending_total,
        status_message="等待后台 worker 执行",
        priority=payload.get("priority", 0) if job_type == JOB_TYPE_AI_EXPLANATION else 0,
        subject_question_id=payload["question_id"] if job_type == JOB_TYPE_AI_EXPLANATION else None,
        max_attempts=1 if job_type == JOB_TYPE_AI_EXPLANATION else 3,
        created_by=created_by,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if not _is_active_scope_unique_conflict(exc):
            raise
        existing = (
            db.query(BackgroundJob)
            .filter_by(active_scope_key=scope_key)
            .order_by(BackgroundJob.id.desc())
            .first()
        )
        if existing:
            return "existing", existing, "已有后台任务正在执行"
        raise
    return "created", job, "后台任务已创建"


def invalidate_active_scope(
    db: Session,
    scope_key: str,
    status_message: str,
    last_error: str | None = None,
    now: datetime | None = None,
) -> BackgroundJob | None:
    """使活跃 scope 的任务失效"""
    now = now or utc_now()
    job = (
        db.query(BackgroundJob)
        .filter_by(active_scope_key=scope_key)
        .order_by(BackgroundJob.id.desc())
        .first()
    )
    if not job:
        return None

    job.status = "failed"
    job.progress_done = (job.success_count or 0) + (job.skipped_count or 0)
    job.progress_total = max(job.progress_total or 0, job.progress_done)
    job.last_error = last_error or status_message
    job.status_message = status_message
    job.finished_at = now
    job.next_run_at = None
    job.lease_until = None
    job.heartbeat_at = now
    job.active_scope_key = None
    return job


def recover_stale_jobs(db: Session, now: datetime | None = None) -> int:
    now = now or utc_now()
    if is_sqlite_bind(db):
        return _recover_stale_jobs_sqlite(db, now)
    recovered = 0
    candidate_ids = db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.status == "running", BackgroundJob.lease_until < now,
        )
    ).scalars().all()
    for job_id in candidate_ids:
        # fail_job 会提交，因此逐项锁定并刷新；不能依赖一次性批量锁的旧快照。
        # SQLite 没有行锁，恢复改为在短写事务内重新核对 lease 后更新。
        job = (
            db.query(BackgroundJob)
            .filter(BackgroundJob.id == job_id, BackgroundJob.status == "running", BackgroundJob.lease_until < now)
            .with_for_update(skip_locked=True)
            .populate_existing()
            .first()
        )
        if job is None:
            continue
        if not job.lease_until:
            continue
        normalized_lease = _normalize_utc(job.lease_until)
        normalized_now = _normalize_utc(now)
        if normalized_lease is not None and normalized_now is not None and normalized_lease >= normalized_now:
            continue
        if job.job_type == JOB_TYPE_AI_EXPLANATION:
            fail_job(db, job, "执行已中断，请手动重试")
            recovered += 1
            continue
        job.status = "queued"
        job.lease_until = None
        job.heartbeat_at = None
        job.status_message = "检测到 worker 中断，任务已重新排队"
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def _recover_stale_jobs_sqlite(db: Session, now: datetime) -> int:
    """SQLite 没有行锁：用条件 UPDATE（CAS）代替 FOR UPDATE SKIP LOCKED 重读。

    逐条推进，避免一次事务里长时间持有写权限；并发恢复者只有 CAS 成功者计数。
    """
    recovered = 0
    while True:
        job_id = db.execute(
            select(BackgroundJob.id).where(
                BackgroundJob.status == "running",
                BackgroundJob.lease_until.is_not(None),
                BackgroundJob.lease_until < now,
            ).order_by(BackgroundJob.id.asc()).limit(1)
        ).scalar()
        if job_id is None:
            break
        expired = (
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.lease_until.is_not(None),
            BackgroundJob.lease_until < now,
        )
        job_type = db.execute(
            select(BackgroundJob.job_type).where(BackgroundJob.id == job_id)
        ).scalar()
        if job_type == JOB_TYPE_AI_EXPLANATION:
            values = {
                "status": "failed",
                "progress_done": BackgroundJob.success_count + BackgroundJob.skipped_count,
                "last_error": "执行已中断，请手动重试",
                "status_message": "解析失败，可手动重试",
                "finished_at": now,
                "next_run_at": None,
                "lease_until": None,
                "active_scope_key": None,
            }
        else:
            values = {
                "status": "queued",
                "lease_until": None,
                "heartbeat_at": None,
                "status_message": "检测到 worker 中断，任务已重新排队",
            }
        result = db.execute(
            update(BackgroundJob).where(*expired).values(**values),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount == 1:
            recovered += 1
        db.commit()
    return recovered


def claim_next_job(
    db: Session,
    worker_id: str,
    lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
) -> BackgroundJob | None:
    now = utc_now()
    candidate_ids = db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.status == "queued",
            or_(BackgroundJob.next_run_at.is_(None), BackgroundJob.next_run_at <= now),
    ).order_by(BackgroundJob.priority.desc(), BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
    ).scalars().all()

    for job_id in candidate_ids:
        job = try_claim_job_by_id(db, job_id, worker_id=worker_id, lease_seconds=lease_seconds, now=now)
        if job is not None:
            return job
    return None


def try_claim_job_by_id(
    db: Session,
    job_id: int,
    worker_id: str,
    lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
    now: datetime | None = None,
) -> BackgroundJob | None:
    now = now or utc_now()
    candidate = db.get(BackgroundJob, job_id)
    if candidate is not None and candidate.job_type in (JOB_TYPE_QUESTION_IMPORT_LLM, JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE):
        from app.services.import_execution import try_claim_import
        return try_claim_import(db, candidate, worker_id, now, settings.WORKER_LEASE_SECONDS)
    is_explanation = candidate is not None and candidate.job_type == JOB_TYPE_AI_EXPLANATION
    reservation = None
    if is_explanation:
        reservation = _acquire_explanation_slot(db)
        if reservation is None:
            db.rollback()
            return None
    if reservation is not None:
        setattr(candidate, "_explanation_slot", reservation)
    if is_explanation:
        # 解析任务执行期间不续约，租约须覆盖两次模型调用的最坏耗时。
        lease_seconds = max(lease_seconds, EXPLANATION_JOB_LEASE_SECONDS)
    try:
        lease_until = now + timedelta(seconds=lease_seconds)
        result = db.execute(
            update(BackgroundJob).where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "queued",
                or_(BackgroundJob.next_run_at.is_(None), BackgroundJob.next_run_at <= now),
            ).values(
                status="running",
                attempt_count=BackgroundJob.attempt_count + 1,
                started_at=case(
                    (BackgroundJob.started_at.is_(None), now),
                    else_=BackgroundJob.started_at,
                ),
                heartbeat_at=now,
                lease_until=lease_until,
                next_run_at=None,
                status_message=f"worker {worker_id} 已接手任务",
            ),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            db.rollback()
            if reservation is not None:
                setattr(candidate, "_explanation_slot", reservation)
                release_explanation_slot(candidate)
            return None
        db.commit()
        claimed = db.get(BackgroundJob, job_id)
        if reservation is not None:
            setattr(claimed, "_explanation_slot", reservation)
        return claimed
    except Exception:
        db.rollback()
        release_explanation_slot(candidate)
        raise


def _guard_import_attempt(
    db: Session, job: BackgroundJob, execution: ImportExecution | None,
) -> ImportExecution | None:
    """非导入保持旧行为；导入所有生命周期写入使用同一个不可变领取 token。"""
    execution = execution or getattr(job, "_import_execution", None)
    if execution is None and job.job_type not in (JOB_TYPE_QUESTION_IMPORT_LLM, JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE):
        return None
    from app.services.import_execution import LeaseLost
    if execution is None:
        raise LeaseLost("缺少不可变导入 attempt token")
    if execution.token.background_job_id != job.id:
        raise LeaseLost("导入 token 不属于该后台请求")
    execution.guard(db)
    return execution


def heartbeat_job(
    db: Session,
    job: BackgroundJob,
    success_increment: int = 0,
    skipped_increment: int = 0,
    status_message: str | None = None,
    lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
    *,
    execution: ImportExecution | None = None,
) -> BackgroundJob | None:
    now = utc_now()
    execution = _guard_import_attempt(db, job, execution)
    if execution is not None:
        lease_seconds = execution.lease_seconds
    current = db.get(BackgroundJob, job.id)
    if current is None or current.status != "running":
        return current

    current.success_count = (current.success_count or 0) + success_increment
    current.skipped_count = (current.skipped_count or 0) + skipped_increment
    current.progress_done = current.success_count + current.skipped_count
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.heartbeat_at = now
    current.lease_until = now + timedelta(seconds=lease_seconds)
    if status_message:
        current.status_message = status_message
    db.commit()
    return current


def complete_job(
    db: Session,
    job: BackgroundJob,
    status_message: str = "任务完成",
    *,
    execution: ImportExecution | None = None,
) -> BackgroundJob | None:
    now = utc_now()
    execution = _guard_import_attempt(db, job, execution)
    current = db.get(BackgroundJob, job.id)
    if current is None or current.status != "running":
        return current

    current.status = "completed"
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = None
    current.status_message = status_message
    current.heartbeat_at = now
    current.finished_at = now
    current.next_run_at = None
    current.lease_until = None
    current.active_scope_key = None
    db.commit()
    return current


def requeue_job(
    db: Session,
    job: BackgroundJob,
    error_message: str,
    delay_seconds: int = DEFAULT_REQUEUE_DELAY_SECONDS,
    *,
    execution: ImportExecution | None = None,
) -> BackgroundJob | None:
    execution = _guard_import_attempt(db, job, execution)
    current = db.get(BackgroundJob, job.id)
    if current is None or current.status != "running":
        return current

    if (current.attempt_count or 0) >= (current.max_attempts or 0):
        return fail_job(db, current, error_message, execution=execution)

    now = utc_now()
    current.status = "queued"
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = str(error_message)
    current.status_message = f"第 {current.attempt_count}/{current.max_attempts} 次执行失败，15 秒后自动重试"
    current.next_run_at = now + timedelta(seconds=delay_seconds)
    current.lease_until = None
    current.heartbeat_at = None
    db.commit()
    return current


def fail_job(
    db: Session,
    job: BackgroundJob,
    error_message: str,
    *,
    execution: ImportExecution | None = None,
) -> BackgroundJob | None:
    now = utc_now()
    execution = _guard_import_attempt(db, job, execution)
    current = db.get(BackgroundJob, job.id)
    if current is None or current.status not in {"queued", "running"}:
        return current

    current.status = "failed"
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = str(error_message)
    current.status_message = "解析失败，可手动重试" if current.job_type == JOB_TYPE_AI_EXPLANATION else f"任务已自动执行 {current.max_attempts} 次仍失败"
    current.finished_at = now
    current.next_run_at = None
    current.lease_until = None
    current.active_scope_key = None
    db.commit()
    return current


def should_retry(job: BackgroundJob) -> bool:
    return (job.attempt_count or 0) < (job.max_attempts or 0)


# ─── 内部辅助 ──────────────────────────────────────


def _normalize_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_active_scope_unique_conflict(error: Exception) -> bool:
    raw_message = str(getattr(error, "orig", error))
    return (
        "background_jobs.active_scope_key" in raw_message
        or "uq_background_jobs_active_scope_key" in raw_message
    )
