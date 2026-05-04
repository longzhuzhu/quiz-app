"""PR-3 单元测试：reparse 卫生 + imported_qnos 题号去重。

覆盖路径（PR-3 design H.2，TC-1 ~ TC-8）：

    TC-1  imported_qnos 命中题号 → DUPLICATE_QNO 路径（issues.details[0].reason="qno"）；
          不调 _write_question_to_bank；parsed_questions += 1，imported_questions 不变。
    TC-2  imported_qnos 不命中 → 走正常 quality_check + auto_import 路径。
    TC-3  imported_qnos=None（默认）→ 完全跳过 DUPLICATE_QNO 检查（向后兼容）。
    TC-4  run_reparse 从 ImportParsedQuestion 表（import_status='imported'）构建
          imported_qnos；'skipped' / 'pending' / 'waiting' 行不进集合。
    TC-5  run_reparse 调 _process_chunk 时透传 bg_job=background_job（PR-2 留的尾巴）。
    TC-6  _normalize_qno 处理 ' #222 ' / '#223' / '224' 等格式漂移；
          parsed_q.source_question_no=' 222 ' 命中 imported_qnos={'222'}。
    TC-7  对 imported 题号反复 reparse 不会再次写 Question；DUPLICATE_QNO 行重复累积，
          原 imported 行从未被删（run_reparse 入口跳过 import_status='imported'）。
    TC-8  DUPLICATE_QNO 路径不污染 seen_signatures（不调 .add）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# 把 backend/ 加入 sys.path，使 `from app.services...` 可用
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.import_parsed_question import ImportParsedQuestion  # noqa: E402
from app.schemas.llm_parse import ParsedOption, ParsedQuestion  # noqa: E402
from app.services import smart_import_service as svc  # noqa: E402


# ─── 工具 / Fixtures ─────────────────────────────────────────────────


def _make_parsed_question(
    *,
    source_question_no: str | None = "222",
    content: str = "Stem text long enough for schema check (more than ten characters).",
    options: list[tuple[str, str]] | None = None,
    correct_answer: list[str] | None = None,
    confidence: float = 0.95,
) -> ParsedQuestion:
    """构造一个合法的 ParsedQuestion。"""
    if options is None:
        options = [("A", "Option A text"), ("B", "Option B text"),
                   ("C", "Option C text"), ("D", "Option D text")]
    return ParsedQuestion(
        source_question_no=source_question_no,
        question_type="single",
        scenario=None,
        content=content,
        options=[ParsedOption(label=lbl, text=txt) for lbl, txt in options],
        correct_answer=correct_answer if correct_answer is not None else ["A"],
        explanation="",
        references=[],
        confidence=confidence,
        issues=[],
    )


class _FakeDB:
    """轻量 db 替身：捕获 add() 的对象列表、flush/commit 计数、query() 路由。

    使用方式：
        db = _FakeDB()
        db.set_query_result(Question, bank_id=1, result=[])
        db.set_query_result(ImportParsedQuestion, ..., import_status='imported', result=[...])
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0
        # query 路由表：(model_cls, frozenset(filter_kwargs.items())) -> result_list
        self._query_results: dict[tuple[Any, frozenset], list[Any]] = {}
        self._next_id = 1

    def add(self, obj: Any) -> None:
        # 模拟 PG 返回的自增 id
        if not getattr(obj, "id", None):
            try:
                obj.id = self._next_id
                self._next_id += 1
            except Exception:
                pass
        self.added.append(obj)

    def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    def flush(self) -> None:
        self.flushed += 1

    def commit(self) -> None:
        self.committed += 1

    def get(self, model: Any, pk: Any) -> Any:  # noqa: ARG002
        return None

    def set_query_result(self, model: Any, result: list[Any], **filter_kwargs: Any) -> None:
        key = (model, frozenset(filter_kwargs.items()))
        self._query_results[key] = result

    def query(self, model: Any) -> "_FakeQuery":
        return _FakeQuery(self, model)


