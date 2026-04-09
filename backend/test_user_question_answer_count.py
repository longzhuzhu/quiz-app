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
from models import db, User, Question, QuestionBank
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
