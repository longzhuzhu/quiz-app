import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SYSTEM_SETTINGS_ENCRYPTION_KEY = os.environ.get(
        'SYSTEM_SETTINGS_ENCRYPTION_KEY',
        SECRET_KEY,
    )
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', f'sqlite:///{os.path.join(basedir, "quiz.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=7)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB upload limit

    # AI config
    AI_API_BASE_URL = os.environ.get('AI_API_BASE_URL', 'https://api.openai.com')
    AI_API_KEY = os.environ.get('AI_API_KEY', '')
    AI_MODEL = os.environ.get('AI_MODEL', 'gpt-4o-mini')