class _FakeQuery:
    def __init__(self, db: _FakeDB, model: Any) -> None:
        self._db = db
        self._model = model
        self._filters: dict[str, Any] = {}

    def filter_by(self, **kwargs: Any) -> "_FakeQuery":
        self._filters.update(kwargs)
        return self

    def order_by(self, *_args: Any) -> "_FakeQuery":
        return self

    def all(self) -> list[Any]:
        key = (self._model, frozenset(self._filters.items()))
        return self._db._query_results.get(key, [])

    def delete(self, **_kw: Any) -> int:
        # 用于 ImportReviewItem 的 cascade delete；返回受影响行数即可
        return 0

    def first(self) -> Any:
        results = self.all()
        return results[0] if results else None

    def scalar(self) -> Any:
        return None


def _make_import_job() -> Any:
    job = MagicMock(name="import_job")
    job.id = 7
    job.bank_id = 4
    job.config_json = {"auto_import": True}
    job.failed_chunks = 0
    job.parsed_questions = 0
    job.imported_questions = 0
    job.review_questions = 0
    job.review_status = "pending"
    return job


def _make_chunk(chunk_no: int = 1) -> Any:
    chunk = MagicMock(name="chunk")
    chunk.id = chunk_no
    chunk.chunk_no = chunk_no
    chunk.import_job_id = 7
    chunk.chunk_text = ""
    chunk.chunk_hash = "deadbeef" * 8
    chunk.status = "pending"
    chunk.llm_request_json = None
    chunk.llm_response_json = None
    chunk.issues_json = None
    return chunk


# ─── TC-1 ────────────────────────────────────────────────────────────


def test_save_parsed_question_qno_in_imported_qnos_goes_duplicate(monkeypatch):
    """imported_qnos 命中题号 → 走 DUPLICATE 路径（reason='qno'），
    不调 _write_question_to_bank，parsed_questions += 1，imported_questions 不变。
    """
    db = _FakeDB()
    job = _make_import_job()
    chunk = _make_chunk()
    parsed_q = _make_parsed_question(source_question_no="222")

    # 哨兵：保证 _write_question_to_bank 不应被触发
    write_calls: list[Any] = []
    monkeypatch.setattr(
        svc, "_write_question_to_bank",
        lambda *a, **kw: write_calls.append((a, kw)) or MagicMock(id=999),
    )

    seen_signatures: set = set()
    svc._save_parsed_question(
        db=db,
        parsed_q=parsed_q,
        import_job=job,
        chunk=chunk,
        chunk_text="",
        auto_import=True,
        seen_signatures=seen_signatures,
        imported_qnos={"222"},
    )

    assert len(db.added) == 1, "DUPLICATE_QNO 路径应仅 db.add 一行"
    pq_row = db.added[0]
    assert isinstance(pq_row, ImportParsedQuestion)
    assert pq_row.review_status == "duplicate"
    assert pq_row.import_status == "skipped"

    issues = pq_row.issues_json
    assert issues["issues"] == ["DUPLICATE"]
    assert issues["details"][0]["code"] == "DUPLICATE"
    assert issues["details"][0]["reason"] == "qno"
    assert issues["details"][0]["severity"] == "LOW"

    assert job.parsed_questions == 1
    assert job.imported_questions == 0
    assert job.review_questions == 0

    assert write_calls == [], "DUPLICATE_QNO 路径绝不应调用 _write_question_to_bank"


# ─── TC-2 ────────────────────────────────────────────────────────────


def test_save_parsed_question_qno_not_in_imported_qnos_goes_normal(monkeypatch):
    """imported_qnos 不命中题号 → 走正常路径（quality_check + 自动入库 / ReviewItem）。"""
    db = _FakeDB()
    job = _make_import_job()
    chunk = _make_chunk()
    parsed_q = _make_parsed_question(source_question_no="999")

    written_questions: list[Any] = []

    def _fake_write(db_, pq, bank_id):
        q = MagicMock(name="question")
        q.id = 12345
        written_questions.append(q)
        return q

    monkeypatch.setattr(svc, "_write_question_to_bank", _fake_write)

    svc._save_parsed_question(
        db=db,
        parsed_q=parsed_q,
        import_job=job,
        chunk=chunk,
        chunk_text=parsed_q.content,
        auto_import=True,
        seen_signatures=set(),
        imported_qnos={"100", "200"},  # 999 不在集合内
    )

    # 应有 1 个 ImportParsedQuestion 被 add（不是 DUPLICATE 路径）
    pq_rows = [o for o in db.added if isinstance(o, ImportParsedQuestion)]
    assert len(pq_rows) == 1
    pq_row = pq_rows[0]
    # 不应进 DUPLICATE 路径
    assert pq_row.review_status != "duplicate"
    assert pq_row.import_status != "skipped"

    # 高质量题应自动入库
    assert len(written_questions) == 1
    assert pq_row.review_status == "auto_accepted"
    assert pq_row.import_status == "imported"
    assert job.imported_questions == 1
    assert job.parsed_questions == 1


