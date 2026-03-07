from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quiz_sessions = db.relationship('QuizSession', backref='user', lazy='dynamic')
    wrong_answers = db.relationship('WrongAnswer', backref='user', lazy='dynamic')


class QuestionBank(db.Model):
    __tablename__ = 'question_banks'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    source_filename = db.Column(db.String(300), nullable=True)
    question_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    questions = db.relationship('Question', backref='bank', lazy='dynamic',
                                cascade='all, delete-orphan')


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    bank_id = db.Column(db.Integer, db.ForeignKey('question_banks.id'), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # single/multiple/truefalse
    content = db.Column(db.Text, nullable=False)
    content_zh = db.Column(db.Text, nullable=True)
    options = db.Column(db.Text, nullable=False)  # JSON string
    correct_answer = db.Column(db.String(20), nullable=False)
    explanation = db.Column(db.Text, nullable=True)
    explanation_zh = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class QuizSession(db.Model):
    __tablename__ = 'quiz_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bank_id = db.Column(db.Integer, db.ForeignKey('question_banks.id'), nullable=False)
    mode = db.Column(db.String(20), nullable=False)  # sequential/random
    total_questions = db.Column(db.Integer, nullable=False)
    answered_count = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    is_completed = db.Column(db.Boolean, default=False)
    question_ids = db.Column(db.Text, nullable=True)  # JSON: 本次答题的题目 ID 列表
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)

    bank = db.relationship('QuestionBank', backref='sessions')
    answers = db.relationship('QuizAnswer', backref='session', lazy='dynamic',
                              cascade='all, delete-orphan')


class QuizAnswer(db.Model):
    __tablename__ = 'quiz_answers'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('quiz_sessions.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    user_answer = db.Column(db.String(20), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    answered_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    question = db.relationship('Question')
    __table_args__ = (db.UniqueConstraint('session_id', 'question_id'),)


class WrongAnswer(db.Model):
    __tablename__ = 'wrong_answers'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    wrong_count = db.Column(db.Integer, default=1)
    last_wrong_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_resolved = db.Column(db.Boolean, default=False)

    question = db.relationship('Question')
    __table_args__ = (db.UniqueConstraint('user_id', 'question_id'),)


class Vocabulary(db.Model):
    __tablename__ = 'vocabularies'
    id = db.Column(db.Integer, primary_key=True)
    term = db.Column(db.String(200), nullable=False)
    definition = db.Column(db.Text, nullable=True)
    term_zh = db.Column(db.String(200), nullable=True)
    definition_zh = db.Column(db.Text, nullable=True)
    is_system = db.Column(db.Boolean, default=False)  # True=专业词汇, False=用户个人
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='vocabularies')


class BankWordFrequency(db.Model):
    __tablename__ = 'bank_word_frequencies'
    id = db.Column(db.Integer, primary_key=True)
    bank_id = db.Column(db.Integer, db.ForeignKey('question_banks.id'), nullable=False, index=True)
    term = db.Column(db.String(200), nullable=False)
    term_zh = db.Column(db.String(200), nullable=True)
    frequency = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    bank = db.relationship('QuestionBank', backref=db.backref('word_frequencies', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('bank_id', 'term'),
        db.Index('idx_bank_word_frequency_bank_frequency', 'bank_id', 'frequency'),
    )


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = SystemSetting(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
