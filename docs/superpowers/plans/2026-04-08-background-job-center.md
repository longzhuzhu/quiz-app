# Background Job Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为专业词汇批量翻译和高频词批量翻译落地一个可持久化的后台任务中心，支持页面刷新不中断、任务状态恢复、失败自动重试 3 次后结束，并允许再次点击继续翻译剩余未翻译数据。

**Architecture:** 后端新增通用 `BackgroundJob` 模型、`/api/jobs` 路由、`job_service` 状态机和独立 `job_worker` 常驻进程；两类翻译任务都由 handler 按批执行并逐批提交。前端新增 `useBackgroundJob` 轮询封装，`VocabularyView.vue` 与 `FileUpload.vue` 只负责创建/恢复任务和展示状态，不再用 `while (true)` 自己编排后台翻译。

**Tech Stack:** Flask 3, SQLAlchemy, SQLite, Vue 3, Axios, Vite, Pytest, systemd, bash

---

> **Known baseline:** `pytest backend/tests backend/test_high_frequency_vocab.py -q` 当前在本 worktree 中有 3 个既有失败用例（都在 `backend/test_high_frequency_vocab.py`）。按用户要求，本计划继续推进后台任务中心，不先中断去修这 3 个基线失败；每个任务只跑本任务新增/改动的定向验证命令，最终验证至少保证新测试与前端构建通过。

## File Map

- Modify: `backend/models.py:1-225`
  - 新增 `BackgroundJob` 模型与索引/约束
- Modify: `backend/app.py:1-111`
  - 注册 jobs blueprint，ensure `background_jobs` schema
- Create: `backend/routes/jobs.py`
  - 创建任务、查询任务、按作用域查询活动任务
- Create: `backend/services/job_service.py`
  - 作用域构造、互斥创建、序列化、抢占、续租、重试、失败、回收 stale job
- Create: `backend/services/job_handlers.py`
  - `professional_vocab_translate` / `bank_frequent_translate` 两类任务处理器
- Create: `backend/workers/job_worker.py`
  - `process_one_job()` 单轮执行与常驻 `main()` 循环
- Modify: `backend/routes/vocab.py:209-340`
  - 为前端暴露未翻译计数辅助字段并复用“是否待翻译”判断
- Create: `backend/tests/test_background_jobs_api.py`
  - jobs API 的创建 / 复用 / no_work / active 查询测试
- Create: `backend/tests/test_background_job_worker.py`
  - worker 成功执行 / 自动重试 / stale job 回收测试
- Create: `frontend/src/composables/useBackgroundJob.js`
  - 统一的创建任务、恢复活动任务、轮询、停止轮询逻辑
- Modify: `frontend/src/views/VocabularyView.vue:30-50,460-894`
  - 专业词汇与高频词按钮改为后台任务模式，展示进度与重试文案
- Modify: `frontend/src/components/FileUpload.vue:1-97`
  - 导入后创建高频词后台任务，不再前端 `while true`
- Modify: `frontend/src/views/AdminBanksView.vue:86-188`
  - 导入 modal 保持可见，让用户能看到后台翻译说明
- Create: `scripts/start-worker.sh`
  - 本地/生产统一 worker 启动脚本
- Modify: `scripts/install-systemd-service.sh:1-44`
  - 安装主服务时一并安装 worker 服务
- Create: `deploy/systemd/quiz-app-worker.service`
  - worker 的参考 unit 文件
- Modify: `README.md:58-127,129-177`
  - 补 worker 启动、systemd 双服务、后台任务中心说明

### Task 1: 写 jobs API 与未翻译计数的失败测试

**Files:**
- Create: `backend/tests/test_background_jobs_api.py`
- Test: `backend/tests/test_background_jobs_api.py`

- [ ] **Step 1: 写专业词汇任务创建/复用/查询的失败测试**

```python
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import BackgroundJob, QuestionBank, User, Vocabulary, db


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


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def seed_admin_and_vocab(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        bank = QuestionBank(name="bank-1", description="job-target")
        db.session.add_all([
            admin,
            bank,
            Vocabulary(term="privacy", definition="privacy concept", is_system=True),
            Vocabulary(term="controller", definition="purpose decision", term_zh="控制者", definition_zh=None, is_system=True),
        ])
        db.session.commit()
        return {
            "token": create_access_token(identity=str(admin.id)),
            "bank_id": bank.id,
        }


def test_post_jobs_creates_professional_vocab_job(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()

    response = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["result"] == "created"
    assert payload["job"]["job_type"] == "professional_vocab_translate"
    assert payload["job"]["scope_key"] == "professional_vocab"
    assert payload["job"]["status"] == "queued"
    assert payload["job"]["progress_total"] == 2


def test_post_jobs_reuses_existing_professional_vocab_job(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()

    first = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )
    second = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["result"] == "existing"
    assert second.get_json()["job"]["id"] == first.get_json()["job"]["id"]


def test_get_job_detail_returns_serialized_job(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()
    created = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    response = client.get(
        f"/api/jobs/{created.get_json()['job']['id']}",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["job"]["attempt_count"] == 0
    assert payload["job"]["max_attempts"] == 3
    assert payload["job"]["status_message"] == "等待后台 worker 执行"


def test_get_active_job_returns_professional_job_by_scope(app):
    seeded = seed_admin_and_vocab(app)
    client = app.test_client()
    created = client.post(
        "/api/jobs",
        json={"job_type": "professional_vocab_translate"},
        headers=auth_headers(seeded["token"]),
    )

    response = client.get(
        "/api/jobs/active?job_type=professional_vocab_translate",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json()["job"]["id"] == created.get_json()["job"]["id"]
```

- [ ] **Step 2: 跑失败测试，确认当前仓库还没有 jobs 系统**