# ─── TC-3 ────────────────────────────────────────────────────────────


def test_save_parsed_question_imported_qnos_none_keeps_legacy_behavior(monkeypatch):
    """imported_qnos=None → 完全跳过 DUPLICATE_QNO 检查（向后兼容初次导入路径）。"""
    db = _FakeDB()
    job = _make_import_job()
    chunk = _make_chunk()
    # 即使题号是常见值 "222"，也不应进 DUPLICATE_QNO 路径
    parsed_q = _make_parsed_question(source_question_no="222")

    written_questions: list[Any] = []

    def _fake_write(db_, pq, bank_id):
        q = MagicMock(name="question")
        q.id = 99
        written_questions.append(q)
        return q

    monkeypatch.setattr(svc, "_write_question_to_bank", _fake_write)

    # 哨兵：_persist_duplicate_parsed_question 绝不应被调用
    dup_calls: list[Any] = []
    real_persist = svc._persist_duplicate_parsed_question

    def _spy_persist(*args, **kwargs):
        dup_calls.append((args, kwargs))
        return real_persist(*args, **kwargs)

    monkeypatch.setattr(svc, "_persist_duplicate_parsed_question", _spy_persist)

    svc._save_parsed_question(
        db=db,
        parsed_q=parsed_q,
        import_job=job,
        chunk=chunk,
        chunk_text=parsed_q.content,
        auto_import=True,
        seen_signatures=set(),
        imported_qnos=None,  # 显式 None
    )

    assert dup_calls == [], (
        "imported_qnos=None 时 _persist_duplicate_parsed_question 不应被调用"
    )
    # 正常入库
    assert len(written_questions) == 1


# ─── TC-4 ────────────────────────────────────────────────────────────


