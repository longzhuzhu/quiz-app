"""Admin Users API 路由 - 用户列表、创建、禁用、删除、重置密码

账号由管理员创建，没有自助注册。所有破坏性操作都受三条约束：
不能操作自己、操作后至少保留一个可用管理员、有运行中的后台任务时不能删除。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.auth import (
    CreateUserRequest,
    MessageResponse,
    ResetPasswordRequest,
    UpdateUserRequest,
)
from app.services.exam_service import delete_user_data

router = APIRouter()


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


def _usable_admin_query(db: Session):
    return db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True))


def _ensure_not_self(admin: User, target_user: User, action: str) -> None:
    if admin.id == target_user.id:
        raise HTTPException(status_code=400, detail=f"不能{action}自己的账号")


def _ensure_another_usable_admin(db: Session, target_user: User) -> None:
    """目标账号若失去可用性（降级或停用），必须仍有其他可用管理员能登录。

    调用方先判断本次操作是否真的让目标失去可用性，本函数只看结果状态。
    """
    remaining = _usable_admin_query(db).filter(User.id != target_user.id).count()
    if remaining == 0:
        raise HTTPException(status_code=400, detail="系统必须保留至少一个可用管理员")


def _get_user_or_404(db: Session, user_id: int) -> User:
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return target_user


def _validate_new_password(new_password: str) -> None:
    if not isinstance(new_password, str) or new_password.strip() == "":
        raise HTTPException(status_code=400, detail="新密码不能为空")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")


@router.get("")
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.id.asc()).all()
    return [user_to_dict(u) for u in users]


@router.post("", status_code=201)
def create_user(
    data: CreateUserRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    username = data.username.strip()
    email = data.email.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not email:
        raise HTTPException(status_code=400, detail="邮箱不能为空")
    _validate_new_password(data.password)

    if db.query(User).filter_by(username=username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status_code=400, detail="邮箱已存在")

    user = User(
        username=username,
        email=email,
        password_hash=get_password_hash(data.password),
        is_admin=data.is_admin,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    data: UpdateUserRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_user = _get_user_or_404(db, user_id)

    next_is_admin = target_user.is_admin if data.is_admin is None else data.is_admin
    next_is_active = target_user.is_active if data.is_active is None else data.is_active
    demoting = target_user.is_admin and not next_is_admin
    disabling = target_user.is_active and not next_is_active

    if demoting:
        _ensure_not_self(current_admin, target_user, "降级")
    if disabling:
        _ensure_not_self(current_admin, target_user, "停用")

    if (demoting or disabling) and target_user.is_admin and target_user.is_active:
        _ensure_another_usable_admin(db, target_user)

    target_user.is_admin = next_is_admin
    target_user.is_active = next_is_active
    db.commit()
    db.refresh(target_user)
    return user_to_dict(target_user)


@router.delete("/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_user = _get_user_or_404(db, user_id)
    _ensure_not_self(current_admin, target_user, "删除")
    if target_user.is_admin and target_user.is_active:
        _ensure_another_usable_admin(db, target_user)

    delete_user_data(db, target_user)
    return MessageResponse(message="用户已删除")


@router.put("/{user_id}/password", response_model=MessageResponse)
def reset_user_password(
    user_id: int,
    data: ResetPasswordRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_user = _get_user_or_404(db, user_id)
    _validate_new_password(data.new_password)

    target_user.password_hash = get_password_hash(data.new_password)
    db.commit()

    return MessageResponse(message="密码已重置")
