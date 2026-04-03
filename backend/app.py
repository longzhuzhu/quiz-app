import os

from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from sqlalchemy import inspect, text

from config import Config
from models import db, UserVocabProgress, UserBankWordProgress, BankWordExclusion


def _apply_runtime_env_overrides(app):
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        app.config.get('SQLALCHEMY_DATABASE_URI')
    )
    app.config['JWT_SECRET_KEY'] = os.environ.get(
        'JWT_SECRET_KEY',
        app.config.get('JWT_SECRET_KEY')
    )
    app.config['AI_API_BASE_URL'] = os.environ.get(
        'AI_API_BASE_URL',
        app.config.get('AI_API_BASE_URL')
    )
    app.config['AI_API_KEY'] = os.environ.get(
        'AI_API_KEY',
        app.config.get('AI_API_KEY')
    )
    app.config['AI_MODEL'] = os.environ.get(
        'AI_MODEL',
        app.config.get('AI_MODEL')
    )
    app.config['SYSTEM_SETTINGS_ENCRYPTION_KEY'] = os.environ.get(
        'SYSTEM_SETTINGS_ENCRYPTION_KEY',
        app.config.get('SYSTEM_SETTINGS_ENCRYPTION_KEY')
    )


def _ensure_bank_word_frequency_columns():
    inspector = inspect(db.engine)
    if 'bank_word_frequencies' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('bank_word_frequencies')}
    if 'term_zh' not in columns:
        db.session.execute(text('ALTER TABLE bank_word_frequencies ADD COLUMN term_zh VARCHAR(200)'))
        db.session.commit()


def _ensure_user_vocab_progress_schema():
    inspector = inspect(db.engine)
    if 'user_vocab_progress' not in inspector.get_table_names():
        UserVocabProgress.__table__.create(bind=db.engine, checkfirst=True)


def _ensure_bank_word_progress_schema():
    inspector = inspect(db.engine)
    if 'user_bank_word_progress' not in inspector.get_table_names():
        UserBankWordProgress.__table__.create(bind=db.engine, checkfirst=True)


def _ensure_bank_word_exclusion_schema():
    inspector = inspect(db.engine)
    if 'bank_word_exclusions' not in inspector.get_table_names():
        BankWordExclusion.__table__.create(bind=db.engine, checkfirst=True)



def create_app():
    dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist'))
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    _apply_runtime_env_overrides(app)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)

    from routes.auth import auth_bp
    from routes.banks import banks_bp
    from routes.questions import questions_bp
    from routes.quiz import quiz_bp
    from routes.wrong import wrong_bp
    from routes.ai import ai_bp
    from routes.settings import settings_bp
    from routes.vocab import vocab_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(banks_bp, url_prefix='/api/banks')
    app.register_blueprint(questions_bp, url_prefix='/api/questions')
    app.register_blueprint(quiz_bp, url_prefix='/api/quiz')
    app.register_blueprint(wrong_bp, url_prefix='/api/wrong')
    app.register_blueprint(ai_bp, url_prefix='/api/ai')
    app.register_blueprint(settings_bp, url_prefix='/api/settings')
    app.register_blueprint(vocab_bp, url_prefix='/api/vocab')

    with app.app_context():
        db.create_all()
        _ensure_bank_word_frequency_columns()
        _ensure_user_vocab_progress_schema()
        _ensure_bank_word_progress_schema()
        _ensure_bank_word_exclusion_schema()

    @app.route('/')
    @app.route('/<path:path>')
    def serve_frontend(path=''):
        if path and os.path.isfile(os.path.join(dist_dir, path)):
            return send_from_directory(dist_dir, path)
        return send_from_directory(dist_dir, 'index.html')

    return app
