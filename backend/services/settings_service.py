import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from models import SystemSetting

AI_API_KEY_SETTING = 'ai_api_key'
ENCRYPTED_VALUE_PREFIX = 'enc:'


def get_effective_ai_settings(*, base_url=None, api_key=None, model=None):
    config = current_app.config
    return {
        'base_url': _resolve_value(
            override=base_url,
            stored=SystemSetting.get('ai_api_base_url', ''),
            fallback=config.get('AI_API_BASE_URL', 'https://api.openai.com'),
        ),
        'api_key': _resolve_api_key(api_key),
        'model': _resolve_value(
            override=model,
            stored=SystemSetting.get('ai_model', ''),
            fallback=config.get('AI_MODEL', 'gpt-4o-mini'),
        ),
    }


def set_encrypted_ai_api_key(api_key):
    SystemSetting.set(AI_API_KEY_SETTING, _encrypt_secret(api_key.strip()))


def has_effective_ai_api_key():
    try:
        return bool(get_effective_ai_settings().get('api_key'))
    except ValueError:
        return False


def get_masked_effective_ai_api_key():
    try:
        return _mask_key(get_effective_ai_settings().get('api_key', ''))
    except ValueError:
        return ''


def _resolve_api_key(override):
    candidate = (override or '').strip()
    if candidate:
        return candidate

    stored_value = SystemSetting.get(AI_API_KEY_SETTING, '')
    if stored_value:
        return _decrypt_secret(stored_value)

    return current_app.config.get('AI_API_KEY', '')


def _resolve_value(*, override, stored, fallback):
    candidate = (override or '').strip()
    if candidate:
        return candidate
    if stored:
        return stored
    return fallback


def _encrypt_secret(value):
    if not value:
        return ''

    encrypted = _get_fernet().encrypt(value.encode('utf-8')).decode('utf-8')
    return ENCRYPTED_VALUE_PREFIX + encrypted


def _decrypt_secret(value):
    if not value:
        return ''
    if not value.startswith(ENCRYPTED_VALUE_PREFIX):
        raise ValueError('已保存的 API Key 格式无效，请重新输入并保存')

    token = value[len(ENCRYPTED_VALUE_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode('utf-8')).decode('utf-8')
    except InvalidToken as exc:
        raise ValueError('已保存的 API Key 无法解密，请重新输入并保存') from exc


def _get_fernet():
    secret = current_app.config.get('SYSTEM_SETTINGS_ENCRYPTION_KEY') or current_app.config.get('SECRET_KEY')
    digest = hashlib.sha256(secret.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _mask_key(key):
    if not key or len(key) < 8:
        return '***' if key else ''
    return key[:4] + '*' * (len(key) - 8) + key[-4:]
