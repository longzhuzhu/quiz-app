from pathlib import Path
import sys
from io import BytesIO

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import (
    db,
    BankWordFrequency,
    QuestionBank,
    User,
    UserBankWordProgress,
    UserVocabProgress,
    Vocabulary,
)


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


def seed_vocab_data(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        learner = User(username="learner", email="learner@test.com", password_hash="x", is_admin=False)
        db.session.add_all([admin, learner])
        db.session.flush()

        personal_alpha = Vocabulary(
            term="alpha",
            definition="first term",
            is_system=False,
            user_id=learner.id,
        )
        personal_beta = Vocabulary(
            term="beta",
            definition="second term",
            is_system=False,
            user_id=learner.id,
        )
        professional_word = Vocabulary(
            term="privacy",
            definition="system term",
            is_system=True,
        )
        professional_second = Vocabulary(term="compliance", is_system=True)
        db.session.add_all([personal_alpha, personal_beta, professional_word, professional_second])
        db.session.commit()

        db.session.add_all([
            UserVocabProgress(user_id=learner.id, vocabulary_id=personal_alpha.id, is_mastered=True),
            UserVocabProgress(user_id=learner.id, vocabulary_id=professional_word.id, is_mastered=True),
        ])
        db.session.commit()

        admin_token = create_access_token(identity=str(admin.id))
        learner_token = create_access_token(identity=str(learner.id))

        return {
            "admin_token": admin_token,
            "learner_token": learner_token,
            "learner_id": learner.id,
            "personal_alpha_id": personal_alpha.id,
            "personal_beta_id": personal_beta.id,
            "professional_word_id": professional_word.id,
            "professional_second_id": professional_second.id,
        }


def seed_frequent_vocab_data(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        learner = User(username="learner", email="learner@test.com", password_hash="x", is_admin=False)
        bank = QuestionBank(name="frequency bank", description="frequent vocab")
        db.session.add_all([admin, learner, bank])
        db.session.flush()

        db.session.add_all([
            BankWordFrequency(bank_id=bank.id, term="privacy", term_zh="隐私", frequency=8),
            BankWordFrequency(bank_id=bank.id, term="controller", term_zh="控制者", frequency=5),
            BankWordFrequency(bank_id=bank.id, term="governance", term_zh="治理", frequency=3),
        ])
        db.session.commit()

        return {
            "admin_token": create_access_token(identity=str(admin.id)),
            "learner_token": create_access_token(identity=str(learner.id)),
            "bank_id": bank.id,
            "admin_id": admin.id,
            "learner_id": learner.id,
        }


def seed_frequent_progress_state(app, user_id, bank_id, term, is_mastered):
    with app.app_context():
        db.session.add(UserBankWordProgress(
            user_id=user_id,
            bank_id=bank_id,
            term=term,
            is_mastered=is_mastered,
        ))
        db.session.commit()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_personal_vocab_exposes_progress_fields(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    res = client.get("/api/vocab/personal", headers=auth_headers(seeded["learner_token"]))

    assert res.status_code == 200
    items = res.get_json()
    assert len(items) == 2
    items_by_term = {item["term"]: item for item in items}
    assert set(items_by_term) == {"alpha", "beta"}
    assert items_by_term["alpha"]["is_mastered"] is True
    assert items_by_term["beta"]["is_mastered"] is False
    assert items_by_term["alpha"]["can_delete"] is False
    assert items_by_term["beta"]["can_delete"] is False
    assert items_by_term["alpha"]["can_mark_mastered"] is True
    assert items_by_term["beta"]["can_mark_mastered"] is True


def test_get_personal_vocab_filters_unmastered_items(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    res = client.get(
        "/api/vocab/personal?mastered=false",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert res.status_code == 200
    items = res.get_json()
    assert [item["term"] for item in items] == ["beta"]


def test_put_vocab_item_progress_creates_or_updates_state_and_persists_db_state(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    first_res = client.put(
        f"/api/vocab/items/{seeded['personal_beta_id']}/progress",
        json={"is_mastered": True},
        headers=auth_headers(seeded["learner_token"]),
    )

    assert first_res.status_code == 200
    assert first_res.get_json()["message"] == "已标记为掌握"

    with app.app_context():
        row = db.session.execute(
            text(
                """
                SELECT is_mastered
                FROM user_vocab_progress
                WHERE user_id = :user_id AND vocabulary_id = :vocabulary_id
                """
            ),
            {"user_id": seeded["learner_id"], "vocabulary_id": seeded["personal_beta_id"]},
        ).fetchone()
        assert row is not None
        assert row.is_mastered in (1, True)
        first_state = row.is_mastered

    second_res = client.put(
        f"/api/vocab/items/{seeded['personal_beta_id']}/progress",
        json={"is_mastered": False},
        headers=auth_headers(seeded["learner_token"]),
    )

    assert second_res.status_code == 200
    assert second_res.get_json()["message"] == "已取消掌握"

    with app.app_context():
        row = db.session.execute(
            text(
                """
                SELECT is_mastered
                FROM user_vocab_progress
                WHERE user_id = :user_id AND vocabulary_id = :vocabulary_id
                """
            ),
            {"user_id": seeded["learner_id"], "vocabulary_id": seeded["personal_beta_id"]},
        ).fetchone()
        assert row is not None
        assert row.is_mastered in (0, False)
        second_state = row.is_mastered

    assert first_state in (1, True)
    assert second_state in (0, False)


def test_get_professional_vocab_filters_by_mastered_state(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    mastered_res = client.get(
        "/api/vocab/professional?mastered=true",
        headers=auth_headers(seeded["learner_token"]),
    )
    unmastered_res = client.get(
        "/api/vocab/professional?mastered=false",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert mastered_res.status_code == 200
    assert [item["term"] for item in mastered_res.get_json()] == ["privacy"]

    assert unmastered_res.status_code == 200
    assert [item["term"] for item in unmastered_res.get_json()] == ["compliance"]


def test_delete_vocab_item_requires_admin(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    res = client.delete(
        f"/api/vocab/items/{seeded['personal_alpha_id']}",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert res.status_code == 403
    assert res.get_json()["error"] == "仅管理员可操作"


def test_admin_can_delete_personal_vocab_item(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    res = client.delete(
        f"/api/vocab/items/{seeded['personal_alpha_id']}",
        headers=auth_headers(seeded["admin_token"]),
    )

    assert res.status_code == 200
    assert res.get_json()["message"] == "已删除"

    with app.app_context():
        assert db.session.get(Vocabulary, seeded["personal_alpha_id"]) is None
        row = db.session.execute(
            text(
                """
                SELECT id
                FROM user_vocab_progress
                WHERE user_id = :user_id AND vocabulary_id = :vocabulary_id
                """
            ),
            {"user_id": seeded["learner_id"], "vocabulary_id": seeded["personal_alpha_id"]},
        ).fetchone()
        assert row is None


def test_admin_can_delete_professional_vocab_item(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    res = client.delete(
        f"/api/vocab/items/{seeded['professional_word_id']}",
        headers=auth_headers(seeded["admin_token"]),
    )

    assert res.status_code == 200
    assert res.get_json()["message"] == "已删除"

    with app.app_context():
        assert db.session.get(Vocabulary, seeded["professional_word_id"]) is None


def test_get_frequent_vocab_returns_user_progress_and_permissions(app):
    seeded = seed_frequent_vocab_data(app)
    seed_frequent_progress_state(app, seeded["learner_id"], seeded["bank_id"], "privacy", True)
    client = app.test_client()

    learner_res = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["learner_token"]),
    )
    admin_res = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["admin_token"]),
    )

    assert learner_res.status_code == 200
    assert admin_res.status_code == 200

    learner_items = {item["term"]: item for item in learner_res.get_json()["items"]}
    admin_items = {item["term"]: item for item in admin_res.get_json()["items"]}

    assert learner_items["privacy"]["is_mastered"] is True
    assert learner_items["privacy"]["can_delete"] is False
    assert learner_items["privacy"]["can_mark_mastered"] is True
    assert admin_items["privacy"]["is_mastered"] is False
    assert admin_items["privacy"]["can_delete"] is True
    assert learner_items["controller"]["is_mastered"] is False
    assert learner_items["controller"]["can_delete"] is False
    assert learner_items["controller"]["can_mark_mastered"] is True
    assert admin_items["controller"]["is_mastered"] is False
    assert admin_items["controller"]["can_delete"] is True


def test_get_frequent_vocab_filters_by_mastered_state(app):
    seeded = seed_frequent_vocab_data(app)
    seed_frequent_progress_state(app, seeded["learner_id"], seeded["bank_id"], "privacy", True)
    client = app.test_client()

    mastered_res = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}&mastered=true",
        headers=auth_headers(seeded["learner_token"]),
    )
    unmastered_res = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}&mastered=false",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert mastered_res.status_code == 200
    assert [item["term"] for item in mastered_res.get_json()["items"]] == ["privacy"]

    assert unmastered_res.status_code == 200
    assert [item["term"] for item in unmastered_res.get_json()["items"]] == ["controller", "governance"]


def test_put_frequent_vocab_item_progress_creates_user_state(app):
    seeded = seed_frequent_vocab_data(app)
    client = app.test_client()

    response = client.put(
        "/api/vocab/frequent-items/progress",
        json={
            "bank_id": seeded["bank_id"],
            "term": "privacy",
            "is_mastered": True,
        },
        headers=auth_headers(seeded["learner_token"]),
    )

    assert response.status_code == 200
    assert response.get_json()["message"] == "已标记为掌握"

    with app.app_context():
        row = db.session.execute(
            text(
                """
                SELECT is_mastered
                FROM user_bank_word_progress
                WHERE user_id = :user_id AND bank_id = :bank_id AND term = :term
                """
            ),
            {
                "user_id": seeded["learner_id"],
                "bank_id": seeded["bank_id"],
                "term": "privacy",
            },
        ).fetchone()
        assert row is not None
        assert row.is_mastered in (1, True)

    refreshed = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert refreshed.status_code == 200
    items = {item["term"]: item for item in refreshed.get_json()["items"]}
    assert items["privacy"]["is_mastered"] is True
    assert items["privacy"]["can_delete"] is False

    admin_view = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["admin_token"]),
    )

    assert admin_view.status_code == 200
    admin_items = {item["term"]: item for item in admin_view.get_json()["items"]}
    assert admin_items["privacy"]["is_mastered"] is False


def test_delete_frequent_vocab_item_excludes_term_from_subsequent_results(app):
    seeded = seed_frequent_vocab_data(app)
    client = app.test_client()

    delete_res = client.delete(
        f"/api/vocab/frequent-items?bank_id={seeded['bank_id']}&term=privacy",
        headers=auth_headers(seeded["admin_token"]),
    )

    assert delete_res.status_code == 200
    assert delete_res.get_json()["message"] == "已删除"

    refreshed = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert refreshed.status_code == 200
    terms = [item["term"] for item in refreshed.get_json()["items"]]
    assert "privacy" not in terms
    assert "controller" in terms


def test_delete_frequent_vocab_item_rejects_unknown_term(app):
    seeded = seed_frequent_vocab_data(app)
    client = app.test_client()

    delete_res = client.delete(
        f"/api/vocab/frequent-items?bank_id={seeded['bank_id']}&term=nonexistent",
        headers=auth_headers(seeded["admin_token"]),
    )

    assert delete_res.status_code == 404
    assert delete_res.get_json()["error"] == "词条不存在"


def test_non_admin_cannot_delete_frequent_vocab_item(app):
    seeded = seed_frequent_vocab_data(app)
    client = app.test_client()

    delete_res = client.delete(
        f"/api/vocab/frequent-items?bank_id={seeded['bank_id']}&term=privacy",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert delete_res.status_code == 403
    assert delete_res.get_json()["error"] == "仅管理员可操作"

    refreshed = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert refreshed.status_code == 200
    terms = [item["term"] for item in refreshed.get_json()["items"]]
    assert "privacy" in terms


def test_excluded_frequent_terms_stay_hidden_after_bank_import_rebuild(app):
    seeded = seed_frequent_vocab_data(app)
    client = app.test_client()

    delete_res = client.delete(
        f"/api/vocab/frequent-items?bank_id={seeded['bank_id']}&term=privacy",
        headers=auth_headers(seeded["admin_token"]),
    )
    assert delete_res.status_code == 200
    assert delete_res.get_json()["message"] == "已删除"

    baseline = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["learner_token"]),
    )
    assert baseline.status_code == 200
    baseline_terms = [item["term"] for item in baseline.get_json()["items"]]
    assert "privacy" not in baseline_terms
    assert "controller" in baseline_terms

    import routes.banks as banks_module
    original_parse_file = banks_module.parse_file if hasattr(banks_module, 'parse_file') else None

    def fake_parse_file(file_storage, filename):
        return [
            {
                'content': 'Security program privacy security governance',
                'options': [{'key': 'A', 'text': 'Security privacy governance'}],
                'correct_answer': 'A',
                'question_type': 'single',
                'answer_missing': False,
            },
            {
                'content': 'Privacy compliance and security privacy controls',
                'options': [{'key': 'A', 'text': 'Security privacy controls'}],
                'correct_answer': 'A',
                'question_type': 'single',
                'answer_missing': False,
            },
        ]

    banks_module.parse_file = fake_parse_file
    try:
        import_res = client.post(
            f"/api/banks/{seeded['bank_id']}/import",
            data={"file": (BytesIO(b"ignored"), "questions.docx")},
            content_type="multipart/form-data",
            headers=auth_headers(seeded["admin_token"]),
        )

        assert import_res.status_code == 200

        refreshed = client.get(
            f"/api/vocab/frequent?bank_id={seeded['bank_id']}",
            headers=auth_headers(seeded["learner_token"]),
        )

        assert refreshed.status_code == 200
        terms = [item["term"] for item in refreshed.get_json()["items"]]
        assert "privacy" not in terms
        assert "security" in terms
    finally:
        if original_parse_file is not None:
            banks_module.parse_file = original_parse_file
        else:
            delattr(banks_module, 'parse_file')


def test_vocab_list_returns_401_when_current_user_is_missing(app):
    seeded = seed_vocab_data(app)
    client = app.test_client()

    with app.app_context():
        learner = User.query.filter_by(username="learner").first()
        db.session.delete(learner)
        db.session.commit()

    response = client.get(
        "/api/vocab/personal",
        headers=auth_headers(seeded["learner_token"]),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "用户不存在或登录已失效"
