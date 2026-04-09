import json
import os
import sqlite3
import sys
import tempfile
from io import BytesIO

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from models import db, User, QuestionBank, BankWordFrequency
from routes.auth import auth_bp
from routes.banks import banks_bp
from routes.vocab import vocab_bp
from services.import_service import build_bank_word_frequencies


class TestConfig:
    TESTING = True
    SECRET_KEY = 'test-secret'
    JWT_SECRET_KEY = 'test-jwt-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DummyUploadFile(BytesIO):
    def __init__(self, text, filename='questions.docx'):
        super().__init__(text.encode('utf-8'))
        self.filename = filename


class DummyParsedFile:
    def __init__(self, filename='questions.docx'):
        self.filename = filename



def create_test_app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    app = Flask(__name__)
    app.config.update({
        'TESTING': True,
        'SECRET_KEY': TestConfig.SECRET_KEY,
        'JWT_SECRET_KEY': TestConfig.JWT_SECRET_KEY,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    })

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(banks_bp, url_prefix='/api/banks')
    app.register_blueprint(vocab_bp, url_prefix='/api/vocab')

    with app.app_context():
        db.create_all()

    return app, db_fd, db_path



def seed_admin(app):
    with app.app_context():
        admin = User(
            username='admin',
            email='admin@example.com',
            password_hash='hashed',
            is_admin=True,
        )
        bank = QuestionBank(name='Test Bank', description='desc')
        db.session.add_all([admin, bank])
        db.session.commit()
        return admin.id, bank.id



def auth_headers(client, admin_id):
    with client.application.app_context():
        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(admin_id))
    return {'Authorization': f'Bearer {token}'}



def test_build_bank_word_frequencies_filters_noise_and_counts_terms():
    questions = [
        {
            'content': 'The privacy controller protects privacy and data subjects.',
            'options': [
                {'key': 'A', 'text': 'A privacy program with privacy metrics'},
                {'key': 'B', 'text': 'An and but or 1st second wow is as are be not can was'},
            ],
        },
        {
            'content': 'Privacy by design improves privacy controls for controller teams.',
            'options': [
                {'key': 'A', 'text': 'Controller accountability and privacy reviews'},
            ],
        },
    ]

    frequencies = build_bank_word_frequencies(questions)

    assert frequencies == [
        {'term': 'privacy', 'frequency': 7},
        {'term': 'controller', 'frequency': 3},
    ]



def test_build_bank_word_frequencies_excludes_terms_with_four_or_fewer_letters():
    questions = [
        {
            'content': 'Data privacy data risk data user data',
            'options': [
                {'key': 'A', 'text': 'Risk data privacy user privacy'},
            ],
        },
    ]

    frequencies = build_bank_word_frequencies(questions)

    assert frequencies == [
        {'term': 'privacy', 'frequency': 3},
    ]



def test_import_rebuilds_bank_word_frequencies_for_full_bank():
    app, db_fd, db_path = create_test_app()
    try:
        admin_id, bank_id = seed_admin(app)
        client = app.test_client()
        headers = auth_headers(client, admin_id)

        with app.app_context():
            stale = BankWordFrequency(bank_id=bank_id, term='stale', frequency=99)
            db.session.add(stale)
            db.session.commit()

        import routes.banks as banks_module

        original_parse_file = banks_module.parse_file if hasattr(banks_module, 'parse_file') else None

        def fake_parse_file(file_storage, filename):
            return [
                {
                    'content': 'Privacy program privacy governance',
                    'options': [{'key': 'A', 'text': 'Privacy governance'}],
                    'correct_answer': 'A',
                    'question_type': 'single',
                    'answer_missing': False,
                },
                {
                    'content': 'Controller responsibilities for controller operations',
                    'options': [{'key': 'A', 'text': 'Privacy controller'}],
                    'correct_answer': 'A',
                    'question_type': 'single',
                    'answer_missing': False,
                },
            ]

        banks_module.parse_file = fake_parse_file

        response = client.post(
            f'/api/banks/{bank_id}/import',
            data={'file': (BytesIO(b'ignored'), 'questions.docx')},
            content_type='multipart/form-data',
            headers=headers,
        )

        if original_parse_file is not None:
            banks_module.parse_file = original_parse_file
        else:
            delattr(banks_module, 'parse_file')

        assert response.status_code == 200

        with app.app_context():
            frequencies = BankWordFrequency.query.filter_by(bank_id=bank_id).order_by(
                BankWordFrequency.frequency.desc(), BankWordFrequency.term.asc()
            ).all()
            assert [(item.term, item.frequency) for item in frequencies] == [
                ('privacy', 4),
                ('controller', 3),
                ('governance', 2),
            ]
    finally:
        os.close(db_fd)
        os.unlink(db_path)



