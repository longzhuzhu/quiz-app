from io import BytesIO
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, User, QuestionBank, Question


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


@pytest.fixture()
def seeded_admin_bank(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        bank = QuestionBank(name="bank-1", description="import-target")
        db.session.add_all([admin, bank])
        db.session.commit()

        token = create_access_token(identity=str(admin.id))
        return {"token": token, "bank_id": bank.id}


def test_import_skips_questions_already_present_in_bank(app, seeded_admin_bank, monkeypatch):
    client = app.test_client()

    parsed_questions = [
        {
            "content": "What is privacy by design?",
            "options": [{"key": "A", "text": "Embed privacy into design"}],
            "correct_answer": "A",
            "question_type": "single",
            "answer_missing": False,
        },
        {
            "content": "What is data minimization?",
            "options": [{"key": "A", "text": "Collect less personal data"}],
            "correct_answer": "A",
            "question_type": "single",
            "answer_missing": False,
        },
    ]

    monkeypatch.setattr("routes.banks.parse_file", lambda file_storage, filename: parsed_questions)

    headers = {"Authorization": f"Bearer {seeded_admin_bank['token']}"}
    first_res = client.post(
        f"/api/banks/{seeded_admin_bank['bank_id']}/import",
        data={"file": (BytesIO(b"ignored"), "questions.docx")},
        content_type="multipart/form-data",
        headers=headers,
    )
    second_res = client.post(
        f"/api/banks/{seeded_admin_bank['bank_id']}/import",
        data={"file": (BytesIO(b"ignored"), "questions.docx")},
        content_type="multipart/form-data",
        headers=headers,
    )

    assert first_res.status_code == 200
    assert first_res.get_json()["count"] == 2
    assert first_res.get_json()["skipped_duplicate_count"] == 0

    assert second_res.status_code == 200
    assert second_res.get_json()["count"] == 0
    assert second_res.get_json()["skipped_duplicate_count"] == 2

    with app.app_context():
        questions = Question.query.filter_by(bank_id=seeded_admin_bank["bank_id"]).order_by(
            Question.order_index.asc(),
            Question.id.asc(),
        ).all()
        bank = QuestionBank.query.get(seeded_admin_bank["bank_id"])

        assert len(questions) == 2
        assert [question.order_index for question in questions] == [0, 1]
        assert bank.question_count == 2


def test_import_skips_duplicate_questions_within_single_file(app, seeded_admin_bank, monkeypatch):
    client = app.test_client()

    parsed_questions = [
        {
            "content": "Which control best protects confidentiality?",
            "options": [{"key": "A", "text": "Encryption"}],
            "correct_answer": "A",
            "question_type": "single",
            "answer_missing": False,
        },
        {
            "content": "Which control best protects confidentiality?",
            "options": [{"key": "A", "text": "Encryption"}],
            "correct_answer": "A",
            "question_type": "single",
            "answer_missing": False,
        },
        {
            "content": "Which control best protects integrity?",
            "options": [{"key": "A", "text": "Checksums"}],
            "correct_answer": "A",
            "question_type": "single",
            "answer_missing": False,
        },
    ]

    monkeypatch.setattr("routes.banks.parse_file", lambda file_storage, filename: parsed_questions)

    res = client.post(
        f"/api/banks/{seeded_admin_bank['bank_id']}/import",
        data={"file": (BytesIO(b"ignored"), "questions.docx")},
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {seeded_admin_bank['token']}"},
    )

    assert res.status_code == 200
    assert res.get_json()["count"] == 2
    assert res.get_json()["skipped_duplicate_count"] == 1

    with app.app_context():
        questions = Question.query.filter_by(bank_id=seeded_admin_bank["bank_id"]).order_by(
            Question.order_index.asc(),
            Question.id.asc(),
        ).all()

        assert len(questions) == 2
        assert [question.content for question in questions] == [
            "Which control best protects confidentiality?",
            "Which control best protects integrity?",
        ]
