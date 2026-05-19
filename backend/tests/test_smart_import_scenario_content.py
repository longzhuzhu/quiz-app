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
from scripts.clear_question_explanations import clear_question_explanations  # noqa: E402


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


def test_inline_answer_blocks_do_not_strip_following_questions():
    text = """
Question 1
Which identifier should be used?
Options:
A- Driver license
B- Email
Answer:
A
Explanation:
Option A is strongest. References mention 4.1 controls, section 1.2, and article 7.
Question 2
Which control helps most?
Options:
A- Logging
B- None
Answer:
A
Explanation:
Logging helps.
"""

    answer_key = svc._extract_answer_key(svc._normalize_text(text))
    segments = svc._split_by_question_markers(svc._normalize_text(text))

    assert answer_key == {}
    assert len(svc._split_by_single_question(segments[0]["text"])) == 2
    assert "Question 2" in segments[0]["text"]


def test_answer_key_detection_supports_common_terminal_formats():
    answer_key_text = """
Question 1
Which identifier should be used?
A. Driver license
B. Email
Question 2
Which control helps most?
A. Logging
B. None
Question 3
Which notice is required?
A. Privacy notice
B. No notice

Answer Key:
1: A
2. B
3) True
"""
    answers_colon_text = """
Question 1
Which identifier should be used?
A. Driver license
B. Email

Answers:
1 A
2: B
3. C
"""

    assert svc._extract_answer_key(svc._normalize_text(answer_key_text)) == {1: "A", 2: "B", 3: "TRUE"}
    assert svc._extract_answer_key(svc._normalize_text(answers_colon_text)) == {1: "A", 2: "B", 3: "C"}


def test_duplicate_cached_chunk_preserves_each_duplicate_parsed_record(db_session, bank_and_job, monkeypatch):
    bank, job, chunk = bank_and_job
    chunk.chunk_text = """
Question #1
Which identifier should be used?
A. Driver license
B. Email
Question #2
Which control helps most?
A. Logging
B. None
Question #3
Which notice is required?
A. Privacy notice
B. No notice
"""
    existing_questions = [
        Question(
            bank_id=bank.id,
            question_type="single",
            content=content,
            options=[{"key": "A", "text": option_a}, {"key": "B", "text": option_b}],
            correct_answer="A",
            order_index=index,
        )
        for index, (content, option_a, option_b) in enumerate([
            ("Which identifier should be used?", "Driver license", "Email"),
            ("Which control helps most?", "Logging", "None"),
            ("Which notice is required?", "Privacy notice", "No notice"),
        ])
    ]
    db_session.add_all(existing_questions)
    db_session.commit()
    seen_signatures = {
        svc._question_signature(q.question_type, q.content, q.options, ["A"])
        for q in existing_questions
    }
    cached_questions = [
        {
            "source_question_no": str(index),
            "question_type": "single",
            "scenario": None,
            "content": content,
            "options": [
                {"label": "A", "text": option_a},
                {"label": "B", "text": option_b},
            ],
            "correct_answer": ["A"],
            "explanation": "",
            "references": [],
            "confidence": 0.95,
            "issues": [],
        }
        for index, (content, option_a, option_b) in enumerate([
            ("Which identifier should be used?", "Driver license", "Email"),
            ("Which control helps most?", "Logging", "None"),
            ("Which notice is required?", "Privacy notice", "No notice"),
        ], start=1)
    ]
    monkeypatch.setattr(svc, "_write_reconciliation", lambda db, import_job: None)

    svc._process_chunk_cached(
        db=db_session,
        chunk=chunk,
        cached={"response_text": json.dumps({"questions": cached_questions, "chunk_issues": []})},
        import_job=job,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=seen_signatures,
    )
    svc._finalize_import(db_session, job)

    parsed_rows = db_session.query(ImportParsedQuestion).order_by(ImportParsedQuestion.id).all()
    assert len(parsed_rows) == 3
    assert [pq.source_question_no for pq in parsed_rows] == ["1", "2", "3"]
    assert {pq.review_status for pq in parsed_rows} == {"duplicate"}
    assert {pq.import_status for pq in parsed_rows} == {"skipped"}
    assert db_session.query(Question).filter_by(bank_id=bank.id).count() == 3
    assert job.imported_questions == 0
    assert job.status == "unimported"
    assert job.summary_json["duplicate_skipped"] == 3


