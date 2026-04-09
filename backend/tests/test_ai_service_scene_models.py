from pathlib import Path
import json
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, QuestionBank, Question, SystemSetting
from services import ai_service
from services.settings_service import set_encrypted_ai_api_key


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


class FakeResponse:
    def __init__(self, content):
        self.ok = True
        self.status_code = 200
        self.text = ""
        self.reason = "OK"
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def build_question():
    bank = QuestionBank(name="Test Bank", description="")
    db.session.add(bank)
    db.session.flush()
    question = Question(
        bank_id=bank.id,
        question_type="single",
        content="What is privacy by design?",
        options=json.dumps([
            {"key": "A", "text": "A design principle"},
            {"key": "B", "text": "A legal basis"},
        ], ensure_ascii=False),
        correct_answer="A",
        order_index=0,
    )
    db.session.add(question)
    db.session.commit()
    return question


def configure_ai_settings(*, default_model, translate_model="", explain_model=""):
    SystemSetting.set("ai_api_base_url", "https://api.example.com")
    set_encrypted_ai_api_key("sk-test-secret-12345678")
    SystemSetting.set("ai_model", default_model)
    SystemSetting.set("ai_translate_model", translate_model)
    SystemSetting.set("ai_explain_model", explain_model)


def test_translate_question_uses_translate_scene_model(app, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout, verify):
        captured["model"] = json["model"]
        return FakeResponse(
            '{"content_zh": "什么是隐私保护设计？", "options_zh": ['
            '{"key": "A", "text_zh": "一种设计原则"}, '
            '{"key": "B", "text_zh": "一种法律依据"}]}'
        )

    monkeypatch.setattr(ai_service.requests, "post", fake_post)

    with app.app_context():
        question = build_question()
        configure_ai_settings(default_model="gpt-5.4", translate_model="gpt-5-nano")
        ai_service.translate_question(question)

    assert captured["model"] == "gpt-5-nano"


def test_batch_translate_terms_uses_translate_scene_model(app, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout, verify):
        captured["model"] = json["model"]
        return FakeResponse('[{"id": 1, "term_zh": "隐私", "definition_zh": null}]')

    monkeypatch.setattr(ai_service.requests, "post", fake_post)

    with app.app_context():
        configure_ai_settings(default_model="gpt-5.4", translate_model="gpt-5-nano")
        ai_service.batch_translate_terms([{"id": 1, "term": "privacy"}])

    assert captured["model"] == "gpt-5-nano"


def test_explain_question_falls_back_to_default_model_when_scene_model_missing(app, monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout, verify):
        captured["model"] = json["model"]
        return FakeResponse('{"explanation": "Because privacy by design is proactive.", "explanation_zh": "因为隐私保护设计强调事前预防。"}')

    monkeypatch.setattr(ai_service.requests, "post", fake_post)

    with app.app_context():
        question = build_question()
        configure_ai_settings(default_model="gpt-5.4", explain_model="")
        ai_service.explain_question(question)

    assert captured["model"] == "gpt-5.4"
