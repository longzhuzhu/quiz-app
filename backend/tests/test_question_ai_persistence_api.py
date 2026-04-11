from pathlib import Path
import json
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, Question, QuestionBank, User
from routes import ai as ai_routes


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "quiz_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-0123456789012345")
    monkeypatch.setenv("SECRET_KEY", "test-app-secret-0123456789012345")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()



def seed_user_and_question(app, *, content_zh="已有中文题干", explanation="Existing explanation", explanation_zh="已有中文解析"):
    with app.app_context():
        user = User(
            username="cached-user",
            email="cached-user@test.com",
            password_hash="x",
            is_admin=True,
        )
        bank = QuestionBank(name="AI Bank", description="")
        db.session.add_all([user, bank])
        db.session.flush()

        question = Question(
            bank_id=bank.id,
            question_type="single",
            content="What is privacy by design?",
            content_zh=content_zh,
            options=json.dumps(
                [
                    {"key": "A", "text": "A design principle", "text_zh": "一种设计原则"},
                    {"key": "B", "text": "A legal basis", "text_zh": "一种法律依据"},
                ],
                ensure_ascii=False,
            ),
            correct_answer="A",
            explanation=explanation,
            explanation_zh=explanation_zh,
            order_index=0,
        )
        db.session.add(question)
        db.session.commit()

        token = create_access_token(identity=str(user.id))
        return {"token": token, "question_id": question.id}


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_cached_translate_returns_full_payload_without_calling_ai(app, monkeypatch):
    seeded = seed_user_and_question(app)

    def fail_translate(_question):
        raise AssertionError("translate_question should not be invoked when translation already exists")

    monkeypatch.setattr(ai_routes, "translate_question", fail_translate)

    client = app.test_client()
    res = client.post(
        "/api/ai/translate",
        json={"question_id": seeded["question_id"]},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200
    assert res.get_json() == {
        "content_zh": "已有中文题干",
        "options_zh": [
            {"key": "A", "text_zh": "一种设计原则"},
            {"key": "B", "text_zh": "一种法律依据"},
        ],
        "cached": True,
    }


def test_cached_explain_with_partial_payload_skips_ai(app, monkeypatch):
    seeded = seed_user_and_question(app, explanation=None, explanation_zh="已有中文解析")

    def fail_explain(_question):
        raise AssertionError("explain_question should not be called when explanation payload already exists")

    monkeypatch.setattr(ai_routes, "explain_question", fail_explain)

    client = app.test_client()
    res = client.post(
        "/api/ai/explain",
        json={"question_id": seeded["question_id"]},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200
    assert res.get_json() == {
        "explanation": None,
        "explanation_zh": "已有中文解析",
        "cached": True,
    }


def test_invalidates_ai_fields_when_content_changes(app):
    seeded = seed_user_and_question(app)
    client = app.test_client()

    res = client.put(
        f"/api/questions/{seeded['question_id']}",
        json={"content": "New privacy question text"},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200

    with app.app_context():
        question = Question.query.get(seeded["question_id"])
        assert question.content == "New privacy question text"
        assert question.content_zh is None
        assert question.explanation is None
        assert question.explanation_zh is None
        stored_options = json.loads(question.options)
        assert all(opt.get("text_zh") is None for opt in stored_options)


def test_invalidates_ai_fields_when_options_change(app):
    seeded = seed_user_and_question(app)
    client = app.test_client()

    updated_options = [
        {"key": "B", "text": "A legal basis"},
        {"key": "A", "text": "A design principle"},
    ]

    res = client.put(
        f"/api/questions/{seeded['question_id']}",
        json={"options": updated_options},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200

    with app.app_context():
        question = Question.query.get(seeded["question_id"])
        stored_options = json.loads(question.options)
        assert stored_options[0]["key"] == "B"
        assert question.content_zh is None
        assert question.explanation is None
        assert question.explanation_zh is None
        assert all(opt.get("text_zh") is None for opt in stored_options)


def test_options_update_with_text_zh_strips_translation(app):
    seeded = seed_user_and_question(app)
    client = app.test_client()

    updated_options = [
        {"key": "B", "text": "A legal basis", "text_zh": "旧翻译"},
        {"key": "A", "text": "A design principle", "text_zh": "旧翻译"},
    ]

    res = client.put(
        f"/api/questions/{seeded['question_id']}",
        json={"options": updated_options, "content": "New privacy question text"},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200

    with app.app_context():
        question = Question.query.get(seeded["question_id"])
        stored_options = json.loads(question.options)
        assert stored_options[0]["key"] == "B"
        assert all("text_zh" not in opt for opt in stored_options)
        assert question.content_zh is None
        assert question.explanation is None
        assert question.explanation_zh is None


def test_invalidates_explanation_when_correct_answer_changes(app):
    seeded = seed_user_and_question(app)
    client = app.test_client()

    res = client.put(
        f"/api/questions/{seeded['question_id']}",
        json={"correct_answer": "B"},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200

    with app.app_context():
        question = Question.query.get(seeded["question_id"])
        assert question.correct_answer == "B"
        assert question.content_zh == "已有中文题干"
        stored_options = json.loads(question.options)
        assert stored_options[0].get("text_zh") == "一种设计原则"
        assert question.explanation is None
        assert question.explanation_zh is None


def test_invalidates_explanation_when_question_type_changes(app):
    seeded = seed_user_and_question(app)
    client = app.test_client()

    res = client.put(
        f"/api/questions/{seeded['question_id']}",
        json={"question_type": "multiple"},
        headers=auth_headers(seeded["token"]),
    )

    assert res.status_code == 200

    with app.app_context():
        question = Question.query.get(seeded["question_id"])
        assert question.question_type == "multiple"
        assert question.content_zh == "已有中文题干"
        stored_options = json.loads(question.options)
        assert stored_options[0].get("text_zh") == "一种设计原则"
        assert question.explanation is None
        assert question.explanation_zh is None
