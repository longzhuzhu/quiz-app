"""题目解析的公共行为：读取、确保生成和更新；前台与预热共用。"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session, defer

from app.models.background_job import BackgroundJob
from app.models.question import Question
from app.models.question_explanation import QuestionExplanation
from app.schemas.settings import ExplanationModelSettings
from app.services.ai_service import compose_explanation_zh, generate_structured_explanation
from app.services.answer_keys import answers_equivalent
from app.services.exam_service import DEFAULT_EXPLANATION_PERSONA
from app.services.job_service import (
    ACTIVE_STATUSES, JOB_TYPE_AI_EXPLANATION, complete_job, create_or_reuse_job,
    deserialize_job_payload, fail_job,
)
from app.services.settings_service import get_effective_ai_settings, get_explanation_models

logger = logging.getLogger(__name__)


def input_snapshot(question: Question) -> dict:
    options = json.loads(question.options) if isinstance(question.options, str) else question.options
    return {
        "content": question.content,
        "question_type": question.question_type,
        "options": [{"key": opt["key"], "text": opt["text"]} for opt in options],
    }


def input_fingerprint(question: Question) -> str:
    return hashlib.sha256(json.dumps(input_snapshot(question), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def explanation_scope(exam_id: int, question_id: int, model_id: str, fingerprint: str) -> str:
    model_hash = hashlib.sha256(model_id.encode()).hexdigest()
    return f"explain:{exam_id}:{question_id}:{model_hash}:{fingerprint}"


def _model_setting(db: Session, model_id: str | None) -> ExplanationModelSettings:
    models = get_explanation_models(db)
    if model_id is None:
        return models[0]
    for model in models:
        if model.model_id == model_id:
            return model
    raise HTTPException(status_code=422, detail="解析模型未配置或已移除")


def _result_payload(result: QuestionExplanation | None, question: Question, *, full: bool = False) -> dict | None:
    if result is None or result.input_fingerprint != input_fingerprint(question):
        return None
    payload = {
        "model_id": result.model_id,
        "judged_answer": result.judged_answer,
        "is_conflict": not answers_equivalent(result.judged_answer, question.correct_answer),
        "generated_at": result.generated_at.isoformat(),
        "generation_id": result.generation_id,
    }
    if full:
        payload.update(explanation=result.explanation, explanation_zh=result.explanation_zh, analysis=result.analysis)
    return payload


def _generation_payload(job: BackgroundJob | None) -> dict | None:
    if job is None:
        return None
    return {"id": job.id, "status": job.status, "error": job.last_error if job.status == "failed" else None}


def summaries_for_questions(db: Session, questions: list[Question], exam_id: int) -> dict[int, list[dict]]:
    """批量轻量投影；正文列不随列表或轮询加载。"""
    if not questions:
        return {}
    models = get_explanation_models(db)
    results = db.query(QuestionExplanation).options(
        defer(QuestionExplanation.explanation), defer(QuestionExplanation.explanation_zh), defer(QuestionExplanation.analysis),
    ).filter(QuestionExplanation.question_id.in_([q.id for q in questions])).all()
    by_result = {(r.question_id, r.model_id): r for r in results}
    scopes = {
        (q.id, model.model_id): explanation_scope(exam_id, q.id, model.model_id, input_fingerprint(q))
        for q in questions for model in models
    }
    jobs = db.query(BackgroundJob).filter(
        BackgroundJob.job_type == JOB_TYPE_AI_EXPLANATION,
        BackgroundJob.scope_key.in_(list(scopes.values())),
    ).distinct(BackgroundJob.scope_key).order_by(BackgroundJob.scope_key, BackgroundJob.id.desc()).all()
    by_scope = {job.scope_key: job for job in jobs}
    return {
        q.id: [{
            "model_id": model.model_id,
            "result": _result_payload(by_result.get((q.id, model.model_id)), q),
            "generation": _generation_payload(by_scope.get(scopes[(q.id, model.model_id)])),
        } for model in models] for q in questions
    }


def read_explanations(db: Session, question: Question, exam_id: int) -> dict:
    return {
        "question_id": question.id,
        "correct_answer": question.correct_answer,
        "input_fingerprint": input_fingerprint(question),
        "models": summaries_for_questions(db, [question], exam_id)[question.id],
        "has_legacy_explanation": bool(question.explanation_zh or question.explanation),
    }


def read_explanation(db: Session, question: Question, exam_id: int, model_id: str) -> dict:
    model = _model_setting(db, model_id)
    entry = summaries_for_questions(db, [question], exam_id)[question.id]
    payload = next(item for item in entry if item["model_id"] == model.model_id)
    result = db.query(QuestionExplanation).filter_by(question_id=question.id, model_id=model.model_id).populate_existing().first()
    payload["input_fingerprint"] = input_fingerprint(question)
    payload["correct_answer"] = question.correct_answer
    payload["result"] = _result_payload(result, question, full=True)
    return payload


def request_explanation(
    db: Session, question: Question, exam_id: int, owner_id: int, *,
    model_id: str | None = None, force: bool = False, prewarm: bool = False,
    expected_fingerprint: str | None = None,
) -> tuple[int, dict]:
    model = _model_setting(db, model_id)
    question = db.query(Question).filter_by(id=question.id).with_for_update().populate_existing().first()
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    if expected_fingerprint is not None and expected_fingerprint != input_fingerprint(question):
        raise HTTPException(status_code=409, detail="题目已变化，请刷新页面后重新解析")
    scope = explanation_scope(exam_id, question.id, model.model_id, input_fingerprint(question))
    latest = db.query(BackgroundJob).filter_by(scope_key=scope).order_by(BackgroundJob.id.desc()).first()
    result = db.query(QuestionExplanation).filter_by(question_id=question.id, model_id=model.model_id).first()
    if latest is not None and latest.status in ACTIVE_STATUSES:
        if not prewarm:
            latest.priority = 10
        db.commit()
        return 202, {"model_id": model.model_id, "result": _result_payload(result, question), "generation": _generation_payload(latest)}
    if not force and _result_payload(result, question) is not None:
        db.commit()
        return 200, {"model_id": model.model_id, "result": _result_payload(result, question), "generation": _generation_payload(latest)}
    if prewarm and latest is not None and latest.status == "failed":
        db.commit()
        return 200, {"model_id": model.model_id, "result": None, "generation": _generation_payload(latest)}
    payload = {
        "exam_id": exam_id, "question_id": question.id,
        "model_id": model.model_id, "input_fingerprint": input_fingerprint(question),
        "reasoning_effort": model.reasoning_effort, "priority": 0 if prewarm else 10,
    }
    _, job, _ = create_or_reuse_job(db, JOB_TYPE_AI_EXPLANATION, payload, owner_id)
    return 202, {"model_id": model.model_id, "result": _result_payload(result, question), "generation": _generation_payload(job)}


def invalidate_explanations(db: Session, question: Question) -> None:
    """调用者已经锁定题目；新题意不得复用旧结果或旧任务。"""
    db.query(QuestionExplanation).filter_by(question_id=question.id).delete(synchronize_session=False)
    db.query(BackgroundJob).filter(
        BackgroundJob.job_type == JOB_TYPE_AI_EXPLANATION,
        BackgroundJob.subject_question_id == question.id,
        BackgroundJob.status.in_(ACTIVE_STATUSES),
    ).update({
        "status": "failed", "last_error": "题目已变化，请重新解析", "status_message": "题目已变化",
        "active_scope_key": None, "finished_at": datetime.now(timezone.utc), "lease_until": None,
    }, synchronize_session=False)


def execute_explanation(db: Session, job: BackgroundJob) -> str:
    """网络期间无事务，成功结果与任务终态一起提交。"""
    payload = deserialize_job_payload(job)
    job_id = job.id
    question = db.get(Question, payload["question_id"])
    if question is None or input_fingerprint(question) != payload["input_fingerprint"]:
        fail_job(db, job, "题目已变化或已删除，请重新解析")
        return "解析输入已失效"
    snapshot = SimpleNamespace(**input_snapshot(question))
    profile = question.bank.exam.ai_profile or {}
    persona = profile.get("explanation_system_prompt") or DEFAULT_EXPLANATION_PERSONA
    try:
        config = get_effective_ai_settings(db, model=payload["model_id"], scene="explain")
        db.commit()
        analysis = generate_structured_explanation(
            snapshot, persona=persona, ai_config=config, reasoning_effort=payload["reasoning_effort"],
        )
        question = db.query(Question).filter_by(id=payload["question_id"]).with_for_update().populate_existing().first()
        current = db.query(BackgroundJob).filter_by(id=job_id).with_for_update().populate_existing().first()
        if current is None or current.status != "running":
            db.rollback()
            return "解析任务已失效"
        if question is None or input_fingerprint(question) != payload["input_fingerprint"]:
            fail_job(db, current, "题目已变化或已删除，请重新解析")
            return "解析输入已失效"
        result = db.query(QuestionExplanation).filter_by(question_id=question.id, model_id=payload["model_id"]).first()
        if result is None:
            result = QuestionExplanation(question_id=question.id, model_id=payload["model_id"])
            db.add(result)
        result.input_fingerprint = payload["input_fingerprint"]
        result.judged_answer = analysis["judged_answer"]
        result.explanation = analysis.get("explanation") or None
        result.explanation_zh = compose_explanation_zh(analysis)
        result.analysis = analysis
        result.generated_at = datetime.now(timezone.utc)
        result.generation_id = job_id
        current.success_count = 1
        complete_job(db, current, "解析完成")
        return "解析完成"
    except Exception as exc:
        logger.warning("解析任务 %s 失败（%s）", job_id, type(exc).__name__)
        db.rollback()
        current = db.get(BackgroundJob, job_id)
        if current is not None:
            message = "模型请求超时，请手动重试" if isinstance(exc, httpx.TimeoutException) else "模型调用或输出校验失败，请检查配置并手动重试"
            fail_job(db, current, message)
        return "解析失败"
