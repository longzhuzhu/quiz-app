"""Auth API 路由 - 注册、登录、当前用户"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    UserResponse,
)

router = APIRouter()


def user_to_dict(user: User) -> dict:
    """用户信息序列化（与 Flask 版本保持一致）"""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if db.query(User).filter_by(email=data.email).first():
        raise HTTPException(status_code=400, detail="邮箱已存在")

    # 第一个注册的用户自动成为管理员
    is_first_user = db.query(User).count() == 0
    user = User(
        username=data.username,
        email=data.email,
        password_hash=get_password_hash(data.password),
        is_admin=is_first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return RegisterResponse(
        message="注册成功",
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin,
            created_at=user.created_at.isoformat(),
        ),
    )


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(subject=str(user.id))

    return LoginResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin,
            created_at=user.created_at.isoformat(),
        ),
    )


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return user_to_dict(current_user)
