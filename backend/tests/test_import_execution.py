"""真实 PostgreSQL 的导入 writer 协调、失租与 worker finally 回归。"""
from datetime import datetime, timedelta, timezone
import json
import threading

import pytest
from sqlalchemy import update

from app.models.background_job import BackgroundJob
from app.models.import_chunk import ImportChunk
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.import_review_item import ImportReviewItem
from app.services import job_service, smart_import_service as svc
from app.services.import_execution import (
    ImportBusy, LeaseLost, acquire_import_lock, execution_for,
    release_import_execution, release_import_lock, review_writer,
)
from app.workers import job_worker
from test_smart_import_retry_idempotency import case, sessions, counts  # noqa: F401


def complete_release(db, bg):
    job_service.complete_job(db, bg)
    release_import_execution(db, bg)


def queued_for_worker(db, bg):
    job_id = bg.id
    job_service.requeue_job(db, bg, "prepare worker", delay_seconds=0)
    release_import_execution(db, bg)
    db.rollback()
    return job_id


def worker_for(monkeypatch, sessions, job_id, captured):
    monkeypatch.setattr(job_worker, "SessionLocal", sessions)
    monkeypatch.setattr(job_service, "claim_next_job", lambda db, worker_id: job_service.try_claim_job_by_id(db, job_id, worker_id))
    real_run = job_worker.run_job
    def record(db, bg):
        captured.append((execution_for(db), db))
        return real_run(db, bg)
    monkeypatch.setattr(job_worker, "run_job", record)


def assert_closed(captured):
    execution, db = captured[0]
    assert execution.connection.closed
    assert not execution.thread.is_alive()
    assert execution_for(db) is None


@pytest.mark.parametrize("failure", ["none", "response", "finalization", "lost"])
def test_import_execution_worker_terminal_and_finally(case, sessions, monkeypatch, failure):
    db, bg, job, model = case
    job_id = queued_for_worker(db, bg)
    captured = []
    worker_for(monkeypatch, sessions, job_id, captured)
    if failure == "response":
        monkeypatch.setattr(svc, "_persist_chunk_questions", lambda *_, **__: (_ for _ in ()).throw(RuntimeError("after response")))
    elif failure == "finalization":
        monkeypatch.setattr(svc, "_write_reconciliation", lambda *_: (_ for _ in ()).throw(RuntimeError("finalization")))
    elif failure == "lost":
        def lose(*_, **__):
            captured[0][0].connection.invalidate()
            return model.return_value
        monkeypatch.setattr(svc, "call_ai_api", lose)
    assert job_worker.process_one_job("real-worker") is True
    assert_closed(captured)
    assert sessions.kw["bind"].pool.checkedout() == 0
    db.expire_all()
    current = db.get(BackgroundJob, job_id)
    assert current.attempt_count == 2
    assert current.status == {"none": "completed", "response": "queued", "finalization": "queued", "lost": "running"}[failure]
    assert counts(db, job) == {"none": (1, 2, 2), "response": (1, 0, 0), "finalization": (1, 2, 2), "lost": (1, 0, 0)}[failure]


def test_import_execution_main_reparse_review_compete_without_spending_attempt(case, sessions, monkeypatch):
    db, bg, job, model = case
    job_id = queued_for_worker(db, bg)
    import_id, bank_id, user_id = job.id, job.bank_id, bg.created_by
    entered, finish = threading.Event(), threading.Event()
    captured, errors = [], []
    worker_for(monkeypatch, sessions, job_id, captured)
    def block(*_, **__):
        entered.set()
        assert finish.wait(10), "模型桩未收到释放事件"
        return model.return_value
    monkeypatch.setattr(svc, "call_ai_api", block)
    def run():
        try:
            job_worker.process_one_job("main-worker")
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(10)
        with sessions() as other:
            chunk_id = other.query(ImportChunk.id).filter_by(import_job_id=import_id).scalar()
            requested = svc.create_reparse_job(other, import_id, chunk_id, user_id)
            reparse_id = requested["background_job_id"]
            assert job_service.try_claim_job_by_id(other, reparse_id, "competing") is None
            other.expire_all()
            assert other.get(BackgroundJob, reparse_id).attempt_count == 0
            assert other.get(BackgroundJob, job_id).attempt_count == 2
            assert svc.accept_review_item(other, import_id, 999, user_id)["status_code"] == 409
            assert svc.skip_review_item(other, import_id, 999, user_id)["status_code"] == 409
            with pytest.raises(ImportBusy):
                with review_writer(other, import_id):
                    pass
            # 主请求也不能被再次 claim。
            assert job_service.try_claim_job_by_id(other, job_id, "competing-main") is None
    finally:
        finish.set()
        thread.join(10)
    assert not thread.is_alive() and not errors
    assert_closed(captured)
    with sessions() as other:
        reparse = job_service.try_claim_job_by_id(other, reparse_id, "reparse")
        assert reparse.attempt_count == 1
        release_import_execution(other, reparse)


