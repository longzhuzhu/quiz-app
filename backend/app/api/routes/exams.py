"""Exam API 路由 - 我的考试项目"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.exam import Exam
from app.models.user import User
from app.schemas.exam import ExamCreateRequest, ExamUpdateRequest
from app.services.exam_service import DEFAULT_AI_PROFILE, delete_exam_data, get_owned_exam_or_404, now_utc, serialize_exam

router = APIRouter()


def _clean_slug(slug: str) -> str:
    return slug.strip()


def _profile_for_create(data: ExamCreateRequest, current_user: User, db: Session) -> dict:
    mode = data.ai_profile_mode or "default"
    if mode == "custom":
        return data.ai_profile or DEFAULT_AI_PROFILE
    if mode == "copy":
        if not data.copy_ai_profile_from:
            raise HTTPException(status_code=400, detail="copy_ai_profile_from 不能为空")
        source = get_owned_exam_or_404(db, current_user, data.copy_ai_profile_from)
        return source.ai_profile or DEFAULT_AI_PROFILE
    if mode != "default":
        raise HTTPException(status_code=400, detail="ai_profile_mode 不支持")
    return DEFAULT_AI_PROFILE


@router.get("")
@router.get("/")
def list_exams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exams = (
        db.query(Exam)
        .filter_by(owner_id=current_user.id)
        .order_by(Exam.sort_order.asc(), Exam.created_at.asc())
        .all()
    )
    return {"items": [serialize_exam(exam, db) for exam in exams]}


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_exam(
    data: ExamCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    slug = _clean_slug(data.slug)
    exists = db.query(Exam).filter_by(owner_id=current_user.id, slug=slug).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="EXAM_SLUG_EXISTS")

    exam = Exam(
        owner_id=current_user.id,
        slug=slug,
        name=data.name.strip(),
        short_name=data.short_name.strip(),
        description=data.description,
        icon=data.icon,
        locale=data.locale,
        sort_order=data.sort_order,
        ai_profile=_profile_for_create(data, current_user, db),
        quiz_profile={},
    )
    db.add(exam)
    db.flush()
    current_user.active_exam_id = exam.id
    db.commit()
    db.refresh(exam)
    return serialize_exam(exam, db)


@router.get("/{slug}")
def get_exam(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = get_owned_exam_or_404(db, current_user, slug)
    return serialize_exam(exam, db)


@router.patch("/{slug}")
def update_exam(
    slug: str,
    data: ExamUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = get_owned_exam_or_404(db, current_user, slug)

    if data.slug is not None:
        new_slug = _clean_slug(data.slug)
        if new_slug != exam.slug:
            exists = db.query(Exam).filter_by(owner_id=current_user.id, slug=new_slug).first()
            if exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="EXAM_SLUG_EXISTS")
            exam.slug = new_slug
    if data.name is not None:
        exam.name = data.name.strip()
    if data.short_name is not None:
        exam.short_name = data.short_name.strip()
    if data.description is not None:
        exam.description = data.description
    if data.icon is not None:
        exam.icon = data.icon
    if data.locale is not None:
        exam.locale = data.locale
    if data.sort_order is not None:
        exam.sort_order = data.sort_order
    if data.ai_profile is not None:
        exam.ai_profile = data.ai_profile
    exam.updated_at = now_utc()

    db.commit()
    db.refresh(exam)
    return serialize_exam(exam, db)


@router.delete("/{slug}")
def delete_exam(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = get_owned_exam_or_404(db, current_user, slug)
    delete_exam_data(db, exam)
    return {"message": "考试项目已删除"}
