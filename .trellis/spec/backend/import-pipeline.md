# Smart Import 流水线规范

> 题库 PDF/XLSX/DOCX → LLM 解析 → 复核入库的核心流水线，位于 `backend/app/services/smart_import_service.py`。本文记录 chunk 失败两级重试、reparse 卫生、reconciliation 报告三条对外契约。

适用范围：FastAPI 一侧（Flask 旧版 `backend/services/import_service.py` 仅维持现状，不增量）。

---

## Scenario A：Chunk 失败两级重试 + 单题降级

### 1. Scope / Trigger

LLM 长 chunk（≈12k 字符 / 24 题量级）整体调用偶发 `httpx.TimeoutException`，单点失败即丢失整 chunk 题量。CIPT 283 PDF 实测 chunk 27 在 60s 默认 timeout 下整体超时 → 24 题（题号 222–245）全失。

### 2. Signatures

```python
# backend/app/services/ai_service.py
def call_ai_api(
    messages,
    db,
    scene: str = "default",
    timeout: float = 60.0,
) -> str: ...
# smart_import 场景必须显式传 timeout=120.0；其余 scene 沿用 60s。
# 异常透传：httpx.TimeoutException / httpx.HTTPError / ValueError 不 wrap。

# backend/app/services/smart_import_service.py
def _process_chunk(
    db, chunk, import_job, *,
    seen_signatures: set | None = None,
    bg_job: BackgroundJob | None = None,
    imported_qnos: set[str] | None = None,
) -> None: ...
# bg_job：长循环必须传，用于 heartbeat 续 lease。
# imported_qnos：reparse 时传入，初次导入留 None。
```

### 3. Contracts

**模块常量**（位于 `smart_import_service.py` 顶部）：

| 常量 | 值 | 含义 |
|------|---|------|
| `L1_MAX_RETRIES` | `1` | L1 整 chunk 重试次数（不计首次调用） |
| `L1_RETRY_BACKOFF_SECONDS` | `2.0` | L1 重试前固定 sleep（不实际执行指数退避，因为只重 1 次） |
| `RETRY_BASE_SECONDS` / `RETRY_CAP_SECONDS` | `2.0 / 10.0` | 预留给未来多次重试，PR-2 暂不消费 |
| `L2_PER_QUESTION_TIMEOUT` | `60.0` | L2 单题降级时每段 LLM 调用 timeout |
| `CHUNK_TOTAL_BUDGET_SECONDS` | `480.0` | 单 chunk 总耗时上限（约 2.7 个 lease 周期），超时 break |
| `HEARTBEAT_EVERY_N_SEGMENTS` | `3` | L2 单题循环每 3 段调一次 heartbeat |

**异常分类**：

| 异常类型 | 是否重试 |
|---|---|
| `httpx.TimeoutException` | ✅ L1 / L2 重试候选 |
| `httpx.HTTPError`（含 5xx） | ✅ 重试候选 |
| `ValueError("AI API Key 未配置")` | ❌ 直接失败，不重试 |
| `ValueError("AI API 错误 (4xx)")` | ❌ 不重试 |
| Pydantic `ValidationError` | ❌ 不重试（输出 schema 不合法） |

定义为常量元组：`RETRYABLE_HTTP_EXC = (httpx.TimeoutException, httpx.HTTPError)`。

**`chunk.status`（String(32)，无 enum 约束）取值扩展**：

| 状态 | 含义 |
|------|------|
| `parsed` | 首次成功 |
| `parsed_retry` | L1 重试成功 |
| `parsed_fallback` | L2 单题降级**全部成功** |
| `parsed_partial` | L2 部分成功（含 `per_question_failures`） |
| `failed` | 不可重试错误 / L2 全部失败 / 预算超时未来得及降级 |

**`chunk.issues_json` 最终 schema**：

```jsonc
{
  "chunk_issues": [...],          // LLM 原返回的 issues（既有）
  "retry_count": 0,               // L1 实际重试次数（0 或 1）
  "fallback_used": false,         // L2 是否触发
  "per_question_failures": [
    {"source_question_no": "222",
     "stage": "L2_fallback" | "L2_fallback_budget_exceeded",
     "error": "TimeoutException after 60.0s"}
  ],
  "fallback_meta": {"total_segments": 24, "succeeded": 22, "failed": 2,
                    "elapsed_seconds": 1320.5}
}
```

### 4. Validation & Error Matrix