def test_duplicate_non_cached_chunk_preserves_each_duplicate_parsed_record(db_session, bank_and_job, monkeypatch):
    bank, job, chunk = bank_and_job
    question_rows = [
        ("1", "Which identifier should be used?", "Driver license", "Email"),
        ("2", "Which control helps most?", "Logging", "None"),
        ("3", "Which notice is required?", "Privacy notice", "No notice"),
    ]
    chunk.chunk_text = "\n".join(
        f"Question #{qno}\n{content}\nA. {option_a}\nB. {option_b}"
        for qno, content, option_a, option_b in question_rows
    )
    existing_questions = [
        Question(
            bank_id=bank.id,
            question_type="single",
            content=content,
            options=[{"key": "A", "text": option_a}, {"key": "B", "text": option_b}],
            correct_answer="A",
            order_index=index,
        )
        for index, (_qno, content, option_a, option_b) in enumerate(question_rows)
    ]
    db_session.add_all(existing_questions)
    db_session.commit()
    seen_signatures = {
        svc._question_signature(q.question_type, q.content, q.options, ["A"])
        for q in existing_questions
    }
    llm_questions = [
        {
            "source_question_no": qno,
            "question_type": "single",
            "scenario": None,
            "content": content,
            "options": [{"label": "A", "text": option_a}, {"label": "B", "text": option_b}],
            "correct_answer": ["A"],
            "explanation": "",
            "references": [],
            "confidence": 0.95,
            "issues": [],
        }
        for qno, content, option_a, option_b in question_rows
    ]
    monkeypatch.setattr(
        svc,
        "call_ai_api",
        lambda messages, db, scene="default", timeout=60.0: json.dumps({"questions": llm_questions, "chunk_issues": []}),
    )
    monkeypatch.setattr(svc, "_write_reconciliation", lambda db, import_job: None)

    svc._process_chunk(
        db=db_session,
        chunk=chunk,
        import_job=job,
        auto_import=True,
        use_llm_cache=False,
        seen_signatures=seen_signatures,
    )
    svc._finalize_import(db_session, job)

    parsed_rows = db_session.query(ImportParsedQuestion).order_by(ImportParsedQuestion.id).all()
    assert len(parsed_rows) == 3
    assert [pq.source_question_no for pq in parsed_rows] == ["1", "2", "3"]
    assert {pq.review_status for pq in parsed_rows} == {"duplicate"}
    assert {pq.import_status for pq in parsed_rows} == {"skipped"}
    assert db_session.query(Question).filter_by(bank_id=bank.id).count() == 3
    assert job.status == "unimported"
    assert job.summary_json["duplicate_skipped"] == 3


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


def _parsed_question(
    *,
    scenario: str | None = SCENARIO,
    qno: str = "247",
    explanation: str = "",
) -> ParsedQuestion:
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
        explanation=explanation,
        references=[],
        confidence=0.96,
        issues=[],
    )


def _parsed_row(
    job: ImportJob,
    chunk: ImportChunk,
    *,
    scenario: str | None = SCENARIO,
    explanation: str | None = None,
) -> ImportParsedQuestion:
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
        explanation=explanation,
        llm_confidence=0.96,
        final_confidence=0.96,
        review_status="pending",
        import_status="waiting",
    )


def test_auto_import_writes_full_scenario_content(db_session, bank_and_job):
    bank, job, chunk = bank_and_job

    svc._save_parsed_question(
        db_session,
        _parsed_question(explanation="导入解析：应仅保留在导入解析记录中"),
        job,
        chunk,
        chunk_text=chunk.chunk_text,
        auto_import=True,
        seen_signatures=set(),
    )

    question = db_session.query(Question).one()
    parsed = db_session.query(ImportParsedQuestion).one()
    assert question.content == FULL_CONTENT
    assert question.explanation is None
    assert question.explanation_zh is None
    assert parsed.scenario_text == SCENARIO
    assert parsed.content == CONTENT
    assert parsed.explanation == "导入解析：应仅保留在导入解析记录中"


