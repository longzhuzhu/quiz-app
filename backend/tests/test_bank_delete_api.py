import json
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import (
    db,
    User,
    QuestionBank,
    Question,
    QuizSession,
    QuizAnswer,
    WrongAnswer,
    BankWordFrequency,
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


def seed_data(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        learner = User(username="u1", email="u1@test.com", password_hash="x", is_admin=False)
        db.session.add_all([admin, learner])
        db.session.flush()

        bank_1 = QuestionBank(name="bank-1", description="to-delete")
        bank_2 = QuestionBank(name="bank-2", description="keep")
        db.session.add_all([bank_1, bank_2])
        db.session.flush()

        q1 = Question(
            bank_id=bank_1.id,
            question_type="single",
            content="q1",
            options=json.dumps([{"key": "A", "text": "A"}, {"key": "B", "text": "B"}]),
            correct_answer="A",
            order_index=1,
        )
        q2 = Question(
            bank_id=bank_2.id,
            question_type="single",
            content="q2",
            options=json.dumps([{"key": "A", "text": "A"}, {"key": "B", "text": "B"}]),
            correct_answer="A",
            order_index=1,
        )
        db.session.add_all([q1, q2])
        db.session.flush()

        session_1 = QuizSession(
            user_id=learner.id,
            bank_id=bank_1.id,
            mode="sequential",
            total_questions=1,
            question_ids=json.dumps([q1.id]),
        )
        session_2 = QuizSession(
            user_id=learner.id,
            bank_id=bank_2.id,
            mode="sequential",
            total_questions=1,
            question_ids=json.dumps([q2.id]),
        )
        db.session.add_all([session_1, session_2])
        db.session.flush()

        answer_1 = QuizAnswer(session_id=session_1.id, question_id=q1.id, user_answer="A", is_correct=True)
        answer_2 = QuizAnswer(session_id=session_2.id, question_id=q2.id, user_answer="A", is_correct=True)
        wrong_1 = WrongAnswer(user_id=learner.id, question_id=q1.id, wrong_count=1)
        wrong_2 = WrongAnswer(user_id=learner.id, question_id=q2.id, wrong_count=1)
        freq_1 = BankWordFrequency(bank_id=bank_1.id, term="privacy", term_zh="隐私", frequency=2)
        freq_2 = BankWordFrequency(bank_id=bank_2.id, term="security", term_zh="安全", frequency=3)
        db.session.add_all([answer_1, answer_2, wrong_1, wrong_2, freq_1, freq_2])
        db.session.commit()

        token = create_access_token(identity=str(admin.id))
        return {
            "token": token,
            "bank_1_id": bank_1.id,
            "bank_2_id": bank_2.id,
            "q2_id": q2.id,
            "session_2_id": session_2.id,
        }


def test_delete_bank_removes_related_records_and_keeps_other_bank_data(app):
    seeded = seed_data(app)
    client = app.test_client()

    res = client.delete(
        f"/api/banks/{seeded['bank_1_id']}",
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    assert res.status_code == 200
    assert res.get_json()["message"] == "题库已删除"

    with app.app_context():
        remaining_bank_ids = {item.id for item in QuestionBank.query.all()}
        remaining_question_ids = {item.id for item in Question.query.all()}
        remaining_session_ids = {item.id for item in QuizSession.query.all()}
        remaining_answer_question_ids = {item.question_id for item in QuizAnswer.query.all()}
        remaining_wrong_question_ids = {item.question_id for item in WrongAnswer.query.all()}
        remaining_frequency_bank_ids = {item.bank_id for item in BankWordFrequency.query.all()}

        assert remaining_bank_ids == {seeded["bank_2_id"]}
        assert remaining_question_ids == {seeded["q2_id"]}
        assert remaining_session_ids == {seeded["session_2_id"]}
        assert remaining_answer_question_ids == {seeded["q2_id"]}
        assert remaining_wrong_question_ids == {seeded["q2_id"]}
        assert remaining_frequency_bank_ids == {seeded["bank_2_id"]}


def test_create_bank_returns_401_when_jwt_user_not_exists(app):
    with app.app_context():
        token = create_access_token(identity="9999")

    client = app.test_client()
    res = client.post(
        "/api/banks/",
        json={"name": "bank-1", "description": "d"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 401
    assert res.get_json()["error"] == "用户不存在，请重新登录"
