from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, User
from services.password_security import verify_password


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "quiz_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-0123456789012345")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def seed_users(app):
    with app.app_context():
        admin = User(
            username="admin",
            email="admin@test.com",
            password_hash=generate_password_hash("admin-pass", method="pbkdf2:sha256"),
            is_admin=True,
        )
        normal = User(
            username="user1",
            email="user1@test.com",
            password_hash=generate_password_hash("old-password", method="pbkdf2:sha256"),
            is_admin=False,
        )
        other = User(
            username="user2",
            email="user2@test.com",
            password_hash=generate_password_hash("user2-password", method="pbkdf2:sha256"),
            is_admin=False,
        )
        db.session.add_all([admin, normal, other])
        db.session.commit()

        return {
            "admin_id": admin.id,
            "normal_id": normal.id,
            "other_id": other.id,
            "admin_token": create_access_token(identity=str(admin.id)),
            "normal_token": create_access_token(identity=str(normal.id)),
        }


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_get_user_list(app):
    seeded = seed_users(app)
    client = app.test_client()

    res = client.get("/api/admin/users", headers=auth_headers(seeded["admin_token"]))

    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body, list)
    usernames = {user["username"] for user in body}
    assert usernames == {"admin", "user1", "user2"}


def test_admin_can_reset_target_user_password(app):
    seeded = seed_users(app)
    client = app.test_client()

    res = client.put(
        f"/api/admin/users/{seeded['normal_id']}/password",
        json={"new_password": "new-password"},
        headers=auth_headers(seeded["admin_token"]),
    )

    assert res.status_code == 200
    assert res.get_json() == {"message": "密码已重置"}

    with app.app_context():
        user = db.session.get(User, seeded["normal_id"])
        assert user is not None
        assert verify_password("new-password", user.password_hash)
        assert not verify_password("old-password", user.password_hash)


@pytest.mark.parametrize(
    "method,path_builder",
    [
        ("get", lambda seeded: "/api/admin/users"),
        ("put", lambda seeded: f"/api/admin/users/{seeded['other_id']}/password"),
    ],
)
def test_non_admin_cannot_access_admin_users_endpoints(app, method, path_builder):
    seeded = seed_users(app)
    client = app.test_client()

    path = path_builder(seeded)
    kwargs = {"headers": auth_headers(seeded["normal_token"])}
    if method == "put":
        kwargs["json"] = {"new_password": "new-password"}
    res = getattr(client, method)(path, **kwargs)

    assert res.status_code == 403


def test_reset_password_returns_404_when_target_user_not_found(app):
    seeded = seed_users(app)
    client = app.test_client()

    res = client.put(
        "/api/admin/users/999999/password",
        json={"new_password": "new-password"},
        headers=auth_headers(seeded["admin_token"]),
    )

    assert res.status_code == 404
    assert res.get_json()["error"] == "用户不存在"


@pytest.mark.parametrize(
    "bad_password,expected_error",
    [
        ("", "新密码不能为空"),
        ("123", "新密码至少6位"),
    ],
)
def test_reset_password_uses_unified_password_validation(app, bad_password, expected_error):
    seeded = seed_users(app)
    client = app.test_client()

    res = client.put(
        f"/api/admin/users/{seeded['other_id']}/password",
        json={"new_password": bad_password},
        headers=auth_headers(seeded["admin_token"]),
    )

    assert res.status_code == 400
    assert res.get_json()["error"] == expected_error
