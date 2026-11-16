"""平台题库共享契约：题目校验、来源协调、发布、目录与个人副本选用。

本模块只承载平台侧规则。个人题库/题目的读写仍走既有服务；这里提供
`ensure_bank_accepts_formal_writes` / `ensure_question_accepts_formal_writes`
给写入口复用，避免把「是否平台副本」的判断散落到每个路由。

锁顺序（跨后端统一）：
- 平台写者：PlatformBank → ImportJob → BackgroundJob
- 选用副本：Exam → PlatformBank → 个人 QuestionBank
- 删除项目：先锁 Exam，再枚举清理
不允许出现 PlatformBank → Exam 的反向取锁。
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob
from app.models.exam import Exam
from app.models.import_job import ImportJob
from app.models.platform_bank import (
    PLATFORM_RELEASE_SCHEMA_VERSION,
    PlatformBank,
    PlatformBankRelease,
    PlatformDraftQuestion,
)
from app.models.question import Question
from app.models.question_bank import QuestionBank

QUESTION_TYPES = ("single", "multiple", "truefalse")
# 与智能导入一致的可用性下限：完整题干至少 10 字符、至少两个选项。
MIN_CONTENT_LENGTH = 10
MIN_OPTIONS = 2
LISTED_CONFLICT_DETAIL = "题库有导入任务正在写入，请稍后再试"
UNLISTED_ADOPT_DETAIL = "题库已下架或暂不可选用，请刷新目录"


# ─── 题目内容校验 ─────────────────────────────────────────────────


def _normalize_options(raw_options) -> list[dict]:
    if isinstance(raw_options, str):
        raw_options = json.loads(raw_options or "[]")
    options = []
    for option in raw_options or []:
        if not isinstance(option, dict):
            continue
        key = str(option.get("key") or option.get("label") or "").strip()
        text = str(option.get("text") or "").strip()
        options.append({"key": key, "text": text})
    return options


def _normalize_answer_list(correct_answer) -> list[str]:
    if isinstance(correct_answer, list):
        return [str(item).strip().upper() for item in correct_answer if str(item).strip()]
    if isinstance(correct_answer, str):
        return [part.strip().upper() for part in correct_answer.split(",") if part.strip()]
    return []


def validate_question_content(
    question_type: str, content: str, options, correct_answer
) -> tuple[list[dict], str]:
    """校验草稿/发布题的完整结构与答案，返回 (规范化选项, 规范化答案串)

    不可用时抛 ValueError（路由层转 400）；发布时对全部草稿题再跑一次。
    """
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"不支持的题型: {question_type}")

    if not content or len(content.strip()) < MIN_CONTENT_LENGTH:
        raise ValueError("题干缺失或过短")

    normalized_options = _normalize_options(options)
    if len(normalized_options) < MIN_OPTIONS:
        raise ValueError("选项不足")

    keys = [option["key"] for option in normalized_options]
    if any(not key for key in keys):
        raise ValueError("选项缺少标识")
    if len({key.upper() for key in keys}) != len(keys):
        raise ValueError("选项标识重复")
    if any(not option["text"] for option in normalized_options):
        raise ValueError("选项内容不能为空")

    answers = _normalize_answer_list(correct_answer)
    if not answers:
        raise ValueError("缺少正确答案")
    option_labels = {key.upper() for key in keys}
    if any(answer not in option_labels for answer in answers):
        raise ValueError("正确答案不在选项中")

    if question_type == "single" and len(answers) != 1:
        raise ValueError("单选题只能有一个正确答案")
    if question_type == "multiple" and len(answers) < 2:
        raise ValueError("多选题至少需要两个正确答案")
    if question_type == "truefalse":
        if len(answers) != 1:
            raise ValueError("判断题只能有一个正确答案")
        if answers[0] not in {"A", "B"} or len(normalized_options) != 2:
            raise ValueError("判断题必须是两个选项且答案为 A 或 B")

    return normalized_options, ",".join(answers)


def _normalize_topics(raw_topics) -> list | None:
    """来源考点只保存描述数据（字符串或 {"code","name"}），不接受任意对象"""
    if raw_topics is None:
        return None
    if isinstance(raw_topics, str):
        raw_topics = json.loads(raw_topics or "[]")
    topics = []
    for topic in raw_topics or []:
        if isinstance(topic, str):
            text = topic.strip()
            if text:
                topics.append(text)
            continue
        if isinstance(topic, dict):
            entry = {}
            for field in ("code", "name"):
                value = topic.get(field)
                if isinstance(value, str) and value.strip():
                    entry[field] = value.strip()
            if entry:
                topics.append(entry)
    return topics or None


# ─── 来源协调与活动写者 ───────────────────────────────────────────


def get_platform_bank_or_404(db: Session, source_id: str) -> PlatformBank:
    bank = db.get(PlatformBank, source_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="平台题库不存在")
    return bank


def lock_platform_bank(db: Session, source_id: str) -> PlatformBank:
    """取得来源行锁（PostgreSQL FOR UPDATE；SQLite 由 BEGIN IMMEDIATE 提供）"""
    bank = (
        db.query(PlatformBank)
        .filter_by(id=source_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if bank is None:
        raise HTTPException(status_code=404, detail="平台题库不存在")
    return bank


def active_platform_jobs_query(db: Session, source_id: str):
    """该来源所有仍在排队或执行中的后台请求（主导入 + 重解析）"""
    return db.query(BackgroundJob).filter(
        BackgroundJob.platform_bank_id == source_id,
        BackgroundJob.status.in_(("queued", "running")),
    )


def has_active_platform_imports(db: Session, source_id: str) -> bool:
    return (
        db.query(BackgroundJob.id)
        .filter(
            BackgroundJob.platform_bank_id == source_id,
            BackgroundJob.status.in_(("queued", "running")),
        )
        .first()
        is not None
    )


def ensure_platform_source_idle(db: Session, source_id: str) -> None:
    """草稿写入口在来源锁内确认没有活动写者；有则 409"""
    if has_active_platform_imports(db, source_id):
        raise HTTPException(status_code=409, detail=LISTED_CONFLICT_DETAIL)


# ─── 来源型正式写保护 ─────────────────────────────────────────────

PLATFORM_BANK_WRITE_FORBIDDEN = (
    "该题库是平台题库的个人副本，正式内容只读；如需修正正确答案请使用专用入口"
)


def is_platform_copy(bank: QuestionBank | None) -> bool:
    return bool(bank is not None and bank.source_platform_bank_id is not None)


def ensure_bank_accepts_formal_writes(bank: QuestionBank | None) -> None:
    """平台副本禁止增题、再导入、批量考点等正式内容写入（403）"""
    if is_platform_copy(bank):
        raise HTTPException(status_code=403, detail=PLATFORM_BANK_WRITE_FORBIDDEN)


def ensure_question_accepts_formal_writes(db: Session, question: Question | None) -> None:
    """按题目所属题库判断是否为平台副本；通用整题修改/删除在此拒绝"""
    if question is None:
        return
    bank = db.get(QuestionBank, question.bank_id)
    ensure_bank_accepts_formal_writes(bank)


# ─── 发布 ─────────────────────────────────────────────────────────


def _draft_to_snapshot_item(draft: PlatformDraftQuestion) -> dict:
    return {
        "question_type": draft.question_type,
        "content": draft.content,
        "content_zh": draft.content_zh,
        "options": copy.deepcopy(_normalize_options(draft.options)),
        "correct_answer": draft.correct_answer,
        "order_index": draft.order_index,
        "source_topics": copy.deepcopy(draft.source_topics),
    }


def build_release_payload(drafts: list[PlatformDraftQuestion]) -> list[dict]:
    """按稳定顺序 (order_index, id) 构造完整快照；先全量校验，不静默过滤坏题"""
    if not drafts:
        raise ValueError("题库没有可发布的题目")
    ordered = sorted(drafts, key=lambda item: (item.order_index, item.id))
    payload = []
    for position, draft in enumerate(ordered):
        try:
            options, answer = validate_question_content(
                draft.question_type, draft.content, draft.options, draft.correct_answer
            )
        except ValueError as exc:
            raise ValueError(f"第 {position + 1} 道草稿题不可发布：{exc}") from exc
        item = _draft_to_snapshot_item(draft)
        item["options"] = options
        item["correct_answer"] = answer
        payload.append(item)
    return payload


def publish_platform_bank(db: Session, source_id: str, publisher_id: int) -> PlatformBankRelease:
    """锁来源 → 确认无活动写者 → 全量校验 → 写新版本并上架（单事务）"""
    bank = lock_platform_bank(db, source_id)
    ensure_platform_source_idle(db, source_id)

    drafts = (
        db.query(PlatformDraftQuestion)
        .filter_by(platform_bank_id=source_id)
        .order_by(PlatformDraftQuestion.order_index, PlatformDraftQuestion.id)
        .all()
    )
    payload = build_release_payload(drafts)

    latest_version = (
        db.query(func.max(PlatformBankRelease.version_number))
        .filter_by(platform_bank_id=source_id)
        .scalar()
        or 0
    )
    release = PlatformBankRelease(
        platform_bank_id=source_id,
        version_number=latest_version + 1,
        name=bank.name,
        description=bank.description,
        question_count=len(payload),
        schema_version=PLATFORM_RELEASE_SCHEMA_VERSION,
        payload=payload,
        created_by=publisher_id,
    )
    db.add(release)
    bank.is_listed = True
    db.flush()
    return release


def unpublish_platform_bank(db: Session, source_id: str) -> PlatformBank:
    """下架：只关闭目录可选用状态，保留快照与草稿，不触碰个人副本"""
    bank = lock_platform_bank(db, source_id)
    bank.is_listed = False
    db.flush()
    return bank


# ─── 目录 ─────────────────────────────────────────────────────────


def listed_platform_banks(db: Session) -> list[PlatformBank]:
    return (
        db.query(PlatformBank)
        .filter(PlatformBank.is_listed.is_(True))
        .order_by(PlatformBank.created_at, PlatformBank.id)
        .all()
    )


def latest_release(db: Session, source_id: str) -> PlatformBankRelease | None:
    """来源下最大已提交版本；不存循环发布指针"""
    return (
        db.query(PlatformBankRelease)
        .filter_by(platform_bank_id=source_id)
        .order_by(PlatformBankRelease.version_number.desc())
        .first()
    )


def latest_releases_by_source(
    db: Session, source_ids: list[str]
) -> dict[str, PlatformBankRelease]:
    """批量取每个来源的最大版本（不用 ONLY PostgreSQL 的 DISTINCT ON）"""
    if not source_ids:
        return {}
    newest = (
        db.query(
            PlatformBankRelease.platform_bank_id.label("source_id"),
            func.max(PlatformBankRelease.version_number).label("version_number"),
        )
        .filter(PlatformBankRelease.platform_bank_id.in_(source_ids))
        .group_by(PlatformBankRelease.platform_bank_id)
        .subquery()
    )
    releases = (
        db.query(PlatformBankRelease)
        .join(
            newest,
            (PlatformBankRelease.platform_bank_id == newest.c.source_id)
            & (PlatformBankRelease.version_number == newest.c.version_number),
        )
        .all()
    )
    return {release.platform_bank_id: release for release in releases}


def adopted_banks_by_source(db: Session, exam_id: int, source_ids: list[str]) -> dict[str, int]:
    if not source_ids:
        return {}
    rows = (
        db.query(QuestionBank.source_platform_bank_id, QuestionBank.id)
        .filter(
            QuestionBank.exam_id == exam_id,
            QuestionBank.source_platform_bank_id.in_(source_ids),
        )
        .all()
    )
    return {source_id: bank_id for source_id, bank_id in rows}


def directory_response(db: Session, exam: Exam) -> list[dict]:
    """目录只返回上架来源的展示信息，不含答案、快照 payload 或任务数据"""
    banks = listed_platform_banks(db)
    source_ids = [bank.id for bank in banks]
    releases = latest_releases_by_source(db, source_ids)
    adopted = adopted_banks_by_source(db, exam.id, source_ids)

    items = []
    for bank in banks:
        release = releases.get(bank.id)
        if release is None:
            # 上架状态必须有可用版本；没有版本视为不可选用，目录不展示。
            continue
        items.append(
            {
                "id": bank.id,
                "name": release.name,
                "description": release.description,
                "question_count": release.question_count,
                "published_version": release.version_number,
                "adopted_bank_id": adopted.get(bank.id),
            }
        )
    return items


# ─── 选用副本 ─────────────────────────────────────────────────────


def _lock_exam(db: Session, exam_id: int) -> Exam | None:
    return (
        db.query(Exam)
        .filter_by(id=exam_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _existing_copy(db: Session, exam_id: int, source_id: str) -> QuestionBank | None:
    return (
        db.query(QuestionBank)
        .filter_by(exam_id=exam_id, source_platform_bank_id=source_id)
        .first()
    )


def _copy_questions(
    db: Session, bank: QuestionBank, release: PlatformBankRelease
) -> int:
    """同一事务内整库复制；只在最后统一 flush，不逐题 commit"""
    created = 0
    for position, item in enumerate(release.payload or []):
        options = _normalize_options(item.get("options"))
        db.add(
            Question(
                bank_id=bank.id,
                question_type=item.get("question_type") or "single",
                content=item.get("content") or "",
                content_zh=item.get("content_zh"),
                options=options,
                correct_answer=item.get("correct_answer") or "",
                # 正式题解析只代表用户自己生成的 AI 解析，不复制平台导入审计。
                explanation=None,
                explanation_zh=None,
                order_index=position,
                source_topics=copy.deepcopy(item.get("source_topics")),
            )
        )
        created += 1
    db.flush()
    return created


def adopt_platform_bank(
    db: Session, exam: Exam, source_id: str, user_id: int
) -> tuple[QuestionBank, PlatformBankRelease, bool]:
    """获取（或复用）当前项目的个人副本。

    返回 (题库, 发布版本, 是否本次创建)。已存在的副本即使来源刚下架也照常返回，
    但这只对已经拥有副本的用户生效。
    """
    locked_exam = _lock_exam(db, exam.id)
    if locked_exam is None or locked_exam.owner_id != user_id:
        raise HTTPException(status_code=404, detail="考试项目不存在")

    bank = lock_platform_bank(db, source_id)

    existing = _existing_copy(db, exam.id, source_id)
    if existing is not None:
        release = db.get(PlatformBankRelease, existing.source_platform_release_id)
        return existing, release, False

    if not bank.is_listed:
        raise HTTPException(status_code=409, detail=UNLISTED_ADOPT_DETAIL)

    release = latest_release(db, source_id)
    if release is None:
        raise HTTPException(status_code=409, detail="题库尚未发布，暂不可选用")
    if release.schema_version != PLATFORM_RELEASE_SCHEMA_VERSION:
        raise HTTPException(status_code=409, detail="题库版本暂不受支持，请稍后再试")

    copy_bank = QuestionBank(
        exam_id=exam.id,
        name=release.name,
        description=release.description,
        source_filename=None,
        question_count=0,
        source_platform_bank_id=source_id,
        source_platform_release_id=release.id,
    )
    db.add(copy_bank)
    db.flush()

    created = _copy_questions(db, copy_bank, release)
    copy_bank.question_count = created
    db.flush()
    return copy_bank, release, True


def adopt_with_unique_retry(
    db: Session, exam: Exam, source_id: str, user_id: int
) -> tuple[QuestionBank, PlatformBankRelease | None, bool]:
    """并发兜底：只捕获项目+来源唯一键冲突并读取胜出副本，其他异常整体回滚

    任何失败都必须完整回滚：既不能留下空库/半套题，也不能让连接带着
    aborted 事务或未释放的行锁回到会话池。
    """
    try:
        return adopt_platform_bank(db, exam, source_id, user_id)
    except IntegrityError as exc:
        db.rollback()
        if not _is_source_unique_conflict(exc):
            raise
        existing = _existing_copy(db, exam.id, source_id)
        if existing is None:
            raise
        release = db.get(PlatformBankRelease, existing.source_platform_release_id)
        return existing, release, False
    except BaseException:
        db.rollback()
        raise


def _is_source_unique_conflict(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "uq_question_banks_exam_platform_source" in message


def parse_release_provenance(bank: QuestionBank) -> dict | None:
    if not is_platform_copy(bank):
        return None
    return {
        "platform_bank_id": bank.source_platform_bank_id,
        "release_id": bank.source_platform_release_id,
    }
