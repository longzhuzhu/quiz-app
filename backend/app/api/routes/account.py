"""Account API 路由 - 账户信息、修改密码"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, MessageResponse
from app.schemas.exam import ActiveExamRequest
from app.services.exam_service import get_owned_exam_or_404, serialize_exam

router = APIRouter()


def user_to_dict(user: User, db: Session | None = None) -> dict:
    data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "active_exam_id": user.active_exam_id,
        "created_at": user.created_at.isoformat(),
    }
    if db is not None:
        data["exam_count"] = user.owned_exams.count()
        data["active_exam"] = serialize_exam(user.active_exam, db) if user.active_exam else None
    return data


@router.get("")
def get_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return user_to_dict(current_user, db)


@router.post("/active-exam")
def set_active_exam(
    data: ActiveExamRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exam = get_owned_exam_or_404(db, current_user, data.slug.strip())
    current_user.active_exam_id = exam.id
    db.commit()
    db.refresh(current_user)
    return {"active_exam": serialize_exam(exam, db)}


@router.put("/password", response_model=MessageResponse)
def update_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not data.current_password:
        raise HTTPException(status_code=400, detail="当前密码错误")
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")

    new_password = data.new_password
    if not isinstance(new_password, str) or new_password.strip() == "":
        raise HTTPException(status_code=400, detail="新密码不能为空")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")

    current_user.password_hash = get_password_hash(new_password)
    db.commit()

    return MessageResponse(message="密码修改成功")
