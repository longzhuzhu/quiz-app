from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


from app.core.database import Base  # noqa: E402
from app.models.background_job import BackgroundJob  # noqa: E402
from app.models.bank_word import BankWordExclusion, BankWordFrequency  # noqa: E402,F401
from app.models.import_chunk import ImportChunk  # noqa: E402
from app.models.import_job import ImportJob  # noqa: E402
from app.models.import_parsed_question import ImportParsedQuestion  # noqa: E402
from app.models.import_review_item import ImportReviewItem  # noqa: E402
from app.models.llm_parse_cache import LlmParseCache  # noqa: E402,F401
from app.models.question import Question  # noqa: E402
from app.models.question_bank import QuestionBank  # noqa: E402
from app.models.user import User  # noqa: E402,F401
from app.models.vocabulary import Vocabulary  # noqa: E402,F401
from app.schemas.llm_parse import ParsedOption, ParsedQuestion  # noqa: E402
from app.services import smart_import_service as svc  # noqa: E402
from scripts.backfill_scenario_question_content import backfill_scenario_question_content  # noqa: E402


SCENARIO = "SCENARIO\nAn organization discovers that customer data was exposed during a vendor migration."
CONTENT = "Which is the best next step the organization should take?"
FULL_CONTENT = f"{SCENARIO}\n\n{CONTENT}"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def bank_and_job(db_session):
    bank = QuestionBank(name="Scenario Bank", description="test")
    db_session.add(bank)
    db_session.flush()
    job = ImportJob(
        bank_id=bank.id,
        file_name="scenario.pdf",
        file_path="/tmp/scenario.pdf",
        file_hash="abc" * 16,
        file_type="pdf",
        status="parsing",
        config_json={"auto_import": True},
    )
    db_session.add(job)
    db_session.flush()
    chunk = ImportChunk(
        import_job_id=job.id,
        chunk_no=1,
        chunk_text=f"{SCENARIO}\nQuestion #247\n{CONTENT}\nA. Notify regulators\nB. Ignore\nCorrect Answer: A",
        chunk_hash="hash-1",
        status="pending",
    )
    db_session.add(chunk)
    db_session.flush()
    return bank, job, chunk


def test_create_smart_import_job_allows_duplicate_file_hash(db_session, bank_and_job, monkeypatch):
    bank, existing_job, _chunk = bank_and_job
    existing_job.status = "review_required"
    db_session.commit()
    monkeypatch.setattr(
        svc,
        "save_upload_file",
        lambda file_bytes, filename: ("/tmp/duplicate.pdf", existing_job.file_hash),
    )

    result = svc.create_smart_import_job(
        db=db_session,
        bank_id=bank.id,
        file_bytes=b"same pdf content",
        filename="duplicate.pdf",
        user_id=1,
    )

    assert "error" not in result
    new_job = db_session.get(ImportJob, result["import_job_id"])
    assert new_job.id != existing_job.id
    assert new_job.config_json["duplicate_file_of"] == existing_job.id
    assert new_job.config_json["duplicate_file_status"] == "review_required"
    assert new_job.background_job_id == result["background_job_id"]


def test_duplicate_file_question_content_is_skipped_without_new_question(db_session, bank_and_job):
    bank, job, chunk = bank_and_job
    existing_question = Question(
        bank_id=bank.id,
        question_type="single",
        content=FULL_CONTENT,
        options=[
            {"key": "A", "text": "Notify regulators and affected customers"},
            {"key": "B", "text": "Ignore the incident"},
            {"key": "C", "text": "Delete all records"},
            {"key": "D", "text": "Wait for a complaint"},
        ],
        correct_answer="A",
        order_index=0,
    )
    db_session.add(existing_question)
    db_session.commit()
    seen_signatures = {
        svc._question_signature(
            existing_question.question_type,
            existing_question.content,
            existing_question.options,
            ["A"],
        )
    }

    svc._save_parsed_question(
        db_session,
        _parsed_question(),
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=seen_signatures,
    )

    assert db_session.query(Question).filter_by(bank_id=bank.id).count() == 1
    parsed = db_session.query(ImportParsedQuestion).one()
    assert parsed.review_status == "duplicate"
    assert parsed.import_status == "skipped"
    assert parsed.imported_question_id is None
    assert parsed.issues_json["details"][0]["reason"] == "content"
    assert job.imported_questions == 0


