from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, User
from services.auth_service import login_user


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


def seed_user_and_token(app):
    with app.app_context():
        user = User(
            username="demo",
            email="demo@test.com",
            password_hash=generate_password_hash("old-password", method="pbkdf2:sha256"),
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))
        return user.id, token


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_account_returns_current_user_profile(app):
    user_id, token = seed_user_and_token(app)
    client = app.test_client()

    res = client.get("/api/account", headers=auth_headers(token))

    assert res.status_code == 200
    data = res.get_json()
    assert data["id"] == user_id
    assert data["username"] == "demo"
    assert data["email"] == "demo@test.com"
    assert data["is_admin"] is False
    assert "created_at" in data


def test_put_account_password_returns_400_when_current_password_is_wrong(app):
    _, token = seed_user_and_token(app)
    client = app.test_client()

    res = client.put(
        "/api/account/password",
        json={"current_password": "bad-password", "new_password": "new-password"},
        headers=auth_headers(token),
    )

    assert res.status_code == 400
    assert res.get_json()["error"] == "当前密码错误"


def test_put_account_password_returns_400_when_current_password_is_null(app):
    _, token = seed_user_and_token(app)
    client = app.test_client()

    res = client.put(
        "/api/account/password",
        json={"current_password": None, "new_password": "new-password"},
        headers=auth_headers(token),
    )

    assert res.status_code == 400
    assert res.get_json()["error"] == "当前密码错误"


def test_put_account_password_success_and_new_password_can_login(app):
    _, token = seed_user_and_token(app)
    client = app.test_client()

    res = client.put(
        "/api/account/password",
        json={"current_password": "old-password", "new_password": "new-password"},
        headers=auth_headers(token),
    )

    assert res.status_code == 200
    assert res.get_json() == {"message": "密码修改成功"}

    with app.app_context():
        with pytest.raises(ValueError):
            login_user("demo", "old-password")
        new_token, user = login_user("demo", "new-password")
        assert new_token
        assert user.username == "demo"
