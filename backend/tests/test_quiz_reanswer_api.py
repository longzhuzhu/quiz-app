import json
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, User, QuestionBank, Question, QuizSession, QuizAnswer


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "quiz_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def seed_session(app, *, initial_answer, initial_is_correct, correct_count):
    with app.app_context():
        user = User(username="u1", email="u1@test.com", password_hash="x")
        bank = QuestionBank(name="bank", description="d")
        db.session.add_all([user, bank])
        db.session.flush()

        q = Question(
            bank_id=bank.id,
            question_type="single",
            content="question",
            content_zh=None,
            options=json.dumps([
                {"key": "A", "text": "A"},
                {"key": "B", "text": "B"}
            ]),
            correct_answer="A",
            explanation="exp",
            explanation_zh=None,
            order_index=1,
        )
        db.session.add(q)
        db.session.flush()

        session = QuizSession(
            user_id=user.id,
            bank_id=bank.id,
            mode="sequential",
            total_questions=1,
            answered_count=1,
            correct_count=correct_count,
            question_ids=json.dumps([q.id]),
        )
        db.session.add(session)
        db.session.flush()

        existing = QuizAnswer(
            session_id=session.id,
            question_id=q.id,
            user_answer=initial_answer,
            is_correct=initial_is_correct,
        )
        db.session.add(existing)
        db.session.commit()

        token = create_access_token(identity=str(user.id))
        return {
            "token": token,
            "session_id": session.id,
            "question_id": q.id,
        }


def test_submit_answer_rejects_question_not_in_session_question_ids(app):
    with app.app_context():
        user = User(username="u2", email="u2@test.com", password_hash="x")
        bank = QuestionBank(name="bank-2", description="d")
        db.session.add_all([user, bank])
        db.session.flush()

        in_session_question = Question(
            bank_id=bank.id,
            question_type="single",
            content="in session question",
            content_zh=None,
            options=json.dumps([
                {"key": "A", "text": "A"},
                {"key": "B", "text": "B"}
            ]),
            correct_answer="A",
            explanation="exp",
            explanation_zh=None,
            order_index=1,
        )
        out_of_session_question = Question(
            bank_id=bank.id,
            question_type="single",
            content="out of session question",
            content_zh=None,
            options=json.dumps([
                {"key": "A", "text": "A"},
                {"key": "B", "text": "B"}
            ]),
            correct_answer="A",
            explanation="exp",
            explanation_zh=None,
            order_index=2,
        )
        db.session.add_all([in_session_question, out_of_session_question])
        db.session.flush()

        session = QuizSession(
            user_id=user.id,
            bank_id=bank.id,
            mode="sequential",
            total_questions=1,
            answered_count=0,
            correct_count=0,
            question_ids=json.dumps([in_session_question.id]),
        )
        db.session.add(session)
        db.session.commit()

        token = create_access_token(identity=str(user.id))
        session_id = session.id
        out_question_id = out_of_session_question.id

    client = app.test_client()
    res = client.post(
        "/api/quiz/answer",
        json={
            "session_id": session_id,
            "question_id": out_question_id,
            "user_answer": "A",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 400

    with app.app_context():
        assert QuizAnswer.query.filter_by(session_id=session_id).count() == 0
        session = QuizSession.query.get(session_id)
        assert session.answered_count == 0
        assert session.correct_count == 0


def test_reanswer_wrong_to_correct_updates_existing_record_and_counts(app):
    seeded = seed_session(app, initial_answer="B", initial_is_correct=False, correct_count=0)
    client = app.test_client()

    res = client.post(
        "/api/quiz/answer",
        json={
            "session_id": seeded["session_id"],
            "question_id": seeded["question_id"],
            "user_answer": "A",
        },
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    # 当前 RED：尚未支持重答覆盖时这里会返回 400（该题已作答）
    assert res.status_code == 200

    with app.app_context():
        answers = QuizAnswer.query.filter_by(
            session_id=seeded["session_id"],
            question_id=seeded["question_id"],
        ).all()
        assert len(answers) == 1
        assert answers[0].user_answer == "A"
        assert answers[0].is_correct is True

        session = QuizSession.query.get(seeded["session_id"])
        assert session.answered_count == 1
        assert session.correct_count == 1


def test_reanswer_correct_to_wrong_decrements_correct_count_without_incrementing_answered_count(app):
    seeded = seed_session(app, initial_answer="A", initial_is_correct=True, correct_count=1)
    client = app.test_client()

    res = client.post(
        "/api/quiz/answer",
        json={
            "session_id": seeded["session_id"],
            "question_id": seeded["question_id"],
            "user_answer": "B",
        },
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    # 当前 RED：尚未支持重答覆盖时这里会返回 400（该题已作答）
    assert res.status_code == 200

    with app.app_context():
        answers = QuizAnswer.query.filter_by(
            session_id=seeded["session_id"],
            question_id=seeded["question_id"],
        ).all()
        assert len(answers) == 1
        assert answers[0].user_answer == "B"
        assert answers[0].is_correct is False

        session = QuizSession.query.get(seeded["session_id"])
        assert session.answered_count == 1
        assert session.correct_count == 0
