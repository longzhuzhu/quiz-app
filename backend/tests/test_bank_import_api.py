from io import BytesIO
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import BackgroundJob, BankWordFrequency, db, User, QuestionBank, Question


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


def test_import_invalidates_old_bank_frequency_job_before_creating_new_one(app, seeded_admin_bank, monkeypatch):
    client = app.test_client()
    bank_id = seeded_admin_bank["bank_id"]
    scope_key = f"bank_frequent:{bank_id}"

    parsed_questions = [
        {
            "content": "What is personal data?",
            "options": [{"key": "A", "text": "Any data about an identified person"}],
            "correct_answer": "A",
            "question_type": "single",
            "answer_missing": False,
        }
    ]
    monkeypatch.setattr("routes.banks.parse_file", lambda file_storage, filename: parsed_questions)
    monkeypatch.setattr(
        "routes.banks.build_bank_word_frequencies",
        lambda questions: [
            {"term": "controller", "frequency": 4},
            {"term": "processor", "frequency": 2},
        ],
    )

    with app.app_context():
        old_job = BackgroundJob(
            job_type="bank_frequent_translate",
            scope_key=scope_key,
            active_scope_key=scope_key,
            payload_json=f'{{"bank_id": {bank_id}}}',
            status="running",
            progress_total=99,
            progress_done=40,
            success_count=40,
            skipped_count=0,
            status_message="旧任务仍在执行",
            created_by=1,
        )
        db.session.add(old_job)
        db.session.add(BankWordFrequency(bank_id=bank_id, term="legacy", term_zh=None, frequency=9))
        db.session.commit()
        old_job_id = old_job.id

    headers = {"Authorization": f"Bearer {seeded_admin_bank['token']}"}
    import_res = client.post(
        f"/api/banks/{bank_id}/import",
        data={"file": (BytesIO(b"ignored"), "questions.docx")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert import_res.status_code == 200

    create_job_res = client.post(
        "/api/jobs",
        json={"job_type": "bank_frequent_translate", "bank_id": bank_id},
        headers=headers,
    )

    assert create_job_res.status_code == 201
    payload = create_job_res.get_json()
    assert payload["result"] == "created"
    assert payload["job"]["id"] != old_job_id
    assert payload["job"]["progress_total"] == 2

    with app.app_context():
        old_job = db.session.get(BackgroundJob, old_job_id)
        assert old_job.active_scope_key is None
        assert old_job.status != "running"
