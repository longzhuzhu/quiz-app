"""API 依赖注入 - 数据库会话、当前用户、管理员权限"""

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.exam import Exam
from app.models.user import User

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """获取当前认证用户。

    - 前端使用 Bearer token
    - JWT sub 字段存储用户 ID（字符串形式）
    - 401 触发前端登出
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization credentials",
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in token",
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求管理员权限"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


def get_exam_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_exam_slug: str | None = Header(None, alias="X-Exam-Slug"),
) -> Exam:
    if x_exam_slug is None or not x_exam_slug.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="EXAM_REQUIRED")

    exam = db.query(Exam).filter_by(
        owner_id=current_user.id,
        slug=x_exam_slug.strip(),
    ).first()
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="EXAM_NOT_FOUND")
    return exam