| 触发条件 | 行为 | chunk.status |
|---|---|---|
| 首次调用成功 | 直接保存 | `parsed` |
| 首次抛 `httpx.TimeoutException` → 重试成功 | sleep 2s 后再调 1 次 | `parsed_retry`（`retry_count=1`） |
| L1 重试仍失败 → L2 切单题 | `_split_by_single_question` 切段，逐题调 LLM | `parsed_fallback` / `parsed_partial` |
| L2 单题失败 | **不**写 `ImportParsedQuestion` 占位行；记入 `per_question_failures` | 取决于全失败/部分失败 |
| L2 累计耗时 > 480s | 剩余段写 `stage="L2_fallback_budget_exceeded"`，break | `parsed_partial` 或 `failed` |
| 4xx / API Key 缺失 / ValidationError | 不重试，直接 `failed` | `failed` |

**Heartbeat 约束**：`run_smart_import` / `run_reparse` 调 `_process_chunk` 时必须传 `bg_job=background_job`；L2 循环每 `HEARTBEAT_EVERY_N_SEGMENTS=3` 段调 `heartbeat_job(db, bg_job)`，把 lease 续到 `now + DEFAULT_JOB_LEASE_SECONDS(180s)`。heartbeat 自身失败时 `logger.warning` 但不 raise（避免淹没原异常）。

### 5. Good / Base / Bad Cases

- **Good**：所有 chunk 首次成功，0 retry / 0 fallback。
- **Base**：1 个 chunk timeout，L1 重试成功（`retry_count=1, fallback_used=false`）。
- **Bad**：1 个 chunk L1+L2 全失败 → 题号入 `missing_qnos`；用户走 reparse 时由 `imported_qnos` 拒重复入库。

### 6. Tests Required

文件：`backend/tests/test_smart_import_process_chunk_retry.py`（PR-2，12 TC）。断言点：

- L1 retry 成功后 `chunk.status == "parsed_retry"` 且 `retry_count == 1`
- L2 全成功后 `chunk.status == "parsed_fallback"` 且 `fallback_meta.succeeded == total_segments`
- L2 部分失败时 `per_question_failures` 含失败题号 + stage
- 不可重试异常（如 `ValueError("AI API Key 未配置")`）首次失败立即 `failed`，无 retry
- L2 累计耗时 > `CHUNK_TOTAL_BUDGET_SECONDS` 时剩余段标 `L2_fallback_budget_exceeded`
- `bg_job` 传入时 heartbeat 被周期性调用

### 7. Wrong vs Correct

#### Wrong（PR-2 之前的状态）

```python
# _process_chunk 内
try:
    response_text = call_ai_api(messages, db, scene="smart_import")  # 60s 硬编码
except Exception as exc:
    chunk.status = "failed"
    chunk.issues_json = {"error": str(exc)}
    db.commit()
    raise  # 整 chunk 全失，24 题题号丢失
```

问题：单点 timeout 即丢失整 chunk 题量，无降级路径，长 chunk 在线上不可恢复。

#### Correct

```python
# 1. 显式 timeout
def _call_llm_with_l1_retry(messages, db) -> str:
    try:
        return call_ai_api(messages, db, scene="smart_import", timeout=120.0)
    except RETRYABLE_HTTP_EXC:
        time.sleep(L1_RETRY_BACKOFF_SECONDS)
        return call_ai_api(messages, db, scene="smart_import", timeout=120.0)

# 2. L1 失败后切单题降级，预算 + heartbeat
def _run_per_question_fallback(chunk, db, bg_job):
    segments = _split_by_single_question(chunk.chunk_text)
    start = time.monotonic()
    for i, seg in enumerate(segments):
        if time.monotonic() - start > CHUNK_TOTAL_BUDGET_SECONDS:
            # 剩余段写 budget_exceeded 并 break
            ...
            break
        if i % HEARTBEAT_EVERY_N_SEGMENTS == 0 and bg_job:
            try: heartbeat_job(db, bg_job)
            except Exception: logger.warning(...)
        # 调用单题 LLM ... 失败入 per_question_failures
```

---

## Scenario B：Reparse 卫生（imported_qnos 题号去重）

### 1. Scope / Trigger

`run_reparse` 二次解析 chunk 时，已 imported 的题号会被 LLM 再次返回 → 走 `_save_parsed_question` 默认路径写新行 → 同题号在 `import_parsed_questions` 表出现多行 `imported`，污染前端复核列表与 reconciliation。CIPT 283 PDF 实测虚胖 16 行（题号 174–180、182–188、265、266）。

### 2. Signatures

```python
def _save_parsed_question(
    db, parsed_q, import_job, chunk,
    *,
    seen_signatures: set | None = None,
    imported_qnos: set[str] | None = None,
) -> None: ...

def _normalize_qno(qno: str | None) -> str | None:
    """归一化题号：strip + lstrip("#") + strip；空返回 None。"""

def _persist_duplicate_parsed_question(
    db, parsed_q, import_job, chunk, *, reason: Literal["qno", "content"]
) -> None: ...
```