Run: `pytest backend/tests/test_background_jobs_api.py -k "professional or detail or active" -v`

Expected:
- FAIL，报错集中在 `BackgroundJob`、`/api/jobs` blueprint 或序列化字段尚不存在

- [ ] **Step 3: 补高频词 no_work / active scope 与 summary 未翻译计数测试**

```python
from models import BankWordFrequency


def seed_bank_frequency(app):
    with app.app_context():
        admin = User(username="bank-admin", email="bank-admin@test.com", password_hash="x", is_admin=True)
        bank = QuestionBank(name="freq-bank", description="job-target")
        db.session.add_all([admin, bank])
        db.session.flush()
        db.session.add_all([
            BankWordFrequency(bank_id=bank.id, term="privacy", term_zh=None, frequency=8),
            BankWordFrequency(bank_id=bank.id, term="controller", term_zh=None, frequency=5),
            BankWordFrequency(bank_id=bank.id, term="governance", term_zh="治理", frequency=3),
        ])
        db.session.commit()
        return {
            "token": create_access_token(identity=str(admin.id)),
            "bank_id": bank.id,
        }


def test_post_jobs_returns_no_work_when_bank_has_no_untranslated_terms(app):
    seeded = seed_bank_frequency(app)
    client = app.test_client()

    with app.app_context():
        BankWordFrequency.query.filter_by(bank_id=seeded["bank_id"]).update({"term_zh": "已有翻译"})
        db.session.commit()

    response = client.post(
        "/api/jobs",
        json={"job_type": "bank_frequent_translate", "bank_id": seeded["bank_id"]},
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "result": "no_work",
        "job": None,
        "message": "当前没有待翻译数据",
    }


def test_get_active_job_scopes_bank_frequency_by_bank_id(app):
    seeded = seed_bank_frequency(app)
    client = app.test_client()
    created = client.post(
        "/api/jobs",
        json={"job_type": "bank_frequent_translate", "bank_id": seeded["bank_id"]},
        headers=auth_headers(seeded["token"]),
    )

    response = client.get(
        f"/api/jobs/active?job_type=bank_frequent_translate&bank_id={seeded['bank_id']}",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json()["job"]["scope_key"] == f"bank_frequent:{seeded['bank_id']}"
    assert response.get_json()["job"]["id"] == created.get_json()["job"]["id"]


def test_get_frequent_summary_includes_untranslated_terms(app):
    seeded = seed_bank_frequency(app)
    client = app.test_client()

    response = client.get(
        f"/api/vocab/frequent?bank_id={seeded['bank_id']}&page=1&per_page=20",
        headers=auth_headers(seeded["token"]),
    )

    assert response.status_code == 200
    assert response.get_json()["summary"]["untranslated_terms"] == 2
```

- [ ] **Step 4: 再跑一轮失败测试，确认失败原因仍聚焦于缺少实现而不是测试拼写**

Run: `pytest backend/tests/test_background_jobs_api.py -v`

Expected:
- FAIL，且失败集中在 jobs 系统缺失、`untranslated_terms` 字段缺失或权限/路由尚未接入

- [ ] **Step 5: 提交失败测试**

```bash
git add backend/tests/test_background_jobs_api.py
git commit -m "test: add failing background job api coverage"
```

### Task 2: 实现 `BackgroundJob` 模型、jobs 路由和未翻译计数接口

**Files:**
- Modify: `backend/models.py:1-225`
- Modify: `backend/app.py:1-111`
- Create: `backend/services/job_service.py`
- Create: `backend/routes/jobs.py`
- Modify: `backend/routes/vocab.py:209-340`
- Test: `backend/tests/test_background_jobs_api.py`

- [ ] **Step 1: 在 `models.py` 与 `app.py` 中加入最小 schema 支撑**

```python
class BackgroundJob(db.Model):
    __tablename__ = 'background_jobs'

    id = db.Column(db.Integer, primary_key=True)
    job_type = db.Column(db.String(64), nullable=False)
    scope_key = db.Column(db.String(255), nullable=False)
    active_scope_key = db.Column(db.String(255), nullable=True)
    payload_json = db.Column(db.Text, nullable=False, default='{}')
    status = db.Column(db.String(20), nullable=False, default='queued')
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    progress_total = db.Column(db.Integer, nullable=False, default=0)
    progress_done = db.Column(db.Integer, nullable=False, default=0)
    success_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
    status_message = db.Column(db.String(255), nullable=True)
    next_run_at = db.Column(db.DateTime, nullable=True)
    heartbeat_at = db.Column(db.DateTime, nullable=True)
    lease_until = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', backref=db.backref('background_jobs', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('active_scope_key', name='uq_background_jobs_active_scope_key'),
        db.Index('idx_background_jobs_status_next_run', 'status', 'next_run_at'),
        db.Index('idx_background_jobs_status_lease', 'status', 'lease_until'),
        db.Index('idx_background_jobs_type_created_at', 'job_type', 'created_at'),
    )
```

```python
from models import db, UserVocabProgress, UserBankWordProgress, BankWordExclusion, BackgroundJob


def _ensure_background_job_schema():
    inspector = inspect(db.engine)
    if 'background_jobs' not in inspector.get_table_names():
        BackgroundJob.__table__.create(bind=db.engine, checkfirst=True)


from routes.jobs import jobs_bp
app.register_blueprint(jobs_bp, url_prefix='/api/jobs')

with app.app_context():
    db.create_all()
    _ensure_background_job_schema()
```

- [ ] **Step 2: 新建 `job_service.py` 与 `routes/jobs.py`，打通创建/复用/查询逻辑**

