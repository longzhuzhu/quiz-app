"""智能导入服务 - 文件抽取、Chunk 切片、LLM 解析、质量评分、自动入库/人工复核

核心流程：
  文件上传 → 创建 ImportJob/BackgroundJob → Worker 异步执行
  → 文本抽取 → Chunk 切片 → LLM 结构化解析 → Pydantic/程序校验
  → 高置信度自动入库 → 低置信度进入人工复核
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import compute_file_hash, save_upload_file
from app.models.background_job import BackgroundJob
from app.models.bank_word import BankWordExclusion, BankWordFrequency
from app.models.import_chunk import ImportChunk
from app.models.import_job import ImportJob
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.import_review_item import ImportReviewItem
from app.models.llm_parse_cache import LlmParseCache
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.schemas.llm_parse import LlmParseResult, ParsedQuestion
from app.services.ai_service import call_ai_api
from app.services.import_service import build_bank_word_frequencies
from app.services.job_service import (
    JOB_TYPE_QUESTION_IMPORT_LLM,
    JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE,
    complete_job,
    fail_job,
    heartbeat_job,
    requeue_job,
)

logger = logging.getLogger(__name__)

# ─── 常量 ──────────────────────────────────────

PROMPT_VERSION = "v1"
CHUNK_MAX_CHARS = 12000
CHUNK_MIN_CHARS = 500
AUTO_ACCEPT_CONFIDENCE = Decimal("0.90")

# 题号分割模式（优先级从高到低）
QUESTION_SPLIT_PATTERNS = [
    re.compile(r'(?:^|\n)\s*Question\s+#?\d+', re.IGNORECASE),
    re.compile(r'(?:^|\n)\s*QUESTION\s*[:#]\s*\d+', re.IGNORECASE),
    re.compile(r'(?:^|\n)\s*NEW\s+QUESTION\s+\d+', re.IGNORECASE),
    re.compile(r'(?:^|\n)\s*NO\.\s*\d+', re.IGNORECASE),
]

# 答案键检测模式
ANSWER_KEY_PATTERN = re.compile(
    r'(?:Answer\s*Key|Answers?\s*:|ANSWER\s*KEY|正确答案)[:\s]*\n([\s\S]+?)$',
    re.IGNORECASE,
)

# 答案键条目解析
ANSWER_ENTRY_PATTERN = re.compile(
    r'(\d{1,4})[.\s)]+\s*([A-Ea-e](?:\s*[,，]\s*[A-Ea-e])*|True|False)',
    re.IGNORECASE,
)

# 噪声关键词（页眉页脚常见内容）
NOISE_PATTERNS = [
    re.compile(r'CIPT\s+(?:Exam|Dumps|Questions|Practice)', re.IGNORECASE),
    re.compile(r'Page\s+\d+\s*(?:of|/)\s*\d+', re.IGNORECASE),
    re.compile(r'Passing\s+Score.*Time\s+Limit', re.IGNORECASE),
    re.compile(r'IAPP\s+Certified\s+Information', re.IGNORECASE),
    re.compile(r'www\.\S+\.(com|net|org)', re.IGNORECASE),
    re.compile(r'ExamQuestions\s+v\d', re.IGNORECASE),
    re.compile(r'by\s+Willow', re.IGNORECASE),
    re.compile(r'File\s+Version\s+\d', re.IGNORECASE),
]


# ─── 去重签名 ──────────────────────────────────


def _question_signature(
    question_type: str, content: str, options: list, correct_answer: list
) -> tuple:
    """生成题目唯一签名，用于去重（复用旧版逻辑，增强 options/answer 排序归一化）"""
    normalized_options = (
        json.dumps(
            sorted(options, key=lambda o: o.get("label", o.get("key", ""))),
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        if isinstance(options, list)
        else str(options)
    )
    normalized_answer = (
        ",".join(sorted(a.strip().upper() for a in correct_answer))
        if correct_answer
        else ""
    )
    return (
        question_type,
        (content or "").strip(),
        normalized_options,
        normalized_answer,
    )


# ─── 创建导入任务 ──────────────────────────────────


def create_smart_import_job(
    db: Session,
    bank_id: int,
    file_bytes: bytes,
    filename: str,
    user_id: int,
    auto_import: bool = True,
    use_llm_cache: bool = True,
    force: bool = False,
) -> dict:
    """创建 ImportJob + BackgroundJob，返回导入任务信息"""
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        return {"error": "题库不存在"}

    # 校验文件大小
    if len(file_bytes) > settings.upload_max_size_bytes:
        return {"error": f"文件大小超过限制（最大 {settings.MAX_UPLOAD_SIZE_MB}MB）"}

    # 确定文件类型
    filename_lower = (filename or "").lower()
    if filename_lower.endswith(".pdf"):
        file_type = "pdf"
    elif filename_lower.endswith(".xlsx"):
        file_type = "xlsx"
    elif filename_lower.endswith(".docx"):
        file_type = "docx"
    else:
        return {"error": f"不支持的文件格式: {filename}"}

    # 保存文件（先保存以获取 file_hash）
    file_path, file_hash = save_upload_file(file_bytes, filename)

    # 同文件重复导入检测
    if not force:
        dup_job = (
            db.query(ImportJob)
            .filter_by(bank_id=bank_id, file_hash=file_hash)
            .filter(ImportJob.status.in_(["completed", "partial_imported", "parsing", "extracting", "chunking", "validating", "review_required"]))
            .first()
        )
        if dup_job:
            return {
                "error": "该文件已导入过",
                "duplicate_of": dup_job.id,
                "existing_status": dup_job.status,
                "hint": "使用 force=true 强制重新导入",
            }

    # 创建 ImportJob
    import_job = ImportJob(
        bank_id=bank_id,
        file_name=filename,
        file_path=file_path,
        file_hash=file_hash,
        file_type=file_type,
        status="pending",
        config_json={
            "auto_import": auto_import,
            "use_llm_cache": use_llm_cache,
        },
        created_by=user_id,
    )
    db.add(import_job)
    db.flush()

    # 创建 BackgroundJob
    scope_key = f"import_llm:{import_job.id}"
    payload = {
        "import_job_id": import_job.id,
        "bank_id": bank_id,
        "file_path": file_path,
        "file_name": filename,
        "file_type": file_type,
        "auto_import": auto_import,
        "use_llm_cache": use_llm_cache,
    }
    bg_job = BackgroundJob(
        job_type=JOB_TYPE_QUESTION_IMPORT_LLM,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="queued",
        progress_total=0,
        status_message="等待后台 worker 执行智能导入",
        created_by=user_id,
    )
    db.add(bg_job)
    db.flush()

    import_job.background_job_id = bg_job.id
    db.commit()

    return {
        "import_job_id": import_job.id,
        "background_job_id": bg_job.id,
        "status": "pending",
    }


# ─── 主编排器 ──────────────────────────────────


def run_smart_import(db: Session, background_job: BackgroundJob) -> None:
    """智能导入主编排器，由 Worker 调用"""
    payload = _deserialize_payload(background_job)
    import_job_id = payload.get("import_job_id")
    if not import_job_id:
        raise ValueError("payload 缺少 import_job_id")

    import_job = db.get(ImportJob, import_job_id)
    if not import_job:
        raise ValueError(f"ImportJob {import_job_id} 不存在")

    file_path = payload.get("file_path", "")
    file_type = payload.get("file_type", "")
    auto_import = payload.get("auto_import", True)
    use_llm_cache = payload.get("use_llm_cache", True)

    # 阶段1：文本抽取
    _update_import_job_status(db, import_job, "extracting")
    try:
        pages = _extract_pages_from_file(file_path, file_type)
    except Exception as exc:
        _fail_import_job(db, import_job, f"文件抽取失败: {exc}")
        return

    if not pages:
        _fail_import_job(db, import_job, "文件抽取结果为空")
        return

    import_job.total_pages = len(pages)
    db.commit()

    # 阶段2：文本规范化与 Chunk 切片
    _update_import_job_status(db, import_job, "chunking")
    full_text = "\n".join(p["text"] for p in pages)
    normalized_text = _normalize_text(full_text)

    # 检测并提取答案键
    answer_key = _extract_answer_key(normalized_text)
    answer_key_text = ""
    if answer_key:
        # 移除答案键部分以避免重复解析
        normalized_text = ANSWER_KEY_PATTERN.sub("", normalized_text).strip()
        answer_key_text = _format_answer_key(answer_key)

    chunks_data = _split_into_chunks(pages, normalized_text, answer_key_text)

    if not chunks_data:
        _fail_import_job(db, import_job, "文本切片结果为空，无法继续解析")
        return

    # 保存 chunks 到数据库
    for chunk_data in chunks_data:
        chunk_hash = hashlib.sha256(chunk_data["chunk_text"].encode("utf-8")).hexdigest()
        chunk = ImportChunk(
            import_job_id=import_job.id,
            chunk_no=chunk_data["chunk_no"],
            start_page=chunk_data.get("start_page"),
            end_page=chunk_data.get("end_page"),
            chunk_text=chunk_data["chunk_text"],
            normalized_text=chunk_data.get("normalized_text", ""),
            chunk_hash=chunk_hash,
            status="pending",
        )
        db.add(chunk)
    db.flush()

    import_job.total_chunks = len(chunks_data)

    # 将 answer_key_text 持久化到 config_json，供 _process_chunk 引用
    if answer_key_text:
        config = import_job.config_json or {}
        config["answer_key_text"] = answer_key_text
        import_job.config_json = config

    db.commit()

    # 阶段3：LLM 解析
    _update_import_job_status(db, import_job, "parsing")

    # 构建 seen_signatures：Bank 已有题目 + 本 Job 已入库题目
    seen_signatures = set()
    existing_questions = db.query(Question).filter_by(bank_id=import_job.bank_id).all()
    for eq in existing_questions:
        eq_options = eq.options if isinstance(eq.options, list) else json.loads(eq.options or "[]")
        eq_answer = [a.strip() for a in (eq.correct_answer or "").split(",")] if eq.correct_answer else []
        seen_signatures.add(_question_signature(eq.question_type, eq.content, eq_options, eq_answer))

    chunks = (
        db.query(ImportChunk)
        .filter_by(import_job_id=import_job.id)
        .order_by(ImportChunk.chunk_no.asc())
        .all()
    )

    # 更新 BackgroundJob progress_total 为实际 chunk 数
    bg_job = db.get(BackgroundJob, background_job.id)
    if bg_job and bg_job.progress_total == 0:
        bg_job.progress_total = len(chunks)
        db.commit()

    for index, chunk in enumerate(chunks, start=1):
        # 刷新 import_job 引用
        import_job = db.get(ImportJob, import_job_id)
        bg_job = db.get(BackgroundJob, background_job.id)

        try:
            _process_chunk(
                db=db,
                chunk=chunk,
                import_job=import_job,
                auto_import=auto_import,
                use_llm_cache=use_llm_cache,
                seen_signatures=seen_signatures,
            )
        except Exception as exc:
            logger.error("Chunk %d 解析失败: %s", chunk.chunk_no, exc)
            chunk.status = "failed"
            chunk.issues_json = {"error": str(exc)}
            import_job.failed_chunks = (import_job.failed_chunks or 0) + 1
            db.commit()
            # 单个 chunk 失败不中断整个导入

        # 心跳更新进度
        heartbeat_job(
            db,
            bg_job,
            success_increment=1,
            status_message=f"解析 Chunk {index}/{len(chunks)}",
        )

    # 阶段4：验证与汇总
    _update_import_job_status(db, import_job, "validating")
    import_job = db.get(ImportJob, import_job_id)
    _finalize_import(db, import_job)


def _process_chunk(
    db: Session,
    chunk: ImportChunk,
    import_job: ImportJob,
    auto_import: bool,
    use_llm_cache: bool,
    seen_signatures: set | None = None,
) -> None:
    """处理单个 chunk：LLM 解析 → 质量评分 → 自动入库或人工复核"""
    chunk.status = "parsing"
    db.commit()

    chunk_text = chunk.chunk_text
    config = import_job.config_json or {}
    answer_key_text = config.get("answer_key_text", "")

    # 查找 LLM 缓存
    cache_key = _build_cache_key(chunk.chunk_hash)
    cached = None
    if use_llm_cache:
        cached = _lookup_llm_cache(db, cache_key)

    if cached:
        response_text = cached.get("response_text", "")
        chunk.llm_request_json = cached.get("request_json")
        chunk.llm_response_json = json.loads(response_text) if response_text else None
        chunk.status = "parsed_cached"
    else:
        # 构建 prompt 并调用 LLM
        messages = _build_llm_prompt(chunk_text, answer_key_text)
        chunk.llm_request_json = {"messages": messages}
        db.commit()

        try:
            response_text = call_ai_api(messages, db, scene="smart_import", timeout=120.0)
        except Exception as exc:
            chunk.status = "llm_failed"
            chunk.issues_json = {"error": f"LLM 调用失败: {exc}"}
            db.commit()
            raise

        # 解析 LLM 响应
        try:
            llm_result = _parse_llm_response(response_text)
        except Exception as exc:
            chunk.status = "parse_failed"
            chunk.issues_json = {"error": f"LLM 响应解析失败: {exc}", "raw_response": response_text[:500]}
            chunk.llm_response_json = {"raw": response_text[:2000]}
            db.commit()
            raise

        chunk.llm_response_json = json.loads(response_text) if response_text else None
        chunk.status = "parsed"

        # 存入缓存
        if use_llm_cache:
            _store_llm_cache(
                db, cache_key, chunk.chunk_hash,
                request_json=chunk.llm_request_json,
                response_text=response_text,
            )

    # 如果是从缓存加载的，需要重新解析
    if cached:
        try:
            llm_result = _parse_llm_response(response_text)
        except Exception as exc:
            chunk.status = "parse_failed"
            chunk.issues_json = {"error": f"缓存响应解析失败: {exc}"}
            db.commit()
            raise

    # 保存 chunk issues
    if llm_result.chunk_issues:
        chunk.issues_json = {"chunk_issues": llm_result.chunk_issues}

    db.commit()

    # 保存解析结果
    for parsed_q in llm_result.questions:
        _save_parsed_question(
            db=db,
            parsed_q=parsed_q,
            import_job=import_job,
            chunk=chunk,
            chunk_text=chunk_text,
            auto_import=auto_import,
            seen_signatures=seen_signatures,
        )


def _save_parsed_question(
    db: Session,
    parsed_q: ParsedQuestion,
    import_job: ImportJob,
    chunk: ImportChunk,
    chunk_text: str,
    auto_import: bool,
    seen_signatures: set | None = None,
) -> None:
    """保存单个解析题目，执行质量评分并决定自动入库或人工复核"""
    # 去重签名检查
    correct_answer_list = parsed_q.correct_answer or []
    question_type = parsed_q.question_type
    if question_type == "unknown":
        question_type = "single"

    options_for_sig = [{"label": opt.label, "text": opt.text} for opt in parsed_q.options]
    sig = _question_signature(question_type, parsed_q.content, options_for_sig, correct_answer_list)
    if seen_signatures is not None and sig in seen_signatures:
        # 转换 options 格式用于存储
        options_for_storage = [{"key": opt.label, "text": opt.text} for opt in parsed_q.options]
        correct_answer_str = ",".join(correct_answer_list) if correct_answer_list else ""
        parsed_question = ImportParsedQuestion(
            import_job_id=import_job.id,
            chunk_id=chunk.id,
            source_question_no=parsed_q.source_question_no,
            question_type=question_type,
            scenario_text=parsed_q.scenario,
            content=parsed_q.content,
            options_json=options_for_storage,
            correct_answer=correct_answer_str.split(",") if correct_answer_str else [],
            explanation=parsed_q.explanation or None,
            references_json=parsed_q.references if parsed_q.references else None,
            llm_confidence=Decimal(str(round(parsed_q.confidence, 4))),
            final_confidence=Decimal("0"),
            issues_json={"issues": ["DUPLICATE"], "details": [{"code": "DUPLICATE", "severity": "LOW", "detail": "与已有题目重复"}]},
            review_status="duplicate",
            import_status="skipped",
        )
        db.add(parsed_question)
        import_job.parsed_questions = (import_job.parsed_questions or 0) + 1
        db.commit()
        return

    if seen_signatures is not None:
        seen_signatures.add(sig)

    # 质量检查
    final_confidence, issues = _quality_check(parsed_q, chunk_text)

    # 转换 options 格式：ParsedOption(label, text) -> dict(key, text)
    options_for_storage = [{"key": opt.label, "text": opt.text} for opt in parsed_q.options]

    # 转换 correct_answer 格式：list[str] -> str
    correct_answer_str = ",".join(correct_answer_list) if correct_answer_list else ""

    # 创建 ImportParsedQuestion
    parsed_question = ImportParsedQuestion(
        import_job_id=import_job.id,
        chunk_id=chunk.id,
        source_question_no=parsed_q.source_question_no,
        question_type=question_type,
        scenario_text=parsed_q.scenario,
        content=parsed_q.content,
        options_json=options_for_storage,
        correct_answer=correct_answer_str.split(",") if correct_answer_str else [],
        explanation=parsed_q.explanation or None,
        references_json=parsed_q.references if parsed_q.references else None,
        llm_confidence=Decimal(str(round(parsed_q.confidence, 4))),
        final_confidence=final_confidence,
        issues_json={"issues": [i["code"] for i in issues], "details": issues} if issues else None,
        review_status="pending",
        import_status="waiting",
    )
    db.add(parsed_question)
    db.flush()

    # 判断是否自动入库
    should_auto_import = (
        auto_import
        and _auto_accept_check(final_confidence, issues)
        and correct_answer_str  # 必须有答案
    )

    if should_auto_import:
        # 写入 Question 表
        question = _write_question_to_bank(db, parsed_question, import_job.bank_id)
        parsed_question.import_status = "imported"
        parsed_question.review_status = "auto_accepted"
        parsed_question.imported_question_id = question.id
        import_job.imported_questions = (import_job.imported_questions or 0) + 1
    else:
        # 创建 ReviewItem
        severity = "HIGH" if any(i.get("severity") == "HIGH" for i in issues) else "MEDIUM"
        review_type = issues[0]["code"] if issues else "LOW_CONFIDENCE"
        review_item = ImportReviewItem(
            import_job_id=import_job.id,
            parsed_question_id=parsed_question.id,
            review_type=review_type,
            severity=severity,
            before_json={
                "content": parsed_q.content,
                "options": options_for_storage,
                "correct_answer": parsed_q.correct_answer,
            },
            status="pending",
        )
        db.add(review_item)
        import_job.review_questions = (import_job.review_questions or 0) + 1

    import_job.parsed_questions = (import_job.parsed_questions or 0) + 1
    db.commit()


def _write_question_to_bank(
    db: Session,
    parsed_question: ImportParsedQuestion,
    bank_id: int,
) -> Question | None:
    """将解析结果写入 Question 表（双重保险：再次检查 Question 表去重）"""
    # 转换 options 和 correct_answer 格式
    options = parsed_question.options_json
    if isinstance(options, list):
        options = [
            {"key": opt.get("key", opt.get("label", "")), "text": opt.get("text", "")}
            for opt in options
        ]

    correct_answer = parsed_question.correct_answer
    if isinstance(correct_answer, list):
        correct_answer_list = correct_answer
        correct_answer_str = ",".join(correct_answer) if correct_answer else ""
    else:
        correct_answer_str = str(correct_answer) if correct_answer else ""
        correct_answer_list = [a.strip() for a in correct_answer_str.split(",")] if correct_answer_str else []

    # 双重保险：检查 Question 表是否已存在相同签名
    sig = _question_signature(
        parsed_question.question_type or "single",
        parsed_question.content,
        options,
        correct_answer_list,
    )
    existing = (
        db.query(Question)
        .filter_by(bank_id=bank_id, content=sig[1])
        .first()
    )
    if existing:
        # 比较完整签名
        existing_sig = _question_signature(
            existing.question_type,
            existing.content,
            existing.options if isinstance(existing.options, list) else json.loads(existing.options or "[]"),
            [a.strip() for a in (existing.correct_answer or "").split(",")] if existing.correct_answer else [],
        )
        if existing_sig == sig:
            logger.info("题库 %d 已存在相同题目 (id=%d)，跳过写入", bank_id, existing.id)
            parsed_question.import_status = "skipped"
            parsed_question.review_status = "duplicate"
            parsed_question.imported_question_id = existing.id
            db.flush()
            return existing

    # 获取当前最大 order_index
    max_order = db.query(func.max(Question.order_index)).filter_by(bank_id=bank_id).scalar() or -1

    question = Question(
        bank_id=bank_id,
        question_type=parsed_question.question_type or "single",
        content=parsed_question.content,
        options=options,
        correct_answer=correct_answer_str,
        explanation=parsed_question.explanation,
        order_index=max_order + 1,
    )
    db.add(question)
    db.flush()

    # 回写 imported_question_id
    parsed_question.imported_question_id = question.id
    db.flush()

    return question


# ─── 重新解析 ──────────────────────────────────


def create_reparse_job(
    db: Session,
    import_job_id: int,
    chunk_id: int,
    user_id: int,
) -> dict:
    """为单个 chunk 创建重新解析的 BackgroundJob"""
    import_job = db.get(ImportJob, import_job_id)
    if not import_job:
        return {"error": "导入任务不存在"}

    chunk = db.get(ImportChunk, chunk_id)
    if not chunk or chunk.import_job_id != import_job_id:
        return {"error": "Chunk 不存在或不属于该导入任务"}

    # 检查是否已有进行中的 reparse 任务
    scope_key = f"import_reparse:{chunk_id}"
    existing = (
        db.query(BackgroundJob)
        .filter_by(active_scope_key=scope_key)
        .order_by(BackgroundJob.id.desc())
        .first()
    )
    if existing and existing.status in ("queued", "running"):
        return {
            "background_job_id": existing.id,
            "status": existing.status,
            "message": "该 chunk 已有重新解析任务正在执行",
        }

    payload = {
        "import_job_id": import_job_id,
        "chunk_id": chunk_id,
        "bank_id": import_job.bank_id,
    }
    bg_job = BackgroundJob(
        job_type=JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="queued",
        progress_total=1,
        status_message="等待后台 worker 执行重新解析",
        created_by=user_id,
    )
    db.add(bg_job)
    db.commit()

    return {
        "background_job_id": bg_job.id,
        "status": "queued",
        "message": "重新解析任务已创建",
    }


def run_reparse(db: Session, background_job: BackgroundJob) -> None:
    """重新解析单个 chunk"""
    payload = _deserialize_payload(background_job)
    import_job_id = payload.get("import_job_id")
    chunk_id = payload.get("chunk_id")
    bank_id = payload.get("bank_id")

    import_job = db.get(ImportJob, import_job_id)
    if not import_job:
        raise ValueError(f"ImportJob {import_job_id} 不存在")

    chunk = db.get(ImportChunk, chunk_id)
    if not chunk:
        raise ValueError(f"ImportChunk {chunk_id} 不存在")

    # 删除该 chunk 下未导入的 parsed_questions 及关联的 review_items
    old_parsed = (
        db.query(ImportParsedQuestion)
        .filter_by(chunk_id=chunk_id)
        .all()
    )
    for pq in old_parsed:
        if pq.import_status == "imported" and pq.imported_question_id:
            # 已导入的题目保留，不删除
            continue
        # 删除关联的 review_items
        db.query(ImportReviewItem).filter_by(parsed_question_id=pq.id).delete()
        # 更新 import_job 统计
        if pq.review_status == "pending":
            import_job.review_questions = max(0, (import_job.review_questions or 0) - 1)
        import_job.parsed_questions = max(0, (import_job.parsed_questions or 0) - 1)
        db.delete(pq)

    db.flush()

    # 重置 chunk 状态
    chunk.status = "pending"
    chunk.llm_request_json = None
    chunk.llm_response_json = None
    chunk.issues_json = None
    db.commit()

    # 重新处理该 chunk
    config = import_job.config_json or {}
    auto_import = config.get("auto_import", True)
    use_llm_cache = False  # 重新解析时跳过缓存

    # 构建已入库题目的 seen_signatures
    seen_signatures = set()
    existing_questions = db.query(Question).filter_by(bank_id=import_job.bank_id).all()
    for eq in existing_questions:
        eq_options = eq.options if isinstance(eq.options, list) else json.loads(eq.options or "[]")
        eq_answer = [a.strip() for a in (eq.correct_answer or "").split(",")] if eq.correct_answer else []
        seen_signatures.add(_question_signature(eq.question_type, eq.content, eq_options, eq_answer))

    _process_chunk(
        db=db,
        chunk=chunk,
        import_job=import_job,
        auto_import=auto_import,
        use_llm_cache=use_llm_cache,
        seen_signatures=seen_signatures,
    )

    # 更新 import_job 状态
    if import_job.review_questions > 0:
        _update_import_job_status(db, import_job, "review_required")
    else:
        _update_import_job_status(db, import_job, "imported")

    # 更新题库统计
    _update_bank_stats(db, import_job.bank_id)


# ─── 复核操作 ──────────────────────────────────


def accept_review_item(
    db: Session,
    import_job_id: int,
    review_item_id: int,
    reviewer_id: int,
) -> dict:
    """接受复核项，按 LLM 解析结果原样写入 Question"""
    import_job = db.get(ImportJob, import_job_id)
    if not import_job:
        return {"error": "导入任务不存在"}

    review_item = db.get(ImportReviewItem, review_item_id)
    if not review_item or review_item.import_job_id != import_job_id:
        return {"error": "复核项不存在或不属于该导入任务"}

    if review_item.status != "pending":
        return {"error": f"复核项状态为 {review_item.status}，无法再次操作"}

    parsed_question = db.get(ImportParsedQuestion, review_item.parsed_question_id)
    if not parsed_question:
        return {"error": "关联的解析题目不存在"}

    # 写入 Question
    question = _write_question_to_bank(db, parsed_question, import_job.bank_id)

    # 更新状态
    parsed_question.import_status = "imported"
    parsed_question.review_status = "accepted"
    parsed_question.imported_question_id = question.id
    review_item.status = "accepted"
    review_item.reviewer_id = reviewer_id
    review_item.reviewed_at = datetime.now(timezone.utc)

    import_job.imported_questions = (import_job.imported_questions or 0) + 1
    import_job.review_questions = max(0, (import_job.review_questions or 0) - 1)
    db.commit()

    # 更新题库统计
    _update_bank_stats(db, import_job.bank_id)

    return {"question_id": question.id, "message": "题目已入库"}


def skip_review_item(
    db: Session,
    import_job_id: int,
    review_item_id: int,
    reviewer_id: int,
) -> dict:
    """跳过复核项，不入库"""
    import_job = db.get(ImportJob, import_job_id)
    if not import_job:
        return {"error": "导入任务不存在"}

    review_item = db.get(ImportReviewItem, review_item_id)
    if not review_item or review_item.import_job_id != import_job_id:
        return {"error": "复核项不存在或不属于该导入任务"}

    if review_item.status != "pending":
        return {"error": f"复核项状态为 {review_item.status}，无法再次操作"}

    parsed_question = db.get(ImportParsedQuestion, review_item.parsed_question_id)

    # 更新状态
    if parsed_question:
        parsed_question.import_status = "skipped"
        parsed_question.review_status = "skipped"
    review_item.status = "skipped"
    review_item.reviewer_id = reviewer_id
    review_item.reviewed_at = datetime.now(timezone.utc)

    import_job.review_questions = max(0, (import_job.review_questions or 0) - 1)
    db.commit()

    return {"message": "题目已跳过"}


# ─── 文件抽取 ──────────────────────────────────


def _extract_pages_from_file(file_path: str, file_type: str) -> list[dict]:
    """从文件中逐页/逐表抽取文本，返回 [{page_no, text}]"""
    if file_type == "pdf":
        return _extract_pdf_pages(file_path)
    elif file_type == "xlsx":
        return _extract_xlsx_pages(file_path)
    elif file_type == "docx":
        return _extract_docx_pages(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {file_type}")


def _extract_pdf_pages(file_path: str) -> list[dict]:
    """使用 pdfplumber 逐页抽取 PDF 文本"""
    import pdfplumber

    pages = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text and text.strip():
                pages.append({"page_no": i, "text": _clean_text(text)})
    return pages


def _extract_xlsx_pages(file_path: str) -> list[dict]:
    """使用 openpyxl 逐 sheet 抽取 XLSX 文本"""
    from openpyxl import load_workbook

    pages = []
    wb = load_workbook(file_path, read_only=True)
    for sheet_index, ws in enumerate(wb.worksheets, start=1):
        lines = []
        for row in ws.iter_rows(values_only=True):
            line = " ".join(str(c) for c in row if c is not None)
            if line.strip():
                lines.append(line)
        if lines:
            pages.append({
                "page_no": sheet_index,
                "text": "\n".join(lines),
            })
    wb.close()
    return pages


def _extract_docx_pages(file_path: str) -> list[dict]:
    """使用 python-docx 抽取 DOCX 文本（视为单页）"""
    from docx import Document

    doc = Document(file_path)
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if text:
        return [{"page_no": 1, "text": text}]
    return []


def _clean_text(text: str) -> str:
    """清理 PDF 提取文本中的控制字符和常见 ligature 问题"""
    # 复用 import_service 中的清洗逻辑
    from app.services.import_service import _clean_text as _import_clean
    return _import_clean(text)


# ─── 文本处理 ──────────────────────────────────


def _normalize_text(text: str) -> str:
    """规范化文本：合并连续空白、去除控制字符"""
    # 去除控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # 合并连续空白行为单个换行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 合并行内连续空格
    text = re.sub(r'[^\S\n]{2,}', ' ', text)
    return text.strip()


def _extract_answer_key(text: str) -> dict[int, str]:
    """从文本末尾提取答案键（如 Answer Key 部分）"""
    match = ANSWER_KEY_PATTERN.search(text)
    if not match:
        return {}

    key_text = match.group(1)
    answer_key = {}
    for m in ANSWER_ENTRY_PATTERN.finditer(key_text):
        q_num = int(m.group(1))
        answer = m.group(2).strip().upper().replace("，", ",")
        answer_key[q_num] = answer

    return answer_key if len(answer_key) >= 3 else {}  # 至少3条才算答案键


def _format_answer_key(answer_key: dict[int, str]) -> str:
    """将答案键格式化为文本供 LLM 参考"""
    lines = []
    for q_num in sorted(answer_key.keys()):
        lines.append(f"{q_num}. {answer_key[q_num]}")
    return "\n".join(lines)


def _split_into_chunks(
    pages: list[dict],
    normalized_text: str,
    answer_key_text: str,
) -> list[dict]:
    """将文本按题号切分成 chunks，每个 chunk 包含 1-5 道题

    返回: [{chunk_no, start_page, end_page, chunk_text, normalized_text}]
    答案参考表不再拼入 chunk_text，通过 _build_llm_prompt() 的 system prompt 传递
    """
    # 尝试按题号模式分割
    segments = _split_by_question_markers(normalized_text)

    if not segments:
        # 没有找到题号模式，按字符数粗切
        segments = _split_by_char_count(normalized_text)

    chunks = []
    for i, segment in enumerate(segments, start=1):
        chunks.append({
            "chunk_no": i,
            "start_page": segment.get("start_page"),
            "end_page": segment.get("end_page"),
            "chunk_text": segment["text"],
            "normalized_text": segment["text"],
        })

    return chunks


def _split_by_question_markers(text: str) -> list[dict]:
    """使用题号模式将文本分割为片段"""
    # 找到所有分割点
    best_pattern = None
    best_count = 0

    for pattern in QUESTION_SPLIT_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) > best_count:
            best_count = len(matches)
            best_pattern = pattern

    if best_count < 2 or not best_pattern:
        return []

    matches = list(best_pattern.finditer(text))
    segments = []

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment_text = text[start:end].strip()

        if segment_text:
            segments.append({"text": segment_text, "start_page": None, "end_page": None})

    # 将过小的片段合并
    merged = []
    buffer_text = ""
    for seg in segments:
        if len(buffer_text) + len(seg["text"]) > CHUNK_MAX_CHARS and buffer_text:
            merged.append({"text": buffer_text, "start_page": None, "end_page": None})
            buffer_text = seg["text"]
        else:
            buffer_text = buffer_text + "\n\n" + seg["text"] if buffer_text else seg["text"]

    if buffer_text:
        merged.append({"text": buffer_text, "start_page": None, "end_page": None})

    return merged if merged else segments


def _split_by_char_count(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[dict]:
    """按字符数粗切文本（当没有题号模式时的 fallback）"""
    if len(text) <= max_chars:
        return [{"text": text, "start_page": None, "end_page": None}]

    segments = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            # 在最近的换行处断开
            newline_pos = text.rfind("\n", start + CHUNK_MIN_CHARS, end)
            if newline_pos > start:
                end = newline_pos
        segment_text = text[start:end].strip()
        if segment_text:
            segments.append({"text": segment_text, "start_page": None, "end_page": None})
        start = end
    return segments


# ─── LLM 交互 ──────────────────────────────────


def _build_llm_prompt(chunk_text: str, answer_key_text: str = "") -> list[dict]:
    """构建 LLM 请求 messages"""
    answer_key_section = ""
    if answer_key_text:
        answer_key_section = (
            "\n以下是本文档的答案参考表，请结合此表确定每道题的答案：\n"
            f"{answer_key_text}\n"
        )

    system_content = (
        "你是一个 PDF/DOCX/XLSX 题库结构化解析器。\n"
        "\n"
        "要求：\n"
        "1. 只根据原文抽取题目，不要编造。\n"
        "2. 一个文本片段可能包含一道题或多道题。\n"
        "3. 识别题干（content）、选项（options）、答案（correct_answer）、解析（explanation）、参考资料（references）。\n"
        "4. 如果是场景题，把案例背景放入 scenario 字段。\n"
        "5. 答案必须来自原文中的 Answer / Correct Answer / Answer Key 等标记"
        + ("或答案参考表" if answer_key_text else "") + "。\n"
        "6. 如果原文没有答案，correct_answer 输出空数组。\n"
        "7. 忽略页眉、页脚、广告、水印、文件版本信息等无关内容。\n"
        "8. 输出必须是 JSON，不要输出 Markdown 代码块标记。\n"
        "9. question_type 取值: single（单选）、multiple（多选）、truefalse（判断题）、unknown（不确定）。\n"
        "10. 如果选项标记有 [CORRECT] 或类似标记，该选项即为正确答案。\n"
        "11. 只提取有明确题号标记的题目（如 Q1、Question #1、1. 等编号格式），"
        "忽略没有题号标记的段落、知识点讲解、案例分析说明等非题目内容。\n"
        "12. 如果一段文字是知识讲解而非考试题目，不要将其转化为题目格式。\n"
        f"{answer_key_section}"
        "\n"
        'JSON 格式要求：\n'
        '{\n'
        '  "questions": [\n'
        '    {\n'
        '      "source_question_no": "题号",\n'
        '      "question_type": "single",\n'
        '      "scenario": null,\n'
        '      "content": "题干文本",\n'
        '      "options": [\n'
        '        {"label": "A", "text": "选项A文本"},\n'
        '        {"label": "B", "text": "选项B文本"},\n'
        '        {"label": "C", "text": "选项C文本"},\n'
        '        {"label": "D", "text": "选项D文本"}\n'
        '      ],\n'
        '      "correct_answer": ["A"],\n'
        '      "explanation": "",\n'
        '      "references": [],\n'
        '      "confidence": 0.95,\n'
        '      "issues": []\n'
        '    }\n'
        '  ],\n'
        '  "chunk_issues": []\n'
        '}'
    )

    user_content = f"请解析以下题库文本片段：\n\n{chunk_text}"

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_llm_response(response_text: str) -> LlmParseResult:
    """解析 LLM 的 JSON 响应，使用 Pydantic 校验"""
    text = response_text.strip()

    # 去除可能的 Markdown 代码块标记
    if text.startswith("```"):
        lines = text.split("\n", 1)
        if len(lines) > 1:
            text = lines[1]
        text = text.rsplit("```", 1)[0]
        text = text.strip()

    # 尝试直接解析
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取 JSON 部分
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("LLM 响应不是合法的 JSON")

    # Pydantic 校验
    return LlmParseResult.model_validate(data)


# ─── 质量检查 ──────────────────────────────────


def _quality_check(
    parsed_q: ParsedQuestion,
    chunk_text: str,
) -> tuple[Decimal, list[dict]]:
    """质量评分，返回 (final_confidence, issues)

    评分公式：
      final_confidence = 0.25 * llm_confidence
                       + 0.20 * schema_score
                       + 0.20 * answer_evidence_score
                       + 0.15 * option_quality_score
                       + 0.10 * duplicate_safety_score
                       + 0.10 * noise_clean_score
    """
    issues = []

    # 1. schema_score: 基本字段完整性
    schema_score = 1.0
    if not parsed_q.content or len(parsed_q.content.strip()) < 10:
        schema_score *= 0.5
        issues.append({"code": "STEM_TOO_SHORT", "severity": "MEDIUM", "detail": "题干过短"})
    if len(parsed_q.options) < 2:
        schema_score *= 0.3
        issues.append({"code": "OPTION_COUNT_ABNORMAL", "severity": "HIGH", "detail": f"选项数量异常: {len(parsed_q.options)}"})
    if not parsed_q.correct_answer:
        issues.append({"code": "ANSWER_MISSING", "severity": "HIGH", "detail": "未找到答案"})

    # 2. answer_evidence_score: 答案是否在选项中
    answer_evidence_score = 1.0
    if parsed_q.correct_answer:
        option_labels = {opt.label.upper() for opt in parsed_q.options}
        for ans in parsed_q.correct_answer:
            if ans.upper() not in option_labels:
                answer_evidence_score *= 0.3
                issues.append({
                    "code": "ANSWER_NOT_IN_OPTIONS",
                    "severity": "HIGH",
                    "detail": f"答案 {ans} 不在选项中",
                })
                break
    else:
        answer_evidence_score = 0.0

    # 3. option_quality_score: 选项数量和质量
    option_quality_score = 1.0
    opt_count = len(parsed_q.options)
    if opt_count < 2 or opt_count > 8:
        option_quality_score = 0.5
    elif opt_count < 4:
        option_quality_score = 0.8
    # 检查选项文本是否过短
    short_options = sum(1 for opt in parsed_q.options if len(opt.text.strip()) < 3)
    if short_options > 0:
        option_quality_score *= 0.8

    # 4. duplicate_safety_score: 无题号标记的题目降分
    if not parsed_q.source_question_no or parsed_q.source_question_no.strip().lower() in ("unknown", ""):
        duplicate_safety_score = 0.5
        issues.append({"code": "NO_QUESTION_NO", "severity": "MEDIUM", "detail": "无题号标记，可能不是正式题目"})
    else:
        duplicate_safety_score = 1.0

    # 5. noise_clean_score: 噪声检测
    noise_clean_score = 1.0
    combined_text = parsed_q.content + " " + " ".join(opt.text for opt in parsed_q.options)
    for noise_pattern in NOISE_PATTERNS:
        if noise_pattern.search(combined_text):
            noise_clean_score *= 0.7
            issues.append({
                "code": "NOISE_DETECTED",
                "severity": "LOW",
                "detail": f"检测到可能的噪声内容",
            })
            break

    # 计算最终置信度
    llm_conf = float(parsed_q.confidence)
    final_confidence = (
        0.25 * llm_conf
        + 0.20 * schema_score
        + 0.20 * answer_evidence_score
        + 0.15 * option_quality_score
        + 0.10 * duplicate_safety_score
        + 0.10 * noise_clean_score
    )
    final_confidence = round(final_confidence, 4)

    return Decimal(str(final_confidence)), issues


def _auto_accept_check(final_confidence: Decimal, issues: list[dict]) -> bool:
    """判断是否满足自动入库条件：
    - final_confidence >= 0.90
    - 无 HIGH severity issue
    - 答案证据存在（无 ANSWER_MISSING 或 ANSWER_NOT_IN_OPTIONS）
    """
    if final_confidence < AUTO_ACCEPT_CONFIDENCE:
        return False
    for issue in issues:
        if issue.get("severity") == "HIGH":
            return False
        if issue.get("code") in ("ANSWER_MISSING", "ANSWER_NOT_IN_OPTIONS", "ANSWER_CONFLICT"):
            return False
    return True


# ─── 缓存管理 ──────────────────────────────────


def _build_cache_key(chunk_hash: str) -> str:
    """构建缓存键: sha256(model_name + prompt_version + chunk_hash)"""
    raw = f"{PROMPT_VERSION}:{chunk_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _lookup_llm_cache(db: Session, cache_key: str) -> dict | None:
    """查找 LLM 缓存"""
    cached = db.query(LlmParseCache).filter_by(cache_key=cache_key).first()
    if not cached:
        return None
    return {
        "response_text": json.dumps(cached.response_json, ensure_ascii=False) if cached.response_json else "",
        "request_json": cached.request_json,
    }


def _store_llm_cache(
    db: Session,
    cache_key: str,
    chunk_hash: str,
    request_json: dict | None = None,
    response_text: str = "",
) -> None:
    """存储 LLM 缓存"""
    response_json = None
    if response_text:
        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError:
            response_json = {"raw": response_text[:2000]}

    cache_entry = LlmParseCache(
        cache_key=cache_key,
        model_name=None,
        prompt_version=PROMPT_VERSION,
        chunk_hash=chunk_hash,
        request_json=request_json,
        response_json=response_json,
    )
    db.add(cache_entry)
    db.flush()


# ─── ImportJob 状态管理 ──────────────────────────────────


IMPORT_JOB_STATUSES = {
    "pending", "extracting", "chunking", "parsing",
    "validating", "importing", "imported",
    "review_required", "partial_imported", "failed", "cancelled",
}


def _update_import_job_status(db: Session, import_job: ImportJob, status: str) -> None:
    """更新 ImportJob 状态"""
    import_job = db.get(ImportJob, import_job.id)
    if import_job:
        import_job.status = status
        import_job.updated_at = datetime.now(timezone.utc)
        db.commit()


def _fail_import_job(db: Session, import_job: ImportJob, error_message: str) -> None:
    """标记 ImportJob 为失败"""
    import_job = db.get(ImportJob, import_job.id)
    if import_job:
        import_job.status = "failed"
        import_job.error_message = error_message
        import_job.updated_at = datetime.now(timezone.utc)
        db.commit()


def _finalize_import(db: Session, import_job: ImportJob) -> None:
    """导入完成后的汇总处理"""
    import_job = db.get(ImportJob, import_job.id)
    if not import_job:
        return

    # 统计最终结果
    total_parsed = import_job.parsed_questions or 0
    total_imported = import_job.imported_questions or 0
    total_review = import_job.review_questions or 0
    total_failed = import_job.failed_chunks or 0

    # 生成摘要
    summary = {
        "total_parsed": total_parsed,
        "total_imported": total_imported,
        "total_review": total_review,
        "total_failed": total_failed,
        "auto_import_rate": round(total_imported / total_parsed, 4) if total_parsed > 0 else 0,
    }
    import_job.summary_json = summary

    # 确定最终状态
    if total_review > 0 and total_imported > 0:
        import_job.status = "partial_imported"
    elif total_review > 0:
        import_job.status = "review_required"
    elif total_failed > 0:
        import_job.status = "partial_imported"
    else:
        import_job.status = "imported"

    import_job.updated_at = datetime.now(timezone.utc)
    db.commit()

    # 更新题库统计和高频词
    if total_imported > 0:
        _update_bank_stats(db, import_job.bank_id)

    # 更新题库源文件名
    bank = db.get(QuestionBank, import_job.bank_id)
    if bank:
        bank.source_filename = import_job.file_name
        db.commit()


def _update_bank_stats(db: Session, bank_id: int) -> None:
    """更新题库题目数量和高频词统计"""
    bank = db.get(QuestionBank, bank_id)
    if not bank:
        return

    # 更新题目数量
    total_questions = db.query(func.count(Question.id)).filter_by(bank_id=bank_id).scalar() or 0
    bank.question_count = total_questions

    # 重建高频词统计（保留已有翻译）
    existing_translations = {
        row.term: row.term_zh
        for row in db.query(BankWordFrequency).filter_by(bank_id=bank_id).all()
        if row.term_zh
    }

    all_questions = (
        db.query(Question)
        .filter_by(bank_id=bank_id)
        .order_by(Question.order_index.asc(), Question.id.asc())
        .all()
    )

    frequency_items = build_bank_word_frequencies([
        {
            "content": q.content,
            "options": q.options if isinstance(q.options, list) else json.loads(q.options),
        }
        for q in all_questions
    ])

    excluded_terms = {
        row.term
        for row in db.query(BankWordExclusion).filter_by(bank_id=bank_id).all()
    }

    db.query(BankWordFrequency).filter_by(bank_id=bank_id).delete()
    for item in frequency_items:
        if item["term"] in excluded_terms:
            continue
        db.add(BankWordFrequency(
            bank_id=bank_id,
            term=item["term"],
            term_zh=existing_translations.get(item["term"]),
            frequency=item["frequency"],
        ))

    db.commit()


# ─── 序列化辅助 ──────────────────────────────────


def serialize_import_job(import_job: ImportJob) -> dict:
    """将 ImportJob 序列化为字典"""
    bg_job = None
    if import_job.background_job_id:
        bg_job_record = import_job.background_job
        if bg_job_record:
            bg_job = {
                "id": bg_job_record.id,
                "status": bg_job_record.status,
                "progress_total": bg_job_record.progress_total,
                "progress_done": bg_job_record.progress_done,
                "status_message": bg_job_record.status_message,
            }

    return {
        "id": import_job.id,
        "bank_id": import_job.bank_id,
        "background_job_id": import_job.background_job_id,
        "file_name": import_job.file_name,
        "file_type": import_job.file_type,
        "status": import_job.status,
        "total_pages": import_job.total_pages,
        "total_chunks": import_job.total_chunks,
        "parsed_questions": import_job.parsed_questions,
        "imported_questions": import_job.imported_questions,
        "review_questions": import_job.review_questions,
        "failed_chunks": import_job.failed_chunks,
        "summary": import_job.summary_json,
        "error_message": import_job.error_message,
        "created_by": import_job.created_by,
        "created_at": import_job.created_at.isoformat() if import_job.created_at else None,
        "updated_at": import_job.updated_at.isoformat() if import_job.updated_at else None,
        "background_job": bg_job,
    }


def serialize_chunk(chunk: ImportChunk) -> dict:
    """将 ImportChunk 序列化为字典"""
    return {
        "id": chunk.id,
        "import_job_id": chunk.import_job_id,
        "chunk_no": chunk.chunk_no,
        "start_page": chunk.start_page,
        "end_page": chunk.end_page,
        "chunk_text": chunk.chunk_text,
        "status": chunk.status,
        "issues": chunk.issues_json,
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
    }


def serialize_parsed_question(pq: ImportParsedQuestion) -> dict:
    """将 ImportParsedQuestion 序列化为字典"""
    correct_answer = pq.correct_answer
    if isinstance(correct_answer, str):
        correct_answer = [a.strip() for a in correct_answer.split(",") if a.strip()]

    return {
        "id": pq.id,
        "import_job_id": pq.import_job_id,
        "chunk_id": pq.chunk_id,
        "source_question_no": pq.source_question_no,
        "question_type": pq.question_type,
        "scenario_text": pq.scenario_text,
        "content": pq.content,
        "options": pq.options_json,
        "correct_answer": correct_answer,
        "explanation": pq.explanation,
        "llm_confidence": float(pq.llm_confidence) if pq.llm_confidence else None,
        "final_confidence": float(pq.final_confidence) if pq.final_confidence else None,
        "issues": pq.issues_json,
        "review_status": pq.review_status,
        "import_status": pq.import_status,
        "imported_question_id": pq.imported_question_id,
    }


def serialize_review_item(ri: ImportReviewItem, parsed_question: ImportParsedQuestion | None = None, db: Session | None = None) -> dict:
    """将 ImportReviewItem 序列化为字典，含关联的解析题目和原始 chunk"""
    result = {
        "id": ri.id,
        "import_job_id": ri.import_job_id,
        "parsed_question_id": ri.parsed_question_id,
        "review_type": ri.review_type,
        "severity": ri.severity,
        "before_json": ri.before_json,
        "after_json": ri.after_json,
        "status": ri.status,
        "reviewer_id": ri.reviewer_id,
        "reviewed_at": ri.reviewed_at.isoformat() if ri.reviewed_at else None,
        "parsed_question": None,
        "chunk_text": None,
    }

    if parsed_question:
        result["parsed_question"] = serialize_parsed_question(parsed_question)
        # 获取关联的 chunk 文本
        if parsed_question.chunk_id and db:
            chunk = db.get(ImportChunk, parsed_question.chunk_id)
            if chunk:
                result["chunk_text"] = chunk.chunk_text

    return result


# ─── 内部辅助 ──────────────────────────────────


def _deserialize_payload(job: BackgroundJob) -> dict:
    """反序列化 BackgroundJob 的 payload_json"""
    if not job.payload_json:
        return {}
    try:
        return json.loads(job.payload_json)
    except json.JSONDecodeError:
        return {}
