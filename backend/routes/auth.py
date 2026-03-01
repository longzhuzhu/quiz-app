from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import User
from services.auth_service import register_user, login_user, user_to_dict

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    try:
        user = register_user(data['username'], data['email'], data['password'])
        return jsonify({'message': '注册成功', 'user': user_to_dict(user)}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    try:
        token, user = login_user(data['username'], data['password'])
        return jsonify({'access_token': token, 'user': user_to_dict(user)})
    except ValueError as e:
        return jsonify({'error': str(e)}), 401


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify(user_to_dict(user))
