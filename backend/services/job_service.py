import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError

from models import BackgroundJob, BankWordExclusion, BankWordFrequency, QuestionBank, Vocabulary, db
from services.import_service import TOP_FREQUENT_TERMS_LIMIT

JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE = 'professional_vocab_translate'
JOB_TYPE_BANK_FREQUENT_TRANSLATE = 'bank_frequent_translate'
ACTIVE_STATUSES = {'queued', 'running'}
DEFAULT_JOB_LEASE_SECONDS = 180
DEFAULT_REQUEUE_DELAY_SECONDS = 15


class JobServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def utc_now():
    return datetime.now(timezone.utc)


def text_missing(value):
    return value is None or not str(value).strip()


def vocabulary_needs_translation(word):
    if text_missing(word.term_zh):
        return True
    if word.definition and text_missing(word.definition_zh):
        return True
    return False


def build_scope_key(job_type, payload):
    if job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return 'professional_vocab'
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return f"bank_frequent:{payload['bank_id']}"
    raise ValueError('不支持的任务类型')


def list_bank_frequent_terms(bank_id):
    excluded_terms = {
        row.term
        for row in BankWordExclusion.query.filter_by(bank_id=bank_id).all()
    }
    frequent_query = BankWordFrequency.query.filter_by(bank_id=bank_id)
    if excluded_terms:
        frequent_query = frequent_query.filter(~BankWordFrequency.term.in_(excluded_terms))
    return frequent_query.order_by(
        BankWordFrequency.frequency.desc(),
        BankWordFrequency.term.asc(),
    ).limit(TOP_FREQUENT_TERMS_LIMIT).all()


def count_pending_items(job_type, payload):
    if job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return sum(
            1
            for word in Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term).all()
            if vocabulary_needs_translation(word)
        )

    bank_id = payload['bank_id']
    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        raise JobServiceError('题库不存在', status_code=404)

    items = list_bank_frequent_terms(bank_id)
    return sum(1 for item in items if text_missing(item.term_zh))


def deserialize_job_payload(job):
    if not job.payload_json:
        return {}
    try:
        return json.loads(job.payload_json)
    except json.JSONDecodeError:
        return {}


def serialize_job(job):
    payload = deserialize_job_payload(job)
    return {
        'id': job.id,
        'job_type': job.job_type,
        'scope_key': job.scope_key,
        'status': job.status,
        'attempt_count': job.attempt_count,
        'max_attempts': job.max_attempts,
        'progress_total': job.progress_total,
        'progress_done': job.progress_done,
        'success_count': job.success_count,
        'skipped_count': job.skipped_count,
        'last_error': job.last_error,
        'status_message': job.status_message,
        'payload': payload,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'next_run_at': job.next_run_at.isoformat() if job.next_run_at else None,
        'heartbeat_at': job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        'lease_until': job.lease_until.isoformat() if job.lease_until else None,
    }


def create_or_reuse_job(job_type, payload, created_by):
    scope_key = build_scope_key(job_type, payload)
    existing = BackgroundJob.query.filter_by(active_scope_key=scope_key).order_by(BackgroundJob.id.desc()).first()
    if existing:
        return 'existing', existing, '已有后台任务正在执行'

    pending_total = count_pending_items(job_type, payload)
    if pending_total <= 0:
        return 'no_work', None, '当前没有待翻译数据'

    job = BackgroundJob(
        job_type=job_type,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status='queued',
        progress_total=pending_total,
        status_message='等待后台 worker 执行',
        created_by=created_by,
    )
    db.session.add(job)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        if not _is_active_scope_unique_conflict(exc):
            raise
        existing = BackgroundJob.query.filter_by(active_scope_key=scope_key).order_by(BackgroundJob.id.desc()).first()
        if existing:
            return 'existing', existing, '已有后台任务正在执行'
        raise
    return 'created', job, '后台任务已创建'


def invalidate_active_scope(scope_key, status_message, last_error=None, now=None):
    now = now or utc_now()
    job = BackgroundJob.query.filter_by(active_scope_key=scope_key).order_by(BackgroundJob.id.desc()).first()
    if not job:
        return None

    job.status = 'failed'
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


