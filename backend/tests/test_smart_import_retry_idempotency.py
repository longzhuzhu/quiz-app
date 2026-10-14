"""真实主编排恢复回归；所有数据位于临时 PostgreSQL，推理仅使用桩。"""
import json
import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Exam, User
from app.models.background_job import BackgroundJob
from app.models.import_chunk import ImportChunk
from app.models.import_job import ImportJob
from app.models.import_parsed_question import ImportParsedQuestion
from app.models.question import Question
from app.models.question_bank import QuestionBank
from app.services import smart_import_service as svc
from postgres_support import isolated_postgres


@pytest.fixture(scope="module")
def sessions():
    with isolated_postgres() as engine:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine)


@pytest.fixture
def case(sessions, monkeypatch):
    db = sessions()
    suffix = uuid.uuid4().hex
    user = User(username=suffix, email=f"{suffix}@invalid.test", password_hash="unused")
    db.add(user)
    db.flush()
    exam = Exam(owner_id=user.id, slug=suffix, name="Test", short_name="Test")
    db.add(exam)
    db.flush()
    bank = QuestionBank(name="Test", exam_id=exam.id)
    db.add(bank)
    db.flush()
    job = ImportJob(bank_id=bank.id, file_name="test.pdf", file_path="unused", file_hash="a" * 64,
                    file_type="pdf", config_json={"auto_import": True}, created_by=user.id)
    db.add(job)
    db.flush()
    bg = BackgroundJob(job_type="question_import_llm", scope_key=f"test:{suffix}",
                       payload_json=json.dumps({"import_job_id": job.id, "file_path": "unused",
                                                "file_type": "pdf", "use_llm_cache": False}),
                       status="queued", created_by=user.id)
    db.add(bg)
    db.flush()
    job.background_job_id = bg.id
    db.commit()
    from app.services.job_service import try_claim_job_by_id
    bg = try_claim_job_by_id(db, bg.id, worker_id="test")
    text = "\n".join(f"Question #{n}\nWhich privacy principle applies to situation {n}?\nA. first\nB. second\nAnswer: A" for n in (1, 2))
    monkeypatch.setattr(svc, "_source_file_hash", lambda *_: "a" * 64)
    monkeypatch.setattr(svc, "_extract_pages_from_file", lambda *_: [{"text": text, "page": 1}])
    response = json.dumps({"questions": [{"source_question_no": str(n), "question_type": "single",
                           "content": f"Which privacy principle applies to situation {n}?",
                           "options": [{"label": "A", "text": "first"}, {"label": "B", "text": "second"}],
                           "correct_answer": ["A"], "confidence": 0.99} for n in (1, 2)]})
    model = Mock(return_value=response)
    monkeypatch.setattr(svc, "call_ai_api", model)
    try:
        yield db, bg, job, model
    finally:
        if hasattr(svc, "release_import_execution"):
            svc.release_import_execution(db, bg)
        db.close()


def counts(db, job):
    return tuple(db.query(cls).filter_by(**filters).count() for cls, filters in (
        (ImportChunk, {"import_job_id": job.id}),
        (ImportParsedQuestion, {"import_job_id": job.id}),
        (Question, {"bank_id": job.bank_id}),
    ))


def test_import_retry_main_reentry_does_not_duplicate_chunks_or_audit(case):
    db, bg, job, model = case
    svc.run_smart_import(db, bg)
    before = counts(db, job)
    finalized_config = dict(job.config_json)
    updated_at = job.updated_at
    svc.run_smart_import(db, bg)
    assert counts(db, job) == before
    assert job.config_json == finalized_config and job.updated_at == updated_at
    assert before == (1, 2, 2)
    assert model.call_count == 1


