"""Auth API 路由 - 登录、当前用户

账号由管理员在用户管理页或 CLI 脚本创建，不提供自助注册。
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.services.exam_service import serialize_exam
from app.schemas.auth import LoginRequest, LoginResponse, UserResponse

router = APIRouter()

LOGIN_RATE_LIMIT_WINDOW = timedelta(minutes=15)
LOGIN_RATE_LIMIT_MAX_FAILURES = 5
_login_failures: dict[str, list[datetime]] = {}


def _login_rate_limit_key(request: Request, username: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{username.strip().lower()}"


def _prune_login_failures(key: str, now: datetime) -> list[datetime]:
    window_start = now - LOGIN_RATE_LIMIT_WINDOW
    attempts = [attempt for attempt in _login_failures.get(key, []) if attempt > window_start]
    if attempts:
        _login_failures[key] = attempts
    else:
        _login_failures.pop(key, None)
    return attempts


def _ensure_login_not_rate_limited(key: str, now: datetime) -> None:
    attempts = _prune_login_failures(key, now)
    if len(attempts) >= LOGIN_RATE_LIMIT_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")


def _record_login_failure(key: str, now: datetime) -> None:
    attempts = _prune_login_failures(key, now)
    attempts.append(now)
    _login_failures[key] = attempts


def _clear_login_failures(key: str) -> None:
    _login_failures.pop(key, None)


def user_to_dict(user: User, db: Session | None = None) -> dict:
    """用户信息序列化。"""
    data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "active_exam_id": user.active_exam_id,
        "created_at": user.created_at.isoformat(),
    }
    if db is not None:
        data["exam_count"] = user.owned_exams.count()
        data["active_exam"] = serialize_exam(user.active_exam, db) if user.active_exam else None
    return data


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rate_limit_key = _login_rate_limit_key(request, data.username)
    _ensure_login_not_rate_limited(rate_limit_key, now)

    user = db.query(User).filter_by(username=data.username).first()
    # 禁用账号与密码错误共用同一提示，不向未认证请求方确认账号存在性。
    if not user or not verify_password(data.password, user.password_hash) or not user.is_active:
        _record_login_failure(rate_limit_key, now)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _clear_login_failures(rate_limit_key)
    token = create_access_token(subject=str(user.id))

    return LoginResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin,
            is_active=user.is_active,
            active_exam_id=user.active_exam_id,
            created_at=user.created_at.isoformat(),
        ),
    )


@router.get("/me")
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return user_to_dict(current_user, db)
