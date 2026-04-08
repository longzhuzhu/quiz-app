from models import BackgroundJob, BankWordFrequency, Vocabulary, db
from services.ai_service import batch_translate_terms, batch_translate_vocab
from services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
    deserialize_job_payload,
    heartbeat_job,
    list_bank_frequent_terms,
    text_missing,
    vocabulary_needs_translation,
)

PROFESSIONAL_VOCAB_BATCH_SIZE = 10
BANK_FREQUENT_BATCH_SIZE = 100

translate_professional_vocab_batch = batch_translate_vocab


def translate_bank_frequency_batch(rows):
    if not rows:
        return 0, 0

    translated_rows = batch_translate_terms([
        {'id': row.id, 'term': row.term}
        for row in rows
    ])
    translation_map = {
        item['id']: item.get('term_zh')
        for item in translated_rows
        if item.get('term_zh')
    }

    translated = 0
    for row in rows:
        term_zh = translation_map.get(row.id)
        if term_zh:
            row.term_zh = term_zh
            translated += 1

    db.session.commit()
    return translated, 0


def get_job_handler(job_type):
    if job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return handle_professional_vocab_translate
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return handle_bank_frequent_translate
    raise ValueError(f'不支持的任务类型: {job_type}')


def handle_professional_vocab_translate(job, worker_id=None):
    while True:
        batch = Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term.asc()).all()
        batch = [word for word in batch if vocabulary_needs_translation(word)][:PROFESSIONAL_VOCAB_BATCH_SIZE]
        if not batch:
            _consume_remaining_as_skipped(job)
            return

        heartbeat_job(
            job,
            status_message=(
                f'worker {worker_id or "unknown"} 正在翻译专业词汇 '
                f'({job.success_count + job.skipped_count}/{job.progress_total})'
            ),
        )
        batch_ids = [word.id for word in batch]
        translate_professional_vocab_batch(batch)
        completed_now = _count_completed_professional_vocab(batch_ids)
        if completed_now <= 0:
            raise RuntimeError('专业词汇批量翻译未产生进展')

        job = db.session.get(BackgroundJob, job.id)
        job.success_count += completed_now
        job.progress_done = job.success_count + job.skipped_count
        job.progress_total = max(job.progress_total or 0, job.progress_done)
        db.session.commit()


def handle_bank_frequent_translate(job, worker_id=None):
    payload = deserialize_job_payload(job)
    bank_id = payload.get('bank_id')
    if bank_id is None:
        raise ValueError('bank_frequent_translate 缺少 bank_id')

    while True:
        batch = [
            item for item in list_bank_frequent_terms(bank_id)
            if text_missing(item.term_zh)
        ][:BANK_FREQUENT_BATCH_SIZE]
        if not batch:
            _consume_remaining_as_skipped(job)
            return

        heartbeat_job(
            job,
            status_message=(
                f'worker {worker_id or "unknown"} 正在翻译高频词 '
                f'({job.success_count + job.skipped_count}/{job.progress_total})'
            ),
        )
        batch_ids = [row.id for row in batch]
        translate_bank_frequency_batch(batch)
        completed_now = _count_completed_bank_frequency(batch_ids)
        if completed_now <= 0:
            raise RuntimeError('高频词批量翻译未产生进展')

        job = db.session.get(BackgroundJob, job.id)
        job.success_count += completed_now
        job.progress_done = job.success_count + job.skipped_count
        job.progress_total = max(job.progress_total or 0, job.progress_done)
        db.session.commit()


def _count_completed_professional_vocab(batch_ids):
    db.session.expire_all()
    return sum(
        1
        for word in Vocabulary.query.filter(Vocabulary.id.in_(batch_ids)).all()
        if not vocabulary_needs_translation(word)
    )


def _count_completed_bank_frequency(batch_ids):
    db.session.expire_all()
    return sum(
        1
        for row in BankWordFrequency.query.filter(BankWordFrequency.id.in_(batch_ids)).all()
        if not text_missing(row.term_zh)
    )


def _consume_remaining_as_skipped(job):
    job = db.session.get(BackgroundJob, job.id)
    remaining = max((job.progress_total or 0) - (job.success_count + job.skipped_count), 0)
    if remaining:
        job.skipped_count += remaining
        job.progress_done = job.success_count + job.skipped_count
        job.progress_total = max(job.progress_total or 0, job.progress_done)
        db.session.commit()