def test_import_retry_hard_failed_terminal_is_verified_noop(case):
    db, bg, job, model = case
    model.side_effect = ValueError("AI API 错误 (401)")
    svc.run_smart_import(db, bg)
    assert job.status == "partial_imported" and job.failed_chunks == 1
    before = dict(job.config_json)
    svc.run_smart_import(db, bg)
    assert job.config_json == before
    assert counts(db, job) == (1, 0, 0) and model.call_count == 1
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    checkpoint = chunk.issues_json["execution_checkpoint"]
    assert checkpoint["terminal_failure"] is True
    assert checkpoint["response_ready"] is False and checkpoint["persistence_done"] is False
    assert "401" in chunk.issues_json["error"]
    owner = bg.created_by
    finish_request(db, bg)
    model.side_effect = None
    reparse = claim_reparse(db, job, chunk, owner)
    svc.run_reparse(db, reparse)
    assert counts(db, job) == (1, 2, 2) and model.call_count == 2
    assert job.config_json["reconciliation"]["missing_qnos"] == []


def test_import_retry_crash_after_slices_preserves_manifest(case, monkeypatch):
    db, bg, job, _ = case
    real = svc._update_import_job_status
    def crash(db, job, status):
        if status == "parsing":
            raise RuntimeError("crash after slices")
        real(db, job, status)
    monkeypatch.setattr(svc, "_update_import_job_status", crash)
    with pytest.raises(RuntimeError, match="crash after slices"):
        svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 0, 0)
    monkeypatch.setattr(svc, "_update_import_job_status", real)
    svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 2, 2)


def retry_claim(db, bg):
    from app.services import job_service
    from app.services.import_execution import release_import_execution
    job_id = bg.id
    job_service.requeue_job(db, bg, "injected crash", delay_seconds=0)
    release_import_execution(db, bg)
    return job_service.try_claim_job_by_id(db, job_id, worker_id="retry")


@pytest.mark.parametrize("stage", ["response", "second_question"])
@pytest.mark.parametrize("mode", ["normal", "cached", "review", "duplicate"])
def test_import_retry_response_and_atomic_persistence_recovery(case, monkeypatch, stage, mode):
    db, bg, job, model = case
    if mode == "review":
        bg.payload_json = json.dumps({**json.loads(bg.payload_json), "auto_import": False})
        db.commit()
    if mode == "duplicate":
        for item in json.loads(model.return_value)["questions"]:
            db.add(Question(bank_id=job.bank_id, question_type="single", content=item["content"],
                            options=[{"key": opt["label"], "text": opt["text"]} for opt in item["options"]],
                            correct_answer="A", order_index=int(item["source_question_no"])))
        db.commit()
    if mode == "cached":
        bg.payload_json = json.dumps({**json.loads(bg.payload_json), "use_llm_cache": True})
        db.commit()
        chunks = svc._initialize_manifest(db, job, json.loads(bg.payload_json))
        chunk = chunks[0]
        svc._store_llm_cache(db, svc._build_cache_key(chunk.chunk_hash), chunk.chunk_hash,
                             response_text=model.return_value)
        svc.commit_import(db)
    original = svc._persist_chunk_questions if stage == "response" else svc._save_parsed_question
    called = 0
    def crash(*args, **kwargs):
        nonlocal called
        called += 1
        if stage == "response":
            raise RuntimeError("response checkpoint crash")
        original(*args, **kwargs)
        if called == 2:
            raise RuntimeError("second question crash")
    name = "_persist_chunk_questions" if stage == "response" else "_save_parsed_question"
    monkeypatch.setattr(svc, name, crash)
    with pytest.raises(RuntimeError, match="crash"):
        svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 0, 2 if mode == "duplicate" else 0)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    assert chunk.issues_json["execution_checkpoint"]["response_ready"] is True
    assert chunk.issues_json["execution_checkpoint"]["persistence_done"] is False
    baseline = job.config_json["expected_qnos"]
    monkeypatch.setattr(svc, name, original)
    bg = retry_claim(db, bg)
    svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 2, 0 if mode == "review" else 2)
    assert model.call_count == (0 if mode == "cached" else 1)
    assert job.config_json["expected_qnos"] == baseline
    assert bg.attempt_count == 2
    assert bg.progress_done == 1
    svc.run_smart_import(db, bg)
    assert counts(db, job)[1] == 2
    assert bg.progress_done == 1