def recover_stale_jobs(now=None):
    now = now or utc_now()
    recovered = 0
    running_jobs = BackgroundJob.query.filter_by(status='running').all()
    for job in running_jobs:
        if not job.lease_until:
            continue
        if _normalize_utc(job.lease_until) >= _normalize_utc(now):
            continue
        job.status = 'queued'
        job.lease_until = None
        job.heartbeat_at = None
        job.status_message = '检测到 worker 中断，任务已重新排队'
        recovered += 1
    if recovered:
        db.session.commit()
    return recovered


def claim_next_job(worker_id, lease_seconds=DEFAULT_JOB_LEASE_SECONDS):
    now = utc_now()
    candidate_ids = db.session.execute(
        select(BackgroundJob.id)
        .where(
            BackgroundJob.status == 'queued',
            or_(BackgroundJob.next_run_at.is_(None), BackgroundJob.next_run_at <= now),
        )
        .order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
    ).scalars().all()

    for job_id in candidate_ids:
        job = try_claim_job_by_id(job_id, worker_id=worker_id, lease_seconds=lease_seconds, now=now)
        if job is not None:
            return job
    return None


def try_claim_job_by_id(job_id, worker_id, lease_seconds=DEFAULT_JOB_LEASE_SECONDS, now=None):
    now = now or utc_now()
    lease_until = now + timedelta(seconds=lease_seconds)
    result = db.session.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == 'queued',
            or_(BackgroundJob.next_run_at.is_(None), BackgroundJob.next_run_at <= now),
        )
        .values(
            status='running',
            attempt_count=BackgroundJob.attempt_count + 1,
            started_at=case(
                (BackgroundJob.started_at.is_(None), now),
                else_=BackgroundJob.started_at,
            ),
            heartbeat_at=now,
            lease_until=lease_until,
            next_run_at=None,
            status_message=f'worker {worker_id} 已接手任务',
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        return None
    db.session.commit()
    return db.session.get(BackgroundJob, job_id)


def heartbeat_job(job, success_increment=0, skipped_increment=0, status_message=None, lease_seconds=DEFAULT_JOB_LEASE_SECONDS):
    now = utc_now()
    current = db.session.get(BackgroundJob, job.id)
    if current is None or current.status != 'running':
        return current

    current.success_count = (current.success_count or 0) + success_increment
    current.skipped_count = (current.skipped_count or 0) + skipped_increment
    current.progress_done = current.success_count + current.skipped_count
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.heartbeat_at = now
    current.lease_until = now + timedelta(seconds=lease_seconds)
    if status_message:
        current.status_message = status_message
    db.session.commit()
    return current


def complete_job(job, status_message='任务完成'):
    now = utc_now()
    current = db.session.get(BackgroundJob, job.id)
    if current is None or current.status != 'running':
        return current

    current.status = 'completed'
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = None
    current.status_message = status_message
    current.heartbeat_at = now
    current.finished_at = now
    current.next_run_at = None
    current.lease_until = None
    current.active_scope_key = None
    db.session.commit()
    return current


def requeue_job(job, error_message, delay_seconds=DEFAULT_REQUEUE_DELAY_SECONDS):
    current = db.session.get(BackgroundJob, job.id)
    if current is None or current.status != 'running':
        return current

    if (current.attempt_count or 0) >= (current.max_attempts or 0):
        return fail_job(current, error_message)

    now = utc_now()
    current.status = 'queued'
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = str(error_message)
    current.status_message = f'第 {current.attempt_count}/{current.max_attempts} 次执行失败，15 秒后自动重试'
    current.next_run_at = now + timedelta(seconds=delay_seconds)
    current.lease_until = None
    current.heartbeat_at = None
    db.session.commit()
    return current


def fail_job(job, error_message):
    now = utc_now()
    current = db.session.get(BackgroundJob, job.id)
    if current is None or current.status not in {'queued', 'running'}:
        return current

    current.status = 'failed'
    current.progress_done = (current.success_count or 0) + (current.skipped_count or 0)
    current.progress_total = max(current.progress_total or 0, current.progress_done)
    current.last_error = str(error_message)
    current.status_message = f'任务已自动执行 {current.max_attempts} 次仍失败'
    current.finished_at = now
    current.next_run_at = None
    current.lease_until = None
    current.active_scope_key = None
    db.session.commit()
    return current


def should_retry(job):
    return (job.attempt_count or 0) < (job.max_attempts or 0)


def _normalize_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_active_scope_unique_conflict(error):
    raw_message = str(getattr(error, 'orig', error))
    return (
        'background_jobs.active_scope_key' in raw_message
        or 'uq_background_jobs_active_scope_key' in raw_message
    )
