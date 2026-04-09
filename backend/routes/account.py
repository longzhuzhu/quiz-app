from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import User
from services.auth_service import change_password, user_to_dict

account_bp = Blueprint('account', __name__)


def _get_current_user():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return User.query.get(user_id)


@account_bp.route('', methods=['GET'])
@jwt_required()
def get_account():
    user = _get_current_user()
    if not user:
        return jsonify({'error': '用户不存在或登录已失效'}), 401
    return jsonify(user_to_dict(user))


@account_bp.route('/password', methods=['PUT'])
@jwt_required()
def update_password():
    user = _get_current_user()
    if not user:
        return jsonify({'error': '用户不存在或登录已失效'}), 401

    data = request.get_json() or {}
    if not isinstance(data, dict):
        return jsonify({'error': '请求体必须为 JSON 对象'}), 400
    try:
        change_password(
            user=user,
            current_password=data.get('current_password', ''),
            new_password=data.get('new_password'),
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    return jsonify({'message': '密码修改成功'})
