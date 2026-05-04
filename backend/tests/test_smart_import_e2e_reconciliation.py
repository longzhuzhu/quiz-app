"""PR-4 集成测试：reconciliation 报告 + logger 补齐 + E2E 链路。

覆盖路径（PR-4 design E.5，TC-1 ~ TC-7）：

    TC-1  31 chunk 全部一次成功 → reconciliation 全绿（missing_qnos=[],
          duplicates_in_db=[], per_question_failures_count=0）。
    TC-2  chunk 27 L1 重试 1 次后成功 → status="parsed_retry"，missing_qnos=[]。
    TC-3  chunk 27 L1 用尽 → L2 24 段全部成功 → status="parsed_fallback"，
          missing_qnos=[]；caplog 中含 "entering L2 per-question fallback" warning。
    TC-4  chunk 27 L2 部分失败（222-225 timeout）→ status="parsed_partial"，
          missing_qnos == ["222","223","224","225"]，per_question_failures_count == 4。
    TC-5  在 TC-4 状态基础上跑 run_reparse（fake 切换为全成功）→ reconciliation
          重算后 missing_qnos == []，且 reparse 不污染 expected_qnos。
    TC-6  _finalize_import 不会 clobber config_json 中已有的 answer_key_text /
          expected_qnos / 其它键（dict spread 协议）。
    TC-7  serialize_import_job 暴露 reconciliation 顶层字段（None / 完整传出）。

关键设计（参见 .trellis/tasks/05-04-smart-import-cipt-283-pdf/research/pr4-design-reconciliation.md）：

* 方案 c：纯 chunk fixture + monkeypatch.setattr(call_ai_api)。**不依赖 pdfplumber**。
* in-memory SQLite + Base.metadata.create_all；JSONB 通过 @compiles 钩子降级为 JSON。
* 不调 run_smart_import（避免 PDF 抽取依赖），直接 setup ImportJob + 31 chunks
  → 模拟 run_smart_import 切片后阶段：写 expected_qnos → 循环 _process_chunk → _finalize_import。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

# 把 backend/ 加入 sys.path，使 `from app.services...` 可用
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# JSONB → JSON 兼容（必须在 import models 前完成）
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    """SQLAlchemy 在 SQLite 方言下把 JSONB 编译为 JSON（仅测试态）。"""
    return "JSON"


from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models.background_job import BackgroundJob  # noqa: E402
from app.models.bank_word import BankWordExclusion, BankWordFrequency  # noqa: E402
from app.models.import_chunk import ImportChunk  # noqa: E402
from app.models.import_job import ImportJob  # noqa: E402
from app.models.import_parsed_question import ImportParsedQuestion  # noqa: E402
from app.models.import_review_item import ImportReviewItem  # noqa: E402
from app.models.llm_parse_cache import LlmParseCache  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.question_bank import QuestionBank  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.vocabulary import Vocabulary  # noqa: E402
from app.services import smart_import_service as svc  # noqa: E402


# ─── CIPT 31 chunk 题号分布（来自 diagnosis-step0.md B.2 表） ────────

CHUNK_DISTRIBUTION = [
    (1, 1, 4), (2, 5, 9), (3, 10, 18), (4, 19, 29), (5, 30, 40),
    (6, 41, 46), (7, 47, 53), (8, 54, 64), (9, 65, 69), (10, 70, 73),
    (11, 74, 83), (12, 84, 86), (13, 87, 91), (14, 92, 97), (15, 98, 106),
    (16, 107, 112), (17, 113, 117), (18, 118, 125), (19, 126, 128),
    (20, 129, 136), (21, 137, 151), (22, 152, 173), (23, 174, 188),
    (24, 189, 202), (25, 203, 205), (26, 206, 221),
    (27, 222, 245),                              # ← timeout 重灾区
    (28, 246, 263), (29, 264, 266), (30, 267, 279), (31, 280, 283),
]
# 题号并集 = {1..283}，共 283 题
assert sum(end - start + 1 for _, start, end in CHUNK_DISTRIBUTION) == 283
CHUNK_27_QNOS = {str(n) for n in range(222, 246)}


# ─── 工具函数 ────────────────────────────────────────────────────────


def make_chunk_text(start: int, end: int) -> str:
    """构造一段含 [start..end] 每题一段的 chunk_text，可被 _split_by_single_question 切分。"""
    parts: list[str] = []
    for n in range(start, end + 1):
        parts.append(
            f"Question #{n} Topic 1\n"
            f"SCENARIO: stub stem text for question {n} that is sufficiently long.\n"
            f"A. Option A for {n}\n"
            f"B. Option B for {n}\n"
            f"C. Option C for {n}\n"
            f"D. Option D for {n}\n"
            f"Correct Answer: A\n"
        )
    return "\n".join(parts)


def make_response_text(qnos: list[int | str]) -> str:
    """构造合法的 LLM JSON 响应（含给定题号清单）。"""
    return json.dumps({
        "questions": [
            {
                "source_question_no": str(q),
                "question_type": "single",
                "scenario": None,
                "content": (
                    f"Stub stem for question {q} that is sufficiently long for "
                    "schema check (more than ten characters)."
                ),
                "options": [
                    {"label": "A", "text": f"Option A for {q}"},
                    {"label": "B", "text": f"Option B for {q}"},
                    {"label": "C", "text": f"Option C for {q}"},
                    {"label": "D", "text": f"Option D for {q}"},
                ],
                "correct_answer": ["A"],
                "explanation": "",
                "references": [],
                "confidence": 0.95,
                "issues": [],
            }
            for q in qnos
        ],
        "chunk_issues": [],
    }, ensure_ascii=False)


def extract_qnos_from_messages(messages: list[dict]) -> list[str]:
    """从 LLM messages 中抽取 chunk_text 里的题号（"Question #N" / "Question N"）。"""
    import re
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    return re.findall(r"Question\s+#?(\d+)", user_content)


def make_fake_call_ai_api(behavior: str = "ALL_OK"):
    """生成 fake_call_ai_api 闭包。

    behavior 取值：
        - "ALL_OK"              : 所有调用正常返回。
        - "L1_RETRY_THEN_OK"    : chunk 27 整体调用第 1 次抛 TimeoutException，第 2 次成功。
        - "L2_FALLBACK"         : chunk 27 整体调用永远 timeout（L1 用尽）；
                                   单题调用全部正常返回。
        - "L2_PARTIAL_FAILURE"  : chunk 27 整体调用永远 timeout；单题调用中
                                   222/223/224/225 抛 timeout，其余正常。
    """
    state: dict = {"l1_chunk27_calls": 0}

    def fake(messages, db, scene="default", timeout=60.0):
        qnos = extract_qnos_from_messages(messages)
        qno_set = set(qnos)
        is_chunk_27_l1 = qno_set == CHUNK_27_QNOS
        is_chunk_27_single = len(qnos) == 1 and qnos[0] in CHUNK_27_QNOS

        if behavior == "ALL_OK":
            return make_response_text(qnos)

        if behavior == "L1_RETRY_THEN_OK":
            if is_chunk_27_l1:
                state["l1_chunk27_calls"] += 1
                if state["l1_chunk27_calls"] == 1:
                    raise httpx.TimeoutException("chunk 27 first attempt timed out")
                return make_response_text(qnos)
            return make_response_text(qnos)

        if behavior == "L2_FALLBACK":
            if is_chunk_27_l1:
                state["l1_chunk27_calls"] += 1
                raise httpx.TimeoutException("chunk 27 L1 always times out")
            # 单题或其它 chunk → 正常返回
            return make_response_text(qnos)

        if behavior == "L2_PARTIAL_FAILURE":
            if is_chunk_27_l1:
                state["l1_chunk27_calls"] += 1
                raise httpx.TimeoutException("chunk 27 L1 always times out")
            if is_chunk_27_single and qnos[0] in {"222", "223", "224", "225"}:
                raise httpx.TimeoutException(f"single question {qnos[0]} timed out")
            return make_response_text(qnos)

        raise AssertionError(f"unknown behavior: {behavior!r}")

    fake.state = state  # type: ignore[attr-defined]
    return fake


# ─── DB / 应用层 fixtures ────────────────────────────────────────────


@pytest.fixture
def db_session():
    """in-memory SQLite + Base.metadata.create_all，每个测试独立。"""
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
def patch_runtime(monkeypatch):
    """屏蔽 backoff sleep 与 heartbeat（heartbeat 会查 BackgroundJob 已 lease 字段，避免噪声）。"""
    monkeypatch.setattr(svc.time, "sleep", lambda _s: None)
    # heartbeat_job 在测试中不需要真实续约，捕获并 noop
    monkeypatch.setattr(svc, "heartbeat_job", lambda db, bg_job, **kw: None)


def setup_bank_and_job(db, *, with_expected: bool = True) -> tuple[QuestionBank, ImportJob]:
    """创建 QuestionBank + ImportJob（含 31 个 ImportChunk）。"""
    bank = QuestionBank(name="CIPT Test Bank", description="e2e test")
    db.add(bank)
    db.flush()

    job = ImportJob(
        bank_id=bank.id,
        file_name="CIPT 283题.pdf",
        file_path="/tmp/fake.pdf",
        file_hash="deadbeef" * 8,
        file_type="pdf",
        status="parsing",
        total_pages=178,
        total_chunks=31,
    )
    db.add(job)
    db.flush()

    # 构造 31 个 ImportChunk
    import hashlib
    for chunk_no, start, end in CHUNK_DISTRIBUTION:
        chunk_text = make_chunk_text(start, end)
        chunk = ImportChunk(
            import_job_id=job.id,
            chunk_no=chunk_no,
            chunk_text=chunk_text,
            chunk_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
            status="pending",
            start_page=None,
            end_page=None,
        )
        db.add(chunk)
    db.flush()

    if with_expected:
        # 模拟 run_smart_import 切完 chunk 后写入 expected_qnos
        expected: set[str] = set()
        for _, start, end in CHUNK_DISTRIBUTION:
            for n in range(start, end + 1):
                expected.add(str(n))
        job.config_json = {
            "expected_qnos": sorted(expected, key=svc._qno_sort_key),
            "auto_import": True,
        }

    db.commit()
    return bank, job


def run_e2e_pipeline(db, job: ImportJob, *, auto_import: bool = True) -> None:
    """模拟 run_smart_import 切片后阶段：循环 _process_chunk → _finalize_import。

    跳过 PDF 抽取 / 切片本身（已通过 setup_bank_and_job 的 chunks 表预置）。
    """
    chunks = (
        db.query(ImportChunk)
        .filter_by(import_job_id=job.id)
        .order_by(ImportChunk.chunk_no.asc())
        .all()
    )
    seen_signatures: set = set()
    for chunk in chunks:
        try:
            svc._process_chunk(
                db=db,
                chunk=chunk,
                import_job=job,
                auto_import=auto_import,
                use_llm_cache=False,        # 测试不走缓存路径
                seen_signatures=seen_signatures,
                bg_job=None,
                imported_qnos=None,
            )
        except Exception as exc:  # 模拟 run_smart_import 外层 except 兜底
            chunk.status = "failed"
            chunk.issues_json = {"error": str(exc)}
            job.failed_chunks = (job.failed_chunks or 0) + 1
            db.commit()

    svc._finalize_import(db, job)


# ─── TC-1 ────────────────────────────────────────────────────────────


def test_smart_import_e2e_full_success(monkeypatch, db_session, patch_runtime):
    """31 chunk 全部一次成功 → reconciliation 字段全绿。"""
    monkeypatch.setattr(svc, "call_ai_api", make_fake_call_ai_api("ALL_OK"))
    _, job = setup_bank_and_job(db_session)

    run_e2e_pipeline(db_session, job)

    db_session.refresh(job)
    recon = (job.config_json or {}).get("reconciliation")
    assert recon is not None, "_finalize_import 未写入 reconciliation"
    assert len(recon["expected"]) == 283
    assert len(recon["imported_unique"]) == 283
    assert recon["missing_qnos"] == []
    assert recon["duplicates_in_db"] == []
    assert recon["per_question_failures_count"] == 0
    # computed_at 必须可解析为 ISO8601
    assert datetime.fromisoformat(recon["computed_at"]) is not None
    assert job.status == "imported"
    assert job.imported_questions == 283


# ─── TC-2 ────────────────────────────────────────────────────────────


def test_smart_import_e2e_chunk_27_recovers_via_l1_retry(
    monkeypatch, db_session, patch_runtime,
):
    """chunk 27 L1 第 1 次 timeout、第 2 次成功 → status='parsed_retry'，missing=[]。"""
    monkeypatch.setattr(svc, "call_ai_api", make_fake_call_ai_api("L1_RETRY_THEN_OK"))
    _, job = setup_bank_and_job(db_session)

    run_e2e_pipeline(db_session, job)

    db_session.refresh(job)
    recon = (job.config_json or {})["reconciliation"]
    assert recon["missing_qnos"] == []
    assert len(recon["imported_unique"]) == 283

    chunk_27 = (
        db_session.query(ImportChunk)
        .filter_by(import_job_id=job.id, chunk_no=27)
        .one()
    )
    assert chunk_27.status == "parsed_retry"
    assert chunk_27.issues_json["retry_count"] == 1
    assert chunk_27.issues_json["fallback_used"] is False


# ─── TC-3 ────────────────────────────────────────────────────────────


def test_smart_import_e2e_chunk_27_recovers_via_l2_fallback(
    monkeypatch, db_session, patch_runtime, caplog,
):
    """chunk 27 L1 用尽 → L2 24 段全部成功；caplog 含 'entering L2' warning。"""
    monkeypatch.setattr(svc, "call_ai_api", make_fake_call_ai_api("L2_FALLBACK"))
    _, job = setup_bank_and_job(db_session)

    with caplog.at_level(logging.WARNING, logger="app.services.smart_import_service"):
        run_e2e_pipeline(db_session, job)

    db_session.refresh(job)
    recon = (job.config_json or {})["reconciliation"]
    assert recon["missing_qnos"] == []
    assert len(recon["imported_unique"]) == 283

    chunk_27 = (
        db_session.query(ImportChunk)
        .filter_by(import_job_id=job.id, chunk_no=27)
        .one()
    )
    assert chunk_27.status == "parsed_fallback"
    assert chunk_27.issues_json["fallback_used"] is True
    assert chunk_27.issues_json["per_question_failures"] == []

    # caplog 验证 logger 命中（PR-4 5 处之一：L2 启动 warning）
    l2_entering = [
        rec for rec in caplog.records
        if "entering L2 per-question fallback" in rec.message
    ]
    assert l2_entering, "未捕获 L2 entering warning（logger 可能未生效）"
    # 至少 1 条 L1 retry warning（L1 重试链路）
    l1_retry = [rec for rec in caplog.records if "L1 retry" in rec.message]
    assert l1_retry, "未捕获 L1 retry warning"


# ─── TC-4 ────────────────────────────────────────────────────────────


def test_smart_import_e2e_chunk_27_l2_partial_failure(
    monkeypatch, db_session, patch_runtime,
):
    """chunk 27 L2 中 222/223/224/225 timeout → status='parsed_partial'，missing=4 题。"""
    monkeypatch.setattr(svc, "call_ai_api", make_fake_call_ai_api("L2_PARTIAL_FAILURE"))
    _, job = setup_bank_and_job(db_session)

    run_e2e_pipeline(db_session, job)

    db_session.refresh(job)
    recon = (job.config_json or {})["reconciliation"]
    assert set(recon["missing_qnos"]) == {"222", "223", "224", "225"}
    assert recon["per_question_failures_count"] == 4
    assert len(recon["imported_unique"]) == 279

    chunk_27 = (
        db_session.query(ImportChunk)
        .filter_by(import_job_id=job.id, chunk_no=27)
        .one()
    )
    assert chunk_27.status == "parsed_partial"
    failures = chunk_27.issues_json["per_question_failures"]
    assert len(failures) == 4
    assert {f["source_question_no"] for f in failures} == {"222", "223", "224", "225"}
    # _finalize_import 把 partial chunk 触发的 failed_chunks 转为 partial_imported
    assert job.failed_chunks == 1
    assert job.status == "partial_imported"


# ─── TC-5 ────────────────────────────────────────────────────────────


def test_run_reparse_recovers_partial_chunk(
    monkeypatch, db_session, patch_runtime,
):
    """先制造 TC-4 partial 状态 → 跑 run_reparse（fake 切回全成功）→ missing=[]。"""
    # 阶段 1：TC-4 partial 状态
    fake_partial = make_fake_call_ai_api("L2_PARTIAL_FAILURE")
    monkeypatch.setattr(svc, "call_ai_api", fake_partial)
    _, job = setup_bank_and_job(db_session)
    run_e2e_pipeline(db_session, job)

    db_session.refresh(job)
    assert set((job.config_json or {})["reconciliation"]["missing_qnos"]) == {
        "222", "223", "224", "225"
    }
    expected_before = list((job.config_json or {})["expected_qnos"])

    # 阶段 2：reparse chunk 27（切换到全成功 fake）
    monkeypatch.setattr(svc, "call_ai_api", make_fake_call_ai_api("ALL_OK"))
    chunk_27 = (
        db_session.query(ImportChunk)
        .filter_by(import_job_id=job.id, chunk_no=27)
        .one()
    )
    bg_job = BackgroundJob(
        job_type=svc.JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE,
        scope_key=f"reparse:chunk:{chunk_27.id}",
        payload_json=json.dumps({
            "import_job_id": job.id,
            "chunk_id": chunk_27.id,
            "bank_id": job.bank_id,
        }),
        status="running",
        created_by=1,
    )
    db_session.add(bg_job)
    db_session.commit()

    svc.run_reparse(db_session, bg_job)

    db_session.refresh(job)
    recon_after = (job.config_json or {})["reconciliation"]
    assert recon_after["missing_qnos"] == [], (
        f"reparse 后 missing_qnos 应为空，实际 = {recon_after['missing_qnos']}"
    )
    assert len(recon_after["imported_unique"]) == 283
    # AC3：reparse 不污染 expected_qnos
    assert (job.config_json or {})["expected_qnos"] == expected_before


# ─── TC-6 ────────────────────────────────────────────────────────────


def test_finalize_import_does_not_clobber_existing_config_json(
    monkeypatch, db_session, patch_runtime,
):
    """_finalize_import 写入 reconciliation 不应覆盖 config_json 中其它键。"""
    bank = QuestionBank(name="ConfigPreserveBank")
    db_session.add(bank)
    db_session.flush()

    job = ImportJob(
        bank_id=bank.id,
        file_name="x.pdf",
        file_path="/tmp/x.pdf",
        file_hash="ab" * 32,
        file_type="pdf",
        status="parsing",
        config_json={
            "answer_key_text": "1.A\n2.B",
            "expected_qnos": ["1", "2"],
            "auto_import": True,
            "custom_marker": "preserve_me",
        },
    )
    db_session.add(job)
    db_session.commit()

    svc._finalize_import(db_session, job)

    db_session.refresh(job)
    config = job.config_json or {}
    assert config.get("answer_key_text") == "1.A\n2.B", "answer_key_text 被覆盖"
    assert config.get("expected_qnos") == ["1", "2"], "expected_qnos 被覆盖"
    assert config.get("auto_import") is True, "auto_import 被覆盖"
    assert config.get("custom_marker") == "preserve_me", "custom_marker 被覆盖"
    assert "reconciliation" in config, "_finalize_import 未写入 reconciliation"


# ─── TC-7 ────────────────────────────────────────────────────────────


def test_serialize_import_job_exposes_reconciliation_field(db_session):
    """serialize_import_job 应暴露 reconciliation 顶层字段（None / 完整传出）。"""
    bank = QuestionBank(name="SerializeBank")
    db_session.add(bank)
    db_session.flush()

    # 场景 A：未跑 finalize（config_json 不含 reconciliation）→ reconciliation == None
    job_a = ImportJob(
        bank_id=bank.id,
        file_name="a.pdf",
        file_path="/tmp/a.pdf",
        file_hash="cd" * 32,
        file_type="pdf",
        status="parsing",
        config_json=None,
    )
    db_session.add(job_a)
    db_session.commit()
    db_session.refresh(job_a)

    serialized_a = svc.serialize_import_job(job_a)
    assert "reconciliation" in serialized_a
    assert serialized_a["reconciliation"] is None

    # 场景 B：手动写 reconciliation → 完整传出
    recon_payload = {
        "expected": ["1", "2", "3"],
        "imported_unique": ["1", "2", "3"],
        "missing_qnos": [],
        "duplicates_in_db": [],
        "per_question_failures_count": 0,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    job_b = ImportJob(
        bank_id=bank.id,
        file_name="b.pdf",
        file_path="/tmp/b.pdf",
        file_hash="ef" * 32,
        file_type="pdf",
        status="imported",
        config_json={
            "expected_qnos": ["1", "2", "3"],
            "reconciliation": recon_payload,
        },
    )
    db_session.add(job_b)
    db_session.commit()
    db_session.refresh(job_b)

    serialized_b = svc.serialize_import_job(job_b)
    assert serialized_b["reconciliation"] == recon_payload