def test_question_signature_normalizes_option_key_label_and_label_case():
    from_question_table = svc._question_signature(
        "single",
        FULL_CONTENT,
        [
            {"key": "A", "text": "Notify regulators and affected customers"},
            {"key": "B", "text": "Ignore the incident"},
        ],
        ["A"],
    )
    from_llm_parse = svc._question_signature(
        "single",
        FULL_CONTENT,
        [
            {"label": " b ", "text": "Ignore the incident"},
            {"label": " a ", "text": "Notify regulators and affected customers"},
        ],
        ["a"],
    )

    assert from_question_table == from_llm_parse


def test_write_question_duplicate_fallback_records_content_reason(db_session, bank_and_job):
    bank, job, chunk = bank_and_job
    existing_question = Question(
        bank_id=bank.id,
        question_type="single",
        content=FULL_CONTENT,
        options=[
            {"key": "A", "text": "Notify regulators and affected customers"},
            {"key": "B", "text": "Ignore the incident"},
            {"key": "C", "text": "Delete all records"},
            {"key": "D", "text": "Wait for a complaint"},
        ],
        correct_answer="A",
        order_index=0,
    )
    db_session.add(existing_question)
    db_session.commit()

    svc._save_parsed_question(
        db_session,
        _parsed_question(),
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=None,
    )

    assert db_session.query(Question).filter_by(bank_id=bank.id).count() == 1
    parsed = db_session.query(ImportParsedQuestion).one()
    assert parsed.review_status == "duplicate"
    assert parsed.import_status == "skipped"
    assert parsed.imported_question_id is None
    assert parsed.issues_json["details"][0]["reason"] == "content"
    assert job.imported_questions == 0


def _parsed_question(*, scenario: str | None = SCENARIO, qno: str = "247") -> ParsedQuestion:
    return ParsedQuestion(
        source_question_no=qno,
        question_type="single",
        scenario=scenario,
        content=CONTENT,
        options=[
            ParsedOption(label="A", text="Notify regulators and affected customers"),
            ParsedOption(label="B", text="Ignore the incident"),
            ParsedOption(label="C", text="Delete all records"),
            ParsedOption(label="D", text="Wait for a complaint"),
        ],
        correct_answer=["A"],
        explanation="",
        references=[],
        confidence=0.96,
        issues=[],
    )


def _parsed_row(job: ImportJob, chunk: ImportChunk, *, scenario: str | None = SCENARIO) -> ImportParsedQuestion:
    return ImportParsedQuestion(
        import_job_id=job.id,
        chunk_id=chunk.id,
        source_question_no="247",
        question_type="single",
        scenario_text=scenario,
        content=CONTENT,
        options_json=[
            {"key": "A", "text": "Notify regulators and affected customers"},
            {"key": "B", "text": "Ignore the incident"},
            {"key": "C", "text": "Delete all records"},
            {"key": "D", "text": "Wait for a complaint"},
        ],
        correct_answer=["A"],
        llm_confidence=0.96,
        final_confidence=0.96,
        review_status="pending",
        import_status="waiting",
    )


def test_auto_import_writes_full_scenario_content(db_session, bank_and_job):
    bank, job, chunk = bank_and_job

    svc._save_parsed_question(
        db_session,
        _parsed_question(),
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=set(),
    )

    question = db_session.query(Question).one()
    parsed = db_session.query(ImportParsedQuestion).one()
    assert question.content == FULL_CONTENT
    assert parsed.scenario_text == SCENARIO
    assert parsed.content == CONTENT


def test_review_accept_writes_full_scenario_content(db_session, bank_and_job, monkeypatch):
    bank, job, chunk = bank_and_job
    parsed = _parsed_row(job, chunk)
    db_session.add(parsed)
    db_session.flush()
    review = ImportReviewItem(
        import_job_id=job.id,
        parsed_question_id=parsed.id,
        review_type="LOW_CONFIDENCE",
        severity="MEDIUM",
        status="pending",
    )
    db_session.add(review)
    db_session.commit()
    monkeypatch.setattr(svc, "_update_bank_stats", lambda db, bank_id: None)

    result = svc.accept_review_item(db_session, job.id, review.id, reviewer_id=1)

    question = db_session.get(Question, result["question_id"])
    assert question.content == FULL_CONTENT
    assert parsed.import_status == "imported"
    assert review.status == "accepted"