```python
import json
from datetime import datetime, timezone

from models import BackgroundJob, BankWordFrequency, QuestionBank, User, Vocabulary, db

JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE = 'professional_vocab_translate'
JOB_TYPE_BANK_FREQUENT_TRANSLATE = 'bank_frequent_translate'
ACTIVE_STATUSES = {'queued', 'running'}


def utc_now():
    return datetime.now(timezone.utc)


def text_missing(value):
    return value is None or not str(value).strip()


def vocabulary_needs_translation(word):
    if text_missing(word.term_zh):
        return True
    if word.definition and text_missing(word.definition_zh):
        return True
    return False


def build_scope_key(job_type, payload):
    if job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return 'professional_vocab'
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return f"bank_frequent:{payload['bank_id']}"
    raise ValueError('不支持的任务类型')


def count_pending_items(job_type, payload):
    if job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return sum(
            1
            for word in Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term).all()
            if vocabulary_needs_translation(word)
        )
    bank_id = payload['bank_id']
    db.get_or_404(QuestionBank, bank_id)
    return BankWordFrequency.query.filter_by(bank_id=bank_id, term_zh=None).count()


def serialize_job(job):
    return {
        'id': job.id,
        'job_type': job.job_type,
        'scope_key': job.scope_key,
        'status': job.status,
        'attempt_count': job.attempt_count,
        'max_attempts': job.max_attempts,
        'progress_total': job.progress_total,
        'progress_done': job.progress_done,
        'success_count': job.success_count,
        'skipped_count': job.skipped_count,
        'last_error': job.last_error,
        'status_message': job.status_message,
        'payload': json.loads(job.payload_json or '{}'),
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
    }


def create_or_reuse_job(job_type, payload, created_by):
    scope_key = build_scope_key(job_type, payload)
    existing = BackgroundJob.query.filter_by(active_scope_key=scope_key).order_by(BackgroundJob.id.desc()).first()
    if existing:
        return 'existing', existing, '已有后台任务正在执行'

    pending_total = count_pending_items(job_type, payload)
    if pending_total <= 0:
        return 'no_work', None, '当前没有待翻译数据'

    job = BackgroundJob(
        job_type=job_type,
        scope_key=scope_key,
        active_scope_key=scope_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status='queued',
        progress_total=pending_total,
        status_message='等待后台 worker 执行',
        created_by=created_by,
    )
    db.session.add(job)
    db.session.commit()
    return 'created', job, '后台任务已创建'
```

```python
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import BackgroundJob, User, db
from services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
    build_scope_key,
    create_or_reuse_job,
    serialize_job,
)

jobs_bp = Blueprint('jobs', __name__)


def _require_admin():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, (jsonify({'error': '用户不存在，请重新登录'}), 401)
    if not user.is_admin:
        return None, (jsonify({'error': '仅管理员可操作'}), 403)
    return user, None


@jobs_bp.route('', methods=['POST'])
@jwt_required()
def create_job():
    user, error = _require_admin()
    if error:
        return error

    data = request.get_json() or {}
    job_type = data.get('job_type')
    payload = {}
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        payload['bank_id'] = data.get('bank_id')
    result, job, message = create_or_reuse_job(job_type, payload, user.id)
    status_code = 201 if result == 'created' else 200
    return jsonify({'result': result, 'job': serialize_job(job) if job else None, 'message': message}), status_code


@jobs_bp.route('/<int:job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    _user, error = _require_admin()
    if error:
        return error
    job = db.get_or_404(BackgroundJob, job_id)
    return jsonify({'job': serialize_job(job)})


@jobs_bp.route('/active', methods=['GET'])
@jwt_required()
def get_active_job():
    _user, error = _require_admin()
    if error:
        return error
    job_type = request.args.get('job_type')
    payload = {}
    if job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        payload['bank_id'] = request.args.get('bank_id', type=int)
    scope_key = build_scope_key(job_type, payload)
    job = BackgroundJob.query.filter_by(active_scope_key=scope_key).order_by(BackgroundJob.id.desc()).first()
    return jsonify({'job': serialize_job(job) if job else None})
```

- [ ] **Step 3: 在 `vocab.py` 补充通用“待翻译”判断和高频词 summary 计数字段**

```python
from services.job_service import text_missing, vocabulary_needs_translation


def word_needs_translation(word):
    return vocabulary_needs_translation(word)


@vocab_bp.route('/frequent', methods=['GET'])
@jwt_required()
def list_frequent():
    user, error = _require_current_user()
    if error:
        return error

    bank_id = request.args.get('bank_id', type=int)
    bank = db.session.get(QuestionBank, bank_id)
    if not bank:
        return jsonify({'error': '题库不存在'}), 404

    excluded_terms = _get_excluded_term_set(bank_id)
    progress_by_term = _get_bank_word_progress_map(user.id, bank_id)
    frequent_query = BankWordFrequency.query.filter_by(bank_id=bank_id)
    if excluded_terms:
        frequent_query = frequent_query.filter(~BankWordFrequency.term.in_(excluded_terms))

    top_terms = frequent_query.order_by(
        BankWordFrequency.frequency.desc(),
        BankWordFrequency.term.asc(),
    ).limit(TOP_FREQUENT_TERMS_LIMIT).all()

    total_terms = len(top_terms)
    untranslated_terms = sum(1 for item in top_terms if text_missing(item.term_zh))

    return jsonify({
        'bank': {'id': bank.id, 'name': bank.name},
        'summary': {
            'total_terms': total_terms,
            'untranslated_terms': untranslated_terms,
            'min_frequency': MIN_FREQUENCY,
            'top_terms_limit': TOP_FREQUENT_TERMS_LIMIT,
        },
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'total_items': total_terms,
        },
        'items': [
            {
                'term': item.term,
                'term_zh': item.term_zh,
                'frequency': item.frequency,
                'is_mastered': progress_by_term.get(item.term, False),
                'can_delete': bool(user and user.is_admin),
                'can_mark_mastered': True,
            }
            for item in items
        ],
    })
```

