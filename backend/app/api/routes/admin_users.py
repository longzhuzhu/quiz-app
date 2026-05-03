"""Admin Users API 路由 - 用户列表、重置密码"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.auth import MessageResponse, ResetPasswordRequest

router = APIRouter()


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat(),
    }


@router.get("")
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.id.asc()).all()
    return [user_to_dict(u) for u in users]


@router.put("/{user_id}/password", response_model=MessageResponse)
def reset_user_password(
    user_id: int,
    data: ResetPasswordRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    new_password = data.new_password
    if not isinstance(new_password, str) or new_password.strip() == "":
        raise HTTPException(status_code=400, detail="新密码不能为空")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")

    target_user.password_hash = get_password_hash(new_password)
    db.commit()

    return MessageResponse(message="密码已重置")
