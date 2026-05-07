"""安全模块 - JWT 认证 + 密码哈希。"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings
from services.password_security import get_password_hash, verify_password


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """创建 JWT access token

    与 Flask-JWT-Extended 保持兼容：
    - 使用同一个 JWT_SECRET_KEY 和算法
    - identity 存储为字符串形式的用户 ID
    - 默认过期时间 7 天
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": subject,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """解码并验证 JWT token，返回 payload 或 None"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None