- [ ] **Step 4: 跑 API 定向测试，确认 jobs 路由与 summary 计数字段转绿**

Run: `pytest backend/tests/test_background_jobs_api.py -v`

Expected:
- PASS

- [ ] **Step 5: 提交 jobs API 实现**

```bash
git add backend/models.py backend/app.py backend/services/job_service.py backend/routes/jobs.py backend/routes/vocab.py backend/tests/test_background_jobs_api.py
git commit -m "feat: add background job api and schema"
```

### Task 3: 写 worker 成功、重试与 stale job 回收的失败测试

**Files:**
- Create: `backend/tests/test_background_job_worker.py`
- Test: `backend/tests/test_background_job_worker.py`

- [ ] **Step 1: 先写成功执行与 stale job 回收的失败测试**

```python
from datetime import timedelta
from pathlib import Path
import json
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import BackgroundJob, BankWordFrequency, QuestionBank, User, Vocabulary, db
from services.job_service import utc_now


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


def seed_professional_job(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash="x", is_admin=True)
        db.session.add_all([
            admin,
            Vocabulary(term="privacy", definition="privacy concept", is_system=True),
            Vocabulary(term="controller", definition="purpose decision", is_system=True),
        ])
        db.session.flush()
        job = BackgroundJob(
            job_type='professional_vocab_translate',
            scope_key='professional_vocab',
            active_scope_key='professional_vocab',
            payload_json='{}',
            status='queued',
            progress_total=2,
            created_by=admin.id,
        )
        db.session.add(job)
        db.session.commit()
        return {'job_id': job.id}


def test_process_one_job_completes_professional_vocab_job(app, monkeypatch):
    seeded = seed_professional_job(app)

    def fake_translate_professional_vocab_batch(batch):
        for word in batch:
            word.term_zh = f"中文-{word.term}"
            word.definition_zh = f"释义-{word.term}"
        db.session.commit()
        return len(batch), 0

    monkeypatch.setattr(
        'services.job_handlers.translate_professional_vocab_batch',
        fake_translate_professional_vocab_batch,
    )

    from workers.job_worker import process_one_job

    processed = process_one_job(app, worker_id='test-worker')

    assert processed is True
    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'completed'
        assert job.success_count == 2
        assert job.progress_done == 2
        assert job.active_scope_key is None


def test_recover_stale_jobs_requeues_running_job(app):
    with app.app_context():
        admin = User(username='admin2', email='admin2@test.com', password_hash='x', is_admin=True)
        db.session.add(admin)
        db.session.flush()
        job = BackgroundJob(
            job_type='professional_vocab_translate',
            scope_key='professional_vocab',
            active_scope_key='professional_vocab',
            payload_json='{}',
            status='running',
            attempt_count=1,
            created_by=admin.id,
            lease_until=utc_now() - timedelta(seconds=5),
            heartbeat_at=utc_now() - timedelta(seconds=5),
        )
        db.session.add(job)
        db.session.commit()

    from services.job_service import recover_stale_jobs

    recover_stale_jobs()

    with app.app_context():
        job = BackgroundJob.query.one()
        assert job.status == 'queued'
        assert job.active_scope_key == 'professional_vocab'
        assert job.attempt_count == 1
```

- [ ] **Step 2: 跑失败测试，确认当前缺的是 handler / worker / stale recovery**

Run: `pytest backend/tests/test_background_job_worker.py -k "process_one_job or recover_stale_jobs" -v`

Expected:
- FAIL，报错集中在 `services.job_handlers`、`workers.job_worker` 或 `recover_stale_jobs()` 未实现

- [ ] **Step 3: 补自动重试与高频词任务执行的失败测试**

```python
def seed_bank_frequency_job(app):
    with app.app_context():
        admin = User(username='bank-admin', email='bank-admin@test.com', password_hash='x', is_admin=True)
        bank = QuestionBank(name='freq-bank', description='worker-target')
        db.session.add_all([admin, bank])
        db.session.flush()
        db.session.add_all([
            BankWordFrequency(bank_id=bank.id, term='privacy', term_zh=None, frequency=8),
            BankWordFrequency(bank_id=bank.id, term='controller', term_zh=None, frequency=5),
        ])
        job = BackgroundJob(
            job_type='bank_frequent_translate',
            scope_key=f'bank_frequent:{bank.id}',
            active_scope_key=f'bank_frequent:{bank.id}',
            payload_json=json.dumps({'bank_id': bank.id}),
            status='queued',
            progress_total=2,
            created_by=admin.id,
        )
        db.session.add(job)
        db.session.commit()
        return {'job_id': job.id, 'bank_id': bank.id}


def test_process_one_job_requeues_failed_job_until_max_attempts(app, monkeypatch):
    seeded = seed_professional_job(app)

    monkeypatch.setattr(
        'services.job_handlers.translate_professional_vocab_batch',
        lambda batch: (_ for _ in ()).throw(RuntimeError('ai timeout')),
    )

    from workers.job_worker import process_one_job

    assert process_one_job(app, worker_id='test-worker') is True

    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'queued'
        assert job.attempt_count == 1
        assert job.last_error == 'ai timeout'
        assert job.active_scope_key == 'professional_vocab'

    assert process_one_job(app, worker_id='test-worker') is True
    assert process_one_job(app, worker_id='test-worker') is True

    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'failed'
        assert job.attempt_count == 3
        assert job.active_scope_key is None
        assert job.finished_at is not None


def test_process_one_job_completes_bank_frequency_job(app, monkeypatch):
    seeded = seed_bank_frequency_job(app)

    def fake_translate_bank_frequency_batch(batch):
        for row in batch:
            row.term_zh = f"中文-{row.term}"
        db.session.commit()
        return len(batch), 0

    monkeypatch.setattr(
        'services.job_handlers.translate_bank_frequency_batch',
        fake_translate_bank_frequency_batch,
    )

    from workers.job_worker import process_one_job

    assert process_one_job(app, worker_id='test-worker') is True
    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'completed'
        assert job.success_count == 2
        assert job.progress_done == 2
```