def test_run_reparse_builds_imported_qnos_from_parsed_questions_table(monkeypatch):
    """run_reparse 从 ImportParsedQuestion (import_status='imported') 构建 imported_qnos；
    skipped / pending / waiting 行不进集合。
    """
    # 模拟 5 条 ImportParsedQuestion：3 imported + 1 skipped + 1 waiting
    pq_imported = [
        MagicMock(spec=ImportParsedQuestion, source_question_no="100",
                  import_status="imported", review_status="auto_accepted",
                  imported_question_id=1, id=1),
        MagicMock(spec=ImportParsedQuestion, source_question_no="101",
                  import_status="imported", review_status="auto_accepted",
                  imported_question_id=2, id=2),
        MagicMock(spec=ImportParsedQuestion, source_question_no="102",
                  import_status="imported", review_status="auto_accepted",
                  imported_question_id=3, id=3),
    ]
    pq_skipped = MagicMock(spec=ImportParsedQuestion, source_question_no="103",
                           import_status="skipped", review_status="duplicate",
                           imported_question_id=None, id=4)
    pq_waiting = MagicMock(spec=ImportParsedQuestion, source_question_no="104",
                           import_status="waiting", review_status="pending",
                           imported_question_id=None, id=5)

    job = MagicMock(name="import_job", id=7, bank_id=4)
    job.config_json = {"auto_import": True}
    job.review_questions = 0
    job.parsed_questions = 5
    chunk = _make_chunk(chunk_no=27)

    db = _FakeDB()
    # 直接 db.get 注入返回值
    db.get = MagicMock(side_effect=lambda model, pk:
                      job if pk == 7 else (chunk if pk == 27 else None))
    # ImportParsedQuestion.filter_by(chunk_id=27).all() —— 重置时删除"未 imported"行；
    # 这里返回与上面 5 行的 chunk_id=27 子集
    for pq in pq_imported + [pq_skipped, pq_waiting]:
        pq.chunk_id = 27
    db.set_query_result(ImportParsedQuestion,
                        chunk_id=27,
                        result=pq_imported + [pq_skipped, pq_waiting])
    # Question.filter_by(bank_id=4).all() —— seen_signatures 来源（空）
    from app.models.question import Question
    db.set_query_result(Question, bank_id=4, result=[])
    # ImportParsedQuestion.filter_by(import_job_id=7, import_status='imported').all()
    db.set_query_result(ImportParsedQuestion,
                        import_job_id=7, import_status="imported",
                        result=pq_imported)

    captured: dict[str, Any] = {}

    def _spy_process_chunk(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(svc, "_process_chunk", _spy_process_chunk)
    monkeypatch.setattr(svc, "_update_import_job_status", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_update_bank_stats", lambda *a, **k: None)

    bg_job = MagicMock(name="bg_job", id=99,
                       payload_json='{"import_job_id":7,"chunk_id":27,"bank_id":4}')

    svc.run_reparse(db, bg_job)

    assert captured["imported_qnos"] == {"100", "101", "102"}, (
        f"应仅含 import_status='imported' 行的题号；实际：{captured.get('imported_qnos')}"
    )
    assert "103" not in captured["imported_qnos"]  # skipped 行
    assert "104" not in captured["imported_qnos"]  # waiting 行


# ─── TC-5 ────────────────────────────────────────────────────────────


def test_run_reparse_passes_bg_job_to_process_chunk(monkeypatch):
    """run_reparse 调 _process_chunk 时必须透传 bg_job=background_job（PR-2 决议 4 第 3 条）。"""
    job = MagicMock(name="import_job", id=7, bank_id=4)
    job.config_json = {"auto_import": True}
    job.review_questions = 0
    chunk = _make_chunk(chunk_no=10)

    db = _FakeDB()
    db.get = MagicMock(side_effect=lambda model, pk:
                      job if pk == 7 else (chunk if pk == 10 else None))
    db.set_query_result(ImportParsedQuestion, chunk_id=10, result=[])

    from app.models.question import Question
    db.set_query_result(Question, bank_id=4, result=[])
    db.set_query_result(ImportParsedQuestion,
                        import_job_id=7, import_status="imported", result=[])

    captured: dict[str, Any] = {}

    def _spy_process_chunk(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(svc, "_process_chunk", _spy_process_chunk)
    monkeypatch.setattr(svc, "_update_import_job_status", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_update_bank_stats", lambda *a, **k: None)

    bg_job = MagicMock(name="bg_job", id=99,
                       payload_json='{"import_job_id":7,"chunk_id":10,"bank_id":4}')

    svc.run_reparse(db, bg_job)

    assert "bg_job" in captured, "_process_chunk 必须收到 bg_job kwarg"
    assert captured["bg_job"] is bg_job, (
        "bg_job 必须是 run_reparse 入参 background_job 本身（identity 比较）"
    )


# ─── TC-6 ────────────────────────────────────────────────────────────


def test_imported_qnos_normalization_strips_hash_and_whitespace(monkeypatch):
    """_normalize_qno 处理 ' #222 ' / '#223' / '224' 等格式漂移；
    parsed_q.source_question_no=' 222 ' 应命中 imported_qnos={'222'}。
    """
    # 1) 先单独验证 _normalize_qno
    assert svc._normalize_qno(" #222 ") == "222"
    assert svc._normalize_qno("#223") == "223"
    assert svc._normalize_qno("224") == "224"
    assert svc._normalize_qno("##5a##") == "5a##"  # lstrip 仅去首字符
    assert svc._normalize_qno("") is None
    assert svc._normalize_qno("   ") is None
    assert svc._normalize_qno("#") is None
    assert svc._normalize_qno(None) is None

    # 2) 验证 _save_parsed_question 入口对 parsed_q.source_question_no 也走 _normalize_qno
    db = _FakeDB()
    job = _make_import_job()
    chunk = _make_chunk()

    monkeypatch.setattr(
        svc, "_write_question_to_bank",
        lambda *a, **kw: MagicMock(id=1),
    )

    # 题号原始值带空白 + '#'，应被归一化后命中
    parsed_q_with_hash = _make_parsed_question(source_question_no=" #222 ")
    svc._save_parsed_question(
        db=db, parsed_q=parsed_q_with_hash, import_job=job, chunk=chunk,
        chunk_text="", auto_import=True,
        seen_signatures=set(), imported_qnos={"222"},
    )

    # 命中 DUPLICATE_QNO
    assert len(db.added) == 1
    pq = db.added[0]
    assert pq.review_status == "duplicate"
    assert pq.issues_json["details"][0]["reason"] == "qno"


# ─── TC-7 ────────────────────────────────────────────────────────────


def test_reparse_double_run_does_not_reimport_qno(monkeypatch):
    """对 imported 题号反复 reparse 不会再次写 Question；DUPLICATE_QNO 行重复累积。

    模拟链：
        - 已有 pq_imported (qno=222, import_status='imported') 占位（不被删除）。
        - LLM 返回的 parsed_q 题号同样是 222。
        - 调 _save_parsed_question(imported_qnos={'222'}) → 走 DUPLICATE_QNO。
    """
    db = _FakeDB()
    job = _make_import_job()
    chunk = _make_chunk(chunk_no=27)
    parsed_q = _make_parsed_question(source_question_no="222")

    # 哨兵：_write_question_to_bank 不应被触发
    write_calls: list[Any] = []
    monkeypatch.setattr(
        svc, "_write_question_to_bank",
        lambda *a, **kw: write_calls.append((a, kw)) or MagicMock(id=1),
    )

    # 第 1 次 reparse：DUPLICATE_QNO
    svc._save_parsed_question(
        db=db, parsed_q=parsed_q, import_job=job, chunk=chunk,
        chunk_text="", auto_import=True,
        seen_signatures=set(), imported_qnos={"222"},
    )
    # 第 2 次 reparse（同一题号又被 LLM 解出）：仍应是 DUPLICATE_QNO
    svc._save_parsed_question(
        db=db, parsed_q=parsed_q, import_job=job, chunk=chunk,
        chunk_text="", auto_import=True,
        seen_signatures=set(), imported_qnos={"222"},
    )

    assert write_calls == [], "Question 表绝不应被新增任何行"

    pq_rows = [o for o in db.added if isinstance(o, ImportParsedQuestion)]
    assert len(pq_rows) == 2, "两次 reparse 各写一行 DUPLICATE_QNO 占位"
    for pq in pq_rows:
        assert pq.review_status == "duplicate"
        assert pq.import_status == "skipped"
        assert pq.issues_json["details"][0]["reason"] == "qno"

    # parsed_questions 累计 +2
    assert job.parsed_questions == 2
    # imported_questions 不增长
    assert job.imported_questions == 0


# ─── TC-8 ────────────────────────────────────────────────────────────


def test_save_parsed_question_qno_collision_does_not_pollute_seen_signatures(monkeypatch):
    """DUPLICATE_QNO 命中后 seen_signatures 不应被 .add() —— 早返回路径不更新签名集合。

    与 DUPLICATE_CONTENT 路径行为对称：两条 DUPLICATE 路径都不污染签名集合。
    """
    db = _FakeDB()
    job = _make_import_job()
    chunk = _make_chunk()
    parsed_q = _make_parsed_question(source_question_no="222")

    monkeypatch.setattr(
        svc, "_write_question_to_bank",
        lambda *a, **kw: MagicMock(id=1),
    )

    seen: set = set()
    svc._save_parsed_question(
        db=db, parsed_q=parsed_q, import_job=job, chunk=chunk,
        chunk_text="", auto_import=True,
        seen_signatures=seen, imported_qnos={"222"},
    )

    assert seen == set(), (
        f"DUPLICATE_QNO 路径不应更新 seen_signatures；实际：{seen}"
    )
