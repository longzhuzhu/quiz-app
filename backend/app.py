import os

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from sqlalchemy import inspect, text

from config import Config
from models import db


def _ensure_bank_word_frequency_columns():
    inspector = inspect(db.engine)
    if 'bank_word_frequencies' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('bank_word_frequencies')}
    if 'term_zh' not in columns:
        db.session.execute(text('ALTER TABLE bank_word_frequencies ADD COLUMN term_zh VARCHAR(200)'))
        db.session.commit()



def create_app():
    app = Flask(__name__, static_folder='../frontend/dist', static_url_path='/')
    app.config.from_object(Config)

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

    @app.route('/')
    @app.route('/<path:path>')
    def serve_frontend(path=''):
        if path and os.path.exists(os.path.join(app.static_folder, path)):
            return app.send_static_file(path)
        return app.send_static_file('index.html')

    return app