def test_import_retry_restores_in_memory_signatures_after_rollback(case, monkeypatch):
    db, bg, job, _ = case
    chunk = svc._initialize_manifest(db, job, json.loads(bg.payload_json))[0]
    signatures, qnos = {("sentinel",)}, {"999"}
    original = svc._save_parsed_question
    calls = 0
    def crash(**kwargs):
        nonlocal calls
        original(**kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError("flush then crash")
    monkeypatch.setattr(svc, "_save_parsed_question", crash)
    with pytest.raises(RuntimeError, match="flush then crash"):
        svc._process_chunk(db, chunk, job, True, False, signatures, bg, qnos)
    assert signatures == {("sentinel",)}
    assert qnos == {"999"}
    assert counts(db, job) == (1, 0, 0)


def test_import_retry_finalization_crash_replays_without_duplicate_or_lost_word_data(case, monkeypatch):
    from app.models.bank_word import BankWordFrequency
    db, bg, job, _ = case
    monkeypatch.setattr(svc, "build_bank_word_frequencies", lambda _: [{"term": "privacy", "frequency": 2}])
    word = BankWordFrequency(bank_id=job.bank_id, term="privacy", frequency=1,
                             term_zh="隐私", definition="meaning", definition_zh="释义")
    db.add(word)
    db.commit()
    word_id = word.id
    original = svc._write_reconciliation
    monkeypatch.setattr(svc, "_write_reconciliation", lambda *_: (_ for _ in ()).throw(RuntimeError("finalization crash")))
    with pytest.raises(RuntimeError, match="finalization crash"):
        svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 2, 2)
    monkeypatch.setattr(svc, "_write_reconciliation", original)
    bg = retry_claim(db, bg)
    svc.run_smart_import(db, bg)
    db.refresh(word)
    assert (word.id, word.term_zh, word.definition, word.definition_zh, word.frequency) == (word_id, "隐私", "meaning", "释义", 2)
    assert counts(db, job) == (1, 2, 2)
    assert job.config_json["reconciliation"]["missing_qnos"] == []


@pytest.mark.parametrize("corruption", ["legacy", "duplicate", "text", "baseline"])
def test_import_retry_ambiguous_history_fails_closed_without_deleting(case, corruption):
    db, bg, job, _ = case
    chunk = svc._initialize_manifest(db, job, json.loads(bg.payload_json))[0]
    if corruption == "legacy":
        job.config_json = {key: value for key, value in job.config_json.items() if key != "chunk_manifest"}
    elif corruption == "duplicate":
        db.add(ImportChunk(import_job_id=job.id, chunk_no=chunk.chunk_no,
                           chunk_hash=chunk.chunk_hash, chunk_text=chunk.chunk_text))
    elif corruption == "text":
        chunk.chunk_text += "changed"
    else:
        job.config_json = {**job.config_json, "expected_qnos": ["9"]}
    db.commit()
    before = counts(db, job)
    with pytest.raises(ValueError, match="manifest|checkpoint"):
        svc.run_smart_import(db, bg)
    assert counts(db, job) == before


def finish_request(db, bg):
    from app.services import job_service
    job_service.complete_job(db, bg)
    svc.release_import_execution(db, bg)


def claim_reparse(db, job, chunk, user_id):
    from app.services import job_service
    result = svc.create_reparse_job(db, job.id, chunk.id, user_id)
    return job_service.try_claim_job_by_id(db, result["background_job_id"], "reparse-test")


def test_import_retry_partial_done_is_stable_and_explicit_reparse_fills_gap(case, monkeypatch):
    import httpx
    db, bg, job, model = case
    full_response = model.return_value
    one = json.dumps({"questions": json.loads(full_response)["questions"][:1]})
    model.side_effect = [httpx.TimeoutException("l1"), httpx.TimeoutException("l1 retry"),
                         one, httpx.TimeoutException("question 2")]
    monkeypatch.setattr(svc.time, "sleep", lambda _: None)
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    assert chunk.status == "parsed_partial" and counts(db, job) == (1, 1, 1)
    assert job.failed_chunks == 1
    before_qnos = list(job.config_json["expected_qnos"])
    bg = retry_claim(db, bg)
    svc.run_smart_import(db, bg)
    assert model.call_count == 4 and counts(db, job) == (1, 1, 1)
    assert job.status == "partial_imported" and job.failed_chunks == 1
    owner = bg.created_by
    finish_request(db, bg)
    model.side_effect = None
    model.return_value = full_response
    reparse = claim_reparse(db, job, chunk, owner)
    svc.run_reparse(db, reparse)
    assert counts(db, job) == (1, 3, 2)  # 原 imported + 本次 duplicate + 补齐题。
    assert job.config_json["reconciliation"]["missing_qnos"] == []
    assert job.config_json["expected_qnos"] == before_qnos
    assert job.failed_chunks == 0
    svc.run_reparse(db, reparse)
    assert counts(db, job) == (1, 3, 2) and model.call_count == 5