- [ ] **Step 4: 再跑一次失败测试，确认红灯来自真实缺口而不是测试自身问题**

Run: `pytest backend/tests/test_background_job_worker.py -v`

Expected:
- FAIL，且失败集中在 worker 执行、重试状态流转和 batch handler 缺失

- [ ] **Step 5: 提交失败测试**

```bash
git add backend/tests/test_background_job_worker.py
git commit -m "test: add failing background job worker coverage"
```

### Task 4: 实现 job handler、worker 循环与 worker 启动脚本

**Files:**
- Create: `backend/services/job_handlers.py`
- Create: `backend/workers/job_worker.py`
- Modify: `backend/services/job_service.py`
- Create: `scripts/start-worker.sh`
- Modify: `scripts/install-systemd-service.sh:1-44`
- Create: `deploy/systemd/quiz-app-worker.service`
- Test: `backend/tests/test_background_job_worker.py`

- [ ] **Step 1: 在 `job_handlers.py` 中实现两类任务的按批处理器**

```python
import json

from models import BackgroundJob, BankWordFrequency, Vocabulary, db
from services.ai_service import batch_translate_terms, batch_translate_vocab
from services.job_service import (
    JOB_TYPE_BANK_FREQUENT_TRANSLATE,
    JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE,
    heartbeat_job,
    serialize_job,
    text_missing,
    vocabulary_needs_translation,
)

PROFESSIONAL_BATCH_SIZE = 10
BANK_FREQUENT_BATCH_SIZE = 100


def translate_professional_vocab_batch(batch):
    translated = batch_translate_vocab(batch)
    return translated, 0


def translate_bank_frequency_batch(batch):
    translations = batch_translate_terms([
        {'id': index, 'term': row.term}
        for index, row in enumerate(batch, start=1)
    ])
    translated_map = {item['id']: item.get('term_zh') for item in translations}
    success_count = 0
    skipped_count = 0
    for index, row in enumerate(batch, start=1):
        translated = translated_map.get(index)
        if translated:
            row.term_zh = translated
            success_count += 1
        elif not text_missing(row.term_zh):
            skipped_count += 1
    db.session.commit()
    return success_count, skipped_count


def handle_professional_vocab_translate(job):
    while True:
        batch = [
            word
            for word in Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term).all()
            if vocabulary_needs_translation(word)
        ][:PROFESSIONAL_BATCH_SIZE]
        if not batch:
            return
        success_count, skipped_count = translate_professional_vocab_batch(batch)
        heartbeat_job(
            job,
            success_increment=success_count,
            skipped_increment=skipped_count,
            status_message=f'专业词汇翻译中，已处理 {job.progress_done + success_count + skipped_count}/{job.progress_total}',
        )


def handle_bank_frequent_translate(job):
    payload = json.loads(job.payload_json or '{}')
    bank_id = payload['bank_id']
    while True:
        batch = BankWordFrequency.query.filter_by(bank_id=bank_id, term_zh=None).order_by(
            BankWordFrequency.frequency.desc(),
            BankWordFrequency.term.asc(),
        ).limit(BANK_FREQUENT_BATCH_SIZE).all()
        if not batch:
            return
        success_count, skipped_count = translate_bank_frequency_batch(batch)
        heartbeat_job(
            job,
            success_increment=success_count,
            skipped_increment=skipped_count,
            status_message=f'高频词翻译中，已处理 {job.progress_done + success_count + skipped_count}/{job.progress_total}',
        )


def run_job(job):
    if job.job_type == JOB_TYPE_PROFESSIONAL_VOCAB_TRANSLATE:
        return handle_professional_vocab_translate(job)
    if job.job_type == JOB_TYPE_BANK_FREQUENT_TRANSLATE:
        return handle_bank_frequent_translate(job)
    raise ValueError(f'不支持的任务类型: {job.job_type}')
```

- [ ] **Step 2: 在 `job_service.py` 与 `job_worker.py` 中补齐 claim / retry / stale recovery / CLI**

```python
from datetime import timedelta

from models import BackgroundJob, db

LEASE_SECONDS = 60
RETRY_DELAY_SECONDS = 15


def claim_next_job(worker_id):
    now = utc_now()
    job = BackgroundJob.query.filter(
        BackgroundJob.status == 'queued',
        (BackgroundJob.next_run_at.is_(None) | (BackgroundJob.next_run_at <= now)),
    ).order_by(BackgroundJob.created_at.asc()).first()
    if not job:
        return None
    job.status = 'running'
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    job.status_message = f'worker {worker_id} 已接手任务'
    db.session.commit()
    return job


def heartbeat_job(job, success_increment=0, skipped_increment=0, status_message=None):
    now = utc_now()
    job.success_count += success_increment
    job.skipped_count += skipped_increment
    job.progress_done = job.success_count + job.skipped_count
    job.heartbeat_at = now
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    if status_message:
        job.status_message = status_message
    db.session.commit()


def complete_job(job, status_message='任务完成'):
    job.status = 'completed'
    job.active_scope_key = None
    job.finished_at = utc_now()
    job.lease_until = None
    job.heartbeat_at = utc_now()
    job.status_message = status_message
    db.session.commit()


def requeue_job(job, error_message):
    now = utc_now()
    if job.attempt_count >= job.max_attempts:
        return fail_job(job, error_message)
    job.status = 'queued'
    job.next_run_at = now + timedelta(seconds=RETRY_DELAY_SECONDS)
    job.last_error = error_message
    job.status_message = f'第 {job.attempt_count}/{job.max_attempts} 次执行失败，15 秒后自动重试'
    job.lease_until = None
    db.session.commit()


def fail_job(job, error_message):
    job.status = 'failed'
    job.active_scope_key = None
    job.last_error = error_message
    job.finished_at = utc_now()
    job.lease_until = None
    job.status_message = '任务已自动执行 3 次仍失败'
    db.session.commit()


def recover_stale_jobs():
    now = utc_now()
    jobs = BackgroundJob.query.filter(
        BackgroundJob.status == 'running',
        BackgroundJob.lease_until.is_not(None),
        BackgroundJob.lease_until < now,
    ).all()
    for job in jobs:
        job.status = 'queued'
        job.status_message = '检测到 worker 中断，任务已重新排队'
        job.lease_until = None
    if jobs:
        db.session.commit()
```

