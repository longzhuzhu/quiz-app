"""Account API 路由 - 账户信息、修改密码"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, MessageResponse

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
def get_account(current_user: User = Depends(get_current_user)):
    return user_to_dict(current_user)


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
