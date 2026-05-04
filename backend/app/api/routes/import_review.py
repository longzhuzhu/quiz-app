"""Import Review API 路由 - 人工复核：查看待复核项、接受、跳过、重新解析"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.import_review_item import ImportReviewItem
from app.models.user import User
from app.services.smart_import_service import (
    accept_review_item,
    create_reparse_job,
    serialize_review_item,
    skip_review_item,
)

router = APIRouter()


@router.get("/{job_id}/review-items")
def list_review_items(
    job_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """获取导入任务的待复核项目"""
    from app.models.import_job import ImportJob
    import_job = db.get(ImportJob, job_id)
    if not import_job:
        raise HTTPException(status_code=404, detail="导入任务不存在")

    review_items = (
        db.query(ImportReviewItem)
        .filter_by(import_job_id=job_id)
        .order_by(ImportReviewItem.id.asc())
        .all()
    )

    result = []
    for ri in review_items:
        parsed_q = db.get(ImportParsedQuestion, ri.parsed_question_id)
        result.append(serialize_review_item(ri, parsed_q, db))

    return {"items": result}


@router.post("/{job_id}/review-items/{item_id}/accept")
def accept_item(
    job_id: int,
    item_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """接受复核项，按 LLM 解析结果原样写入 Question"""
    result = accept_review_item(db, job_id, item_id, _admin.id)
    if "error" in result:
        status_code = 404 if "不存在" in result["error"] else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.post("/{job_id}/review-items/{item_id}/skip")
def skip_item(
    job_id: int,
    item_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """跳过复核项，不入库"""
    result = skip_review_item(db, job_id, item_id, _admin.id)
    if "error" in result:
        status_code = 404 if "不存在" in result["error"] else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.post("/{job_id}/review-items/{item_id}/reparse")
def reparse_item(
    job_id: int,
    item_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """异步重新解析复核项对应的 chunk"""
    # 先获取 review item 找到关联的 chunk
    review_item = db.get(ImportReviewItem, item_id)
    if not review_item or review_item.import_job_id != job_id:
        raise HTTPException(status_code=404, detail="复核项不存在或不属于该导入任务")

    parsed_q = db.get(ImportParsedQuestion, review_item.parsed_question_id)
    if not parsed_q or not parsed_q.chunk_id:
        raise HTTPException(status_code=400, detail="关联的解析题目或 chunk 不存在")

    result = create_reparse_job(db, job_id, parsed_q.chunk_id, _admin.id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
