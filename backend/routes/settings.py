from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import requests as http_requests

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


@settings_bp.route('/ai/key', methods=['GET'])
@jwt_required()
def get_ai_key():
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    return jsonify({'ai_api_key': SystemSetting.get('ai_api_key', '')})


@settings_bp.route('/ai/test', methods=['POST'])
@jwt_required()
def test_ai_connection():
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    data = request.get_json()
    base_url = (data.get('ai_api_base_url') or '').strip()
    api_key = (data.get('ai_api_key') or '').strip()
    model = (data.get('ai_model') or '').strip()

    # 如果 API Key 是遮罩值，从数据库读取真实 key
    if api_key.startswith('***'):
        api_key = SystemSetting.get('ai_api_key', '')

    if not api_key:
        return jsonify({'success': False, 'error': 'API Key 未配置'}), 400
    if not base_url:
        return jsonify({'success': False, 'error': 'API Base URL 未配置'}), 400

    # 拼接 URL（复用 ai_service 的逻辑）
    base = base_url.rstrip('/')
    if base.endswith('/chat/completions'):
        api_url = base
    elif base.endswith('/v1'):
        api_url = base + '/chat/completions'
    else:
        api_url = base + '/v1/chat/completions'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': model or 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': '请将以下英文单词翻译为中文，只返回翻译结果。'},
            {'role': 'user', 'content': 'apple'},
        ],
        'temperature': 0.3,
    }

    try:
        resp = http_requests.post(api_url, json=payload, headers=headers, timeout=15, verify=False)
        if not resp.ok:
            detail = resp.text[:200] if resp.text else resp.reason
            return jsonify({'success': False, 'error': f'API 返回错误 ({resp.status_code}): {detail}'})
        result = resp.json()
        content = result['choices'][0]['message']['content']
        return jsonify({'success': True, 'message': f'连接成功！AI 回复：{content}'})
    except http_requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': '请求超时（15秒），请检查 API 地址是否可达'})
    except http_requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': '无法连接到 API 服务器，请检查 URL 是否正确'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'测试失败：{str(e)}'})


def _mask_key(key):
    if not key or len(key) < 8:
        return '***' if key else ''
    return key[:4] + '*' * (len(key) - 8) + key[-4:]
