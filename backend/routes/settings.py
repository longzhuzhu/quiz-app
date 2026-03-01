from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import User, SystemSetting

settings_bp = Blueprint('settings', __name__)

AI_SETTING_KEYS = ['ai_api_base_url', 'ai_api_key', 'ai_model']


@settings_bp.route('/ai', methods=['GET'])
@jwt_required()
def get_ai_settings():
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    return jsonify({
        'ai_api_base_url': SystemSetting.get('ai_api_base_url', ''),
        'ai_api_key': _mask_key(SystemSetting.get('ai_api_key', '')),
        'ai_model': SystemSetting.get('ai_model', ''),
    })


@settings_bp.route('/ai', methods=['PUT'])
@jwt_required()
def update_ai_settings():
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    data = request.get_json()
    if 'ai_api_base_url' in data:
        SystemSetting.set('ai_api_base_url', data['ai_api_base_url'].strip())
    if 'ai_api_key' in data and not data['ai_api_key'].startswith('***'):
        SystemSetting.set('ai_api_key', data['ai_api_key'].strip())
    if 'ai_model' in data:
        SystemSetting.set('ai_model', data['ai_model'].strip())

    return jsonify({'message': '设置已保存'})


def _mask_key(key):
    if not key or len(key) < 8:
        return '***' if key else ''
    return key[:4] + '*' * (len(key) - 8) + key[-4:]