```python
import argparse
import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / 'backend'))

from app import create_app
from services.job_handlers import run_job
from services.job_service import claim_next_job, complete_job, recover_stale_jobs, requeue_job


def process_one_job(app, worker_id='job-worker'):
    with app.app_context():
        recover_stale_jobs()
        job = claim_next_job(worker_id)
        if not job:
            return False
        try:
            run_job(job)
            complete_job(job)
        except Exception as exc:
            requeue_job(job, str(exc))
        return True


def main(poll_interval=2, worker_id='job-worker'):
    app = create_app()
    while True:
        processed = process_one_job(app, worker_id=worker_id)
        if not processed:
            time.sleep(poll_interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--worker-id', default='job-worker')
    args = parser.parse_args()
    app = create_app()
    if args.once:
        process_one_job(app, worker_id=args.worker_id)
    else:
        main(worker_id=args.worker_id)
```

- [ ] **Step 3: 新增 worker 启动脚本与 systemd 安装逻辑**

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"

ensure_python() {
  if [[ -x "${PYTHON_BIN}" ]] && "${PYTHON_BIN}" -c 'import flask, sqlalchemy' >/dev/null 2>&1; then
    return 0
  fi
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import flask, sqlalchemy' >/dev/null 2>&1; then
    PYTHON_BIN="python3"
    return 0
  fi
  echo "未找到可用的 Python 运行环境。请先安装 backend/requirements.txt 中的依赖。"
  exit 1
}

main() {
  cd "${ROOT_DIR}"
  ensure_python
  export PYTHONUNBUFFERED=1
  exec "${PYTHON_BIN}" "${ROOT_DIR}/backend/workers/job_worker.py" "$@"
}

main "$@"
```

```bash
WORKER_SERVICE_NAME="${SERVICE_NAME}-worker"
WORKER_SERVICE_FILE="/etc/systemd/system/${WORKER_SERVICE_NAME}.service"

cat >"${WORKER_SERVICE_FILE}" <<EOF_WORKER
[Unit]
Description=CIPT Quiz App Worker
After=network-online.target ${SERVICE_NAME}.service
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${ROOT_DIR}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${ROOT_DIR}/.env
ExecStart=${ROOT_DIR}/scripts/start-worker.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF_WORKER

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"
systemctl enable --now "${WORKER_SERVICE_NAME}.service"
```

```ini
[Unit]
Description=CIPT Quiz App Worker
After=network-online.target quiz-app.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/github/quiz-app
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/home/ubuntu/github/quiz-app/.env
ExecStart=/home/ubuntu/github/quiz-app/scripts/start-worker.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: 跑 worker 定向测试与单轮 smoke 命令**

Run: `pytest backend/tests/test_background_job_worker.py -v`

Run: `python3 backend/workers/job_worker.py --once --worker-id smoke-test`

Expected:
- Pytest PASS
- `--once` 命令直接退出，退出码 0；若当前无任务，不输出错误

- [ ] **Step 5: 提交 worker 实现**

```bash
git add backend/services/job_handlers.py backend/workers/job_worker.py backend/services/job_service.py scripts/start-worker.sh scripts/install-systemd-service.sh deploy/systemd/quiz-app-worker.service backend/tests/test_background_job_worker.py
git commit -m "feat: add background job worker runtime"
```

### Task 5: 用 composable 改造 `VocabularyView.vue` 的后台任务交互

**Files:**
- Create: `frontend/src/composables/useBackgroundJob.js`
- Modify: `frontend/src/views/VocabularyView.vue:30-50,460-894`
- Test: `backend/tests/test_background_jobs_api.py`

- [ ] **Step 1: 新建 `useBackgroundJob.js`，封装创建、恢复、轮询、停止轮询**

```javascript
import { onUnmounted, ref } from 'vue'
import client from '../api/client'

export function useBackgroundJob() {
  const job = ref(null)
  const polling = ref(false)
  let timerId = null

  function stopPolling() {
    if (timerId) {
      clearTimeout(timerId)
      timerId = null
    }
    polling.value = false
  }

  async function fetchJob(jobId) {
    const res = await client.get(`/jobs/${jobId}`)
    job.value = res.data.job
    return job.value
  }

  function startPolling(jobId, { onFinished } = {}) {
    stopPolling()
    polling.value = true

    const tick = async () => {
      const current = await fetchJob(jobId)
      if (!current || ['completed', 'failed'].includes(current.status)) {
        polling.value = false
        if (onFinished) await onFinished(current)
        return
      }
      timerId = window.setTimeout(tick, 2000)
    }

    tick()
  }

  async function createJob(payload, options = {}) {
    const res = await client.post('/jobs', payload)
    job.value = res.data.job
    if (job.value && ['queued', 'running'].includes(job.value.status)) {
      startPolling(job.value.id, options)
    }
    return res.data
  }

  async function restoreActiveJob(params, options = {}) {
    const query = new URLSearchParams(params).toString()
    const res = await client.get(`/jobs/active?${query}`)
    job.value = res.data.job
    if (job.value && ['queued', 'running'].includes(job.value.status)) {
      startPolling(job.value.id, options)
    }
    return job.value
  }

  onUnmounted(stopPolling)

  return {
    job,
    polling,
    createJob,
    restoreActiveJob,
    stopPolling,
  }
}
```

