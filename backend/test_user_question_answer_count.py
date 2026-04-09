import json
import os
import sys
import tempfile

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token
from sqlalchemy import inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app import create_app
from models import db, User, Question, QuestionBank, QuizSession, UserQuestionStat
from routes.auth import auth_bp
from routes.quiz import quiz_bp
from routes.wrong import wrong_bp


def create_test_app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    app = Flask(__name__)
    app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
        'JWT_SECRET_KEY': 'test-jwt-secret',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    })

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(quiz_bp, url_prefix='/api/quiz')
    app.register_blueprint(wrong_bp, url_prefix='/api/wrong')

    with app.app_context():
        db.create_all()

    return app, db_fd, db_path


def auth_headers(app, user_id):
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {'Authorization': f'Bearer {token}'}


def seed_user_bank_questions(app):
    with app.app_context():
        user = User(username='learner', email='learner@example.com', password_hash='hashed')
        bank = QuestionBank(name='Count Bank', description='count test bank')
        db.session.add_all([user, bank])
        db.session.flush()

        q1 = Question(
            bank_id=bank.id,
            question_type='single',
            content='Question 1',
            options=json.dumps([
                {'key': 'A', 'text': 'Alpha'},
                {'key': 'B', 'text': 'Beta'},
            ]),
            correct_answer='A',
            order_index=0,
        )
        q2 = Question(
            bank_id=bank.id,
            question_type='single',
            content='Question 2',
            options=json.dumps([
                {'key': 'A', 'text': 'One'},
                {'key': 'B', 'text': 'Two'},
            ]),
            correct_answer='B',
            order_index=1,
        )
        db.session.add_all([q1, q2])
        db.session.commit()
        return user.id, bank.id, q1.id, q2.id


def test_start_quiz_returns_zero_user_answer_count_for_new_user():
    app, db_fd, db_path = create_test_app()
    try:
        user_id, bank_id, _, _ = seed_user_bank_questions(app)
        client = app.test_client()

        response = client.post(
            '/api/quiz/start',
            json={'bank_id': bank_id, 'mode': 'sequential'},
            headers=auth_headers(app, user_id),
        )

        assert response.status_code == 200
        data = response.get_json()
        assert [question['user_answer_count'] for question in data['questions']] == [0, 0]
    finally:
        os.close(db_fd)
        os.unlink(db_path)


def test_create_app_ensures_user_question_stats_schema():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    database_url = f'sqlite:///{db_path}'
    original_database_url = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = database_url
    try:
        app = create_app()
        with app.app_context():
            inspector = inspect(db.engine)
            assert 'user_question_stats' in inspector.get_table_names()
    finally:
        if original_database_url is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = original_database_url
        os.close(db_fd)
        os.unlink(db_path)


def start_quiz(client, headers, bank_id, mode='sequential'):
    response = client.post(
        '/api/quiz/start',
        json={'bank_id': bank_id, 'mode': mode},
        headers=headers,
    )
    assert response.status_code == 200
    return response.get_json()


def test_submit_answer_counts_once_per_session_and_across_sessions():
    app, db_fd, db_path = create_test_app()
    try:
        user_id, bank_id, q1_id, _ = seed_user_bank_questions(app)
        client = app.test_client()
        headers = auth_headers(app, user_id)

        first_session = start_quiz(client, headers, bank_id)
        first_session_id = first_session['session']['id']

        first_submit = client.post(
            '/api/quiz/answer',
            json={'session_id': first_session_id, 'question_id': q1_id, 'user_answer': 'A'},
            headers=headers,
        )
        assert first_submit.status_code == 200
        assert first_submit.get_json()['user_answer_count'] == 1
        assert first_submit.get_json()['counted_as_new_attempt'] is True

        repeat_submit = client.post(
            '/api/quiz/answer',
            json={'session_id': first_session_id, 'question_id': q1_id, 'user_answer': 'B'},
            headers=headers,
        )
        assert repeat_submit.status_code == 200
        assert repeat_submit.get_json()['user_answer_count'] == 1
        assert repeat_submit.get_json()['counted_as_new_attempt'] is False

        second_session = start_quiz(client, headers, bank_id)
        second_session_id = second_session['session']['id']
        second_submit = client.post(
            '/api/quiz/answer',
            json={'session_id': second_session_id, 'question_id': q1_id, 'user_answer': 'A'},
            headers=headers,
        )
        assert second_submit.status_code == 200
        assert second_submit.get_json()['user_answer_count'] == 2
        assert second_submit.get_json()['counted_as_new_attempt'] is True

        with app.app_context():
            stat = UserQuestionStat.query.filter_by(user_id=user_id, question_id=q1_id).first()
            assert stat is not None
            assert stat.answer_count == 2
            assert stat.first_answered_at is not None
            assert stat.last_answered_at is not None
    finally:
        os.close(db_fd)
        os.unlink(db_path)


def test_wrong_practice_and_session_resume_include_user_answer_count():
    app, db_fd, db_path = create_test_app()
    try:
        user_id, bank_id, q1_id, _ = seed_user_bank_questions(app)
        client = app.test_client()
        headers = auth_headers(app, user_id)

        session_data = start_quiz(client, headers, bank_id)
        session_id = session_data['session']['id']

        wrong_submit = client.post(
            '/api/quiz/answer',
            json={'session_id': session_id, 'question_id': q1_id, 'user_answer': 'B'},
            headers=headers,
        )
        assert wrong_submit.status_code == 200
        assert wrong_submit.get_json()['user_answer_count'] == 1

        wrong_practice = client.post(
            '/api/wrong/practice',
            json={'bank_id': bank_id},
            headers=headers,
        )
        assert wrong_practice.status_code == 200
        wrong_data = wrong_practice.get_json()
        assert wrong_data['questions'][0]['user_answer_count'] == 1

        resumed = client.get(
            f"/api/quiz/session/{wrong_data['session']['id']}",
            headers=headers,
        )
        assert resumed.status_code == 200
        resumed_data = resumed.get_json()
        resumed_question = next(item for item in resumed_data['questions'] if item['id'] == q1_id)
        assert resumed_question['user_answer_count'] == 1

        with app.app_context():
            wrong_session = QuizSession.query.get(wrong_data['session']['id'])
            assert json.loads(wrong_session.question_ids) == [q1_id]
    finally:
        os.close(db_fd)
        os.unlink(db_path)
