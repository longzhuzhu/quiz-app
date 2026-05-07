"""密码哈希生成与校验，兼容历史密码哈希格式。"""

import hashlib
import hmac
import re

from passlib.context import CryptContext

try:
    import bcrypt as bcrypt_lib
except ImportError:  # pragma: no cover - 依赖缺失时只是不支持 bcrypt 兼容格式
    bcrypt_lib = None


# 新密码继续使用 FastAPI 已采用的 passlib pbkdf2_sha256 格式。
# bcrypt 通过 bcrypt 库手动验证，避免 passlib 与新版 bcrypt 包的兼容噪音。
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)


def _verify_werkzeug_pbkdf2(plain_password: str, hashed_password: str) -> bool | None:
    """验证 Werkzeug pbkdf2 哈希。

    Werkzeug 格式: pbkdf2:sha256:iterations$salt$hex_checksum
    salt 为明文 ASCII，checksum 为 hex 编码，与 passlib 的编码格式不同。
    """
    match = re.fullmatch(r"pbkdf2:([A-Za-z0-9_]+):(\d+)\$(.+)\$([0-9a-fA-F]+)", hashed_password)
    if not match:
        return None

    hash_name, iterations_text, salt, expected_checksum = match.groups()
    try:
        iterations = int(iterations_text)
        actual_checksum = hashlib.pbkdf2_hmac(
            hash_name,
            plain_password.encode(),
            salt.encode(),
            iterations,
        ).hex()
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(actual_checksum, expected_checksum.lower())


def _verify_bcrypt(plain_password: str, hashed_password: str) -> bool | None:
    """验证 bcrypt 哈希（$2a$/$2b$/$2y$）。"""
    if not re.match(r"^\$2[aby]\$", hashed_password):
        return None
    if bcrypt_lib is None:
        return False
    try:
        return bcrypt_lib.checkpw(plain_password.encode(), hashed_password.encode())
    except (ValueError, TypeError):
        return False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配。

    兼容格式：
    - passlib pbkdf2_sha256（新版默认生成）
    - bcrypt $2a$/$2b$/$2y$（兼容历史/导入数据）
    - Werkzeug pbkdf2:sha256（历史兼容格式）
    """
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False
    if plain_password == "" or hashed_password == "":
        return False

    try:
        if pwd_context.verify(plain_password, hashed_password):
            return True
    except Exception:
        pass

    bcrypt_result = _verify_bcrypt(plain_password, hashed_password)
    if bcrypt_result is not None:
        return bcrypt_result

    werkzeug_result = _verify_werkzeug_pbkdf2(plain_password, hashed_password)
    if werkzeug_result is not None:
        return werkzeug_result

    return False


def get_password_hash(password: str) -> str:
    """生成 passlib pbkdf2_sha256 密码哈希。"""
    return pwd_context.hash(password)
