from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, User, SystemSetting
import routes.settings as settings_routes


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "quiz_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-0123456789012345")
    monkeypatch.setenv("SECRET_KEY", "test-app-secret-0123456789012345")
    monkeypatch.setenv("SYSTEM_SETTINGS_ENCRYPTION_KEY", "test-settings-secret-0123456789012345")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def create_admin_token(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        db.session.add(admin)
        db.session.commit()
        return create_access_token(identity=str(admin.id))


class FakeResponse:
    ok = True
    status_code = 200
    text = ""
    reason = "OK"

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "苹果"}}]}


def test_save_ai_settings_encrypts_key_and_masks_response(app):
    token = create_admin_token(app)
    client = app.test_client()

    res = client.put(
        "/api/settings/ai",
        json={
            "ai_api_base_url": "https://api.example.com",
            "ai_api_key": "sk-test-secret-12345678",
            "ai_model": "gpt-4o-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200

    with app.app_context():
        stored = SystemSetting.query.filter_by(key="ai_api_key").first()
        assert stored is not None
        assert stored.value != "sk-test-secret-12345678"
        assert stored.value.startswith("enc:")

    get_res = client.get(
        "/api/settings/ai",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert get_res.status_code == 200
    body = get_res.get_json()
    assert body["ai_api_key"] != "sk-test-secret-12345678"
    assert "*" in body["ai_api_key"]
    assert body["ai_api_key"].startswith("sk-")


def test_save_ai_settings_keeps_existing_key_when_payload_key_is_blank_and_test_uses_stored_key(app, monkeypatch):
    token = create_admin_token(app)
    client = app.test_client()

    first_save = client.put(
        "/api/settings/ai",
        json={
            "ai_api_base_url": "https://gateway.example.com",
            "ai_api_key": "sk-stored-secret-keepme",
            "ai_model": "gpt-4o-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first_save.status_code == 200

    with app.app_context():
        encrypted_before = SystemSetting.query.filter_by(key="ai_api_key").first().value

    second_save = client.put(
        "/api/settings/ai",
        json={
            "ai_api_base_url": "https://gateway.example.com",
            "ai_api_key": "",
            "ai_model": "gpt-4.1-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_save.status_code == 200

    with app.app_context():
        encrypted_after = SystemSetting.query.filter_by(key="ai_api_key").first().value
        assert encrypted_after == encrypted_before

    captured = {}

    def fake_post(url, json, headers, timeout, verify):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["verify"] = verify
        return FakeResponse()

    monkeypatch.setattr(settings_routes.http_requests, "post", fake_post)

    test_res = client.post(
        "/api/settings/ai/test",
        json={
            "ai_api_base_url": "https://gateway.example.com",
            "ai_api_key": "",
            "ai_model": "gpt-4.1-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert test_res.status_code == 200
    assert test_res.get_json()["success"] is True
    assert captured["url"] == "https://gateway.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-stored-secret-keepme"


def test_get_ai_key_no_longer_returns_plaintext_secret(app):
    token = create_admin_token(app)
    client = app.test_client()

    save_res = client.put(
        "/api/settings/ai",
        json={
            "ai_api_base_url": "https://api.example.com",
            "ai_api_key": "sk-no-echo-secret",
            "ai_model": "gpt-4o-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert save_res.status_code == 200

    res = client.get(
        "/api/settings/ai/key",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 410
    assert "不再支持" in res.get_json()["error"]