def test_run_reparse_writes_full_scenario_content(db_session, bank_and_job, monkeypatch):
    bank, job, chunk = bank_and_job
    bg_job = BackgroundJob(
        job_type="question_import_llm_reparse",
        scope_key=f"import_reparse:{chunk.id}",
        active_scope_key=f"import_reparse:{chunk.id}",
        payload_json=json.dumps({"import_job_id": job.id, "chunk_id": chunk.id, "bank_id": bank.id}),
        status="running",
        created_by=1,
    )
    db_session.add(bg_job)
    db_session.commit()

    def fake_call_ai_api(messages, db, scene="default", timeout=60.0):
        return json.dumps({
            "questions": [{
                "source_question_no": "247",
                "question_type": "single",
                "scenario": SCENARIO,
                "content": CONTENT,
                "options": [
                    {"label": "A", "text": "Notify regulators and affected customers"},
                    {"label": "B", "text": "Ignore the incident"},
                    {"label": "C", "text": "Delete all records"},
                    {"label": "D", "text": "Wait for a complaint"},
                ],
                "correct_answer": ["A"],
                "explanation": "",
                "references": [],
                "confidence": 0.96,
                "issues": [],
            }],
            "chunk_issues": [],
        })

    monkeypatch.setattr(svc, "call_ai_api", fake_call_ai_api)
    monkeypatch.setattr(svc, "heartbeat_job", lambda db, bg_job, **kw: None)
    monkeypatch.setattr(svc, "_update_bank_stats", lambda db, bank_id: None)

    svc.run_reparse(db_session, bg_job)

    question = db_session.query(Question).one()
    assert question.content == FULL_CONTENT


def test_leading_scenario_material_is_attached_to_first_question():
    text = (
        "SCENARIO\n"
        "A privacy team receives a long incident report from a processor. "
        "The report describes unauthorized access, affected systems, and customer impact. "
        "The team must decide what to do next.\n\n"
        "Question #247\nWhich is the best next step?\nA. Notify\nB. Ignore\n"
        "Question #248\nWhich control helps most?\nA. Audit\nB. None\n"
    )

    segments = svc._split_by_single_question(text)

    assert segments[0]["text"].startswith("SCENARIO")
    assert "Question #247" in segments[0]["text"]
    assert segments[1]["text"].startswith("Question #248")


def test_leading_noise_is_not_attached_to_first_question():
    text = (
        "Page 162 of 283\nwww.example.com\nPassing Score 70% Time Limit 180 min\n"
        "Question #247\nWhich is the best next step?\nA. Notify\nB. Ignore\n"
        "Question #248\nWhich control helps most?\nA. Audit\nB. None\n"
    )

    segments = svc._split_by_single_question(text)

    assert segments[0]["text"].startswith("Question #247")
    assert "Page 162" not in segments[0]["text"]


def test_quality_check_keeps_scenario_missing_as_quality_tip_not_unusable():
    parsed = _parsed_question(scenario=None)
    final_confidence, issues = svc._quality_check(parsed, f"{SCENARIO}\nQuestion #247\n{CONTENT}")

    assert final_confidence < 1
    assert any(issue["code"] == "SCENARIO_MISSING" and issue["severity"] == "HIGH" for issue in issues)
    assert svc._unusable_question_issues(parsed) == []


def test_quality_check_does_not_apply_scenario_marker_to_other_questions():
    parsed = _parsed_question(scenario=None, qno="248")
    chunk_text = (
        f"{SCENARIO}\nQuestion #247\n{CONTENT}\nA. Notify\nB. Ignore\n"
        "Question #248\nWhich control helps most?\nA. Audit logs\nB. No control\n"
    )

    final_confidence, issues = svc._quality_check(parsed, chunk_text)

    assert final_confidence > 0
    assert not any(issue["code"] == "SCENARIO_MISSING" for issue in issues)
    assert svc._unusable_question_issues(parsed) == []


@pytest.mark.parametrize("case", ["missing_stem", "missing_options", "missing_answer", "answer_not_in_options"])
def test_unusable_question_auto_skips_without_review_item(db_session, bank_and_job, case):
    bank, job, chunk = bank_and_job
    parsed = _parsed_question()
    if case == "missing_stem":
        parsed.scenario = None
        parsed.content = ""
    elif case == "missing_options":
        parsed.options = [ParsedOption(label="A", text="Only one option")]
    elif case == "missing_answer":
        parsed.correct_answer = []
    elif case == "answer_not_in_options":
        parsed.correct_answer = ["Z"]

    svc._save_parsed_question(
        db_session,
        parsed,
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=set(),
    )

    parsed_row = db_session.query(ImportParsedQuestion).one()
    assert parsed_row.review_status == "auto_skipped"
    assert parsed_row.import_status == "skipped"
    assert parsed_row.imported_question_id is None
    assert db_session.query(Question).count() == 0
    assert db_session.query(ImportReviewItem).count() == 0
    assert job.review_questions == 0
    assert job.imported_questions == 0