def test_import_retry_new_reparse_keeps_new_audit_but_same_request_is_noop(case):
    db, bg, job, model = case
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    imported_ids = {row.id for row in db.query(ImportParsedQuestion).filter_by(import_job_id=job.id)}
    owner = bg.created_by
    finish_request(db, bg)
    reparse = claim_reparse(db, job, chunk, owner)
    svc.run_reparse(db, reparse)
    duplicate_ids = {row.id for row in db.query(ImportParsedQuestion).filter_by(import_job_id=job.id, review_status="duplicate")}
    assert len(duplicate_ids) == 2
    assert counts(db, job) == (1, 4, 2)
    reparse = retry_claim(db, reparse)
    svc.run_reparse(db, reparse)
    assert counts(db, job) == (1, 4, 2) and model.call_count == 2
    assert {row.id for row in db.query(ImportParsedQuestion).filter_by(import_job_id=job.id, review_status="duplicate")} == duplicate_ids
    finish_request(db, reparse)
    another = claim_reparse(db, job, chunk, owner)
    svc.run_reparse(db, another)
    assert model.call_count == 3
    assert imported_ids <= {row.id for row in db.query(ImportParsedQuestion).filter_by(import_job_id=job.id)}
    assert not duplicate_ids & {row.id for row in db.query(ImportParsedQuestion).filter_by(import_job_id=job.id, review_status="duplicate")}
    assert counts(db, job) == (1, 4, 2)


