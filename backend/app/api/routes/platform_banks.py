"""平台题库 API：管理员维护入口 + 登录用户的目录与个人副本选用

两组路由权限边界明确：
- `/api/admin/platform-banks/**` 全部 require_admin，不依赖 X-Exam-Slug；
  无个人项目的管理员也能管理平台内容。普通用户的个人导入路由不会读这些任务。
- `/api/platform-banks/**` 需要登录 + 显式当前项目，只提供上架目录与选用动作。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_exam_context, require_admin
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.models.exam import Exam
from app.models.import_job import ImportJob
from app.models.platform_bank import PlatformBankRelease, PlatformDraftQuestion
from app.models.user import User
from app.schemas.platform_bank import (
    PlatformAdoptResponse,
    PlatformBankCreateRequest,
    PlatformBankUpdateRequest,
    PlatformDraftQuestionCreateRequest,
    PlatformDraftQuestionUpdateRequest,
)
from app.services import platform_bank_service as service

admin_router = APIRouter()
user_router = APIRouter()


# ─── 序列化 ───────────────────────────────────────────────────────


def _draft_to_dict(draft: PlatformDraftQuestion) -> dict:
    return {
        "id": draft.id,
        "platform_bank_id": draft.platform_bank_id,
        "question_type": draft.question_type,
        "content": draft.content,
        "content_zh": draft.content_zh,
        "options": draft.options,
        "correct_answer": draft.correct_answer,
        "order_index": draft.order_index,
        "source_topics": draft.source_topics,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def _release_to_dict(release: PlatformBankRelease | None) -> dict | None:
    if release is None:
        return None
    return {
        "id": release.id,
        "version_number": release.version_number,
        "name": release.name,
        "description": release.description,
        "question_count": release.question_count,
        "schema_version": release.schema_version,
        "created_at": release.created_at.isoformat(),
    }


def _admin_bank_to_dict(db: Session, bank) -> dict:
    latest = service.latest_release(db, bank.id)
    draft_count = (
        db.query(func.count(PlatformDraftQuestion.id))
        .filter_by(platform_bank_id=bank.id)
        .scalar()
        or 0
    )
    return {
        "id": bank.id,
        "name": bank.name,
        "description": bank.description,
        "is_listed": bank.is_listed,
        "draft_question_count": draft_count,
        "latest_release": _release_to_dict(latest),
        "has_active_import": service.has_active_platform_imports(db, bank.id),
        "created_at": bank.created_at.isoformat(),
        "updated_at": bank.updated_at.isoformat(),
    }


# ─── 管理员：来源与元数据 ─────────────────────────────────────────


@admin_router.get("")
def list_platform_banks(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    banks = (
        db.query(service.PlatformBank)
        .order_by(service.PlatformBank.created_at.desc(), service.PlatformBank.id)
        .all()
    )
    return [_admin_bank_to_dict(db, bank) for bank in banks]


@admin_router.post("", status_code=201)
def create_platform_bank(
    data: PlatformBankCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = service.PlatformBank(
        name=data.name.strip(), description=data.description, created_by=admin.id
    )
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return _admin_bank_to_dict(db, bank)


@admin_router.get("/{source_id}")
def get_platform_bank(
    source_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _admin_bank_to_dict(db, service.get_platform_bank_or_404(db, source_id))


@admin_router.put("/{source_id}")
def update_platform_bank(
    source_id: str,
    data: PlatformBankUpdateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # 只改草稿元数据：目录仍显示最近发布版本冻结的名称与简介。
    bank = service.lock_platform_bank(db, source_id)
    if data.name is not None:
        bank.name = data.name.strip()
    if data.description is not None:
        bank.description = data.description
    db.commit()
    db.refresh(bank)
    return _admin_bank_to_dict(db, bank)


# ─── 管理员：草稿题维护 ───────────────────────────────────────────


@admin_router.get("/{source_id}/questions")
def list_draft_questions(
    source_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service.get_platform_bank_or_404(db, source_id)
    query = (
        db.query(PlatformDraftQuestion)
        .filter_by(platform_bank_id=source_id)
        .order_by(PlatformDraftQuestion.order_index, PlatformDraftQuestion.id)
    )
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "questions": [_draft_to_dict(item) for item in items],
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


@admin_router.post("/{source_id}/questions", status_code=201)
def create_draft_question(
    source_id: str,
    data: PlatformDraftQuestionCreateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service.lock_platform_bank(db, source_id)
    service.ensure_platform_source_idle(db, source_id)
    try:
        options, answer = service.validate_question_content(
            data.question_type, data.content, data.options, data.correct_answer
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    max_order = (
        db.query(func.max(PlatformDraftQuestion.order_index))
        .filter_by(platform_bank_id=source_id)
        .scalar()
    )
    draft = PlatformDraftQuestion(
        platform_bank_id=source_id,
        question_type=data.question_type,
        content=data.content.strip(),
        content_zh=data.content_zh,
        options=options,
        correct_answer=answer,
        order_index=(max_order + 1) if max_order is not None else 0,
        source_topics=service._normalize_topics(data.source_topics),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_to_dict(draft)


def _get_draft_or_404(db: Session, source_id: str, draft_id: int) -> PlatformDraftQuestion:
    draft = (
        db.query(PlatformDraftQuestion)
        .filter_by(id=draft_id, platform_bank_id=source_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿题目不存在")
    return draft


@admin_router.put("/{source_id}/questions/{draft_id}")
def update_draft_question(
    source_id: str,
    draft_id: int,
    data: PlatformDraftQuestionUpdateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service.lock_platform_bank(db, source_id)
    service.ensure_platform_source_idle(db, source_id)
    draft = _get_draft_or_404(db, source_id, draft_id)

    question_type = data.question_type or draft.question_type
    content = data.content if data.content is not None else draft.content
    options = data.options if data.options is not None else draft.options
    correct_answer = (
        data.correct_answer if data.correct_answer is not None else draft.correct_answer
    )
    try:
        normalized_options, answer = service.validate_question_content(
            question_type, content, options, correct_answer
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    draft.question_type = question_type
    draft.content = content.strip()
    draft.options = normalized_options
    draft.correct_answer = answer
    if data.content_zh is not None:
        draft.content_zh = data.content_zh
    if data.source_topics is not None:
        draft.source_topics = service._normalize_topics(data.source_topics)

    db.commit()
    db.refresh(draft)
    return _draft_to_dict(draft)


@admin_router.delete("/{source_id}/questions/{draft_id}")
def delete_draft_question(
    source_id: str,
    draft_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service.lock_platform_bank(db, source_id)
    service.ensure_platform_source_idle(db, source_id)
    draft = _get_draft_or_404(db, source_id, draft_id)
    db.delete(draft)
    db.commit()
    return {"message": "草稿题目已删除"}


# ─── 管理员：导入与发布 ───────────────────────────────────────────


@admin_router.post("/{source_id}/import")
def import_into_platform_bank(
    source_id: str,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # 延迟导入：平台路由在应用启动时注册，导入流水线只在真正上传时加载。
    from app.services.smart_import_service import create_platform_import_job

    service.lock_platform_bank(db, source_id)

    file_bytes = file.file.read()
    if len(file_bytes) > app_settings.upload_max_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超过限制（最大 {app_settings.MAX_UPLOAD_SIZE_MB}MB）",
        )

    result = create_platform_import_job(
        db=db,
        platform_bank_id=source_id,
        file_bytes=file_bytes,
        filename=file.filename or "unknown",
        user_id=admin.id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@admin_router.get("/{source_id}/import-jobs")
def list_platform_import_jobs(
    source_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.smart_import_service import serialize_import_job

    service.get_platform_bank_or_404(db, source_id)
    jobs = (
        db.query(ImportJob)
        .filter_by(platform_bank_id=source_id)
        .order_by(ImportJob.id.desc())
        .all()
    )
    return [serialize_import_job(job, db) for job in jobs]


def _get_platform_job_or_404(db: Session, source_id: str, job_id: int) -> ImportJob:
    """按来源定位导入任务：裸 job_id 不能跨来源/跨目标读取"""
    job = (
        db.query(ImportJob)
        .filter_by(id=job_id, platform_bank_id=source_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return job


@admin_router.get("/{source_id}/import-jobs/{job_id}")
def get_platform_import_job(
    source_id: str,
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.smart_import_service import serialize_import_job

    return serialize_import_job(_get_platform_job_or_404(db, source_id, job_id), db)


@admin_router.get("/{source_id}/import-jobs/{job_id}/chunks")
def list_platform_chunks(
    source_id: str,
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.import_chunk import ImportChunk
    from app.services.smart_import_service import serialize_chunk

    _get_platform_job_or_404(db, source_id, job_id)
    chunks = (
        db.query(ImportChunk)
        .filter_by(import_job_id=job_id)
        .order_by(ImportChunk.chunk_no.asc())
        .all()
    )
    return {"chunks": [serialize_chunk(chunk) for chunk in chunks]}


@admin_router.get("/{source_id}/import-jobs/{job_id}/parsed-questions")
def list_platform_parsed_questions(
    source_id: str,
    job_id: int,
    review_status: str | None = Query(None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """解析明细包含重复与跳过记录，不能只靠 auto-handled 证明「跳过/重复」"""
    from app.models.import_parsed_question import ImportParsedQuestion
    from app.services.smart_import_service import serialize_parsed_question

    _get_platform_job_or_404(db, source_id, job_id)
    query = (
        db.query(ImportParsedQuestion)
        .filter_by(import_job_id=job_id)
        .order_by(ImportParsedQuestion.id.asc())
    )
    if review_status:
        query = query.filter_by(review_status=review_status)
    return {"questions": [serialize_parsed_question(item) for item in query.all()]}


@admin_router.get("/{source_id}/import-jobs/{job_id}/auto-handled")
def list_platform_auto_handled(
    source_id: str,
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.import_parsed_question import ImportParsedQuestion
    from app.services.smart_import_service import serialize_auto_handled_item

    _get_platform_job_or_404(db, source_id, job_id)
    items = (
        db.query(ImportParsedQuestion)
        .filter(ImportParsedQuestion.import_job_id == job_id)
        .filter(ImportParsedQuestion.review_status.in_(["auto_accepted", "auto_skipped"]))
        .order_by(ImportParsedQuestion.id.asc())
        .all()
    )
    return {"items": [serialize_auto_handled_item(item) for item in items], "total": len(items)}


@admin_router.get("/{source_id}/import-jobs/{job_id}/review-items")
def list_platform_review_items(
    source_id: str,
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.import_parsed_question import ImportParsedQuestion
    from app.models.import_review_item import ImportReviewItem
    from app.services.smart_import_service import serialize_review_item

    _get_platform_job_or_404(db, source_id, job_id)
    review_items = (
        db.query(ImportReviewItem)
        .filter_by(import_job_id=job_id)
        .order_by(ImportReviewItem.id.asc())
        .all()
    )
    result = []
    for item in review_items:
        parsed_q = db.get(ImportParsedQuestion, item.parsed_question_id)
        result.append(serialize_review_item(item, parsed_q, db))
    return {"items": result}


def _get_platform_review_item_or_404(db: Session, job_id: int, item_id: int):
    from app.models.import_review_item import ImportReviewItem

    item = db.get(ImportReviewItem, item_id)
    if item is None or item.import_job_id != job_id:
        raise HTTPException(status_code=404, detail="复核项不存在或不属于该导入任务")
    return item


@admin_router.post("/{source_id}/import-jobs/{job_id}/review-items/{item_id}/accept")
def accept_platform_review_item(
    source_id: str,
    job_id: int,
    item_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.smart_import_service import accept_review_item

    _get_platform_job_or_404(db, source_id, job_id)
    _get_platform_review_item_or_404(db, job_id, item_id)
    result = accept_review_item(db, job_id, item_id, admin.id)
    if "error" in result:
        status_code = result.get("status_code", 404 if "不存在" in result["error"] else 400)
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@admin_router.post("/{source_id}/import-jobs/{job_id}/review-items/{item_id}/skip")
def skip_platform_review_item(
    source_id: str,
    job_id: int,
    item_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.smart_import_service import skip_review_item

    _get_platform_job_or_404(db, source_id, job_id)
    _get_platform_review_item_or_404(db, job_id, item_id)
    result = skip_review_item(db, job_id, item_id, admin.id)
    if "error" in result:
        status_code = result.get("status_code", 404 if "不存在" in result["error"] else 400)
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@admin_router.post("/{source_id}/import-jobs/{job_id}/review-items/{item_id}/reparse")
def reparse_platform_chunk(
    source_id: str,
    job_id: int,
    item_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.import_parsed_question import ImportParsedQuestion
    from app.services.smart_import_service import create_reparse_job

    _get_platform_job_or_404(db, source_id, job_id)
    item = _get_platform_review_item_or_404(db, job_id, item_id)
    parsed_q = db.get(ImportParsedQuestion, item.parsed_question_id)
    if parsed_q is None or not parsed_q.chunk_id:
        raise HTTPException(status_code=400, detail="关联的解析题目或 chunk 不存在")

    result = create_reparse_job(db, job_id, parsed_q.chunk_id, admin.id)
    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@admin_router.post("/{source_id}/publish")
def publish_platform_bank(
    source_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        release = service.publish_platform_bank(db, source_id, admin.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(release)
    return {
        "release_id": release.id,
        "version_number": release.version_number,
        "question_count": release.question_count,
        "is_listed": True,
    }


@admin_router.post("/{source_id}/unpublish")
def unpublish_platform_bank(
    source_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bank = service.unpublish_platform_bank(db, source_id)
    db.commit()
    db.refresh(bank)
    return {"id": bank.id, "is_listed": bank.is_listed}


@admin_router.get("/{source_id}/releases")
def list_releases(
    source_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service.get_platform_bank_or_404(db, source_id)
    releases = (
        db.query(PlatformBankRelease)
        .filter_by(platform_bank_id=source_id)
        .order_by(PlatformBankRelease.version_number.desc())
        .all()
    )
    return [_release_to_dict(release) for release in releases]


# ─── 登录用户：目录与选用 ─────────────────────────────────────────


@user_router.get("")
def get_directory(
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    return service.directory_response(db, exam)


@user_router.post("/{source_id}/adopt", response_model=PlatformAdoptResponse)
def adopt_platform_bank(
    source_id: str,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
    bank, release, created = service.adopt_with_unique_retry(
        db, exam, source_id, current_user.id
    )
    db.commit()
    db.refresh(bank)
    if release is None:
        raise HTTPException(status_code=409, detail=service.UNLISTED_ADOPT_DETAIL)
    return PlatformAdoptResponse(
        bank_id=bank.id,
        platform_bank_id=bank.source_platform_bank_id,
        release_id=bank.source_platform_release_id,
        published_version=release.version_number,
        created=created,
    )