def test_import_rebuilds_bank_word_frequencies_and_translate_endpoint_persists_translations():
    app, db_fd, db_path = create_test_app()
    try:
        admin_id, bank_id = seed_admin(app)
        client = app.test_client()
        headers = auth_headers(client, admin_id)

        import routes.banks as banks_module

        original_parse_file = banks_module.parse_file if hasattr(banks_module, 'parse_file') else None
        original_batch_translate_terms = banks_module.batch_translate_terms

        def fake_parse_file(file_storage, filename):
            return [
                {
                    'content': 'Privacy program privacy governance',
                    'options': [{'key': 'A', 'text': 'Privacy governance'}],
                    'correct_answer': 'A',
                    'question_type': 'single',
                    'answer_missing': False,
                },
                {
                    'content': 'Controller responsibilities for controller operations',
                    'options': [{'key': 'A', 'text': 'Privacy controller'}],
                    'correct_answer': 'A',
                    'question_type': 'single',
                    'answer_missing': False,
                },
            ]

        def fake_batch_translate_terms(items):
            translations = {
                'privacy': '隐私',
                'controller': '控制者',
                'governance': '治理',
            }
            return [
                {
                    'id': item['id'],
                    'term_zh': translations.get(item['term']),
                }
                for item in items
            ]

        banks_module.parse_file = fake_parse_file

        response = client.post(
            f'/api/banks/{bank_id}/import',
            data={'file': (BytesIO(b'ignored'), 'questions.docx')},
            content_type='multipart/form-data',
            headers=headers,
        )

        if original_parse_file is not None:
            banks_module.parse_file = original_parse_file
        else:
            delattr(banks_module, 'parse_file')

        assert response.status_code == 200
        assert response.get_json()['frequency_count'] == 3

        with app.app_context():
            frequencies = BankWordFrequency.query.filter_by(bank_id=bank_id).order_by(
                BankWordFrequency.frequency.desc(), BankWordFrequency.term.asc()
            ).all()
            assert [
                (item.term, item.frequency, getattr(item, 'term_zh', None))
                for item in frequencies
            ] == [
                ('privacy', 4, None),
                ('controller', 3, None),
                ('governance', 2, None),
            ]

        banks_module.batch_translate_terms = fake_batch_translate_terms
        translate_res = client.post(
            f'/api/banks/{bank_id}/translate-frequencies',
            headers=headers,
        )
        banks_module.batch_translate_terms = original_batch_translate_terms

        assert translate_res.status_code == 200
        assert translate_res.get_json() == {'translated': 3, 'remaining': 0}

        with app.app_context():
            frequencies = BankWordFrequency.query.filter_by(bank_id=bank_id).order_by(
                BankWordFrequency.frequency.desc(), BankWordFrequency.term.asc()
            ).all()
            assert [
                (item.term, item.frequency, getattr(item, 'term_zh', None))
                for item in frequencies
            ] == [
                ('privacy', 4, '隐私'),
                ('controller', 3, '控制者'),
                ('governance', 2, '治理'),
            ]
    finally:
        os.close(db_fd)
        os.unlink(db_path)



def test_translate_bank_word_frequencies_batches_requests():
    import routes.banks as banks_module

    original_batch_translate_terms = banks_module.batch_translate_terms
    calls = []

    def fake_batch_translate_terms(batch):
        calls.append(len(batch))
        return [
            {'id': item['id'], 'term_zh': f"中文-{item['term']}"}
            for item in batch
        ]

    banks_module.batch_translate_terms = fake_batch_translate_terms

    try:
        items = [
            {'term': f'term-{index}', 'frequency': 10}
            for index in range(205)
        ]

        translated = banks_module.translate_bank_word_frequencies(items)

        assert calls == [100, 100, 5]
        assert translated[0]['term_zh'] == '中文-term-0'
        assert translated[-1]['term_zh'] == '中文-term-204'
    finally:
        banks_module.batch_translate_terms = original_batch_translate_terms



def test_translate_bank_word_frequencies_retries_with_smaller_batches_after_timeout():
    import routes.banks as banks_module

    original_batch_translate_terms = banks_module.batch_translate_terms
    calls = []

    def fake_batch_translate_terms(batch):
        calls.append(len(batch))
        if len(batch) > 5:
            raise TimeoutError('timeout')
        return [
            {'id': item['id'], 'term_zh': f"中文-{item['term']}"}
            for item in batch
        ]

    banks_module.batch_translate_terms = fake_batch_translate_terms

    try:
        items = [
            {'term': f'term-{index}', 'frequency': 10}
            for index in range(12)
        ]

        translated = banks_module.translate_bank_word_frequencies(items)

        assert any(size > 5 for size in calls)
        assert any(size <= 5 for size in calls)
        assert [item['term_zh'] for item in translated] == [
            f'中文-term-{index}'
            for index in range(12)
        ]
    finally:
        banks_module.batch_translate_terms = original_batch_translate_terms