def test_import_retry_reparse_crash_reuses_response_without_repeating_hygiene(case, monkeypatch):
    db, bg, job, model = case
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    owner = bg.created_by
    finish_request(db, bg)
    reparse = claim_reparse(db, job, chunk, owner)
    original = svc._save_parsed_question
    calls = 0
    def crash(**kwargs):
        nonlocal calls
        original(**kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError("reparse crash")
    monkeypatch.setattr(svc, "_save_parsed_question", crash)
    with pytest.raises(RuntimeError, match="reparse crash"):
        svc.run_reparse(db, reparse)
    assert counts(db, job) == (1, 2, 2)
    monkeypatch.setattr(svc, "_save_parsed_question", original)
    reparse = retry_claim(db, reparse)
    svc.run_reparse(db, reparse)
    assert counts(db, job) == (1, 4, 2) and model.call_count == 2


def test_import_retry_fresh_review_accept_survives_stale_reparse_session(case, sessions):
    from app.models.import_review_item import ImportReviewItem
    db, bg, job, _ = case
    bg.payload_json = json.dumps({**json.loads(bg.payload_json), "auto_import": False})
    job.config_json = {**job.config_json, "auto_import": False}
    db.commit()
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    pending = db.query(ImportParsedQuestion).filter_by(import_job_id=job.id).first()
    review = db.query(ImportReviewItem).filter_by(parsed_question_id=pending.id).one()
    import_id, review_id, pending_id, owner = job.id, review.id, pending.id, bg.created_by
    finish_request(db, bg)
    # 先读旧快照，再由独立复核写者接受。
    db.refresh(pending)
    with sessions() as other:
        accepted = svc.accept_review_item(other, import_id, review_id, owner)
        assert "question_id" in accepted
    assert pending.import_status == "waiting"
    reparse = claim_reparse(db, job, chunk, owner)
    svc.run_reparse(db, reparse)
    db.refresh(pending)
    assert pending.id == pending_id and pending.import_status == "imported"
    assert db.get(ImportReviewItem, review_id).status == "accepted"
    assert counts(db, job)[2] == 1


def test_import_retry_new_same_file_job_retains_per_question_duplicate_audit(case):
    from app.services import job_service
    db, bg, job, model = case
    svc.run_smart_import(db, bg)
    owner = bg.created_by
    finish_request(db, bg)
    newer = ImportJob(bank_id=job.bank_id, file_name=job.file_name, file_path=job.file_path,
                      file_hash=job.file_hash, file_type=job.file_type, config_json={"auto_import": True})
    db.add(newer)
    db.flush()
    new_bg = BackgroundJob(job_type="question_import_llm", scope_key=f"new:{newer.id}",
                           payload_json=json.dumps({"import_job_id": newer.id, "use_llm_cache": False}),
                           created_by=owner)
    db.add(new_bg)
    db.flush()
    newer.background_job_id = new_bg.id
    db.commit()
    new_bg = job_service.try_claim_job_by_id(db, new_bg.id, "new-file-import")
    svc.run_smart_import(db, new_bg)
    assert counts(db, newer) == (1, 2, 2)
    assert all(row.review_status == "duplicate" for row in db.query(ImportParsedQuestion).filter_by(import_job_id=newer.id))
    assert newer.status == "unimported" and newer.summary_json["duplicate_skipped"] == 2
    assert model.call_count == 2


@pytest.mark.parametrize("corruption", ["missing_checkpoint", "changed_response"])
def test_import_retry_parsed_or_done_is_not_sufficient_without_verified_checkpoint(case, corruption):
    db, bg, job, _ = case
    svc.run_smart_import(db, bg)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    if corruption == "missing_checkpoint":
        chunk.issues_json = {}
    else:
        chunk.llm_response_json = {"questions": []}
    db.commit()
    before = counts(db, job)
    with pytest.raises(svc.ImportRecoveryError, match="checkpoint"):
        svc.run_smart_import(db, bg)
    assert counts(db, job) == before


def test_import_retry_model_http_runs_without_business_transaction(case, monkeypatch):
    db, bg, job, model = case
    def assert_no_transaction(messages, model_db, **kwargs):
        assert model_db is db and not model_db.in_transaction()
        assert "ai_config" in kwargs
        return model.return_value
    monkeypatch.setattr(svc, "call_ai_api", assert_no_transaction)
    svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 2, 2)


def test_import_retry_cache_key_conflict_is_safe_reuse_not_failed_transaction(case):
    from app.models.llm_parse_cache import LlmParseCache
    db, bg, job, model = case
    bg.payload_json = json.dumps({**json.loads(bg.payload_json), "use_llm_cache": True})
    db.commit()
    chunk = svc._initialize_manifest(db, job, json.loads(bg.payload_json))[0]
    key = svc._build_cache_key(chunk.chunk_hash)
    svc._store_llm_cache(db, key, chunk.chunk_hash, response_text=model.return_value)
    svc.commit_import(db)
    svc.run_smart_import(db, bg)
    before = db.query(LlmParseCache).filter_by(cache_key=key).one().response_json
    svc._store_llm_cache(db, key, chunk.chunk_hash, response_text='{"questions": []}')
    svc.commit_import(db)
    assert db.query(LlmParseCache).filter_by(cache_key=key).count() == 1
    assert db.query(LlmParseCache).filter_by(cache_key=key).one().response_json == before
    svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 2, 2) and model.call_count == 0


def test_import_retry_crash_after_persistence_before_progress_keeps_successful_chunk(case, monkeypatch):
    db, bg, job, model = case
    original = svc._process_chunk
    def crash(**kwargs):
        original(**kwargs)
        raise RuntimeError("after persistence before progress")
    monkeypatch.setattr(svc, "_process_chunk", crash)
    with pytest.raises(RuntimeError, match="after persistence"):
        svc.run_smart_import(db, bg)
    assert counts(db, job) == (1, 2, 2)
    chunk = db.query(ImportChunk).filter_by(import_job_id=job.id).one()
    assert chunk.status == "parsed" and job.failed_chunks == 0
    monkeypatch.setattr(svc, "_process_chunk", original)
    bg = retry_claim(db, bg)
    svc.run_smart_import(db, bg)
    assert job.status == "imported" and job.failed_chunks == 0
    assert bg.progress_done == 1 and model.call_count == 1