- [ ] **Step 2: 在 `VocabularyView.vue` 中替换专业词汇按钮和状态提示**

```javascript
import { useBackgroundJob } from '../composables/useBackgroundJob'

const professionalJobState = useBackgroundJob()
const professionalJob = professionalJobState.job
const frequentJobState = useBackgroundJob()
const frequentJob = frequentJobState.job

function wordNeedsTranslation(word) {
  if (!word.term_zh?.trim()) return true
  if (word.definition?.trim() && !word.definition_zh?.trim()) return true
  return false
}

async function batchTranslate() {
  try {
    const result = await professionalJobState.createJob(
      { job_type: 'professional_vocab_translate' },
      {
        onFinished: async (job) => {
          await fetchProfessional()
          await refreshProfessionalTranslationCount()
          if (job?.status === 'completed') {
            toast.success('任务完成，已自动刷新未翻译数量')
          } else if (job?.status === 'failed') {
            toast.error(job.last_error || '任务已自动执行 3 次仍失败，可重新点击继续翻译剩余未翻译内容')
          }
        },
      },
    )

    if (result.result === 'no_work') {
      toast.success(result.message)
      return
    }
    if (result.result === 'created') {
      toast.success('后台异步翻译已启动，刷新页面不会中断')
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '创建后台翻译任务失败')
  }
}
```

```vue
<BaseButton v-if="isAdmin && professionalUntranslatedCount > 0" @click="batchTranslate" :disabled="professionalJob && ['queued', 'running'].includes(professionalJob.status)" size="sm">
  {{ professionalJob && ['queued', 'running'].includes(professionalJob.status) ? '后台执行中...' : `批量翻译（${professionalUntranslatedCount}）` }}
</BaseButton>

<div v-if="professionalJob && ['queued', 'running', 'failed'].includes(professionalJob.status)" class="mb-4 rounded-card bg-teal-50 dark:bg-teal-900/20 px-4 py-3 text-sm text-teal-700 dark:text-teal-300">
  <div class="font-medium">后台异步翻译，刷新页面不会中断</div>
  <div class="mt-1">{{ professionalJob.status_message || '任务正在后台执行，可离开页面后稍后回来查看' }}</div>
  <div class="mt-1">已处理 {{ professionalJob.progress_done }} / {{ professionalJob.progress_total }}，第 {{ professionalJob.attempt_count || 0 }} / {{ professionalJob.max_attempts }} 次</div>
</div>
```

- [ ] **Step 3: 在同一个页面接入高频词任务恢复、summary 计数和状态提示**

```javascript
const frequentUntranslatedCount = ref(0)

async function fetchFrequent() {
  if (!selectedBankId.value) {
    frequentWords.value = []
    frequentTotal.value = 0
    frequentTotalPages.value = 1
    frequentUntranslatedCount.value = 0
    return
  }

  const res = await client.get('/vocab/frequent', {
    params: {
      bank_id: selectedBankId.value,
      page: frequentPage.value,
      per_page: frequentPerPage.value,
      ...buildMasteredFilterParams(frequentMasteredFilter.value),
    },
  })
  frequentWords.value = res.data.items || []
  frequentTotal.value = res.data.summary?.total_terms || 0
  frequentUntranslatedCount.value = res.data.summary?.untranslated_terms || 0
  frequentTotalPages.value = res.data.pagination?.total_pages || 1
}

async function batchTranslateFrequent() {
  if (!selectedBankId.value) return

  try {
    const result = await frequentJobState.createJob(
      { job_type: 'bank_frequent_translate', bank_id: selectedBankId.value },
      {
        onFinished: async (job) => {
          await fetchFrequent()
          if (job?.status === 'completed') {
            toast.success('任务完成，已自动刷新未翻译数量')
          } else if (job?.status === 'failed') {
            toast.error(job.last_error || '任务已自动执行 3 次仍失败，可重新点击继续翻译剩余未翻译内容')
          }
        },
      },
    )
    if (result.result === 'created') {
      toast.success('高频词后台翻译已启动，刷新页面不会中断')
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '创建高频词后台任务失败')
  }
}

watch(selectedBankId, async () => {
  if (!selectedBankId.value) return
  await fetchFrequent()
  await frequentJobState.restoreActiveJob(
    { job_type: 'bank_frequent_translate', bank_id: selectedBankId.value },
    { onFinished: fetchFrequent },
  )
})

onMounted(async () => {
  await fetchBanks()
  await fetchProfessional()
  await refreshProfessionalTranslationCount()
  await professionalJobState.restoreActiveJob(
    { job_type: 'professional_vocab_translate' },
    { onFinished: async () => {
      await fetchProfessional()
      await refreshProfessionalTranslationCount()
    } },
  )
})
```

```vue
<BaseButton
  v-if="isAdmin && selectedBankId && frequentUntranslatedCount > 0"
  size="sm"
  :disabled="frequentJob && ['queued', 'running'].includes(frequentJob.status)"
  @click="batchTranslateFrequent"
>
  {{ frequentJob && ['queued', 'running'].includes(frequentJob.status) ? '后台执行中...' : `批量翻译（${frequentUntranslatedCount}）` }}
</BaseButton>

<div v-if="frequentJob && ['queued', 'running', 'failed'].includes(frequentJob.status)" class="mb-4 rounded-card bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
  <div class="font-medium">后台异步翻译，刷新页面不会中断</div>
  <div class="mt-1">{{ frequentJob.status_message || '任务正在后台执行，可离开页面后稍后回来查看' }}</div>
  <div class="mt-1">已处理 {{ frequentJob.progress_done }} / {{ frequentJob.progress_total }}，第 {{ frequentJob.attempt_count || 0 }} / {{ frequentJob.max_attempts }} 次</div>
</div>
```

