from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token

from models import db, User


def register_user(username, email, password):
    if User.query.filter_by(username=username).first():
        raise ValueError('用户名已存在')
    if User.query.filter_by(email=email).first():
        raise ValueError('邮箱已存在')
    # 第一个注册的用户自动成为管理员
    is_first_user = User.query.count() == 0
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        is_admin=is_first_user,
    )
    db.session.add(user)
    db.session.commit()
    return user


def login_user(username, password):
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        raise ValueError('用户名或密码错误')
    token = create_access_token(identity=str(user.id))
    return token, user


def validate_new_password(new_password):
    if not isinstance(new_password, str):
        raise ValueError('新密码必须为字符串')
    if new_password.strip() == '':
        raise ValueError('新密码不能为空')
    if len(new_password) < 6:
        raise ValueError('新密码至少6位')


def set_user_password(user, new_password):
    validate_new_password(new_password)
    user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
    return user


def change_password(user, current_password, new_password):
    if not isinstance(current_password, str) or current_password == '':
        raise ValueError('当前密码错误')
    if not check_password_hash(user.password_hash, current_password):
        raise ValueError('当前密码错误')
    set_user_password(user, new_password)
    db.session.commit()
    return user


def user_to_dict(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'is_admin': user.is_admin,
        'created_at': user.created_at.isoformat(),
    }
