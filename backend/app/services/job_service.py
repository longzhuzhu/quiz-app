"""任务服务 - 后台任务生命周期管理（适配 FastAPI + SQLAlchemy 2.x）

- 所有函数显式接收 db: Session 参数
- 使用 SQLAlchemy 2.x select()/update() 风格
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob
from app.models.bank_word import BankWordExclusion, BankWordFrequency
from app.models.question_bank import QuestionBank
from app.services.import_service import TOP_FREQUENT_TERMS_LIMIT

JOB_TYPE_BANK_FREQUENT_TRANSLATE = "bank_frequent_translate"
JOB_TYPE_QUESTION_IMPORT_LLM = "question_import_llm"
JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE = "question_import_llm_reparse"
ACTIVE_STATUSES = {"queued", "running"}
DEFAULT_JOB_LEASE_SECONDS = 180
DEFAULT_REQUEUE_DELAY_SECONDS = 15


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
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return f"bank_frequent:{payload['bank_id']}"
    if job_type == JOB_TYPE_QUESTION_IMPORT_LLM:
        return f"import_llm:{payload.get('import_job_id', 'unknown')}"
    if job_type == JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE:
        return f"import_reparse:{payload.get('chunk_id', 'unknown')}"
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
        return "no_work", None, "当前没有待翻译数据"

    job = BackgroundJob(
        job_type=job_type,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="queued",
        progress_total=pending_total,
        status_message="等待后台 worker 执行",
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
    recovered = 0
    running_jobs = db.query(BackgroundJob).filter_by(status="running").all()
    for job in running_jobs:
        if not job.lease_until:
            continue
        normalized_lease = _normalize_utc(job.lease_until)
        normalized_now = _normalize_utc(now)
        if normalized_lease is not None and normalized_now is not None and normalized_lease >= normalized_now:
            continue
        job.status = "queued"
        job.lease_until = None
        job.heartbeat_at = None
        job.status_message = "检测到 worker 中断，任务已重新排队"
        recovered += 1
    if recovered:
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
        ).order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
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
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return db.get(BackgroundJob, job_id)


def heartbeat_job(
    db: Session,
    job: BackgroundJob,
    success_increment: int = 0,
    skipped_increment: int = 0,
    status_message: str | None = None,
    lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
) -> BackgroundJob | None:
    now = utc_now()
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
) -> BackgroundJob | None:
    now = utc_now()
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
) -> BackgroundJob | None:
    current = db.get(BackgroundJob, job.id)
    if current is None or current.status != "running":
        return current

    if (current.attempt_count or 0) >= (current.max_attempts or 0):
        return fail_job(db, current, error_message)

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
) -> BackgroundJob | None:
    now = utc_now()
    current = db.get(BackgroundJob, job.id)
    if current is None or current.status not in {"queued", "running"}:
        return current

    current.status = "failed"
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = str(error_message)
    current.status_message = f"任务已自动执行 {current.max_attempts} 次仍失败"
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
