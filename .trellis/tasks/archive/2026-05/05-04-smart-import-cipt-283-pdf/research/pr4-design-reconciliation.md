# PR-4 Design — reconciliation 报告 + logger 补齐 + E2E 集成测试

> 研究子代理产出，仅做静态分析；未修改任何源代码、未发起 LLM 调用。
> 数据源：`backend/app/services/smart_import_service.py`（PR-3 commit `4c5ca3e` 之后）、
> `backend/app/models/import_job.py` / `import_chunk.py` / `import_parsed_question.py`、
> `backend/app/api/routes/import_jobs.py`、
> `backend/tests/test_smart_import_process_chunk_retry.py`、`test_smart_import_reparse_hygiene.py`、
> `.trellis/spec/backend/logging-guidelines.md`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/prd.md`、
> `research/diagnosis-step0.md`、`research/pr1-design-…md`、`research/pr2-design-…md`、`research/pr3-design-…md`。

## 行号说明（PR-3 commit `4c5ca3e` 之后）

| 锚点 | 文件 : 行号 |
|---|---|
| `_normalize_qno` | `smart_import_service.py:152` |
| `run_smart_import` | `smart_import_service.py:271` |
| 切完 chunk 后写 config_json 处 | `smart_import_service.py:339-345` |
| `_process_chunk` | `smart_import_service.py:408-622` |
| `_call_llm_with_l1_retry` | `smart_import_service.py:675-712` |
| `_run_per_question_fallback` | `smart_import_service.py:715-793` |
| `_persist_duplicate_parsed_question` | `smart_import_service.py:796-859` |
| `_save_parsed_question` | `smart_import_service.py:862-…` |
| `run_reparse` | `smart_import_service.py:1108-1197` |
| `_split_into_chunks` | `smart_import_service.py:1385-1412` |
| `_split_by_question_markers` | `smart_import_service.py:1415-1454` |
| `_split_by_single_question` | `smart_import_service.py:1457-1490` |
| `_finalize_import` | `smart_import_service.py:1791-1834` |
| `serialize_import_job` | `smart_import_service.py:1891-1924` |

---

## A. expected 题号集的来源与存储

### A.1 三方案对比

| 方案 | 描述 | 评估 |
|---|---|---|
| **(a) chunk 级落库** | 切完 chunk 后，对每个 chunk 调 `_split_by_single_question(chunk.chunk_text)`；把得到的题号清单写入 `chunk.issues_json["expected_qnos_in_chunk"]`；finalize 时合并 31 个 chunk 的题号集合得到 expected | `+` 每 chunk 都有"输入题号清单"诊断价值；`+` 复用现有 `_split_by_single_question`。`−` 31 次额外 commit / JSON 写入；`−` 与 PR-2 `chunk.issues_json` 同字段共存（key 命名空间扩展）；`−` reparse 路径下需要保护该字段不被覆盖（行 1147 `chunk.issues_json = None`）。|
| **(b) finalize 时重算全文** | `_finalize_import` 时把所有 chunk 的 chunk_text 拼起来，重跑一遍 `_split_by_single_question` | `+` 数据来源单一无落库副作用。`−` 重算非纯：normalized_text 在 `_split_into_chunks` 后已被合并、可能修改（裁切空白），重算结果与切片当时的题号集可能不一致；`−` 需要 chunk 顺序 + 拼接逻辑，复杂度高；`−` 同步走 `_split_by_question_markers` 还是 `_split_by_single_question` 又是一个分歧点。 |
| **(c) ImportJob.config_json 顶层** | 切完 chunk 后**遍历每个 chunk 调 `_split_by_single_question`**，合并所有 qnos 一次性写入 `import_job.config_json["expected_qnos"]: ["1","2",...,"283"]`（数值排序、归一化字符串） | `+` 单点单源；`+` 与 PR-4 reconciliation 同表 `config_json`，schema 一致；`+` `run_reparse` 不会触碰该字段（行 1147 仅清 `chunk.issues_json`），稳健；`+` 1 次 commit；`+` 现有 `import_job.config_json` 已被多处使用（行 225-228 / 339-343 / 459 / 1151），多 1 个 key 与 `auto_import` / `use_llm_cache` / `answer_key_text` 同等位阶。`−` 需要 dict 重赋值触发 SQLAlchemy dirty 检测（详见 C.8）。 |

### A.2 推荐方案：c

**理由**：
1. 唯一存储位置 = 唯一来源真相，避免方案 a 的 chunk 字段双写漂移与方案 b 的二次切分非纯；
2. PR-3 已建立 "config_json 是 ImportJob 级元数据 / 跨 chunk 共享配置" 的语义边界（见 `answer_key_text` / `auto_import`），`expected_qnos` 与之同语义；
3. PR-4 reconciliation finalize 阶段读 `import_job.config_json["expected_qnos"]` 即可，无需 join chunk 表 31 行；
4. reparse 路径天然不污染该字段（reparse 不重切 chunk，expected 不变）。

### A.3 实施细节

写入位置：`run_smart_import` 行 345 `db.commit()` 之前（即与 `answer_key_text` 同一事务）：

```python
# 行 339-343 之后追加
expected_qnos: set[str] = set()
for chunk_data in chunks_data:
    for seg in _split_by_single_question(chunk_data["chunk_text"]):
        norm = _normalize_qno(seg.get("source_question_no"))
        if norm is not None:
            expected_qnos.add(norm)

config = import_job.config_json or {}
if answer_key_text:
    config["answer_key_text"] = answer_key_text