def test_get_frequent_vocab_requires_bank_id():
    app, db_fd, db_path = create_test_app()
    try:
        admin_id, _ = seed_admin(app)
        client = app.test_client()
        response = client.get('/api/vocab/frequent', headers=auth_headers(client, admin_id))

        assert response.status_code == 400
        assert response.get_json() == {'error': '缺少 bank_id 参数'}
    finally:
        os.close(db_fd)
        os.unlink(db_path)



def test_get_frequent_vocab_returns_bank_summary_and_paginated_items():
    app, db_fd, db_path = create_test_app()
    try:
        admin_id, bank_id = seed_admin(app)
        client = app.test_client()

        with app.app_context():
            db.session.add_all([
                BankWordFrequency(bank_id=bank_id, term='privacy', term_zh='隐私', frequency=8),
                BankWordFrequency(bank_id=bank_id, term='controller', term_zh='控制者', frequency=5),
                BankWordFrequency(bank_id=bank_id, term='governance', term_zh='治理', frequency=3),
            ])
            db.session.commit()

        response = client.get(
            f'/api/vocab/frequent?bank_id={bank_id}&page=1&per_page=2',
            headers=auth_headers(client, admin_id),
        )

        assert response.status_code == 200
        assert response.get_json() == {
            'bank': {'id': bank_id, 'name': 'Test Bank'},
            'summary': {'total_terms': 3, 'min_frequency': 2, 'top_terms_limit': 5000},
            'pagination': {'page': 1, 'per_page': 2, 'total_pages': 2, 'total_items': 3},
            'items': [
                {
                    'term': 'privacy',
                    'term_zh': '隐私',
                    'frequency': 8,
                    'is_mastered': False,
                    'can_delete': True,
                    'can_mark_mastered': True,
                },
                {
                    'term': 'controller',
                    'term_zh': '控制者',
                    'frequency': 5,
                    'is_mastered': False,
                    'can_delete': True,
                    'can_mark_mastered': True,
                },
            ],
        }
    finally:
        os.close(db_fd)
        os.unlink(db_path)



def test_get_frequent_vocab_limits_results_to_top_5000_before_pagination():
    app, db_fd, db_path = create_test_app()
    try:
        admin_id, bank_id = seed_admin(app)
        client = app.test_client()

        with app.app_context():
            db.session.add_all([
                BankWordFrequency(bank_id=bank_id, term=f'term-{i:04d}', frequency=6000 - i)
                for i in range(5005)
            ])
            db.session.commit()

        response = client.get(
            f'/api/vocab/frequent?bank_id={bank_id}&page=500&per_page=10',
            headers=auth_headers(client, admin_id),
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['summary'] == {'total_terms': 5000, 'min_frequency': 2, 'top_terms_limit': 5000}
        assert payload['pagination'] == {'page': 500, 'per_page': 10, 'total_pages': 500, 'total_items': 5000}
        assert len(payload['items']) == 10
        assert payload['items'][0] == {
            'term': 'term-4990',
            'term_zh': None,
            'frequency': 1010,
            'is_mastered': False,
            'can_delete': True,
            'can_mark_mastered': True,
        }
        assert payload['items'][-1] == {
            'term': 'term-4999',
            'term_zh': None,
            'frequency': 1001,
            'is_mastered': False,
            'can_delete': True,
            'can_mark_mastered': True,
        }
    finally:
        os.close(db_fd)
        os.unlink(db_path)



def test_get_frequent_vocab_returns_404_for_missing_bank():
    app, db_fd, db_path = create_test_app()
    try:
        admin_id, _ = seed_admin(app)
        client = app.test_client()
        response = client.get('/api/vocab/frequent?bank_id=999', headers=auth_headers(client, admin_id))

        assert response.status_code == 404
        assert response.get_json() == {'error': '题库不存在'}
    finally:
        os.close(db_fd)
        os.unlink(db_path)



def test_create_app_adds_missing_term_zh_column_for_bank_word_frequencies():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                'CREATE TABLE bank_word_frequencies ('
                'id INTEGER PRIMARY KEY, '
                'bank_id INTEGER NOT NULL, '
                'term VARCHAR(200) NOT NULL, '
                'frequency INTEGER NOT NULL, '
                'created_at DATETIME, '
                'updated_at DATETIME'
                ')'
            )
            conn.commit()
        finally:
            conn.close()

        os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'

        from app import create_app

        app = create_app()
        with app.app_context():
            columns = [column[1] for column in db.session.execute(db.text('PRAGMA table_info(bank_word_frequencies)')).fetchall()]

        assert 'term_zh' in columns
    finally:
        os.environ.pop('DATABASE_URL', None)
        os.close(db_fd)
        os.unlink(db_path)