def test_low_confidence_complete_question_auto_imports_with_quality_tip(db_session, bank_and_job):
    bank, job, chunk = bank_and_job
    parsed = _parsed_question(qno="")
    parsed.confidence = 0.1

    svc._save_parsed_question(
        db_session,
        parsed,
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=set(),
    )

    parsed_row = db_session.query(ImportParsedQuestion).one()
    assert parsed_row.review_status == "auto_accepted"
    assert parsed_row.import_status == "imported"
    assert db_session.query(Question).count() == 1
    assert db_session.query(ImportReviewItem).count() == 0
    assert job.imported_questions == 1
    item = svc.serialize_auto_handled_item(parsed_row)
    assert item["result"] == "auto_imported"
    assert item["reason"] == "题目结构完整，已自动入库"
    assert "无题号" in item["quality_tips"]


def test_finalize_import_marks_all_auto_skipped_as_unimported(db_session, bank_and_job, monkeypatch):
    bank, job, chunk = bank_and_job
    parsed = _parsed_question()
    parsed.correct_answer = []
    monkeypatch.setattr(svc, "_write_reconciliation", lambda db, import_job: None)

    svc._save_parsed_question(
        db_session,
        parsed,
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=set(),
    )
    svc._finalize_import(db_session, job)

    db_session.refresh(job)
    assert job.status == "unimported"
    assert job.summary_json["auto_skipped"] == 1
    assert job.summary_json["auto_handled"] == 1


def test_history_backfill_dry_run_apply_and_safety_conditions(db_session, bank_and_job):
    bank, job, chunk = bank_and_job

    safe_question = Question(
        bank_id=bank.id,
        question_type="single",
        content=CONTENT,
        options=[{"key": "A", "text": "Notify"}, {"key": "B", "text": "Ignore"}],
        correct_answer="A",
        order_index=0,
    )
    edited_question = Question(
        bank_id=bank.id,
        question_type="single",
        content=f"Human edited: {CONTENT}",
        options=[{"key": "A", "text": "Notify"}, {"key": "B", "text": "Ignore"}],
        correct_answer="A",
        order_index=1,
    )
    no_scenario_question = Question(
        bank_id=bank.id,
        question_type="single",
        content=CONTENT,
        options=[{"key": "A", "text": "Notify"}, {"key": "B", "text": "Ignore"}],
        correct_answer="A",
        order_index=2,
    )
    db_session.add_all([safe_question, edited_question, no_scenario_question])
    db_session.flush()

    safe_parsed = _parsed_row(job, chunk)
    safe_parsed.imported_question_id = safe_question.id
    safe_parsed.import_status = "imported"
    edited_parsed = _parsed_row(job, chunk)
    edited_parsed.imported_question_id = edited_question.id
    edited_parsed.import_status = "imported"
    no_scenario_parsed = _parsed_row(job, chunk, scenario=None)
    no_scenario_parsed.imported_question_id = no_scenario_question.id
    no_scenario_parsed.import_status = "imported"
    missing_question_parsed = _parsed_row(job, chunk)
    missing_question_parsed.imported_question_id = 99999
    missing_question_parsed.import_status = "imported"
    db_session.add_all([safe_parsed, edited_parsed, no_scenario_parsed, missing_question_parsed])
    db_session.commit()

    dry_run = backfill_scenario_question_content(db_session, apply=False)
    db_session.refresh(safe_question)
    assert dry_run.matched == 1
    assert dry_run.updated == 0
    assert safe_question.content == CONTENT

    applied = backfill_scenario_question_content(db_session, apply=True)
    db_session.refresh(safe_question)
    db_session.refresh(edited_question)
    db_session.refresh(no_scenario_question)

    assert applied.matched == 1
    assert applied.updated == 1
    assert safe_question.content == FULL_CONTENT
    assert edited_question.content.startswith("Human edited:")
    assert no_scenario_question.content == CONTENT
    assert applied.skipped_content_mismatch == 1
    assert applied.skipped_no_scenario == 1
    assert applied.skipped_no_question == 1
