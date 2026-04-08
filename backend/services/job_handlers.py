from models import Vocabulary, db
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


def translate_professional_vocab_batch(batch):
    if not batch:
        return 0, 0
    translated_count = batch_translate_vocab(batch)
    return translated_count, 0


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


def run_job(job):
    if job.job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return handle_professional_vocab_translate(job)
    if job.job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return handle_bank_frequent_translate(job)
    raise ValueError(f'不支持的任务类型: {job.job_type}')


def handle_professional_vocab_translate(job):
    while True:
        batch = Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term.asc()).all()
        batch = [word for word in batch if vocabulary_needs_translation(word)][:PROFESSIONAL_VOCAB_BATCH_SIZE]
        if not batch:
            _consume_remaining_as_skipped(job)
            return

        heartbeat_job(job, status_message='正在翻译专业词汇')
        translated_count, skipped_count = translate_professional_vocab_batch(batch)
        if translated_count <= 0 and skipped_count <= 0:
            raise RuntimeError('专业词汇批量翻译未产生进展')
        heartbeat_job(job, success_increment=translated_count, skipped_increment=skipped_count)
        job = db.session.get(type(job), job.id)


def handle_bank_frequent_translate(job):
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

        heartbeat_job(job, status_message='正在翻译高频词')
        translated_count, skipped_count = translate_bank_frequency_batch(batch)
        if translated_count <= 0 and skipped_count <= 0:
            raise RuntimeError('高频词批量翻译未产生进展')
        heartbeat_job(job, success_increment=translated_count, skipped_increment=skipped_count)
        job = db.session.get(type(job), job.id)


def _consume_remaining_as_skipped(job):
    job = db.session.get(type(job), job.id)
    remaining = max((job.progress_total or 0) - (job.success_count + job.skipped_count), 0)
    if remaining:
        heartbeat_job(job, skipped_increment=remaining)