### 3. Contracts

**`imported_qnos` 来源**（仅在 `run_reparse` 入口构建）：

```python
imported_qnos = {
    norm for pq in db.query(ImportParsedQuestion)
        .filter_by(import_job_id=import_job_id, import_status="imported").all()
    if (norm := _normalize_qno(pq.source_question_no)) is not None
}
```

**不**反查 Question 表（避免跨表语义混乱）。初次导入路径 `imported_qnos=None`（等价空集）。

**DUPLICATE 区分接口**（`details[0]` 子字段，主 code 保持 `"DUPLICATE"`）：

```jsonc
{
  "code": "DUPLICATE",
  "details": [{"reason": "qno" | "content", ...}]
}
```

`reason="qno"`：题号已 imported（来自本 helper）。`reason="content"`：内容签名重复（已有内容签名 DUPLICATE 路径在 PR-3 同步加 `reason`）。

### 4. Validation & Error Matrix

| 输入 | 行为 |
|---|---|
| `parsed_q.source_question_no` 归一化后为 `None` | 走原内容签名 DUPLICATE 路径 |
| 归一化题号 ∈ `imported_qnos` | 走 `_persist_duplicate_parsed_question(reason="qno")`：写 `review_status='duplicate', import_status='skipped'`；**不写 Question 表**；不更新 `imported_questions` 计数 |
| 归一化题号 ∉ `imported_qnos` 但内容签名重复 | 走 `_persist_duplicate_parsed_question(reason="content")` |
| 都不重复 | 默认入库路径 |

### 5. Tests Required

文件：`backend/tests/test_smart_import_reparse_hygiene.py`（PR-3，8 TC）。断言点：

- `_normalize_qno("#222")` / `" #222 "` / `"222"` 三种输入归一化结果相等
- `imported_qnos` 命中时 `import_parsed_questions` 新增行 `review_status='duplicate', import_status='skipped'`
- DUPLICATE 命中时 `details[0]["reason"] == "qno"`
- 初次导入（`imported_qnos=None`）行为不变（无 noop 副作用）

### 6. Wrong vs Correct

#### Wrong

```python
# run_reparse 内：仅靠内容签名去重，题号同但内容微调（LLM 重排空格/标点）即被认为不重复
seen_signatures = {_question_signature(pq) for pq in existing_imports}
_process_chunk(..., seen_signatures=seen_signatures)
# 结果：题号 222 在 reparse 后产生第二行 imported，前端复核列表 +1
```

#### Correct

```python
imported_qnos = {
    norm for pq in db.query(ImportParsedQuestion)
        .filter_by(import_job_id=import_job_id, import_status="imported").all()
    if (norm := _normalize_qno(pq.source_question_no)) is not None
}
_process_chunk(..., seen_signatures=seen_signatures,
               imported_qnos=imported_qnos, bg_job=background_job)
```

---

## Scenario C：Reconciliation 报告（cross-layer 契约）

### 1. Scope / Trigger

需要在 ImportJob 终结时回答「283 题导入了多少 / 缺哪些 / 重复哪些」。原本仅 `imported_questions` 计数，无法定位题号缺口。

### 2. Signatures

```python
def _qno_sort_key(qno: str) -> tuple[int, int, str]:
    """题号排序键：纯数字按 int 排，否则 (大数, 0, 原串) lexicographic。"""

def _compute_reconciliation(db, import_job) -> dict: ...

def _write_reconciliation(db, import_job) -> None:
    """计算 reconciliation 并用 dict spread 写入 config_json，触发 ORM dirty。"""
```

### 3. Contracts

**`expected_qnos` 写入时机**：仅在 `run_smart_import` 切完 chunk 后一次性写入：

```python
expected = sorted({
    _normalize_qno(qno)
    for chunk_data in chunks
    for seg in _split_by_single_question(chunk_data["chunk_text"])
    for qno in [seg.get("source_question_no")]
    if _normalize_qno(qno) is not None
}, key=_qno_sort_key)
import_job.config_json = {**(import_job.config_json or {}), "expected_qnos": expected}
```

**reparse 不写 `expected_qnos`**（保持「一次写入永不变」语义，确保 reconciliation 可重复计算）。

**`reconciliation` schema**（写入 `import_job.config_json["reconciliation"]`）：

