"""任务处理器 - 后台任务的具体执行逻辑（适配 FastAPI + SQLAlchemy 2.x）

所有函数显式接收 db: Session 参数。
"""

import json

from app.models.bank_word import BankWordFrequency
from app.models.question import Question
from app.models.quiz import QuizSession
from app.services.ai_service import (
    batch_translate_terms,
    explain_question,
    has_question_explanation,
    has_question_translation,
    translate_question,
)
from app.services.job_service import (
    JOB_TYPE_AI_PREWARM,
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JOB_TYPE_QUESTION_IMPORT_LLM,
    JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE,
    deserialize_job_payload,
    heartbeat_job,
    list_bank_frequent_terms,
    text_missing,
)
from app.services.settings_service import is_quiz_ai_prewarm_enabled

from sqlalchemy.orm import Session

BANK_FREQUENT_BATCH_SIZE = 100


def run_job(db: Session, job) -> None:
    """根据 job_type 分派任务"""
    if job.job_type == JOB_TYPE_AI_PREWARM:
        return handle_ai_prewarm(db, job)
    if job.job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return handle_bank_frequent_translate(db, job)
    if job.job_type == JOB_TYPE_QUESTION_IMPORT_LLM:
        return handle_question_import_llm(db, job)
    if job.job_type == JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE:
        return handle_question_import_llm_reparse(db, job)
    raise ValueError(f"不支持的任务类型: {job.job_type}")


def handle_ai_prewarm(db: Session, job) -> None:
    payload = deserialize_job_payload(job)
    if not is_quiz_ai_prewarm_enabled(db):
        heartbeat_job(db, job, skipped_increment=1, status_message="答题预热已关闭，跳过任务")
        return

    question_id = payload.get("question_id")
    exam_id = payload.get("exam_id")
    session_id = payload.get("session_id")
    artifact_type = payload.get("artifact_type")
    if artifact_type not in {"translation", "explanation"}:
        raise ValueError("ai_prewarm 缺少有效 artifact_type")

    session = db.get(QuizSession, session_id)
    question = db.get(Question, question_id)
    if not session or not question or not question.bank:
        heartbeat_job(db, job, skipped_increment=1, status_message="预热对象不存在，跳过任务")
        return
    if question.bank.exam_id != exam_id or session.bank_id != question.bank_id:
        heartbeat_job(db, job, skipped_increment=1, status_message="预热对象不属于当前考试项目或会话，跳过任务")
        return

    session_question_ids = json.loads(session.question_ids) if session.question_ids else []
    if question.id not in session_question_ids:
        heartbeat_job(db, job, skipped_increment=1, status_message="题目不属于答题会话，跳过任务")
        return

    if artifact_type == "translation":
        if has_question_translation(question):
            heartbeat_job(db, job, skipped_increment=1, status_message="翻译缓存已存在，跳过任务")
            return
        translate_question(db, question)
        heartbeat_job(db, job, success_increment=1, status_message="题目翻译预热完成")
        return

    if has_question_explanation(question):
        heartbeat_job(db, job, skipped_increment=1, status_message="AI 解析缓存已存在，跳过任务")
        return
    explain_question(db, question)
    heartbeat_job(db, job, success_increment=1, status_message="题目 AI 解析预热完成")


def handle_bank_frequent_translate(db: Session, job) -> None:
    payload = deserialize_job_payload(job)
    bank_id = payload.get("bank_id")
    if bank_id is None:
        raise ValueError("bank_frequent_translate 缺少 bank_id")

    while True:
        batch = [
            item for item in list_bank_frequent_terms(db, bank_id)
            if text_missing(item.term_zh)
        ][:BANK_FREQUENT_BATCH_SIZE]
        if not batch:
            return

        translated_count, skipped_count = translate_bank_frequency_batch(db, batch)
        if translated_count <= 0 and skipped_count <= 0:
            raise RuntimeError("高频词批量翻译未产生进展")

        job = db.get(type(job), job.id)
        next_done = (job.success_count or 0) + (job.skipped_count or 0) + translated_count + skipped_count
        heartbeat_job(
            db,
            job,
            success_increment=translated_count,
            skipped_increment=skipped_count,
            status_message=f"高频词翻译中，已处理 {next_done}/{job.progress_total}",
        )
        job = db.get(type(job), job.id)


# ─── 智能导入任务处理 ──────────────────────────────────


def handle_question_import_llm(db: Session, job) -> None:
    """处理智能导入任务"""
    from app.services.smart_import_service import run_smart_import
    run_smart_import(db, job)


def handle_question_import_llm_reparse(db: Session, job) -> None:
    """处理单个 chunk 的重新解析"""
    from app.services.smart_import_service import run_reparse
    run_reparse(db, job)


# ─── 内部辅助 ──────────────────────────────────────


def translate_bank_frequency_batch(db: Session, rows: list) -> tuple[int, int]:
    if not rows:
        return 0, 0

    translated_rows = batch_translate_terms(
        [{"id": row.id, "term": row.term} for row in rows],
        db,
    )
    translation_map = {
        item["id"]: item.get("term_zh")
        for item in translated_rows
        if item.get("term_zh")
    }

    translated_count = 0
    for row in rows:
        term_zh = translation_map.get(row.id)
        if term_zh:
            row.term_zh = term_zh
            translated_count += 1

    db.commit()
    completed_count = _count_completed_bank_frequency(db, [row.id for row in rows])
    skipped_count = max(completed_count - translated_count, 0)
    return translated_count, skipped_count


def _count_completed_bank_frequency(db: Session, batch_ids: list[int]) -> int:
    db.expire_all()
    return sum(
        1
        for row in db.query(BankWordFrequency).filter(BankWordFrequency.id.in_(batch_ids)).all()
        if not text_missing(row.term_zh)
    )