@pytest.mark.parametrize("operation", ["heartbeat", "complete", "requeue", "business"])
def test_import_execution_old_token_cannot_touch_new_attempt(case, sessions, operation):
    db, bg, job, _ = case
    old = execution_for(db)
    old_token = old.token
    job_id, import_id = bg.id, job.id
    old.stop.set()
    old.thread.join()
    old.connection.invalidate()
    db.rollback()
    with sessions() as successor:
        successor.execute(update(BackgroundJob).where(BackgroundJob.id == job_id).values(
            lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        successor.commit()
        assert job_service.recover_stale_jobs(successor) == 1
        newer = job_service.try_claim_job_by_id(successor, job_id, "successor")
        new_execution = execution_for(successor)
        db.refresh(bg)  # ORM attempt 已刷新，旧上下文 token 必须不变。
        assert bg.attempt_count == old_token.attempt_count + 1
        assert old.token == old_token
        with pytest.raises(LeaseLost):
            if operation == "business":
                job.error_message = "old writer"
                svc.commit_import(db)
            elif operation == "requeue":
                job_service.requeue_job(db, bg, "old writer", execution=old)
            elif operation == "complete":
                job_service.complete_job(db, bg, execution=old)
            else:
                job_service.heartbeat_job(db, bg, execution=old)
        db.rollback()
        successor.refresh(newer)
        assert newer.status == "running" and newer.attempt_count == new_execution.token.attempt_count
        successor.refresh(successor.get(type(job), import_id))
        assert successor.get(type(job), import_id).error_message != "old writer"
        release_import_execution(successor, newer)


def test_import_execution_model_late_return_does_not_complete_or_requeue_successor(case, sessions, monkeypatch):
    db, bg, job, model = case
    job_id = queued_for_worker(db, bg)
    entered, finish = threading.Event(), threading.Event()
    captured, errors = [], []
    worker_for(monkeypatch, sessions, job_id, captured)
    def model_call(*_, **__):
        if not entered.is_set():
            entered.set()
            assert finish.wait(10)
        return model.return_value
    monkeypatch.setattr(svc, "call_ai_api", model_call)
    def run():
        try:
            job_worker.process_one_job("old-worker")
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    successor_execution = None
    try:
        assert entered.wait(10)
        old = captured[0][0]
        old.stop.set()
        old.thread.join()
        old.connection.invalidate()
        with sessions() as successor:
            successor.execute(update(BackgroundJob).where(BackgroundJob.id == job_id).values(
                lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
            successor.commit()
            job_service.recover_stale_jobs(successor)
            newer = job_service.try_claim_job_by_id(successor, job_id, "new-worker")
            successor_execution = execution_for(successor)
            assert newer.attempt_count == 3
            svc.run_smart_import(successor, newer)
            job_service.complete_job(successor, newer)
            release_import_execution(successor, newer)
        finish.set()
        thread.join(10)
        assert not thread.is_alive() and not errors
        assert_closed(captured)
        db.expire_all()
        assert db.get(BackgroundJob, job_id).status == "completed"
        assert counts(db, job) == (1, 2, 2)
    finally:
        finish.set()
        thread.join(10)
        if successor_execution is not None and not successor_execution.connection.closed:
            successor_execution.close()


def test_import_execution_renewal_is_independent_and_token_conditional(case, sessions):
    db, bg, _, _ = case
    execution = execution_for(db)
    before = bg.lease_until
    db.rollback()
    execution.renew_once()
    db.refresh(bg)
    assert bg.lease_until >= before
    execution.stop.set()
    execution.thread.join()
    db.rollback()
    with sessions() as other:
        other.execute(update(BackgroundJob).where(BackgroundJob.id == bg.id).values(attempt_count=bg.attempt_count + 1))
        other.commit()
    with pytest.raises(LeaseLost):
        execution.renew_once()


def test_import_execution_lock_connection_loss_fences_all_commits(case):
    db, bg, job, _ = case
    execution = execution_for(db)
    execution.connection.invalidate()
    job.error_message = "must not persist"
    with pytest.raises(LeaseLost):
        svc.commit_import(db)
    db.rollback()
    assert job.error_message is None


def test_import_execution_manual_review_lock_fences_after_connection_loss(case):
    db, bg, job, _ = case
    complete_release(db, bg)
    with pytest.raises(LeaseLost):
        with review_writer(db, job.id):
            db.info["import_review_lock"][0].invalidate()
            job.error_message = "must not persist"
            svc.commit_import(db)
    assert job.error_message is None


def test_import_execution_worker_cancellation_releases_thread_and_lock(case, sessions, monkeypatch):
    db, bg, _, _ = case
    job_id = queued_for_worker(db, bg)
    captured = []
    worker_for(monkeypatch, sessions, job_id, captured)
    def cancel(db, _bg):
        captured.append((execution_for(db), db))
        raise KeyboardInterrupt("cancelled")
    monkeypatch.setattr(job_worker, "run_job", cancel)
    with pytest.raises(KeyboardInterrupt, match="cancelled"):
        job_worker.process_one_job("cancelled-worker")
    assert_closed(captured)


@pytest.mark.parametrize("location", ["l1", "l2", "fallback_heartbeat"])
def test_import_execution_lease_lost_crosses_all_retry_catches(case, monkeypatch, location):
    import httpx
    db, bg, job, _ = case
    if location == "l1":
        monkeypatch.setattr(svc, "call_ai_api", lambda *_, **__: (_ for _ in ()).throw(LeaseLost("l1 lost")))
    else:
        monkeypatch.setattr(svc, "_call_llm_with_l1_retry", lambda *_, **__: (_ for _ in ()).throw(httpx.TimeoutException("use fallback")))
        if location == "l2":
            monkeypatch.setattr(svc, "call_ai_api", lambda *_, **__: (_ for _ in ()).throw(LeaseLost("l2 lost")))
        else:
            monkeypatch.setattr(svc, "HEARTBEAT_EVERY_N_SEGMENTS", 1)
            monkeypatch.setattr(svc, "heartbeat_job", lambda *_, **__: (_ for _ in ()).throw(LeaseLost("heartbeat lost")))
    with pytest.raises(LeaseLost):
        svc.run_smart_import(db, bg)
    db.rollback()
    assert counts(db, job) == (1, 0, 0)
    assert job.failed_chunks == 0


def test_import_execution_reparse_payload_ownership_and_failed_claim_cleanup(case, sessions):
    db, bg, job, _ = case
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    owner = bg.created_by
    complete_release(db, bg)
    malicious = BackgroundJob(job_type="question_import_llm_reparse", scope_key=f"forged:{job.id}",
                              payload_json=json.dumps({"import_job_id": job.id, "chunk_id": chunk.id,
                                                       "bank_id": job.bank_id + 99}),
                              created_by=owner)
    db.add(malicious)
    db.commit()
    with pytest.raises(ValueError, match="不属于"):
        job_service.try_claim_job_by_id(db, malicious.id, "forged-worker")
    db.refresh(malicious)
    assert malicious.attempt_count == 0 and malicious.status == "queued"
    reservation = acquire_import_lock(db, job.id)
    assert reservation is not None
    release_import_lock(reservation, job.id)
    assert execution_for(db) is None


def test_import_execution_lost_renewal_sets_control_flag_and_exits(case):
    db, bg, _, _ = case
    execution = execution_for(db)
    execution.stop.set()
    execution.thread.join()
    execution.stop.clear()
    execution.lease_seconds = 0.3
    execution.connection.invalidate()
    # Event 收到线程的真实退出，而不是用 sleep 猜测。
    finished = threading.Event()
    real_loop = execution._renew_loop
    def loop():
        try:
            real_loop()
        finally:
            finished.set()
    execution.thread = threading.Thread(target=loop)
    execution.thread.start()
    assert finished.wait(10)
    execution.thread.join()
    assert execution.lost.is_set()
    with pytest.raises(LeaseLost):
        job_service.complete_job(db, bg, execution=execution)


def test_import_execution_manual_accept_blocks_reparse_claim_and_preserves_source(case, sessions, monkeypatch):
    db, bg, job, _ = case
    bg.payload_json = json.dumps({**json.loads(bg.payload_json), "auto_import": False})
    job.config_json = {**job.config_json, "auto_import": False}
    db.commit()
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    review = db.query(ImportReviewItem).filter_by(import_job_id=job.id).first()
    parsed_id, import_id, review_id, user_id = review.parsed_question_id, job.id, review.id, bg.created_by
    complete_release(db, bg)
    reparse_id = svc.create_reparse_job(db, import_id, chunk.id, user_id)["background_job_id"]
    entered, finish = threading.Event(), threading.Event()
    original = svc._write_question_to_bank
    result, errors = [], []
    def block(db, parsed, bank_id):
        entered.set()
        assert finish.wait(10)
        return original(db, parsed, bank_id)
    monkeypatch.setattr(svc, "_write_question_to_bank", block)
    def accept():
        try:
            with sessions() as writer:
                result.append(svc.accept_review_item(writer, import_id, review_id, user_id))
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=accept)
    thread.start()
    try:
        assert entered.wait(10)
        with sessions() as contender:
            assert job_service.try_claim_job_by_id(contender, reparse_id, "competing-reparse") is None
            contender.refresh(contender.get(BackgroundJob, reparse_id))
            assert contender.get(BackgroundJob, reparse_id).attempt_count == 0
    finally:
        finish.set()
        thread.join(10)
    assert not thread.is_alive() and not errors and "question_id" in result[0]
    monkeypatch.setattr(svc, "_write_question_to_bank", original)
    reparse = job_service.try_claim_job_by_id(db, reparse_id, "reparse-after-accept")
    svc.run_reparse(db, reparse)
    source = db.get(ImportParsedQuestion, parsed_id)
    db.refresh(source)
    assert source.import_status == "imported"
    assert db.get(ImportReviewItem, review_id).status == "accepted"


def test_import_execution_review_api_reports_retryable_conflict(case):
    from fastapi import HTTPException
    from app.api.routes.import_review import accept_item, skip_item
    from app.models import Exam, User
    db, bg, job, _ = case
    user = db.get(User, bg.created_by)
    exam = db.get(Exam, job.bank.exam_id)
    for route in (accept_item, skip_item):
        with pytest.raises(HTTPException) as caught:
            route(job.id, 999, current_user=user, exam=exam, db=db)
        assert caught.value.status_code == 409


def test_import_execution_worker_exhausted_attempt_fails_under_guard_and_releases(case, sessions, monkeypatch):
    db, bg, _, _ = case
    bg.max_attempts = 2
    db.commit()
    job_id = queued_for_worker(db, bg)
    captured = []
    worker_for(monkeypatch, sessions, job_id, captured)
    monkeypatch.setattr(svc, "_persist_chunk_questions", lambda *_, **__: (_ for _ in ()).throw(RuntimeError("persistence crash")))
    assert job_worker.process_one_job("last-attempt") is True
    assert_closed(captured)
    db.expire_all()
    current = db.get(BackgroundJob, job_id)
    assert current.status == "failed" and current.attempt_count == 2
    assert current.active_scope_key is None and current.lease_until is None


def test_import_execution_second_claim_cannot_replace_owned_session_context(case):
    db, bg, _, _ = case
    execution = execution_for(db)
    assert job_service.try_claim_job_by_id(db, bg.id, "same-session") is None
    assert execution_for(db) is execution
    assert bg.attempt_count == execution.token.attempt_count


def test_import_execution_worker_stale_last_attempt_cannot_claim_again(case, sessions, monkeypatch):
    db, bg, job, model = case
    job_id = bg.id
    bg.max_attempts = bg.attempt_count
    db.commit()
    execution = execution_for(db)
    execution.stop.set()
    execution.thread.join()
    bg.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    release_import_execution(db, bg)
    db.rollback()
    monkeypatch.setattr(job_worker, "SessionLocal", sessions)
    monkeypatch.setattr(job_service, "claim_next_job", lambda db, worker_id: job_service.try_claim_job_by_id(db, job_id, worker_id))
    assert job_worker.process_one_job("stale-last-attempt") is False
    db.expire_all()
    current = db.get(BackgroundJob, job_id)
    assert current.status == "failed" and current.attempt_count == 1
    assert current.active_scope_key is None and current.lease_until is None
    assert current.finished_at is not None
    assert counts(db, job) == (0, 0, 0) and model.call_count == 0
    assert sessions.kw["bind"].pool.checkedout() == 1


def test_import_execution_already_exhausted_queued_request_does_not_consume_attempt(case):
    db, bg, job, model = case
    job_id = queued_for_worker(db, bg)
    bg.max_attempts = bg.attempt_count
    db.commit()
    assert job_service.try_claim_job_by_id(db, job_id, "exhausted-queued") is None
    db.refresh(bg)
    assert bg.status == "failed" and bg.attempt_count == 1
    assert execution_for(db) is None
    assert counts(db, job) == (0, 0, 0) and model.call_count == 0
    lock = acquire_import_lock(db, job.id)
    assert lock is not None
    release_import_lock(lock, job.id)