```jsonc
{
  "expected": ["1", "2", ..., "283"],           // 题号字符串数组（已归一化、已排序）
  "imported_unique": ["1", ..., "283"],         // 实际 imported 的唯一题号
  "missing_qnos": [],                           // expected - imported_unique
  "duplicates_in_db": [],                       // details[0].reason=="qno" 命中题号
  "per_question_failures_count": 0,             // 来自所有 chunk.issues_json
  "computed_at": "2026-05-04T12:34:56Z"         // ISO8601 UTC
}
```

**JSONB dirty 检测**：必须用 dict spread 重新赋值（`config_json = {**old, "key": val}`）；**不**依赖 `flag_modified`（项目惯例：保持显式不可变赋值）。

**API 序列化暴露**：`serialize_import_job` 增加可选顶层 `reconciliation` 字段（前端不依赖即不影响）。

### 4. Validation & Error Matrix

| 触发点 | 行为 |
|---|---|
| `_finalize_import`（首次终结） | 调 `_write_reconciliation` |
| `run_reparse` 末尾 | 调 `_write_reconciliation`（不重写 `expected_qnos`） |
| `expected_qnos` 缺失 | `expected=[]`、`missing_qnos=[]`（不阻塞终结） |
| `import_job.config_json` 为 `None` | 用 `{**(... or {})}` 兜底 |

### 5. Cross-layer Wiring

```
service                    → ImportJob.config_json["reconciliation"]
                                  ↓
                           serialize_import_job() 顶层 reconciliation 字段
                                  ↓
                           前端可读（当前 UI 不展示，运维通过开发者工具直查）
```

前端不改是 PRD 显式 Out of Scope；新字段不破坏既有响应 schema。

### 6. Tests Required

文件：`backend/tests/test_smart_import_e2e_reconciliation.py`（PR-4，7 TC，568 行）：

- TC-1 全成功：`missing_qnos == []`
- TC-2 chunk 27 L1 retry 成功：`retry_count==1`、`missing_qnos == []`
- TC-3 chunk 27 L2 fallback 全成功：`fallback_used==true`、`missing_qnos == []`
- TC-4 chunk 27 L2 部分失败：`missing_qnos` 含失败题号
- TC-5 reparse 后 `missing_qnos == []`、无虚胖
- TC-6 `_finalize_import` 用 dict spread 不破坏其他 `config_json` 键
- TC-7 `serialize_import_job` 输出含 `reconciliation` 顶层字段

**SQLite 跑 PG 类型**：测试文件用 `@compiles(JSONB, "sqlite")` 钩子把 JSONB 编译为 JSON，让 in-memory SQLite 跑真 ORM。详见 [database-guidelines.md "JSONB on SQLite (test only)"](./database-guidelines.md)。

### 7. Wrong vs Correct

#### Wrong

```python
# 直接 mutate JSONB 字段（不触发 dirty，flush 后丢失）
import_job.config_json["reconciliation"] = recon
db.commit()  # config_json 视图未变更，UPDATE SQL 不会发出
```

#### Correct

```python
import_job.config_json = {
    **(import_job.config_json or {}),
    "reconciliation": recon,
}
db.commit()  # 整字段重新赋值，SQLAlchemy 检测到 dirty 发出 UPDATE
```

---

## 关键设计决策汇总

| # | 决策 | 理由 |
|---|---|---|
| D1 | timeout 通过函数签名传，不引入 `settings.AI_API_TIMEOUT_*` | 显式 > 隐式；4 个调用方只 1 个改 |
| D2 | L1 仅重试 1 次（固定 2s sleep） | 整 chunk 重试 ≥2 次的边际收益低于直接进 L2 |
| D3 | L2 单题失败**不**写 ImportParsedQuestion 占位行 | 避免污染前端复核列表与 reconciliation |
| D4 | 缓存键按整 chunk hash；L2 单题响应**不**写 `LlmParseCache` | 写单题响应会破坏 chunk 级一致性 |
| D5 | `imported_qnos` 来自 `import_parsed_questions` 表，不反查 Question | 避免跨表语义混乱 |
| D6 | DUPLICATE 主 code 保持，仅在 `details[0].reason` 子字段区分 qno/content | 前端 / `serialize_parsed_question` 零兼容代价 |
| D7 | `expected_qnos` 一次写入永不变 | 保证 reconciliation 可重复计算（reparse 不污染） |
| D8 | reconciliation 计入 `config_json` 而非新表 / 新字段 | 不引入 Alembic 迁移；运维直查即可 |

---

## 参考

- 任务 PRD：`.trellis/tasks/05-04-smart-import-cipt-283-pdf/prd.md`
- 诊断报告：`.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/diagnosis-step0.md`
- PR 设计文档：`.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/pr{1,2,3,4}-design-*.md`
