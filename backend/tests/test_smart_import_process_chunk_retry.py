"""PR-2 单元测试：_process_chunk 的 L1 重试 + L2 单题降级状态机。

覆盖路径（PR-2 design G.1，TC-1 ~ TC-12）：

    TC-1  正常一次成功 → status=parsed；call_ai_api 调用 1 次；无重试/降级元数据。
    TC-2  L1 重试 1 次后成功 → status=parsed_retry；retry_count=1；写缓存。
    TC-3  L1 用尽 → L2 全部成功 → status=parsed_fallback；不写缓存。
    TC-4  L2 部分失败 → status=parsed_partial；failed_chunks++；含 per_question_failures。
    TC-5  L2 全部失败 → status=failed；failed_chunks++；不 raise（内部记账）。
    TC-6  4xx ValueError → 不重试；status=llm_failed；raise；不进 L2。
    TC-7  5xx ValueError → 走 L1 重试；行为同 TC-2。
    TC-8  Pydantic 校验失败 → 不重试；status=parse_failed；不进 L2。
    TC-9  chunk_text 无题号正则 → L2 segments=0；status=failed；
          per_question_failures.stage="L2_fallback_skipped"。
    TC-10 L1 重试时不再查缓存 → _lookup_llm_cache 调用计数 ≤ 1。
    TC-11 重试期间不短暂 commit chunk.status="llm_failed"。
    TC-12 L2 fallback 路径不写 LlmParseCache。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

# 把 backend/ 加入 sys.path，使 `from app.services...` 可用
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import smart_import_service as svc  # noqa: E402


# ─── Fixtures / 工具 ────────────────────────────────────────────────


def _make_response_text(qno_list: list[int | str]) -> str:
    """构造一个合法的 LLM JSON 响应（含 qno_list 中每个题号）。"""
    return json.dumps({
        "questions": [
            {
                "source_question_no": str(q),
                "question_type": "single",
                "scenario": None,
                "content": f"Question {q} stem text long enough to pass schema check",
                "options": [
                    {"label": "A", "text": "Option A text"},
                    {"label": "B", "text": "Option B text"},
                    {"label": "C", "text": "Option C text"},
                    {"label": "D", "text": "Option D text"},
                ],
                "correct_answer": ["A"],
                "explanation": "",
                "references": [],
                "confidence": 0.95,
                "issues": [],
            }
            for q in qno_list
        ],
        "chunk_issues": [],
    }, ensure_ascii=False)


def _make_chunk_text(qno_list: list[int]) -> str:
    """构造一段含 qno_list 中每题一段的 chunk_text（带题号正则可命中标记）。"""
    parts = []
    for q in qno_list:
        parts.append(
            f"Question #{q} Topic 1\n"
            f"Some stem content for Q{q} that is sufficiently long.\n"
            "A. Option A\nB. Option B\nC. Option C\nD. Option D\n"
            "Correct Answer: A\n"
        )
    return "\n".join(parts)


class _CommitRecorder:
    """db.commit 拦截器：记录每次 commit 时 chunk.status 的快照。"""

    def __init__(self, chunk: Any):
        self._chunk = chunk
        self.statuses_at_commit: list[str] = []

    def __call__(self) -> None:
        self.statuses_at_commit.append(self._chunk.status)


@pytest.fixture
def fake_db_factory():
    """生成 MagicMock 形式的 db（commit 可注入 recorder）。"""

    def _factory(commit_fn=None):
        db = MagicMock(name="db")
        db.commit = commit_fn if commit_fn is not None else MagicMock(name="commit")
        db.flush = MagicMock(name="flush")
        return db

    return _factory


@pytest.fixture
def chunk_factory():
    def _factory(text: str = "", chunk_no: int = 1):
        chunk = MagicMock(name="chunk")
        chunk.id = 1
        chunk.chunk_no = chunk_no
        chunk.chunk_hash = "deadbeef" * 8
        chunk.chunk_text = text
        chunk.status = "pending"
        chunk.llm_request_json = None
        chunk.llm_response_json = None
        chunk.issues_json = None
        return chunk

    return _factory


@pytest.fixture
def import_job_factory():
    def _factory():
        job = MagicMock(name="import_job")
        job.id = 1
        job.bank_id = 1
        job.config_json = {}
        job.failed_chunks = 0
        job.parsed_questions = 0
        job.imported_questions = 0
        job.review_questions = 0
        return job

    return _factory


@pytest.fixture
def patch_io(monkeypatch):
    """通用桩：屏蔽 sleep / 缓存 IO / 入库写入；返回调用计数容器。"""
    counters: dict[str, list] = {
        "lookup_cache": [],
        "store_cache": [],
        "save_parsed": [],
        "heartbeat": [],
        "llm_calls": [],
    }

    monkeypatch.setattr(svc.time, "sleep", lambda _s: counters.setdefault("sleeps", []).append(_s))
    monkeypatch.setattr(
        svc, "_lookup_llm_cache",
        lambda db, key: counters["lookup_cache"].append(key) or None,
    )
    monkeypatch.setattr(
        svc, "_store_llm_cache",
        lambda db, key, ch, **kw: counters["store_cache"].append(key),
    )

    def _fake_save_parsed(*, db, parsed_q, import_job, chunk, chunk_text,
                          auto_import, seen_signatures=None):
        counters["save_parsed"].append(parsed_q.source_question_no)
        import_job.parsed_questions = (import_job.parsed_questions or 0) + 1

    monkeypatch.setattr(svc, "_save_parsed_question", _fake_save_parsed)

    def _fake_heartbeat(db, bg_job, **kw):
        counters["heartbeat"].append(kw.get("status_message"))

    monkeypatch.setattr(svc, "heartbeat_job", _fake_heartbeat)

    return counters


# ─── TC-1 ───────────────────────────────────────────────────────────


def test_process_chunk_normal_path_no_retry_no_regression(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """一次性成功：call_ai_api 调用 1 次，status="parsed"，不含重试/降级元数据。"""
    chunk = chunk_factory(text=_make_chunk_text([1, 2]))
    job = import_job_factory()
    db = fake_db_factory()

    def fake_call(messages, db_, scene, timeout):
        patch_io["llm_calls"].append({"timeout": timeout})
        return _make_response_text([1, 2])

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert len(patch_io["llm_calls"]) == 1
    assert patch_io["llm_calls"][0]["timeout"] == 120.0
    assert chunk.status == "parsed"
    assert chunk.issues_json["retry_count"] == 0
    assert chunk.issues_json["fallback_used"] is False
    assert chunk.issues_json["per_question_failures"] == []
    assert "fallback_meta" not in chunk.issues_json
    assert len(patch_io["store_cache"]) == 1  # 写缓存
    assert len(patch_io["save_parsed"]) == 2
    assert job.failed_chunks == 0


# ─── TC-2 ───────────────────────────────────────────────────────────


def test_process_chunk_l1_retry_succeeds(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L1 第一次 timeout，第二次成功 → status="parsed_retry"；写缓存。"""
    chunk = chunk_factory(text=_make_chunk_text([10, 11]))
    job = import_job_factory()
    db = fake_db_factory()

    call_count = {"n": 0}

    def fake_call(messages, db_, scene, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("timed out")
        return _make_response_text([10, 11])

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert call_count["n"] == 2
    assert chunk.status == "parsed_retry"
    assert chunk.issues_json["retry_count"] == 1
    assert chunk.issues_json["fallback_used"] is False
    assert len(patch_io["store_cache"]) == 1, "L1 重试成功仍应写缓存"
    assert job.failed_chunks == 0


# ─── TC-3 ───────────────────────────────────────────────────────────


def test_process_chunk_l1_exhausted_l2_all_succeed(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L1 两次 timeout → L2 单题降级，每段成功 → status="parsed_fallback"；不写缓存。"""
    qnos = [222, 223, 224]
    chunk = chunk_factory(text=_make_chunk_text(qnos))
    job = import_job_factory()
    db = fake_db_factory()

    call_state = {"l1_calls": 0}

    def fake_call(messages, db_, scene, timeout):
        # L1: 整 chunk prompt 含全部 qno；L2: 单题 prompt 仅含 1 个 qno
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        is_l1 = sum(f"Question #{q}" in user_content for q in qnos) >= 2
        if is_l1:
            call_state["l1_calls"] += 1
            raise httpx.TimeoutException("timed out")
        # L2 单题：找到当前段中的 qno
        for q in qnos:
            if f"Question #{q}" in user_content:
                return _make_response_text([q])
        raise AssertionError("L2 segment did not include a known qno marker")

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert call_state["l1_calls"] == 2  # 首次 + 1 次重试
    assert chunk.status == "parsed_fallback"
    assert chunk.issues_json["fallback_used"] is True
    assert chunk.issues_json["retry_count"] == 1
    assert chunk.issues_json["per_question_failures"] == []
    meta = chunk.issues_json["fallback_meta"]
    assert meta["total_segments"] == 3
    assert meta["succeeded"] == 3
    assert meta["failed"] == 0
    assert len(patch_io["store_cache"]) == 0, "L2 fallback 不应写缓存"
    assert job.failed_chunks == 0
    assert len(patch_io["save_parsed"]) == 3


# ─── TC-4 ───────────────────────────────────────────────────────────


def test_process_chunk_l2_partial_failure(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L2 部分失败 → status="parsed_partial"；failed_chunks++。"""
    qnos = [301, 302, 303]
    chunk = chunk_factory(text=_make_chunk_text(qnos))
    job = import_job_factory()
    db = fake_db_factory()

    def fake_call(messages, db_, scene, timeout):
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        is_l1 = sum(f"Question #{q}" in user_content for q in qnos) >= 2
        if is_l1:
            raise httpx.TimeoutException("timed out")
        # L2: qno=302 失败，其余成功
        if "Question #302" in user_content:
            raise httpx.TimeoutException("single-q timeout")
        for q in qnos:
            if f"Question #{q}" in user_content:
                return _make_response_text([q])
        raise AssertionError("L2 segment did not include a known qno marker")

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert chunk.status == "parsed_partial"
    assert chunk.issues_json["fallback_used"] is True
    failures = chunk.issues_json["per_question_failures"]
    assert len(failures) == 1
    assert failures[0]["source_question_no"] == "302"
    assert failures[0]["stage"] == "L2_fallback"
    assert "TimeoutException" in failures[0]["error"]
    assert job.failed_chunks == 1
    assert len(patch_io["save_parsed"]) == 2  # 仅 301、303 入库
    assert len(patch_io["store_cache"]) == 0


# ─── TC-5 ───────────────────────────────────────────────────────────


def test_process_chunk_l2_all_fail(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L2 全部失败 → status="failed"；failed_chunks++；不 raise。"""
    qnos = [501, 502]
    chunk = chunk_factory(text=_make_chunk_text(qnos))
    job = import_job_factory()
    db = fake_db_factory()

    def fake_call(messages, db_, scene, timeout):
        # 所有调用全部 timeout
        raise httpx.TimeoutException("always timeout")

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    # 不 raise（_process_chunk 应内部记账并 return）
    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert chunk.status == "failed"
    failures = chunk.issues_json["per_question_failures"]
    assert len(failures) == 2
    assert {f["source_question_no"] for f in failures} == {"501", "502"}
    assert all(f["stage"] == "L2_fallback" for f in failures)
    assert job.failed_chunks == 1
    assert len(patch_io["save_parsed"]) == 0
    assert len(patch_io["store_cache"]) == 0


# ─── TC-6 ───────────────────────────────────────────────────────────


def test_process_chunk_4xx_value_error_no_retry(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """4xx ValueError 不重试 → status="llm_failed"；外层 raise。"""
    chunk = chunk_factory(text=_make_chunk_text([1]))
    job = import_job_factory()
    db = fake_db_factory()

    call_count = {"n": 0}

    def fake_call(messages, db_, scene, timeout):
        call_count["n"] += 1
        raise ValueError("AI API 错误 (400): bad request")

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    with pytest.raises(ValueError):
        svc._process_chunk(
            db=db, chunk=chunk, import_job=job,
            auto_import=True, use_llm_cache=True, seen_signatures=set(),
        )

    assert call_count["n"] == 1, "4xx 不应触发重试"
    assert chunk.status == "llm_failed"
    assert chunk.issues_json["retry_count"] == 0
    assert chunk.issues_json["fallback_used"] is False
    assert chunk.issues_json["per_question_failures"] == []
    assert len(patch_io["save_parsed"]) == 0
    assert len(patch_io["store_cache"]) == 0


# ─── TC-7 ───────────────────────────────────────────────────────────


def test_process_chunk_5xx_value_error_does_retry(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """5xx ValueError 进入 L1 重试 → 第二次成功 → status="parsed_retry"。"""
    chunk = chunk_factory(text=_make_chunk_text([7]))
    job = import_job_factory()
    db = fake_db_factory()

    call_count = {"n": 0}

    def fake_call(messages, db_, scene, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValueError("AI API 错误 (502): bad gateway")
        return _make_response_text([7])

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert call_count["n"] == 2
    assert chunk.status == "parsed_retry"
    assert chunk.issues_json["retry_count"] == 1
    assert chunk.issues_json["fallback_used"] is False
    assert job.failed_chunks == 0


# ─── TC-8 ───────────────────────────────────────────────────────────


def test_process_chunk_pydantic_failure_no_retry(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """LLM 返回的 JSON 格式错误（Pydantic 校验失败）→ 不重试，不进 L2 → status="parse_failed"。"""
    chunk = chunk_factory(text=_make_chunk_text([1]))
    job = import_job_factory()
    db = fake_db_factory()

    call_count = {"n": 0}

    def fake_call(messages, db_, scene, timeout):
        call_count["n"] += 1
        # 返回缺少必填字段的 JSON（Pydantic 校验会失败：缺少 content / options）
        return json.dumps({"questions": [{"source_question_no": "1"}], "chunk_issues": []})

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    with pytest.raises(Exception):
        svc._process_chunk(
            db=db, chunk=chunk, import_job=job,
            auto_import=True, use_llm_cache=True, seen_signatures=set(),
        )

    assert call_count["n"] == 1, "Pydantic 失败不应触发 L1 重试或 L2"
    assert chunk.status == "parse_failed"
    assert len(patch_io["save_parsed"]) == 0
    assert len(patch_io["store_cache"]) == 0


# ─── TC-9 ───────────────────────────────────────────────────────────


def test_process_chunk_l2_segment_zero(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L2 切段为 0（chunk_text 无题号正则命中）→ status="failed"；
    per_question_failures 含 stage="L2_fallback_skipped"。
    """
    chunk = chunk_factory(text="Some prose paragraph without any question markers.")
    job = import_job_factory()
    db = fake_db_factory()

    def fake_call(messages, db_, scene, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert chunk.status == "failed"
    failures = chunk.issues_json["per_question_failures"]
    assert len(failures) == 1
    assert failures[0]["stage"] == "L2_fallback_skipped"
    assert failures[0]["error"] == "no_question_markers"
    assert job.failed_chunks == 1


# ─── TC-10 ──────────────────────────────────────────────────────────


def test_process_chunk_l1_retry_does_not_recheck_cache(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L1 重试期间不应再次查 LlmParseCache（缓存键按 chunk_hash，不会突然出现新条目）。"""
    chunk = chunk_factory(text=_make_chunk_text([1]))
    job = import_job_factory()
    db = fake_db_factory()

    call_count = {"n": 0}

    def fake_call(messages, db_, scene, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("timed out")
        return _make_response_text([1])

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert len(patch_io["lookup_cache"]) == 1, (
        f"_lookup_llm_cache 应只在入口被查询 1 次；实际 {len(patch_io['lookup_cache'])} 次"
    )


# ─── TC-11 ──────────────────────────────────────────────────────────


def test_process_chunk_status_resets_on_retry(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L1 重试期间不应短暂 commit chunk.status="llm_failed"。"""
    chunk = chunk_factory(text=_make_chunk_text([1]))
    job = import_job_factory()
    recorder = _CommitRecorder(chunk)
    db = fake_db_factory(commit_fn=recorder)

    call_count = {"n": 0}

    def fake_call(messages, db_, scene, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("timed out")
        return _make_response_text([1])

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert chunk.status == "parsed_retry"
    assert "llm_failed" not in recorder.statuses_at_commit, (
        f"重试期间 chunk.status 不应短暂 commit 为 'llm_failed'；"
        f"实际 commit 序列：{recorder.statuses_at_commit}"
    )
    # 同样不应短暂 parse_failed（不存在中间失败状态写入）
    assert "parse_failed" not in recorder.statuses_at_commit


# ─── TC-12 ──────────────────────────────────────────────────────────


def test_process_chunk_l2_fallback_does_not_write_cache(
    monkeypatch, patch_io, fake_db_factory, chunk_factory, import_job_factory,
):
    """L2 fallback 路径（即使全部成功）不写 LlmParseCache。"""
    qnos = [801, 802]
    chunk = chunk_factory(text=_make_chunk_text(qnos))
    job = import_job_factory()
    db = fake_db_factory()

    def fake_call(messages, db_, scene, timeout):
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        is_l1 = sum(f"Question #{q}" in user_content for q in qnos) >= 2
        if is_l1:
            raise httpx.TimeoutException("timed out")
        for q in qnos:
            if f"Question #{q}" in user_content:
                return _make_response_text([q])
        raise AssertionError("L2 segment did not include a known qno marker")

    monkeypatch.setattr(svc, "call_ai_api", fake_call)

    svc._process_chunk(
        db=db, chunk=chunk, import_job=job,
        auto_import=True, use_llm_cache=True, seen_signatures=set(),
    )

    assert chunk.status == "parsed_fallback"
    assert len(patch_io["store_cache"]) == 0, (
        "L2 fallback 不应触发 _store_llm_cache"
    )
