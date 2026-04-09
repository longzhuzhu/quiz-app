from datetime import timedelta, timezone
from pathlib import Path
import json
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import BackgroundJob, BankWordFrequency, QuestionBank, User, Vocabulary, db
import services.job_service as job_service


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


def test_process_one_job_completes_professional_vocab_job(app, monkeypatch):
    seeded = seed_professional_job(app)

    def fake_translate_professional_vocab_batch(batch):
        for word in batch:
            word.term_zh = f"中文-{word.term}"
            word.definition_zh = f"释义-{word.term}"
        db.session.commit()
        return len(batch), 0

    from workers.job_worker import process_one_job

    monkeypatch.setattr(
        'services.job_handlers.translate_professional_vocab_batch',
        fake_translate_professional_vocab_batch,
    )

    processed = process_one_job(app, worker_id='test-worker')

    assert processed is True
    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'completed'
        assert job.success_count == 2
        assert job.progress_done == 2
        assert job.active_scope_key is None
        privacy = Vocabulary.query.filter_by(term='privacy', is_system=True).one()
        controller = Vocabulary.query.filter_by(term='controller', is_system=True).one()
        assert privacy.term_zh == '中文-privacy'
        assert privacy.definition_zh == '释义-privacy'
        assert controller.term_zh == '中文-controller'
        assert controller.definition_zh == '释义-controller'


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
            lease_until=job_service.utc_now() - timedelta(seconds=5),
            heartbeat_at=job_service.utc_now() - timedelta(seconds=5),
        )
        db.session.add(job)
        db.session.commit()

        job_service.recover_stale_jobs()

    with app.app_context():
        job = BackgroundJob.query.one()
        assert job.status == 'queued'
        assert job.active_scope_key == 'professional_vocab'
        assert job.attempt_count == 1
        assert job.lease_until is None


def normalized_to_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def test_process_one_job_requeues_failed_job_until_max_attempts(app, monkeypatch):
    seeded = seed_professional_job(app)

    from workers.job_worker import process_one_job

    monkeypatch.setattr(
        'services.job_handlers.translate_professional_vocab_batch',
        lambda batch: (_ for _ in ()).throw(RuntimeError('ai timeout')),
    )

    assert process_one_job(app, worker_id='test-worker') is True

    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'queued'
        assert job.attempt_count == 1
        assert job.last_error == 'ai timeout'
        assert job.active_scope_key == 'professional_vocab'
        assert job.next_run_at is not None
        assert normalized_to_utc(job.next_run_at) > normalized_to_utc(job_service.utc_now())
        job.next_run_at = job_service.utc_now() - timedelta(seconds=1)
        db.session.commit()

    assert process_one_job(app, worker_id='test-worker') is True
    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.attempt_count == 2
        assert job.next_run_at is not None
        assert normalized_to_utc(job.next_run_at) > normalized_to_utc(job_service.utc_now())
        job.next_run_at = job_service.utc_now() - timedelta(seconds=1)
        db.session.commit()

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
        assert job.active_scope_key is None
        rows = BankWordFrequency.query.filter_by(bank_id=seeded['bank_id']).order_by(BankWordFrequency.term).all()
        assert len(rows) == 2
        for row in rows:
            assert row.term_zh == f"中文-{row.term}"


def test_translate_professional_vocab_batch_partial_translation_returns_no_completed_items(app, monkeypatch):
    with app.app_context():
        words = Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term.asc()).all()
        if not words:
            seed_professional_job(app)
            words = Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term.asc()).all()

        def fake_batch_translate_vocab(batch):
            for word in batch:
                word.term_zh = f"中文-{word.term}"
            db.session.commit()
            return len(batch)

        monkeypatch.setattr('services.job_handlers.batch_translate_vocab', fake_batch_translate_vocab)

        from services.job_handlers import translate_professional_vocab_batch

        success_count, skipped_count = translate_professional_vocab_batch(words)

        assert success_count == 0
        assert skipped_count == 0
        for word in Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term.asc()).all():
            assert word.term_zh == f"中文-{word.term}"
            assert word.definition_zh is None
            assert job_service.vocabulary_needs_translation(word) is True


def test_process_one_job_partial_professional_translation_requeues_on_no_progress(app, monkeypatch):
    seeded = seed_professional_job(app)

    def fake_partial_translate(batch):
        for word in batch:
            word.term_zh = f"中文-{word.term}"
        db.session.commit()
        return 0, 0

    from workers.job_worker import process_one_job

    monkeypatch.setattr(
        'services.job_handlers.translate_professional_vocab_batch',
        fake_partial_translate,
    )

    assert process_one_job(app, worker_id='test-worker') is True

    with app.app_context():
        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'queued'
        assert job.success_count == 0
        assert job.progress_done == 0
        assert job.last_error == '专业词汇批量翻译未产生进展'
        assert job.active_scope_key == 'professional_vocab'
        words = Vocabulary.query.filter(Vocabulary.is_system.is_(True)).order_by(Vocabulary.term.asc()).all()
        assert len(words) == 2
        for word in words:
            assert word.term_zh == f"中文-{word.term}"
            assert word.definition_zh is None
            assert job_service.vocabulary_needs_translation(word) is True


def test_try_claim_job_is_atomic_for_same_job(app):
    seeded = seed_professional_job(app)

    with app.app_context():
        claimed_once = job_service.try_claim_job_by_id(seeded['job_id'], worker_id='worker-a')
        claimed_twice = job_service.try_claim_job_by_id(seeded['job_id'], worker_id='worker-b')

        assert claimed_once is not None
        assert claimed_once.id == seeded['job_id']
        assert claimed_once.status == 'running'
        assert claimed_once.attempt_count == 1
        assert claimed_twice is None

        job = db.session.get(BackgroundJob, seeded['job_id'])
        assert job.status == 'running'
        assert job.attempt_count == 1
        assert job.status_message == 'worker worker-a 已接手任务'


def test_run_worker_processes_multiple_jobs_with_configured_concurrency(app, monkeypatch):
    professional = seed_professional_job(app)
    bank = seed_bank_frequency_job(app)
    processed_ids = []

    def fake_run_job(job):
        processed_ids.append(job.id)
        job_service.heartbeat_job(job, success_increment=job.progress_total)

    monkeypatch.setattr('workers.job_worker.run_job', fake_run_job)

    from workers.job_worker import run_worker

    run_worker(app, worker_id='test-worker', once=True, concurrency=2)

    with app.app_context():
        jobs = {
            job.id: db.session.get(BackgroundJob, job.id)
            for job in BackgroundJob.query.order_by(BackgroundJob.id).all()
        }

    assert sorted(processed_ids) == sorted([professional['job_id'], bank['job_id']])
    assert jobs[professional['job_id']].status == 'completed'
    assert jobs[bank['job_id']].status == 'completed'
