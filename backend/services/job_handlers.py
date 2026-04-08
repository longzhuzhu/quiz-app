from models import BankWordFrequency, Vocabulary, db
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
    completed_count = _count_completed_professional_vocab([word.id for word in batch])
    skipped_count = max(completed_count - translated_count, 0)
    return translated_count, skipped_count


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

    translated_count = 0
    for row in rows:
        term_zh = translation_map.get(row.id)
        if term_zh:
            row.term_zh = term_zh
            translated_count += 1

    db.session.commit()
    completed_count = _count_completed_bank_frequency([row.id for row in rows])
    skipped_count = max(completed_count - translated_count, 0)
    return translated_count, skipped_count


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
            return

        translated_count, skipped_count = translate_professional_vocab_batch(batch)
        if translated_count <= 0 and skipped_count <= 0:
            raise RuntimeError('专业词汇批量翻译未产生进展')

        job = db.session.get(type(job), job.id)
        next_done = (job.success_count or 0) + (job.skipped_count or 0) + translated_count + skipped_count
        heartbeat_job(
            job,
            success_increment=translated_count,
            skipped_increment=skipped_count,
            status_message=f'专业词汇翻译中，已处理 {next_done}/{job.progress_total}',
        )
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
            return

        translated_count, skipped_count = translate_bank_frequency_batch(batch)
        if translated_count <= 0 and skipped_count <= 0:
            raise RuntimeError('高频词批量翻译未产生进展')

        job = db.session.get(type(job), job.id)
        next_done = (job.success_count or 0) + (job.skipped_count or 0) + translated_count + skipped_count
        heartbeat_job(
            job,
            success_increment=translated_count,
            skipped_increment=skipped_count,
            status_message=f'高频词翻译中，已处理 {next_done}/{job.progress_total}',
        )
        job = db.session.get(type(job), job.id)


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
