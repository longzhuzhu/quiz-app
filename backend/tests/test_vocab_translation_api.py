from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import BankWordFrequency, QuestionBank, User, Vocabulary, db


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


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def seed_admin(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        db.session.add(admin)
        db.session.commit()
        return create_access_token(identity=str(admin.id))


def test_batch_translate_professional_includes_missing_definition_translations(app, monkeypatch):
    admin_token = seed_admin(app)
    client = app.test_client()

    with app.app_context():
        db.session.add_all([
            Vocabulary(term="privacy", definition="privacy concept", term_zh=None, definition_zh=None, is_system=True),
            Vocabulary(term="controller", definition="entity deciding purposes", term_zh="控制者", definition_zh=None, is_system=True),
            Vocabulary(term="processor", definition="entity processing data", term_zh="处理者", definition_zh="处理数据的实体", is_system=True),
        ])
        db.session.commit()

    def fake_batch_translate_vocab(vocab_list):
        updates = {
            "privacy": ("隐私", "隐私概念"),
            "controller": ("控制者", "决定处理目的的实体"),
        }
        for word in vocab_list:
            term_zh, definition_zh = updates[word.term]
            word.term_zh = term_zh
            word.definition_zh = definition_zh
        db.session.commit()
        return len(vocab_list)

    import services.ai_service as ai_service

    monkeypatch.setattr(ai_service, "batch_translate_vocab", fake_batch_translate_vocab)

    response = client.post(
        "/api/vocab/professional/batch-translate",
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "message": "本次翻译 2 个，剩余 0 个",
        "translated": 2,
        "remaining": 0,
    }

    with app.app_context():
        words = {
            word.term: word
            for word in Vocabulary.query.filter_by(is_system=True).all()
        }
        assert words["privacy"].term_zh == "隐私"
        assert words["privacy"].definition_zh == "隐私概念"
        assert words["controller"].term_zh == "控制者"
        assert words["controller"].definition_zh == "决定处理目的的实体"
        assert words["processor"].definition_zh == "处理数据的实体"


def test_get_frequent_vocab_summary_includes_untranslated_count(app):
    admin_token = seed_admin(app)
    client = app.test_client()

    with app.app_context():
        bank = QuestionBank(name="Test Bank", description="desc")
        db.session.add(bank)
        db.session.flush()
        db.session.add_all([
            BankWordFrequency(bank_id=bank.id, term="privacy", term_zh="隐私", frequency=8),
            BankWordFrequency(bank_id=bank.id, term="controller", term_zh=None, frequency=5),
            BankWordFrequency(bank_id=bank.id, term="governance", term_zh=None, frequency=3),
        ])
        db.session.commit()
        bank_id = bank.id

    response = client.get(
        f"/api/vocab/frequent?bank_id={bank_id}&page=1&per_page=2",
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"] == {
        "total_terms": 3,
        "untranslated_terms": 2,
        "min_frequency": 2,
        "top_terms_limit": 5000,
    }
    assert payload["items"] == [
        {
            "term": "privacy",
            "term_zh": "隐私",
            "frequency": 8,
            "is_mastered": False,
            "can_delete": True,
            "can_mark_mastered": True,
        },
        {
            "term": "controller",
            "term_zh": None,
            "frequency": 5,
            "is_mastered": False,
            "can_delete": True,
            "can_mark_mastered": True,
        },
    ]
