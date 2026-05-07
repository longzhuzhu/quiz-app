"""设置服务 - AI 配置管理、加密存储（适配 FastAPI + SQLAlchemy 2.x）"""

import base64
import hashlib

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
    return {
        "base_url": _resolve_value(
            override=base_url,
            stored=get_key(db, "ai_api_base_url", ""),
            fallback=settings.AI_API_BASE_URL,
        ),
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
