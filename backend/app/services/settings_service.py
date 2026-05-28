"""设置服务 - AI 配置管理、加密存储（适配 FastAPI + SQLAlchemy 2.x）"""

import base64
import hashlib
import ipaddress
import socket
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.system_setting import SystemSetting

AI_API_KEY_SETTING = "ai_api_key"
ENCRYPTED_VALUE_PREFIX = "enc:"
SCENE_MODEL_SETTING_KEYS = {
    "translate": "ai_translate_model",
    "explain": "ai_explain_model",
}
QUIZ_AI_PREWARM_ENABLED_SETTING = "quiz_ai_prewarm_enabled"


def parse_bool_setting(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def get_bool_key(db: Session, key: str, default: bool = False) -> bool:
    return parse_bool_setting(get_key(db, key, ""), default)


def set_bool_key(db: Session, key: str, value: bool) -> None:
    set_key(db, key, "true" if value else "false")


def is_quiz_ai_prewarm_enabled(db: Session) -> bool:
    return get_bool_key(db, QUIZ_AI_PREWARM_ENABLED_SETTING, True)

DISALLOWED_AI_HOSTS = {"localhost"}


def validate_ai_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip()
    if not normalized:
        raise ValueError("AI Base URL 未配置")

    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("AI Base URL 仅允许公网 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("AI Base URL 不允许包含认证信息")

    host = parsed.hostname.strip().rstrip(".").lower()
    if host in DISALLOWED_AI_HOSTS:
        raise ValueError("AI Base URL 不允许使用本机地址")

    addresses = _resolve_host_addresses(host)
    if not addresses:
        raise ValueError("AI Base URL 主机无法解析")
    for address in addresses:
        if _is_disallowed_ai_address(address):
            raise ValueError("AI Base URL 仅允许公网地址")

    return normalized


def _resolve_host_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(host)
        return [literal]
    except ValueError:
        pass

    try:
        addrinfo = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("AI Base URL 主机无法解析") from exc

    addresses = []
    for item in addrinfo:
        sockaddr = item[4]
        if not sockaddr:
            continue
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return list(dict.fromkeys(addresses))


def _is_disallowed_ai_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def get_key(db: Session, key: str, default: str = "") -> str:
    """获取 SystemSetting 值。"""
    row = db.query(SystemSetting).filter_by(key=key).first()
    if row and row.value is not None:
        return row.value
    return default


def set_key(db: Session, key: str, value: str) -> None:
    """设置 SystemSetting 值。"""
    row = db.query(SystemSetting).filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    db.flush()


def get_effective_ai_settings(
    db: Session,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    scene: str = "default",
) -> dict:
    """获取有效的 AI 配置（环境变量 < 数据库存储 < 参数覆盖）"""
    default_model = _resolve_value(
        override=model,
        stored=get_key(db, "ai_model", ""),
        fallback=settings.AI_MODEL,
    )
    resolved_base_url = _resolve_value(
        override=base_url,
        stored=get_key(db, "ai_api_base_url", ""),
        fallback=settings.AI_API_BASE_URL,
    )
    return {
        "base_url": validate_ai_base_url(resolved_base_url),
        "api_key": _resolve_api_key(db, api_key),
        "model": _resolve_scene_model(
            db,
            scene=scene,
            explicit_model=model,
            default_model=default_model,
        ),
    }


def set_encrypted_ai_api_key(db: Session, api_key: str) -> None:
    """加密保存 AI API Key"""
    set_key(db, AI_API_KEY_SETTING, _encrypt_secret(api_key.strip()))


def has_effective_ai_api_key(db: Session) -> bool:
    """判断是否已配置有效的 AI API Key"""
    try:
        return bool(get_effective_ai_settings(db).get("api_key"))
    except ValueError:
        return False


def get_masked_effective_ai_api_key(db: Session) -> str:
    """获取脱敏后的 AI API Key"""
    try:
        return _mask_key(get_effective_ai_settings(db).get("api_key", ""))
    except ValueError:
        return ""


def get_effective_ai_api_key(db: Session) -> str:
    """获取有效的 AI API Key 明文。"""
    return _resolve_api_key(db, None)


# ─── 内部辅助 ──────────────────────────────────────


def _resolve_api_key(db: Session, override: str | None) -> str:
    candidate = (override or "").strip()
    if candidate:
        return candidate

    stored_value = get_key(db, AI_API_KEY_SETTING, "")
    if stored_value:
        return _decrypt_secret(stored_value)

    return settings.AI_API_KEY


def _resolve_value(*, override: str | None, stored: str, fallback: str) -> str:
    candidate = (override or "").strip()
    if candidate:
        return candidate
    if stored:
        return stored
    return fallback


def _resolve_scene_model(
    db: Session,
    *,
    scene: str,
    explicit_model: str | None,
    default_model: str,
) -> str:
    explicit = (explicit_model or "").strip()
    if explicit:
        return explicit

    scene_key = SCENE_MODEL_SETTING_KEYS.get(scene)
    if scene_key:
        scene_model = get_key(db, scene_key, "").strip()
        if scene_model:
            return scene_model

    return default_model


def _encrypt_secret(value: str) -> str:
    if not value:
        return ""
    encrypted = _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return ENCRYPTED_VALUE_PREFIX + encrypted


def _decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(ENCRYPTED_VALUE_PREFIX):
        raise ValueError("已保存的 API Key 格式无效，请重新输入并保存")

    token = value[len(ENCRYPTED_VALUE_PREFIX) :]
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("已保存的 API Key 无法解密，请重新输入并保存") from exc


def _get_fernet() -> Fernet:
    secret = settings.SYSTEM_SETTINGS_ENCRYPTION_KEY or settings.SECRET_KEY
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "***" if key else ""
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