def test_review_accept_writes_full_scenario_content(db_session, bank_and_job, monkeypatch):
    bank, job, chunk = bank_and_job
    parsed = _parsed_row(job, chunk, explanation="复核导入解析：不应写入正式题目")
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
    assert question.explanation is None
    assert question.explanation_zh is None
    assert parsed.explanation == "复核导入解析：不应写入正式题目"
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
                "explanation": "reparse 导入解析：仅保留在导入解析记录中",
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
    parsed = db_session.query(ImportParsedQuestion).one()
    assert question.content == FULL_CONTENT
    assert question.explanation is None
    assert question.explanation_zh is None
    assert parsed.explanation == "reparse 导入解析：仅保留在导入解析记录中"


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


def test_finalize_import_failed_chunks_take_priority_over_unimported(db_session, bank_and_job, monkeypatch):
    _bank, job, chunk = bank_and_job
    job.failed_chunks = 1
    duplicate = ImportParsedQuestion(
        import_job_id=job.id,
        chunk_id=chunk.id,
        source_question_no="1",
        question_type="single",
        content="Which identifier should be used?",
        options_json=[{"key": "A", "text": "Driver license"}, {"key": "B", "text": "Email"}],
        correct_answer=["A"],
        review_status="duplicate",
        import_status="skipped",
        issues_json={"details": [{"code": "DUPLICATE", "reason": "content"}]},
    )
    db_session.add(duplicate)
    job.parsed_questions = 1
    monkeypatch.setattr(svc, "_write_reconciliation", lambda db, import_job: None)

    svc._finalize_import(db_session, job)

    db_session.refresh(job)
    assert job.status == "partial_imported"
    assert job.summary_json["duplicate_skipped"] == 1


def test_clear_question_explanations_dry_run_apply_and_preserves_import_parse_explanations(db_session, bank_and_job):
    bank, job, chunk = bank_and_job
    question_with_both = Question(
        bank_id=bank.id,
        question_type="single",
        content="Question with both explanations",
        options=[{"key": "A", "text": "Yes"}, {"key": "B", "text": "No"}],
        correct_answer="A",
        explanation="AI explanation",
        explanation_zh="中文 AI 解析",
        order_index=0,
    )
    question_with_zh_only = Question(
        bank_id=bank.id,
        question_type="single",
        content="Question with zh explanation only",
        options=[{"key": "A", "text": "Yes"}, {"key": "B", "text": "No"}],
        correct_answer="A",
        explanation=None,
        explanation_zh="仅中文 AI 解析",
        order_index=1,
    )
    question_without_explanation = Question(
        bank_id=bank.id,
        question_type="single",
        content="Question without explanations",
        options=[{"key": "A", "text": "Yes"}, {"key": "B", "text": "No"}],
        correct_answer="A",
        explanation=None,
        explanation_zh=None,
        order_index=2,
    )
    parsed = _parsed_row(job, chunk, explanation="导入解析必须保留")
    db_session.add_all([question_with_both, question_with_zh_only, question_without_explanation, parsed])
    db_session.commit()

    dry_run = clear_question_explanations(db_session, apply=False)
    db_session.refresh(question_with_both)
    db_session.refresh(question_with_zh_only)
    db_session.refresh(parsed)

    assert dry_run.matched == 2
    assert dry_run.updated == 0
    assert question_with_both.explanation == "AI explanation"
    assert question_with_both.explanation_zh == "中文 AI 解析"
    assert question_with_zh_only.explanation_zh == "仅中文 AI 解析"
    assert parsed.explanation == "导入解析必须保留"

    applied = clear_question_explanations(db_session, apply=True)
    db_session.refresh(question_with_both)
    db_session.refresh(question_with_zh_only)
    db_session.refresh(question_without_explanation)
    db_session.refresh(parsed)

    assert applied.matched == 2
    assert applied.updated == 2
    assert question_with_both.explanation is None
    assert question_with_both.explanation_zh is None
    assert question_with_zh_only.explanation is None
    assert question_with_zh_only.explanation_zh is None
    assert question_without_explanation.explanation is None
    assert question_without_explanation.explanation_zh is None
    assert parsed.explanation == "导入解析必须保留"


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