config["expected_qnos"] = sorted(expected_qnos, key=_qno_sort_key)
import_job.config_json = config        # 重赋值触发 SQLAlchemy dirty
db.commit()  # 已存在于行 345
```

> ⚠️ 关键：`_split_into_chunks` 已经返回 `chunks_data`（dict 列表）；不需要 db.query chunk 表（chunk 行此时刚 add+flush，复用内存 dict 更省 SQL）。

> 与 PR-2 决策对齐：`_split_by_single_question` 已在 PR-2 commit 中存在（行 1457），PR-4 直接复用，不新建 helper。

### A.4 `_qno_sort_key` 排序辅助

题号是 string，需要数值排序（避免 `"1","10","100","11","2"` 字典序错位）：

```python
def _qno_sort_key(qno: str) -> tuple[int, int | str]:
    """先按 isdigit 分桶（数字优先），再按数值升序；非数字按字典序兜底。"""
    return (0, int(qno)) if qno.isdigit() else (1, qno)
```

> CIPT 283 PDF 全数字，但通用性兜底（PR-3 _normalize_qno 已为 `5a` / `5-1` 等留接口）。

---

## B. reconciliation schema 与计算

### B.1 推荐 schema

```jsonc
import_job.config_json["reconciliation"] = {
  "expected": ["1", "2", ..., "283"],            // 字符串数组，归一化后，按 _qno_sort_key 排序
  "imported_unique": ["1", "2", ..., "283"],     // 实际唯一 imported 的题号
  "missing_qnos": [],                            // expected - imported_unique（合并 per_question_failures）
  "duplicates_in_db": [],                        // 题号去重 skipped 的题号（reason="qno"）
  "per_question_failures_count": 0,              // 各 chunk per_question_failures 合并去重后的题号数
  "computed_at": "2026-05-04T12:34:56+00:00"     // ISO8601 UTC，便于多次 finalize 追溯
}
```

### B.2 与 PRD AC2 的对齐

PRD AC2 字面要求：`{expected:283, imported_unique:283, missing_qnos:[], duplicates_in_db:[]}`。

| AC2 字段 | 本设计 | 差异 |
|---|---|---|
| `expected` | array `["1",..,"283"]` | PRD 写 `283`（数字）；本设计是数组 → **更强**：含完整题号清单，便于排查；`len(expected)` 即 PRD 期望的"283"。**推荐回填 PRD**：把 AC2 中 `expected:283` 改为 `expected: list (length 283)`。|
| `imported_unique` | array `["1",..]` | 同上。`len(imported_unique)` 即原 AC2 的整数 |
| `missing_qnos` | array | ✅ 直接对齐 |
| `duplicates_in_db` | array | ✅ 直接对齐 |
| `per_question_failures_count` | int | **新增**（PRD 未要求，但 PR-2 schema 已可推导，免前端再走一遍 chunk 表）|
| `computed_at` | string | **新增**（reparse 触发二次 finalize 时便于审计；下游 `serialize_import_job` 透传方便） |

> **回填 PRD**：建议把 `expected` / `imported_unique` 字段从"整数 count"改为"题号字符串数组"；保留 `len()` 等于原 AC2 整数的不变量。

### B.3 字段命名对齐 PR-2/PR-3

| PR-4 取数源 | 来源字段（PR-2/PR-3 已定义） | 备注 |
|---|---|---|
| `imported_unique` | `ImportParsedQuestion.source_question_no WHERE import_status='imported'` | PR-3 design B.1 已锁定（来源 = ImportParsedQuestion，不反查 Question 表）|
| `duplicates_in_db` | `ImportParsedQuestion WHERE import_status='skipped' AND issues_json.details[0].reason='qno'` | PR-3 design G.2 已锁定 |
| `per_question_failures` 元素 | `chunk.issues_json["per_question_failures"][*].source_question_no` | PR-2 design F.1 已锁定 |

→ schema 完全对齐 PR-2/PR-3 现有字段，**无需扩展任何 ORM 字段**。

### B.4 计算函数伪代码

```python
def _compute_reconciliation(db: Session, import_job: ImportJob) -> dict:
    """汇总 expected / imported_unique / missing_qnos / duplicates_in_db。

    依赖：
      - import_job.config_json["expected_qnos"]：A.3 写入
      - ImportParsedQuestion 表：本 job 的所有行
      - ImportChunk 表：本 job 的所有 chunk.issues_json["per_question_failures"]
    """
    config = import_job.config_json or {}
    expected_set: set[str] = set(config.get("expected_qnos", []))

    # 1) 实际入库的唯一题号
    imported_set: set[str] = set()
    for pq in (
        db.query(ImportParsedQuestion)
        .filter_by(import_job_id=import_job.id, import_status="imported")
        .all()
    ):
        norm = _normalize_qno(pq.source_question_no)
        if norm is not None:
            imported_set.add(norm)

    # 2) 题号去重（PR-3）skipped 行
    duplicates_set: set[str] = set()
    for pq in (
        db.query(ImportParsedQuestion)
        .filter_by(import_job_id=import_job.id, import_status="skipped")
        .all()
    ):
        if not pq.issues_json:
            continue
        details = pq.issues_json.get("details") or []
        if any(d.get("reason") == "qno" for d in details):
            norm = _normalize_qno(pq.source_question_no)
            if norm is not None:
                duplicates_set.add(norm)

    # 3) chunk 级 per_question_failures
    per_q_failures_set: set[str] = set()
    for chunk in (
        db.query(ImportChunk).filter_by(import_job_id=import_job.id).all()
    ):
        for f in (chunk.issues_json or {}).get("per_question_failures", []):
            norm = _normalize_qno(f.get("source_question_no"))
            if norm is not None:
                per_q_failures_set.add(norm)

    # 4) missing：set diff + 失败合集（合集语义保护极端情况）
    missing_set = (expected_set - imported_set) | per_q_failures_set

    return {
        "expected": sorted(expected_set, key=_qno_sort_key),
        "imported_unique": sorted(imported_set, key=_qno_sort_key),
        "missing_qnos": sorted(missing_set, key=_qno_sort_key),
        "duplicates_in_db": sorted(duplicates_set, key=_qno_sort_key),
        "per_question_failures_count": len(per_q_failures_set),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
```

### B.5 关键设计点评估

| 点位 | 决策 | 理由 |
|---|---|---|
| `expected_set - imported_set` vs `\| per_q_failures_set` | **合集**（`\|`） | 理论上 `per_q_failures_set ⊆ (expected_set - imported_set)`，但合集语义为"防御 LLM 输出格式漂移导致 expected_set 漏题号"提供保护（极端：LLM 在非 timeout chunk 里返回 source_question_no=None 让 expected_qnos 漏掉，但 per_question_failures 仍登记题号）|
| 排序 key | `_qno_sort_key` | 数字优先按 int，非数字字典序兜底。前端展示 / 日志肉眼可读 |
| `computed_at` | **必要** | reparse 触发二次 _compute 时，前端可通过该字段判断"reconciliation 是哪一次跑的"；ISO8601 UTC 与现有 `created_at` / `updated_at` 风格一致 |
| `expected_set` 来源 | A.3 选项 (c) | 单点单源，不二次切分 |

---

## C. 写入时机与位置

### C.1 现有 `_finalize_import` 触发场景

| 调用方 | 是否当前调用 `_finalize_import` |
|---|---|
| `run_smart_import` 行 405 | ✅ |
| `run_reparse` 行 1190-1194 | ❌ **未调用**；直接 `_update_import_job_status`（行 1192/1194）|

### C.2 PR-4 写入策略

| 决策 | 影响 |
|---|---|
| `_finalize_import` 末尾追加 `_compute_reconciliation` 调用 | ✅ run_smart_import 路径 |
| `run_reparse` 行 1188 之后、行 1190-1194 之前**也**调 `_compute_reconciliation` | ✅ reparse 路径下也刷新 reconciliation（覆盖上次 finalize 的旧数据）|

> reparse 不能直接调 `_finalize_import`：那会重新把 `status` 从 `review_required`/`imported` 反推到 `partial_imported`/`imported`，覆盖 reparse 当前的 status 机制（行 1191-1194）。**只复用 `_compute_reconciliation`**，不复用 `_finalize_import` 的状态机部分。

### C.3 `_finalize_import` 修改后伪代码

```python
def _finalize_import(db: Session, import_job: ImportJob) -> None:
    import_job = db.get(ImportJob, import_job.id)
    if not import_job:
        return

    # ... 原有逻辑（计算 imported/review/failed_chunks, 决定 status, summary_json, _update_bank_stats）保留不变
    # 行 1798-1834

    # PR-4 新增：reconciliation 报告
    reconciliation = _compute_reconciliation(db, import_job)
    config = dict(import_job.config_json or {})       # 新建 dict 触发 SQLAlchemy dirty
    config["reconciliation"] = reconciliation
    import_job.config_json = config
    db.commit()
```

### C.4 `run_reparse` 修改后伪代码

```python
def run_reparse(db: Session, background_job: BackgroundJob) -> None:
    # ... 行 1108-1188 原有逻辑

    # 更新 import_job 状态（行 1190-1194 保留原有）
    if import_job.review_questions > 0:
        _update_import_job_status(db, import_job, "review_required")
    else:
        _update_import_job_status(db, import_job, "imported")

    # PR-4 新增：reparse 后也刷新 reconciliation
    reconciliation = _compute_reconciliation(db, import_job)
    config = dict(import_job.config_json or {})
    config["reconciliation"] = reconciliation
    import_job.config_json = config
    db.commit()

    # 更新题库统计（行 1197 保留）
    _update_bank_stats(db, import_job.bank_id)
```

### C.5 SQLAlchemy JSONB dirty 检测陷阱

`ImportJob.config_json` 是 `JSONB` 类型（`import_job.py:37`），无 `MutableDict` 包装；现有代码（行 341-343 / 1155）的写法是：

```python
config = import_job.config_json or {}
config["..."] = ...
import_job.config_json = config       # 关键：重赋值！
```

**项目惯用法**：必须**重新赋值**到属性才能触发 dirty 检测。如果只 `import_job.config_json["k"] = v`（in-place），SQLAlchemy ORM **不会**标记为 dirty。

PR-4 推荐两种等价写法（任选一种，与现有代码风格统一）：

```python
# 风格 1：与现有 行 341-343 一致
config = dict(import_job.config_json or {})
config["reconciliation"] = recon
import_job.config_json = config

# 风格 2：使用 flag_modified（项目 ai_service.py:127, 158 已使用过）
from sqlalchemy.orm.attributes import flag_modified
config = import_job.config_json or {}
config["reconciliation"] = recon
import_job.config_json = config       # 仍然要重赋值（首次为 None 时）
flag_modified(import_job, "config_json")
```

> **推荐风格 1**：与 `run_smart_import` 行 339-343 / `run_reparse` 行 1151 现有代码完全一致；不引入 flag_modified 跨语义（ai_service 用它是因为对 mutable list/dict 做 append 操作；PR-4 是整体替换 reconciliation 子键，重赋值已足够）。

> ⚠️ `**(import_job.config_json or {}) | {"reconciliation": recon}` Python 3.9+ 的 dict union `|=` 用法：能用，但结果仍然是新 dict，与 `dict(...)` + setitem 等价。**为可读性推荐 dict(...) + setitem**。

---

## D. logger 补齐（5 处）

### D.1 现有 logging 风格

* 模块顶部已有 `logger = logging.getLogger(__name__)`（行 45）。
* 现有 logger 调用密度极低（仅 2 处：行 387 chunk 失败 error、行 1021 题库已存在题目 info）。
* `.trellis/spec/backend/logging-guidelines.md` 明确认可此模块为"全后端唯一正确使用 logging 的文件"。

### D.2 5 处插入点（精确行号 + level + message）

| # | 位置 | level | 推荐 message format |
|---|---|---|---|
| **L1 重试触发** | `_call_llm_with_l1_retry` 行 708 `if attempt < max_retries:` 后、`time.sleep(backoff)` 之前 | `warning` | `logger.warning("[smart_import] L1 retry %d/%d after %ss: %s: %s", attempt + 1, max_retries, backoff, type(last_exc).__name__, last_exc)` |
| **L2 启动** | `_run_per_question_fallback` 行 736 `segments = _split_by_single_question(...)` **之后**（用 `len(segments)` 做参数；进入 segments=0 早 return 之前打也行，但更建议分两条分别打：见下方"variant"）| `warning` | `logger.warning("[smart_import] chunk %s entering L2 per-question fallback (%d segments)", chunk.chunk_no, len(segments))` |
| **L2 budget 超时** | `_run_per_question_fallback` 行 750-757 budget kill switch 内部，`break` 之前 | `warning` | `logger.warning("[smart_import] chunk %s L2 budget %ss exceeded, %d segments dropped", chunk.chunk_no, CHUNK_TOTAL_BUDGET_SECONDS, len(segments) - idx + 1)` |
| **heartbeat 失败** | `_run_per_question_fallback` 行 789-791 `except Exception:` 内 | `warning` | `logger.warning("[smart_import] chunk %s heartbeat failed at segment %d/%d (continuing)", chunk.chunk_no, idx, total_segments, exc_info=True)` （或不带 exc_info；推荐**不带**避免 fallback 路径堆栈刷屏）|
| **DUPLICATE 命中** | `_persist_duplicate_parsed_question` 行 857 `db.add(parsed_question)` 之前 | `info` | `logger.info("[smart_import] duplicate parsed question (reason=%s) source_qno=%s skipped", reason, _normalize_qno(parsed_q.source_question_no))` |

#### Variant：L2 启动 segments=0 路径

`_run_per_question_fallback` 行 740-745 是 segments=0 的早 return；建议在 D.2 第 2 条插入点之前（行 736 之后）打一条无条件的 entering 日志，再额外打一条针对 segments=0 的 warning：

```python
segments = _split_by_single_question(chunk_text)
logger.warning(
    "[smart_import] chunk %s entering L2 per-question fallback (%d segments)",
    chunk.chunk_no, len(segments),
)
if not segments:
    logger.warning(
        "[smart_import] chunk %s L2 fallback skipped: no question markers",
        chunk.chunk_no,
    )
    return merged, [{...}]
```

> 两条 log 都属"L2 启动"语义类（必查项 D.9 第 2 条），共占 1 个槽位；不增加 5 处的总计。

### D.3 与 logging-guidelines.md 的一致性

| 规范要求 | PR-4 是否符合 |
|---|---|
| 仅用 `logger = logging.getLogger(__name__)` | ✅（沿用行 45 既有 logger） |
| level 选择：错误 → error；关键业务事件 → info；不用 print | ✅（warning 用于"中间态报警"，info 用于"业务事件"，error 仅在已有的 chunk 失败处使用） |
| message format 用 `%s` 而非 f-string | ✅（推荐都用 lazy formatting） |
| 不在 fallback 内吞噬异常时丢失诊断 | ✅（heartbeat 失败 warning 保留题号 / 段号上下文） |

### D.4 改动估算

5 处 logger 各 1-2 行（含格式化 args 多行折叠），合计 +10 行；不影响控制流。

---

## E. 集成测试设计

### E.1 三方案对比

| 方案 | 描述 | 评估 |
|---|---|---|
| **(a) 全栈集成** | 真 SQLAlchemy + 真 pdfplumber 抽取 reference/CIPT 283 题.pdf + mock LLM + 真 ORM 全套 | `+` 最真实，覆盖 PDF→chunking→LLM→落库→reconciliation 全链；`−` fixture 重（需准备 PG / 至少 SQLite-with-JSONB 等价）；`−` 31 chunk × 平均 9 题的 mock LLM 响应需要构造 ~283 个 stub questions（量大）；`−` PDF 抽取慢（pdfplumber 178 页约 5-10s）让单测变重。|
| **(b) chunking 之后切入** | 真 PDF + chunking 流程，然后 mock `_process_chunk` 或 mock `call_ai_api`，对每个 chunk 注入预期响应；最终调 `_finalize_import` | `+` 跳过 LLM 调用本身但保留切片真实性；`−` 仍需 pdfplumber + ORM；`−` 与方案 (a) 相比改善有限。|
| **(c) 纯 chunk fixture** | 不跑 PDF / chunking。直接构造 31 个 ImportChunk fixture（用诊断 B.2 的题号清单），mock `call_ai_api` 给每个 chunk 返回对应题号集，逐个调 `_process_chunk`；最后调 `_finalize_import` | `+` 单测一致风格；`+` 速度快（毫秒级）；`+` fixture 量可控；`+` 对 reconciliation 计算路径覆盖完整；`−` 不验证 PDF 抽取 / chunking 正确性 —— 但 PR-4 关注 reconciliation/logger，PDF 抽取和 chunking 已被 diagnosis-step0 静态验证 + PR-1/PR-2/PR-3 单测各自覆盖。 |

### E.2 推荐方案：c

**理由**：
1. PR-4 的核心断言是 reconciliation 报告字段正确 + logger 命中关键路径，与 PDF 抽取无关；
2. PR-1/2/3 单测都用 `monkeypatch.setattr` mock + MagicMock chunk fixture，PR-4 沿用同风格保持基线一致；
3. SQLite (`backend/quiz.db` 实际未启用，FastAPI 走 PG) 不支持原生 JSONB，但 SQLAlchemy 在 SQLite 下会把 JSONB 当 `TEXT` 存（dialect 兼容层），现有 PR-2/PR-3 测试已用 MagicMock 模拟 db，**不进真 ORM**——PR-4 沿用 MagicMock 模式即可；
4. `flag_modified` 在 MagicMock 下 noop（不会真触发 dirty），与 reconciliation 写入语义无冲突；
5. fixture 量：31 个 chunk × stub LLM 响应 = 可读性可控（每个 chunk 用诊断 B.2 表的 qno 清单 + `_make_response_text(qno_list)` helper）。

> **回填 PRD（建议）**：把 PRD AC1 的"用 reference/CIPT 283题.pdf 走完整 smart_import"放宽为"用 reference/CIPT 283题.pdf 的诊断 B.2 题号分布构造 31 chunk fixture，跑通 _process_chunk + _finalize_import 全流程"——避免 PDF 抽取耗时拖慢 CI。

### E.3 测试 fixture 与依赖

| 项 | 选择 |
|---|---|
| 文件位置 | `backend/tests/test_smart_import_e2e_reconciliation.py`（新文件） |
| db 模型 | MagicMock（与 PR-2/PR-3 一致；不引入 SQLAlchemy in-memory） |
| LLM mock 方式 | `monkeypatch.setattr("app.services.smart_import_service.call_ai_api", fake_call_ai_api)` |
| `_split_by_single_question` mock | **不 mock**，直接复用真实函数（PR-2 commit 已 ship；fixture chunk_text 用 `_make_chunk_text(qnos)` 构造） |
| pdfplumber | **不依赖** |
| 既有依赖 | 无需新增（沿用 pytest 9 + monkeypatch；与 PR-1/2/3 一致）|
| 行数估算 | ~400 行（与 PR-2 test 598 行 / PR-3 test 549 行相当或略少）|

### E.4 31-chunk fixture builder

```python
# 诊断 B.2 表 → 31 chunk × qno_list 映射（已实测）
CIPT_CHUNK_QNOS = [
    list(range(1, 5)),       # ch1: 1-4
    list(range(5, 10)),      # ch2: 5-9
    list(range(10, 19)),     # ch3: 10-18
    list(range(19, 30)),     # ch4: 19-29
    list(range(30, 41)),     # ch5: 30-40
    list(range(41, 47)),     # ch6: 41-46
    list(range(47, 54)),     # ch7: 47-53
    list(range(54, 65)),     # ch8: 54-64
    list(range(65, 70)),     # ch9: 65-69
    list(range(70, 74)),     # ch10: 70-73
    list(range(74, 84)),     # ch11: 74-83
    list(range(84, 87)),     # ch12: 84-86
    list(range(87, 92)),     # ch13: 87-91
    list(range(92, 98)),     # ch14: 92-97
    list(range(98, 107)),    # ch15: 98-106
    list(range(107, 113)),   # ch16: 107-112
    list(range(113, 118)),   # ch17: 113-117
    list(range(118, 126)),   # ch18: 118-125
    list(range(126, 129)),   # ch19: 126-128
    list(range(129, 137)),   # ch20: 129-136
    list(range(137, 152)),   # ch21: 137-151
    list(range(152, 174)),   # ch22: 152-173
    list(range(174, 189)),   # ch23: 174-188
    list(range(189, 203)),   # ch24: 189-202
    list(range(203, 206)),   # ch25: 203-205
    list(range(206, 222)),   # ch26: 206-221
    list(range(222, 246)),   # ch27: 222-245  ← timeout 重灾区
    list(range(246, 264)),   # ch28: 246-263
    list(range(264, 267)),   # ch29: 264-266
    list(range(267, 280)),   # ch30: 267-279
    list(range(280, 284)),   # ch31: 280-283
]
assert sum(len(qs) for qs in CIPT_CHUNK_QNOS) == 283
```

### E.5 必备 TC 清单

| TC | 名称 | 核心断言 |
|---|---|---|
| **TC-1** | `test_smart_import_e2e_full_success` | 31 chunk 全部一次成功；`_finalize_import` 后 `import_job.config_json["reconciliation"]["expected"]` 长度=283，`imported_unique` 长度=283，`missing_qnos==[]`，`duplicates_in_db==[]`，`per_question_failures_count==0`，`computed_at` 是合法 ISO8601；`status="imported"` |
| **TC-2** | `test_smart_import_e2e_chunk_27_recovers_via_l1_retry` | mock `call_ai_api`：chunk 27 第 1 次抛 `httpx.TimeoutException`、第 2 次返回正常 `_make_response_text(range(222,246))`；其他 chunk 正常；reconciliation `missing_qnos==[]`；status=`"imported"`；`chunk.status=="parsed_retry"` |
| **TC-3** | `test_smart_import_e2e_chunk_27_recovers_via_l2_fallback` | chunk 27 L1 两次都 timeout；L2 24 段全部成功；其他 chunk 正常；reconciliation `missing_qnos==[]`；status=`"imported"`；`chunk.status=="parsed_fallback"`（注：L2 全部成功不计入 failed_chunks） |
| **TC-4** | `test_smart_import_e2e_chunk_27_l2_partial_failure` | chunk 27 L1 timeout 用尽，L2 中 4 段（如 222-225）抛 TimeoutException，其余 20 段成功；reconciliation `missing_qnos==["222","223","224","225"]`、`per_question_failures_count==4`；status=`"partial_imported"`（因 `failed_chunks==1`） |
| **TC-5** | `test_run_reparse_recovers_partial_chunk` | 在 TC-4 状态基础上，run_reparse chunk 27（mock 第二次跑全部成功），断言 `import_job.config_json["reconciliation"]["missing_qnos"]==[]`、`computed_at` 比 TC-4 finalize 时刻更晚；`imported_unique` 长度=283 |
| **TC-6**（补） | `test_reconciliation_records_duplicates_from_qno_dedup` | 构造 chunk 23 reparse 命中 PR-3 imported_qnos → 多条 DUPLICATE_QNO skipped 行；reconciliation `duplicates_in_db` 含正确题号集、不进 `missing_qnos` |
| **TC-7**（补） | `test_reconciliation_writes_to_config_json_without_clobber` | 验证 `config_json` 既有键（`auto_import` / `use_llm_cache` / `answer_key_text`）在 reconciliation 写入后**未丢失**（dict union 而非整体替换）|

> TC-1 ~ TC-5 直接对应任务必查项 E.14；TC-6/7 是 PR-4 自身设计 invariant 的额外保护。

### E.6 mock 策略要点

```python
def make_fake_call_ai_api(scripted: dict[int, list]):
    """scripted: {chunk_idx (1-based): [response_or_exception, ...]}
    每次调用按顺序消费列表中下一个元素；返回 str 或 raise Exception。"""
    counters = {k: 0 for k in scripted}
    def _impl(messages, db, scene="default", timeout=60.0):
        # 通过 messages[1].content 反推 chunk 索引（content 含题号）
        ...
        item = scripted[idx][counters[idx]]
        counters[idx] += 1
        if isinstance(item, Exception):
            raise item
        return item
    return _impl
```

> **关键**：mock 时区分整 chunk 调用（L1）vs 单题调用（L2）。L2 进入时 `messages[1].content` 仅含 1 道题，可用 `len(messages[1].content)` 阈值或正则 `Question #(\d+)` 命中数判断。

### E.7 logger 验证（可选，补强）

PR-4 5 处 logger 可用 `caplog` fixture 验证：

```python
def test_logger_l1_retry_emitted(caplog, ...):
    caplog.set_level(logging.WARNING, logger="app.services.smart_import_service")
    # 跑 TC-2 流程
    assert any("L1 retry" in rec.message for rec in caplog.records)
```

放在 TC-2/TC-3/TC-4 各加 1-2 行 caplog 断言即可，不增加 TC 数量。

---

## F. 序列化 / API 暴露

### F.1 现有 `serialize_import_job`（行 1891-1924）

字段清单（grep 全文）：
```
id, bank_id, background_job_id, file_name, file_type, status, total_pages, total_chunks,
parsed_questions, imported_questions, review_questions, failed_chunks, summary,
error_message, created_by, created_at, updated_at, background_job
```

**未暴露 `config_json` 任何字段**。

### F.2 三种暴露选项

| 选项 | 描述 | 评估 |
|---|---|---|
| **(i) 仅写 DB，不 surface** | 完全不动 `serialize_import_job` | `+` 0 改动，前端零变化；`−` 用户排查问题需直接查 PG |
| **(ii) 在 serialize 顶层加 `reconciliation`** | 新增字段 `"reconciliation": import_job.config_json.get("reconciliation") if import_job.config_json else None` | `+` 不依赖前端改造；`+` 浏览器开发者工具 / curl 即可看到；`+` PRD Out of Scope 已声明前端 UI 不改，本字段对未读取它的前端零副作用 |
| **(iii) 暴露整个 `config`/`config_json`** | 暴露所有 config_json 子字段（含 auto_import / answer_key_text 等） | `−` 把内部配置 leak 给前端，扩散面大；`−` answer_key_text 可能很长；不必要 |

### F.3 推荐选项 ii

> 与必查项 F.16 选项 iii 等价（顶层 `reconciliation` 可选字段）。

具体实现：

```python
# serialize_import_job 内 return 新增一行
"reconciliation": (import_job.config_json or {}).get("reconciliation"),
```

* 前端不读取此字段时零副作用（Vue 模板只渲染指定 key）；
* 用户 / 运维通过 `GET /api/banks/{bank_id}/import-jobs/{id}` 可直接看到 reconciliation 数据，便于线上排查；
* 与 PRD Out of Scope "前端复核页 UI 不改" 完全一致（本 PR 不改任何 .vue / .js 文件）。

---

## G. PR-4 与 PR-2 / PR-3 的兼容验证

### G.1 PR-2 状态机不变量

| 不变量 | PR-4 集成测试覆盖 |
|---|---|
| 一次成功 → `chunk.status=="parsed"` | TC-1 |
| L1 重试成功 → `chunk.status=="parsed_retry"`, retry_count=1 | TC-2 |
| L2 全部成功 → `chunk.status=="parsed_fallback"`, 不写 cache | TC-3 |
| L2 部分成功 → `chunk.status=="parsed_partial"`, failed_chunks++ | TC-4 |
| L2 全部失败 → `chunk.status=="failed"` | （PR-2 单测已覆盖；PR-4 不重复）|

### G.2 PR-3 题号去重不变量

| 不变量 | PR-4 集成测试覆盖 |
|---|---|
| reparse 命中 imported_qnos → ImportParsedQuestion 写 skipped + reason="qno" | TC-6 |
| `duplicates_in_db` 通过 `details[0].reason=="qno"` 过滤准确 | TC-6 |
| reparse 不污染 expected_qnos（A.3 写入后不再变更） | TC-5 隐含验证 |

### G.3 联合 invariant：reconciliation 守恒律

```
len(expected) == len(imported_unique) + len(missing_qnos) - len(set(imported_unique) ∩ set(missing_qnos))
                                       （ 当 missing_qnos ⊄ imported_unique 时，∩ 为空）
```

简化（per_question_failures ⊆ expected - imported 时）：
```
len(expected) == len(imported_unique) + len(missing_qnos)
```

PR-4 测试可加守恒断言（TC-1/2/3 验证 `len(missing) == 0`；TC-4 验证 `len(missing) == 4`，且 `283 == 279 + 4`）。

---

## H. 改动面与代码重用

### H.1 改动文件清单

| 文件 | 变更 | 估算行数 |
|---|---|---|
| `backend/app/services/smart_import_service.py` | (1) 新增 `_qno_sort_key`；(2) 新增 `_compute_reconciliation`；(3) `run_smart_import` 切完 chunk 后写 `expected_qnos` 到 config_json（A.3）；(4) `_finalize_import` 末尾追加 reconciliation 写入；(5) `run_reparse` 末尾追加 reconciliation 写入；(6) 5 处 logger 补齐 | +60 / -2 |
| `backend/app/services/smart_import_service.py: serialize_import_job` | +1 行 `"reconciliation": (import_job.config_json or {}).get("reconciliation")` | +1 |
| `backend/tests/test_smart_import_e2e_reconciliation.py` | 新文件，TC-1 ~ TC-7 | +400 |

> **不改**：`call_ai_api`、`_process_chunk`（PR-2 主体）、`_save_parsed_question`、`_persist_duplicate_parsed_question`（PR-3 主体）、ORM 模型、Alembic、前端、`schemas/llm_parse.py`。

### H.2 Code reuse（按 `code-reuse-thinking-guide.md`）

| 复用点 | 来源 |
|---|---|
| `_normalize_qno` | PR-3 helper（行 152）；构造 `expected_qnos` / `imported_set` / `duplicates_set` / `per_q_failures_set` 都用同一函数 |
| `_split_by_single_question` | PR-2 helper（行 1457）；A.3 expected_qnos 计算复用 |
| dict 重赋值触发 dirty | 现有 `run_smart_import` 行 339-343 / `run_reparse` 行 1151 惯用法 |
| `_make_response_text` / `_make_chunk_text` | PR-2 测试 fixture 风格（test_smart_import_process_chunk_retry.py 行 42-79）|

### H.3 Cross-layer thinking（按 `cross-layer-thinking-guide.md`）

```
Service 层（_compute_reconciliation）
  ↓ 写
ORM 层（ImportJob.config_json["reconciliation"]）
  ↓ 读
Service 层（serialize_import_job）
  ↓ 暴露
API 层（/api/banks/{bank_id}/import-jobs/{id}）
  ↓ 透传
前端（不读取该字段，零变化；运维可通过 API 直接看）
```

每一层语义清晰：
* **service**：计算 reconciliation = 集合差集 / 合集；
* **ORM**：JSONB 字段存元数据；
* **API**：透传可选字段；
* **前端**：不依赖该字段，无破坏性。

---

## I. 推荐落地方案 + 关键代码骨架

### I.1 总览

* 新增 `_qno_sort_key(qno: str) -> tuple[int, int | str]`
* 新增 `_compute_reconciliation(db: Session, import_job: ImportJob) -> dict`
* 改 `run_smart_import` 行 339-345 段：写 `expected_qnos` 到 config_json
* 改 `_finalize_import` 行 1834 之后：追加 reconciliation 写入 + commit
* 改 `run_reparse` 行 1188 之后、行 1190 之前：追加 reconciliation 写入 + commit
* 改 `serialize_import_job`：+1 行返回 reconciliation
* 5 处 logger 补齐

### I.2 关键伪代码（≤80 行）

```python
# ─── 新增辅助函数 ─────────────────────────────────

def _qno_sort_key(qno: str) -> tuple[int, int | str]:
    """题号排序：纯数字按 int 升序，非数字按字典序兜底。"""
    return (0, int(qno)) if qno.isdigit() else (1, qno)


def _compute_reconciliation(db: Session, import_job: ImportJob) -> dict:
    """汇总 expected / imported_unique / missing_qnos / duplicates_in_db。

    依赖：
      - import_job.config_json["expected_qnos"]：run_smart_import 切片后写入
      - ImportParsedQuestion: import_status='imported' / 'skipped' 两类
      - ImportChunk.issues_json["per_question_failures"]: PR-2 写入
    """
    config = import_job.config_json or {}
    expected_set: set[str] = set(config.get("expected_qnos", []))

    imported_set: set[str] = {
        norm
        for pq in (
            db.query(ImportParsedQuestion)
            .filter_by(import_job_id=import_job.id, import_status="imported")
            .all()
        )
        if (norm := _normalize_qno(pq.source_question_no)) is not None
    }

    duplicates_set: set[str] = set()
    for pq in (
        db.query(ImportParsedQuestion)
        .filter_by(import_job_id=import_job.id, import_status="skipped")
        .all()
    ):
        details = (pq.issues_json or {}).get("details") or []
        if any(d.get("reason") == "qno" for d in details):
            norm = _normalize_qno(pq.source_question_no)
            if norm is not None:
                duplicates_set.add(norm)

    per_q_failures_set: set[str] = set()
    for chunk in db.query(ImportChunk).filter_by(import_job_id=import_job.id).all():
        for f in (chunk.issues_json or {}).get("per_question_failures", []):
            norm = _normalize_qno(f.get("source_question_no"))
            if norm is not None:
                per_q_failures_set.add(norm)

    missing_set = (expected_set - imported_set) | per_q_failures_set
    return {
        "expected": sorted(expected_set, key=_qno_sort_key),
        "imported_unique": sorted(imported_set, key=_qno_sort_key),
        "missing_qnos": sorted(missing_set, key=_qno_sort_key),
        "duplicates_in_db": sorted(duplicates_set, key=_qno_sort_key),
        "per_question_failures_count": len(per_q_failures_set),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_reconciliation(db: Session, import_job: ImportJob) -> None:
    """计算 + 写入 + commit。run_smart_import / run_reparse 均调用。"""
    recon = _compute_reconciliation(db, import_job)
    config = dict(import_job.config_json or {})
    config["reconciliation"] = recon
    import_job.config_json = config
    db.commit()


# ─── run_smart_import 改写（仅 339-345 段） ──────────

# 切完 chunk 后，紧邻 answer_key_text 持久化
expected_qnos: set[str] = set()
for chunk_data in chunks_data:
    for seg in _split_by_single_question(chunk_data["chunk_text"]):
        if (n := _normalize_qno(seg.get("source_question_no"))) is not None:
            expected_qnos.add(n)

config = dict(import_job.config_json or {})
if answer_key_text:
    config["answer_key_text"] = answer_key_text
config["expected_qnos"] = sorted(expected_qnos, key=_qno_sort_key)
import_job.config_json = config
db.commit()


# ─── _finalize_import 末尾追加 ────────────────────

def _finalize_import(db, import_job):
    # ... 原有逻辑保留（行 1798-1834）
    _write_reconciliation(db, import_job)


# ─── run_reparse 末尾追加 ────────────────────────

def run_reparse(db, background_job):
    # ... 原有逻辑保留（行 1108-1194）
    _write_reconciliation(db, import_job)
    _update_bank_stats(db, import_job.bank_id)


# ─── serialize_import_job +1 行 ──────────────────

return {
    # ... 原有字段
    "reconciliation": (import_job.config_json or {}).get("reconciliation"),
}
```

### I.3 端到端验证清单

* [ ] `python -m py_compile backend/app/services/smart_import_service.py`
* [ ] `cd backend && python -m pytest tests/test_smart_import_e2e_reconciliation.py -v`（TC-1 ~ TC-7 全绿）
* [ ] `cd backend && python -m pytest tests/test_ai_service_call_api_timeout.py -v`（PR-1 不回归）
* [ ] `cd backend && python -m pytest tests/test_smart_import_process_chunk_retry.py -v`（PR-2 不回归）
* [ ] `cd backend && python -m pytest tests/test_smart_import_reparse_hygiene.py -v`（PR-3 不回归）
* [ ] `cd backend && python -m pytest tests/ -v`（合计 4 个文件全绿）
* [ ] 手工：`grep -nE "logger\.(info|warning|error)" backend/app/services/smart_import_service.py` 至少看到 7 条（原 2 条 + PR-4 新增 5 条）

---

## J. 不做事项 / 留作后续 PR

| 项 | 原因 / 留给哪个 PR |
|---|---|
| 把 `reconciliation` 接入前端复核页 UI（render `missing_qnos` 列表、缺口标记图标等）| PRD Out of Scope 显式排除"前端复核页 UI 不改"；本 PR 仅暴露字段，由用户 / 运维直接消费 |
| 让 `reconciliation.missing_qnos` 非空时自动触发告警 / 邮件 / Slack 通知 | 超出 MVP；告警系统不在本任务范围 |
| 用向量检索做相似题去重 / 把 `duplicates_in_db` 扩展到内容相似 | 超出 MVP；`vector_index` 模型已存在但 PRD 显式 Out of Scope |
| 把 `expected_qnos` 改成 chunk 级持久字段（如 `chunk.expected_qnos: JSONB`）| 用 ImportJob.config_json 即可；新增 chunk 字段需 Alembic 迁移，违反 PRD AC6 |
| 把 `_finalize_import` 与 `run_reparse` 末尾的状态机统一到一个 helper | 超出 PR-4；reparse 状态机（行 1191-1194）与初次导入（行 1813-1821）规则不同，统一需要更大重构 |
| 给 `reconciliation.computed_at` 加历史版本（如 `reconciliation_history: [...]`）| 当前 reparse 直接覆盖；如需追踪多次重跑差异可后续 PR；本 PR 仅保留最新一次 |
| `config_json["expected_qnos"]` 加 mutable 包装（如 `MutableDict.as_mutable(JSONB)`）| 项目现有 JSONB 字段都不用 MutableDict（行 339-343 / 1151 / 225-228 都是重赋值）；保持一致 |
| 暴露 `config_json["expected_qnos"]` 给前端 | 不必要：前端通过 `reconciliation.expected` 即可获得相同信息（且为排序数组）|
| 给 `serialize_chunk` 也透传 `expected_qnos_in_chunk` | A.1 选项 (a) 未采用，chunk 级字段不存在；不必扩展 serialize_chunk |
| 集成测试也跑真 PG / SQLite 持久化路径 | E.2 推荐方案 c（MagicMock）；持久化路径由 PR-1/2/3 的 ORM 字段定义保证；引入真 DB 测试需 conftest.py + fixture 重 |

---

## 给主代理的总结（< 250 字）

1. **expected 题号集存储位置（推荐方案 c）**：在 `run_smart_import` 切完 chunk 后（行 339-345 段），用 `_split_by_single_question(chunk_data["chunk_text"])` 遍历每个 chunk 取题号，归一化后排序写入 `import_job.config_json["expected_qnos"]`。单点单源、与 `answer_key_text` 同语义层；reparse 不污染该字段。
2. **reconciliation schema 与 PRD AC2 对齐**：完全覆盖 `expected / imported_unique / missing_qnos / duplicates_in_db`，并扩展 `per_question_failures_count` + `computed_at` 两字段。**回填 PRD**：建议 AC2 中 `expected:283` / `imported_unique:283` 改写为"长度=283 的题号字符串数组"，便于诊断。`duplicates_in_db` 通过 PR-3 `details[0].reason=="qno"` 过滤稳定。
3. **logger 补齐 5 处精确插入点**：(L1 retry) `_call_llm_with_l1_retry` 行 708 sleep 之前 warning；(L2 entering) `_run_per_question_fallback` 行 736 之后 warning；(L2 budget exceeded) 行 750-757 break 之前 warning；(heartbeat 失败) 行 789-791 except 内 warning（不带 exc_info）；(DUPLICATE 命中) `_persist_duplicate_parsed_question` 行 857 db.add 之前 info。
4. **集成测试技术方案：c**（纯 chunk fixture + MagicMock + monkeypatch.setattr `call_ai_api`）。沿用 PR-2/PR-3 风格，不引入 pdfplumber / pytest-postgresql 新依赖。新增 7 个 TC（TC-1 全成功 / TC-2 L1 重试 / TC-3 L2 全成功 / TC-4 L2 部分失败 / TC-5 reparse 恢复 / TC-6 duplicates / TC-7 config_json 不被 clobber），约 +400 行；用 caplog 捎带验证 logger 命中。
5. **回填 PRD 的新约束（建议 3 条）**：(a) AC2 字段从整数改成数组；(b) AC1 的"全 PDF E2E"放宽为"基于诊断 B.2 题号分布构造 31 chunk fixture"；(c) Technical Approach L4-c 加一句"PR-4 同时为 `serialize_import_job` 暴露 `reconciliation` 顶层字段（前端可选消费）"。
