"""安全模块 - JWT 认证 + 密码哈希（兼容 Werkzeug pbkdf2 格式）"""

import hashlib
import re
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# 密码哈希上下文
# 新密码使用 passlib pbkdf2_sha256 格式，旧 Werkzeug 格式通过 _verify_werkzeug_pbkdf2 兼容
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)


def _verify_werkzeug_pbkdf2(plain_password: str, hashed_password: str) -> bool | None:
    """验证 Werkzeug 格式的 pbkdf2 哈希

    Werkzeug 格式: pbkdf2:sha256:iterations$salt$hex_checksum
    其中 salt 是明文 ASCII，checksum 是 hex 编码。
    与 passlib 的 AB64 编码不同，需要单独处理。
    """
    m = re.match(r"pbkdf2:(\w+):(\d+)\$(.+)\$(.+)", hashed_password)
    if not m:
        return None
    hash_name, iterations_str, salt, hex_checksum = m.groups()
    iterations = int(iterations_str)
    dk = hashlib.pbkdf2_hmac(
        hash_name, plain_password.encode(), salt.encode(), iterations
    )
    return dk.hex() == hex_checksum


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配

    兼容两种格式：
    - passlib pbkdf2_sha256 格式（新系统生成）
    - Werkzeug pbkdf2:sha256 格式（Flask 时期遗留）
    """
    # 先尝试 passlib 格式
    try:
        if pwd_context.verify(plain_password, hashed_password):
            return True
    except Exception:
        pass

    # 再尝试 Werkzeug 格式
    result = _verify_werkzeug_pbkdf2(plain_password, hashed_password)
    if result is not None:
        return result

    return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（passlib 格式）"""
    return pwd_context.hash(password)


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
