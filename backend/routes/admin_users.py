from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import User, db
from services.auth_service import set_user_password, user_to_dict

admin_users_bp = Blueprint('admin_users', __name__)


def _get_current_user():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return db.session.get(User, user_id)


def _require_admin():
    user = _get_current_user()
    if not user:
        return None, (jsonify({'error': '用户不存在或登录已失效'}), 401)
    if not user.is_admin:
        return None, (jsonify({'error': '需要管理员权限'}), 403)
    return user, None


@admin_users_bp.route('', methods=['GET'])
@jwt_required()
def list_users():
    _user, error = _require_admin()
    if error:
        return error

    users = User.query.order_by(User.id.asc()).all()
    return jsonify([user_to_dict(user) for user in users])


@admin_users_bp.route('/<int:user_id>/password', methods=['PUT'])
@jwt_required()
def reset_user_password(user_id):
    _user, error = _require_admin()
    if error:
        return error

    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({'error': '用户不存在'}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': '请求体必须为 JSON 对象'}), 400

    try:
        set_user_password(target_user, data.get('new_password'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    db.session.commit()
    return jsonify({'message': '密码已重置'})
