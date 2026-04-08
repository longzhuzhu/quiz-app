import json
from datetime import datetime, timezone

from models import BackgroundJob, BankWordFrequency, QuestionBank, Vocabulary, db

JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE = 'professional_vocab_translate'
JOB_TYPE_BANK_FREQUENT_TRANSLATE = 'bank_frequent_translate'
ACTIVE_STATUSES = {'queued', 'running'}


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


def count_pending_items(job_type, payload):
    if job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return sum(
            1
            for word in Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term).all()
            if vocabulary_needs_translation(word)
        )

    bank_id = payload['bank_id']
    db.get_or_404(QuestionBank, bank_id)
    return BankWordFrequency.query.filter_by(bank_id=bank_id, term_zh=None).count()


def serialize_job(job):
    payload = {}
    if job.payload_json:
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            payload = {}
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
    db.session.commit()
    return 'created', job, '后台任务已创建'