- [ ] **Step 4: 跑前端构建并做页面级手工验证**

Run: `npm --prefix frontend run build`

Manual verification:
- 专业词汇点击“批量翻译”后立即出现“后台异步翻译，刷新页面不会中断”提示
- 刷新页面后，专业词汇任务状态可自动恢复
- 高频词切换题库后能恢复当前 `bank_id` 的活动任务
- 任务失败时能看到“任务已自动执行 3 次仍失败，可重新点击继续翻译剩余未翻译内容”文案

Expected:
- Vite build PASS
- 手工路径里不再出现浏览器自己 `while (true)` 连续发请求

- [ ] **Step 5: 提交 `VocabularyView` 改造**

```bash
git add frontend/src/composables/useBackgroundJob.js frontend/src/views/VocabularyView.vue
git commit -m "feat: move vocabulary translation to background jobs"
```

### Task 6: 改造导入后自动翻译、补充 README 并完成最终验证

**Files:**
- Modify: `frontend/src/components/FileUpload.vue:1-97`
- Modify: `frontend/src/views/AdminBanksView.vue:86-188`
- Modify: `README.md:58-127,129-177`
- Test: `backend/tests/test_background_jobs_api.py`
- Test: `backend/tests/test_background_job_worker.py`

- [ ] **Step 1: 在 `FileUpload.vue` 中改为“导入成功后创建后台高频词任务”**

```javascript
import { useBackgroundJob } from '../composables/useBackgroundJob'

const frequencyJobState = useBackgroundJob()
const frequencyJob = frequencyJobState.job

async function uploadFile(file) {
  uploading.value = true
  result.value = null
  const formData = new FormData()
  formData.append('file', file)

  try {
    const res = await client.post(`/banks/${props.bankId}/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })

    result.value = { message: res.data.message || '上传成功' }
    emit('imported', res.data)

    if (res.data.frequency_count > 0) {
      await frequencyJobState.createJob(
        { job_type: 'bank_frequent_translate', bank_id: props.bankId },
        {
          onFinished: async (job) => {
            if (job?.status === 'completed') {
              toast.success('高频词后台翻译完成')
            } else if (job?.status === 'failed') {
              toast.error(job.last_error || '高频词后台翻译已自动执行 3 次仍失败')
            }
          },
        },
      )
      result.value = {
        message: '题目导入成功，高频词翻译已转入后台执行，刷新页面不会中断。',
      }
    } else {
      toast.success(res.data.message || '上传成功')
    }
  } catch (e) {
    result.value = { error: e.response?.data?.error || '上传失败' }
    toast.error(result.value.error)
  } finally {
    uploading.value = false
  }
}
```

```vue
<div v-if="frequencyJob && ['queued', 'running', 'failed'].includes(frequencyJob.status)" class="mt-4 text-sm text-primary-600 dark:text-primary-400">
  后台异步翻译中：{{ frequencyJob.progress_done }} / {{ frequencyJob.progress_total }}
  <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ frequencyJob.status_message || '任务正在后台执行，可离开页面后稍后回来查看' }}</div>
</div>
```

- [ ] **Step 2: 调整 `AdminBanksView.vue`，不要在导入后立刻把 modal 关掉**

```javascript
function handleImported(payload) {
  toast.success(payload?.message || '题目导入成功')
  fetchBanks()
}
```

```vue
<BaseModal :open="showImport" title="导入题目" maxWidth="lg" @close="showImport = false">
  <FileUpload :bank-id="selectedBankId" @imported="handleImported" />
  <template #actions>
    <BaseButton variant="secondary" @click="showImport = false">关闭</BaseButton>
  </template>
</BaseModal>
```

- [ ] **Step 3: 在 `README.md` 增补 worker 启动与后台任务说明**

````md
### 3. 启动后端

```bash
pip install -r backend/requirements.txt
python run.py
```

### 4. 启动后台任务 worker

```bash
bash scripts/start-worker.sh
```

后台任务 worker 负责执行批量翻译等异步任务。页面刷新不会中断任务，失败会自动重试 3 次。
````

````md
常用管理命令：

```bash
sudo systemctl status quiz-app
sudo systemctl status quiz-app-worker
sudo systemctl restart quiz-app
sudo systemctl restart quiz-app-worker
sudo journalctl -u quiz-app -f
sudo journalctl -u quiz-app-worker -f
```
````

- [ ] **Step 4: 跑最终定向验证并补手工回归**

Run: `pytest backend/tests/test_background_jobs_api.py backend/tests/test_background_job_worker.py -v`

Run: `npm --prefix frontend run build`

Manual verification:
- 专业词汇后台任务：创建任务 → 刷新页面 → 任务状态恢复 → 成功后计数更新
- 高频词后台任务：选择题库 → 创建任务 → 刷新页面 → 状态恢复
- 导入题目后自动创建高频词后台任务，modal 内能看到“后台异步翻译”说明
- 任务连续失败 3 次后变成终态，按钮可再次点击，且只继续剩余未翻译数据
- systemd 安装脚本执行后，同时启用 `quiz-app.service` 和 `quiz-app-worker.service`

Expected:
- 两个新 pytest 文件 PASS
- `npm --prefix frontend run build` PASS
- 手工路径中不存在前端 `while (true)` 连续打批量翻译接口的行为

- [ ] **Step 5: 提交导入流与文档更新**

```bash
git add frontend/src/components/FileUpload.vue frontend/src/views/AdminBanksView.vue README.md
git commit -m "feat: wire import flow into background translation jobs"
```
