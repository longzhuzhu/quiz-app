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


def seed_admin_and_vocab(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        bank = QuestionBank(name="bank-1", description="job-target")
        db.session.add_all([
            admin,
            bank,
            Vocabulary(term="privacy", definition="privacy concept", is_system=True),
            Vocabulary(term="controller", definition="purpose decision", term_zh="控制者", definition_zh=None, is_system=True),
        ])
        db.session.commit()
        return {
            "token": create_access_token(identity=str(admin.id)),
            "bank_id": bank.id,
        }


def seed_bank_frequency(app):
    with app.app_context():
        admin = User(username="bank-admin", email="bank-admin@test.com", password_hash="x", is_admin=True)
        bank = QuestionBank(name="freq-bank", description="job-target")
        db.session.add_all([admin, bank])
        db.session.flush()
        db.session.add_all([
            BankWordFrequency(bank_id=bank.id, term="privacy", term_zh=None, frequency=8),
            BankWordFrequency(bank_id=bank.id, term="controller", term_zh=None, frequency=5),
            BankWordFrequency(bank_id=bank.id, term="governance", term_zh="治理", frequency=3),
        ])
        db.session.commit()
        return {
            "token": create_access_token(identity=str(admin.id)),
            "bank_id": bank.id,
        }


def test_post_jobs_creates_professional_vocab_job(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()

    response = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["result"] == "created"
    assert payload["job"]["job_type"] == "professional_vocab_translate"
    assert payload["job"]["scope_key"] == "professional_vocab"
    assert payload["job"]["status"] == "queued"
    assert payload["job"]["progress_total"] == 2


def test_post_jobs_reuses_existing_professional_vocab_job(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()

    first = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )
    assert first.status_code == 201
    second = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["result"] == "existing"
    assert second.get_json()["job"]["id"] == first.get_json()["job"]["id"]


def test_get_job_detail_returns_serialized_job(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()
    created = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    assert created.status_code == 201

    response = client.get(
        f"/api/jobs/{created.get_json()["job"]["id"]}",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["job"]["attempt_count"] == 0
    assert payload["job"]["max_attempts"] == 3
    assert payload["job"]["status_message"] == "等待后台 worker 执行"


def test_get_active_job_returns_professional_job_by_scope(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()
    created = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    assert created.status_code == 201

    response = client.get(
        "/api/jobs/active?job_type=professional_vocab_translate",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json()["job"]["id"] == created.get_json()["job"]["id"]


def test_post_jobs_returns_no_work_when_bank_has_no_untranslated_terms(app):
    seeded = seed_bank_frequency(app)
    client = app.test_client()

    with app.app_context():
        BankWordFrequency.query.filter_by(bank_id=seeded["bank_id"]).update({"term_zh": "已有翻译"})
        db.session.commit()

    response = client.post(
        "/api/jobs",
        json={"job_type": "bank_frequent_translate", "bank_id": seeded["bank_id"]},
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "result": "no_work",
        "job": None,
        "message": "当前没有待翻译数据",
    }


def test_get_active_job_scopes_bank_frequency_by_bank_id(app):
    seeded = seed_bank_frequency(app)
    client = app.test_client()
    created = client.post(
        "/api/jobs",
        json={"job_type": "bank_frequent_translate", "bank_id": seeded["bank_id"]},
        headers=auth_headers(seeded["token"]),
    )

    assert created.status_code == 201

    response = client.get(
        f"/api/jobs/active?job_type=bank_frequent_translate&bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json()["job"]["scope_key"] == f"bank_frequent:{seeded['bank_id']}"
    assert response.get_json()["job"]["id"] == created.get_json()["job"]["id"]


def test_get_frequent_summary_includes_untranslated_terms(app):
    seeded = seed_bank_frequency(app)
    client = app.test_client()

    response = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}&page=1&per_page=20",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert "summary" in payload
    assert payload["summary"].get("untranslated_terms") == 2
