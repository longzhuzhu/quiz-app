# Smart Import 流水线规范

> 题库 PDF/XLSX/DOCX → LLM 解析 → 复核入库的核心流水线，位于 `backend/app/services/smart_import_service.py`。本文记录 chunk 失败两级重试、L1 完整性检查、reparse 卫生、reconciliation 报告、场景题完整题干等对外契约。

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
  "chunk_issues": [...],          // LLM 原返回的 issues（既有），也可包含 L1_INCOMPLETE_RESPONSE
  "retry_count": 0,               // L1 实际重试次数（0 或 1）
  "fallback_used": false,         // L2 是否触发
  "per_question_failures": [
    {"source_question_no": "222",
     "stage": "L2_fallback" | "L2_fallback_budget_exceeded",
     "error": "TimeoutException after 60.0s"}
  ],
  "fallback_meta": {"total_segments": 24, "succeeded": 22, "failed": 2,
                    "elapsed_seconds": 1320.5,
                    "reason": "l1_retry_exhausted" | "l1_incomplete_response"}
}
```

**L1 完整性检查**：L1 调用返回合法 JSON 后，保存任何题目前必须用 `_split_by_single_question(chunk_text)` 计算可检测题号段数。若 `len(llm_result.questions) < len(expected_segments)` 且 `expected_segments` 非空，说明 chunk 级 LLM 合法但漏题；此时不得写缓存、不得先保存不完整 L1 结果，应丢弃该 L1 结果并改走 L2 单题降级。命中既有 `LlmParseCache` 时也必须执行同一检查；若缓存响应不完整，应绕过缓存直接走 L2，避免历史坏缓存固化低识别率。最终通过 `fallback_used=true`、`fallback_meta.reason="l1_incomplete_response"` 和 `chunk_issues[0].code="L1_INCOMPLETE_RESPONSE"` 留痕。

### 4. Validation & Error Matrix

| 触发条件 | 行为 | chunk.status |
|---|---|---|
| 首次调用成功 | 直接保存 | `parsed` |
| 首次抛 `httpx.TimeoutException` → 重试成功 | sleep 2s 后再调 1 次 | `parsed_retry`（`retry_count=1`） |
| L1 返回合法 JSON 但题数 < `_split_by_single_question` 可检测段数 | 保存前丢弃不完整 L1 结果，改走 L2；不写 chunk 级缓存 | `parsed_fallback` / `parsed_partial` |
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
- L1 合法 JSON 但返回题数少于可检测题号段时触发 L2，`fallback_meta.reason == "l1_incomplete_response"`，且不写 LlmParseCache
- 既有 LlmParseCache 命中但响应题数少于可检测题号段时绕过缓存触发 L2，防止坏缓存固化
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

## Scenario D：场景题完整题干与历史回填

### 1. Scope / Trigger

LLM 解析 schema 支持把场景/阅读材料放入 `scenario`，把最后一问放入 `content`。正式 `questions` 表没有 `scenario` 字段，答题页、错题本、复制题目、翻译等功能只读取 `Question.content`。因此只保存短 `content` 会导致场景题只剩最后一问。

本契约适用于：新导入自动入库、reparse 自动入库、人工复核 accept、历史回填脚本、PDF 第一个题号前导材料归属、场景题质量检查。

### 2. Signatures

```python
# backend/app/services/smart_import_service.py
def build_full_question_content(
    scenario_text: str | None,
    content: str | None,
) -> str: ...
# 正式题库题干唯一构造入口：scenario_text + "\n\n" + content。
# ImportParsedQuestion 仍保留原始 scenario_text/content 供复核与审计。


def _write_question_to_bank(
    db: Session,
    parsed_question: ImportParsedQuestion,
    bank_id: int,
) -> Question | None: ...
# 自动入库、reparse 自动入库、review accept 都必须经此函数写 Question。


def _looks_like_leading_reading_material(text: str) -> bool: ...
# 保守判断第一个题号前文本是否应归入第一题。


def _source_text_for_quality_check(
    parsed_q: ParsedQuestion,
    chunk_text: str,
) -> str: ...
# 按题号定位当前题原文片段；定位失败时才回退到完整 chunk。
```

```bash
# backend/scripts/backfill_scenario_question_content.py
python3 backend/scripts/backfill_scenario_question_content.py [--apply] [--limit N]
```

### 3. Contracts

**正式题干合成**：

| 输入 | 输出 |
|---|---|
| `scenario_text="SCENARIO..."`, `content="Which..."` | `"SCENARIO...\n\nWhich..."` |
| `scenario_text` 为空 | `content.strip()` |
| `content` 已经以归一化后的 `scenario_text` 开头 | 返回 `content.strip()`，避免重复拼接 |
| 两者都空 | 空字符串 |

**存储边界**：

- `ImportParsedQuestion.scenario_text` 与 `ImportParsedQuestion.content` 保持原始拆分结果，用于复核、审计、历史回填。
- `Question.content` 必须保存 `build_full_question_content(parsed_question.scenario_text, parsed_question.content)` 的结果。
- 不新增 `Question.scenario` / `questions.scenario` 字段。
- 题目内容签名和正式表重复检查必须使用完整题干，避免不同场景题因为同一个短问句被误判重复。

**第一个题号前导材料归属**：

`_split_by_question_markers()` 只能在以下保守条件成立时，把第一个题号前的文本归入第一题：

- 文本明显像场景/阅读材料：包含 `SCENARIO` / `CASE STUDY`，或多段落，或至少 3 个句子，或至少 80 个词；且
- 不匹配拒绝模式：`Correct Answer` / `Answer:` / `Answer Key` / `Explanation:` / `Reference:`、选项行、页码、网站广告、考试版本/Passing Score 等噪声。

**场景题质量检查**：

- `_quality_check()` 的题干长度、噪声检查应基于完整题干。
- 判断 `SCENARIO_MISSING` 时，必须先用 `_source_text_for_quality_check()` 定位当前题片段；不能因为同一个 chunk 中其它题含 `SCENARIO` 就把普通题判为缺场景。
- 仅当当前题片段含 `SCENARIO` / `CASE STUDY`，且解析结果的 `scenario` 为空、完整题干也不含场景标记时，加入 `SCENARIO_MISSING` HIGH issue，阻止高置信自动入库。

**历史回填脚本**：

- 默认 dry-run：不写数据库，最后 `rollback()`。
- 只有传 `--apply` 时才写入并 `commit()`。
- 不自动生成备份文件。
- 只扫描 `ImportParsedQuestion.imported_question_id IS NOT NULL` 的记录。
- 只更新满足全部条件的记录：正式 `Question` 存在、`scenario_text` 非空、当前 `Question.content` 尚未是完整题干、且当前 `Question.content` 与 `ImportParsedQuestion.content` 归一化等价。
- 若当前 `Question.content` 与解析短题干不等价，视为疑似人工编辑，必须跳过。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 新导入 / reparse / review accept 写入含 `scenario_text` 的解析题 | `Question.content = scenario_text\n\ncontent` |
| `scenario_text` 为空 | `Question.content = content.strip()` |
| `content` 已含 scenario 前缀 | 不重复拼接 scenario |
| 第一个题号前文本像场景/阅读材料且非噪声 | 归入第一题 chunk |
| 第一个题号前文本像页眉、广告、答案、解析、选项 | 不归入第一题 |
| 当前题原文含 `SCENARIO` 但 LLM 输出未保留场景 | `SCENARIO_MISSING` HIGH，不能自动入库 |
| 同 chunk 其它题含 `SCENARIO`，当前普通题不含 | 当前普通题不应被标 `SCENARIO_MISSING` |
| 回填脚本未传 `--apply` | dry-run 输出候选，数据库不变 |
| 回填候选 current content 与 parsed short content 不等价 | 跳过，计入疑似人工编辑 |

### 5. Good / Base / Bad Cases

- **Good**：LLM 输出 `scenario="SCENARIO..."`、`content="Which is the best next step..."`；自动入库后正式题干包含两段，中间一个空行。
- **Base**：普通非场景题 `scenario=None`；正式题干仍只保存原 `content`，不会被同 chunk 的场景题误伤。
- **Bad**：把 chunk 级 `SCENARIO` 直接用于所有题的质量判断，导致同 chunk 的普通题被标 `SCENARIO_MISSING` 并进入人工复核。
- **Bad**：历史回填直接覆盖所有 `scenario_text` 非空题目，可能覆盖用户已人工修正的 `Question.content`。

### 6. Tests Required

文件建议：`backend/tests/test_smart_import_scenario_content.py`，必要时联动 `test_smart_import_reparse_hygiene.py` / `test_smart_import_e2e_reconciliation.py`。断言点：

- `build_full_question_content("SCENARIO...", "Which...") == "SCENARIO...\n\nWhich..."`
- `_write_question_to_bank()` 写入的 `Question.content` 使用完整题干，且不新增正式 `scenario` 字段依赖
- `accept_review_item()` 接受含 `scenario_text` 的复核项后，正式题干完整
- reparse 新写入题目时仍经 `_write_question_to_bank()`，正式题干完整且不破坏 `imported_qnos` 去重
- `_split_by_question_markers()` 会归属明显 `SCENARIO` 前导材料，不归属答案/解析/广告/页眉类前导文本
- `_quality_check()` 对当前题片段缺场景返回 `SCENARIO_MISSING`，但不误伤同 chunk 的普通题
- 回填脚本 dry-run 不写；`--apply` 才写；无 `scenario_text`、无正式题、已完整、疑似人工编辑的记录均跳过

### 7. Wrong vs Correct

#### Wrong

```python
# 写正式题时只保存最后一问
question = Question(
    bank_id=bank_id,
    content=parsed_question.content,
    options=options,
    correct_answer=correct_answer_str,
)
```

问题：`scenario_text` 留在导入审计表，答题页只看到 `Which is the best next step...`，无法作答。

#### Correct

```python
full_content = build_full_question_content(
    parsed_question.scenario_text,
    parsed_question.content,
)
question = Question(
    bank_id=bank_id,
    content=full_content,
    options=options,
    correct_answer=correct_answer_str,
)
```

#### Wrong

```python
# chunk 中任意位置出现 SCENARIO，就把所有 parsed_q 都判为缺场景
if "SCENARIO" in chunk_text and not parsed_q.scenario:
    issues.append({"code": "SCENARIO_MISSING", "severity": "HIGH"})
```

#### Correct

```python
source_text = _source_text_for_quality_check(parsed_q, chunk_text)
if has_scenario_marker(source_text) and not parsed_q.scenario:
    issues.append({"code": "SCENARIO_MISSING", "severity": "HIGH"})
```

---

## Scenario E：默认自动处理导入题目

### 1. Scope / Trigger

智能导入此前把低置信度、缺字段等常规质量问题推入人工复核。实际使用中用户对这些待复核题通常只有“接纳结构完整题”或“跳过不可用题”两种选择，因此导入流水线改为默认自动处理，并提供只读追溯入口。

适用范围：`_save_parsed_question()` 首次导入与 reparse 新题写入、`_finalize_import()` 状态机、`serialize_import_job()` 计数字段、`GET /api/import-jobs/{job_id}/auto-handled`。

### 2. Signatures

```python
# backend/app/services/smart_import_service.py
def _unusable_question_issues(parsed_q: ParsedQuestion) -> list[dict]: ...
# 返回导致题目不能用于练习的 HIGH issue：STEM_MISSING / OPTIONS_MISSING /
# ANSWER_MISSING / ANSWER_NOT_IN_OPTIONS。


def _save_parsed_question(
    db: Session,
    parsed_q: ParsedQuestion,
    import_job: ImportJob,
    chunk: ImportChunk,
    *,
    chunk_text: str,
    auto_import: bool,
    seen_signatures: set | None = None,
    imported_qnos: set[str] | None = None,
) -> None: ...
# auto_import=True 时：可入库题目自动写 Question；不可用题目自动跳过。


def serialize_auto_handled_item(pq: ImportParsedQuestion) -> dict: ...
```

```http
GET /api/import-jobs/{job_id}/auto-handled
Authorization: Bearer <admin jwt>
```

### 3. Contracts

**可入库题目**：同时满足题干非空、至少 2 个选项、有正确答案、正确答案能匹配选项。可入库题目在 `auto_import=True` 时写入 `questions`，并标记：

```jsonc
{
  "review_status": "auto_accepted",
  "import_status": "imported",
  "imported_question_id": 123
}
```

低置信度、无题号、疑似噪声、疑似缺少场景材料等不再阻止自动入库；这些只保留在 `issues_json.details`，通过自动处理记录展示为质量提示。

**不可用题目**：缺题干、选项不足、缺少正确答案、正确答案不在选项中。不可用题目必须保留 `ImportParsedQuestion` 审计记录，但不写 `Question`，不创建 `ImportReviewItem`，并标记：

```jsonc
{
  "review_status": "auto_skipped",
  "import_status": "skipped",
  "imported_question_id": null,
  "issues_json": {"details": [{"code": "ANSWER_MISSING", "severity": "HIGH"}]}
}
```

**导入任务序列化新增字段**：

```jsonc
{
  "auto_imported_questions": 10,
  "auto_skipped_questions": 2,
  "auto_handled_questions": 12,
  "summary": {
    "auto_imported": 10,
    "auto_skipped": 2,
    "auto_handled": 12
  }
}
```

**自动处理记录响应**：

```jsonc
{
  "items": [{
    "id": 1,
    "result": "auto_imported" | "auto_skipped",
    "reason": "题目结构完整，已自动入库" | "缺少正确答案",
    "quality_tips": ["无题号", "疑似包含噪声"],
    "source_question_no": "247",
    "content": "Which is the best next step?",
    "scenario_text": "SCENARIO...",
    "correct_answer": ["A"],
    "handled_at": "2026-05-15T10:00:00+00:00"
  }],
  "total": 1
}
```

**`ImportJob.status` 扩展**：`unimported` 表示本次任务有解析题、全部自动跳过、没有入库题、没有失败 chunk、没有待复核。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 题干缺失或过短 | `auto_skipped`，不写 `Question`，不建 `ImportReviewItem` |
| 选项少于 2 个 | `auto_skipped`，不写 `Question`，不建 `ImportReviewItem` |
| `correct_answer=[]` | `auto_skipped`，原因“缺少正确答案” |
| 答案标签不在选项标签集合 | `auto_skipped`，原因“正确答案不在选项中” |
| 结构完整但 `confidence < 0.90` | `auto_accepted`，质量提示保留 |
| 结构完整但 `NO_QUESTION_NO` / `NOISE_DETECTED` / `SCENARIO_MISSING` | `auto_accepted`，质量提示保留 |
| `auto_import=False` | 保留原人工复核兜底路径，创建 `ImportReviewItem` |
| 重复题号 / 重复内容 | 继续走 `review_status='duplicate'`, `import_status='skipped'`，不计入自动处理记录 |
| 全部自动跳过且无失败 chunk | `_finalize_import()` 设置 `status='unimported'` |
| 有失败 chunk | 优先 `partial_imported`，不得被 `unimported` 覆盖 |

### 5. Good / Base / Bad Cases

- **Good**：结构完整但低置信度题目自动入库，自动处理记录显示“题目结构完整，已自动入库”并附“无题号”等质量提示。
- **Base**：缺答案题目自动跳过，用户在自动处理记录中看到“缺少正确答案”，题库题量不增加，待复核数不增加。
- **Bad**：继续用置信度阈值阻止低置信完整题入库，导致复核队列虚高。
- **Bad**：不可用题完全丢弃不保存 `ImportParsedQuestion`，用户无法追溯程序跳过了哪些题。

### 6. Tests Required

文件：`backend/tests/test_smart_import_scenario_content.py`，断言点：

- 缺题干、选项不足、缺答案、答案不在选项中均保存为 `review_status='auto_skipped'`、`import_status='skipped'`。
- 自动跳过不写 `questions`，不创建 `ImportReviewItem`，不增加 `review_questions`。
- 低置信但结构完整题保存为 `auto_accepted/imported`，写入 `questions`，且 `serialize_auto_handled_item()` 返回质量提示。
- 全部自动跳过时 `_finalize_import()` 设置 `ImportJob.status == 'unimported'`，并写入 `summary_json.auto_skipped/auto_handled`。
- 现有 reparse hygiene 与 reconciliation 测试必须继续通过，尤其有失败 chunk 时仍为 `partial_imported`。

### 7. Wrong vs Correct

#### Wrong

```python
should_auto_import = (
    auto_import
    and final_confidence >= Decimal("0.90")
    and not any(issue["severity"] == "HIGH" for issue in issues)
)
if not should_auto_import:
    db.add(ImportReviewItem(...))
```

问题：结构完整但低置信度、无题号或疑似噪声的题仍进入人工复核，制造用户无法有效处理的队列。

#### Correct

```python
unusable_issues = _unusable_question_issues(parsed_q)
if unusable_issues:
    parsed_question.review_status = "auto_skipped"
    parsed_question.import_status = "skipped"
elif auto_import:
    question = _write_question_to_bank(db, parsed_question, import_job.bank_id)
    parsed_question.review_status = "auto_accepted"
    parsed_question.import_status = "imported"
    parsed_question.imported_question_id = question.id
else:
    db.add(ImportReviewItem(...))
```

---

## Scenario F：允许同文件重复导入，去重边界下沉到题目级

### 1. Scope / Trigger

同一题库重复上传相同文件时，`create_smart_import_job()` 曾基于 `bank_id + file_hash` 直接返回 `该文件已导入过`，API 层据此返回 409。这会阻断用户重新导入同一份题库文件，且无法生成本次导入任务、解析记录和跳过原因。

### 2. Contracts

- `file_hash` 只能用于追溯同文件历史导入，不能作为同题库导入的硬阻断。
- 命中同 `bank_id + file_hash` 的历史 `ImportJob` 时，仍必须创建新的 `ImportJob` 与 `BackgroundJob`。
- 新 `ImportJob.config_json` 可记录 `duplicate_file_of`、`duplicate_file_status` 等溯源字段；使用 dict 重新赋值或创建完整 dict，避免 JSONB dirty 检测问题。
- 重复题目去重边界在 `_save_parsed_question()` / `_write_question_to_bank()`：通过题目完整题干、选项、答案、题型组成的内容签名判断重复；命中后必须**逐题**保留 `ImportParsedQuestion`，标记 `review_status="duplicate"`、`import_status="skipped"`，不写新的 `Question`。不得因为整文件重复或整 chunk 缓存命中而只保留第一道重复题。
- 题目签名必须归一化选项标签来源（`label` / `key`），避免 LLM 解析结构与正式表存储结构字段名不同导致同题漏判。
- 全部解析题都为 `duplicate/skipped`、且无新增入库/待复核/失败 chunk 时，`_finalize_import()` 不得把任务标为 `imported`；应使用 `unimported`（或等价的未新增入库语义）并在摘要中暴露 duplicate skipped 数量，避免用户误以为本次导入新增成功。
- PDF 正文中的单题答案块（如每题后跟 `Answer:` / `Explanation:`）不得被当作末尾答案键剥离；只有成段的 `Answer Key` / `Answers:` 等答案键标题才可从正文移除。否则重复旧文件时会在第一道题答案处截断正文，只生成 1 个 chunk / 1 条 parsed record。
- `force=true` 可保留为兼容参数，但同文件重导入不再依赖它。

### 3. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 同一题库、相同 `file_hash` 再次导入 | 创建新导入任务，不返回 400/409 |
| 同一题库、重复文件中的相同题目 | 每道重复题都写 duplicate/skipped 解析记录，不新增正式题 |
| 重复文件全部题目均 duplicate/skipped | 任务终态为 `unimported`（无新增入库），摘要包含 `duplicate_skipped` |
| PDF 每题内联 `Answer:` / `Explanation:` | 不剥离正文，后续题目仍参与 chunk 切分与 parsed record 保存 |
| 不同题库、相同 `file_hash` | 正常创建新任务；题目去重仅在目标题库内生效 |
| `force=true` | 保持兼容，不改变题目级去重语义 |

### 4. Tests Required

- 同 bank 相同 `file_hash` 第二次调用 `create_smart_import_job()` 不返回 error，并记录 duplicate file 溯源字段。
- 重复文件第二次处理同题内容时，`questions` 数量不增加，`import_parsed_questions` 按题目数量逐条新增 duplicate/skipped 记录且 `details[0].reason == "content"`。
- 全部 duplicate/skipped 时 `_finalize_import()` 输出 `status="unimported"` 且 `summary_json.duplicate_skipped` 为重复题数。
- 含每题内联 `Answer:` 的 PDF 文本不会在第一处答案截断，`_extract_answer_key()` 不应把单题答案块识别为末尾答案键。

---

## Scenario G：正式题目 AI 解析与导入解析边界

### 1. Scope / Trigger

智能导入的 LLM 解析会产出 `ImportParsedQuestion.explanation`，但该内容用于辅助识别题目结构、答案和来源材料，不等同于用户在练习中主动请求的 AI 辅导解析。正式题目的 `Question.explanation` / `Question.explanation_zh` 只表示用户点击“AI 解析”后生成并缓存的结果。

### 2. Signatures

```python
# backend/app/services/smart_import_service.py
def _write_question_to_bank(
    db: Session,
    parsed_question: ImportParsedQuestion,
    bank_id: int,
) -> Question | None: ...
# 自动入库、reparse 自动入库、review accept 写正式 Question 的统一入口。
# 不得把 parsed_question.explanation 写入 Question.explanation。
```

```bash
# backend/scripts/clear_question_explanations.py
python3 backend/scripts/clear_question_explanations.py [--apply]
```

### 3. Contracts

- `ImportParsedQuestion.explanation`：导入解析记录，保留在导入任务语境中，用于导入详情、复核和追溯。
- `Question.explanation` / `Question.explanation_zh`：正式题目 AI 解析缓存，只能由用户主动请求 AI 解析的路径写入。
- `_write_question_to_bank()` 创建 `Question` 时必须保持 `explanation=None`、`explanation_zh=None`，即使 `parsed_question.explanation` 非空。
- 清理脚本默认 dry-run，只统计至少一个正式解析字段非空的题目数量并 rollback。
- 清理脚本只有传 `--apply` 时才清空 `Question.explanation` 与 `Question.explanation_zh` 并 commit。
- 清理脚本不得修改 `ImportParsedQuestion.explanation`，不得放进 Alembic migration、应用启动或部署钩子自动执行。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 自动入库解析题含 `parsed_question.explanation` | 正式 `Question.explanation/explanation_zh` 仍为空；导入解析保留在 `ImportParsedQuestion.explanation` |
| 人工复核 accept 的解析题含 `parsed_question.explanation` | 同样经 `_write_question_to_bank()`，正式题目解析字段为空 |
| reparse 新入库题含 LLM explanation | 正式题目解析字段为空，导入解析记录保留 |
| 用户点击 AI 解析且正式题目无解析 | `/api/ai/explain` 调 AI 并写入 `Question.explanation/explanation_zh` |
| 用户点击 AI 解析且正式题目已有解析 | 返回缓存，不重新生成 |
| 清理脚本未传 `--apply` | 输出待清理数量，不修改数据库 |
| 清理脚本传 `--apply` | 清空所有正式题目的 `explanation/explanation_zh`，不动导入解析记录 |

### 5. Good / Base / Bad Cases

- **Good**：导入详情能看到导入解析；练习页首次点击“AI 解析”会生成正式 AI 解析。
- **Base**：题目已有用户生成的 AI 解析时，再次点击只展示缓存。
- **Bad**：把 `ImportParsedQuestion.explanation` 写进 `Question.explanation`，导致前端和后端误以为 AI 解析已存在，用户无法生成真正的辅导解析。
- **Bad**：把历史清理放进 Alembic migration，部署时无提示清空生产解析数据。

### 6. Tests Required

- 自动入库：解析题含非空 `explanation` 时，新建 `Question.explanation/explanation_zh` 为空，`ImportParsedQuestion.explanation` 保留。
- 复核 accept：正式题目解析字段为空，导入解析记录保留。
- reparse：LLM 返回非空 explanation 时，正式题目解析字段为空，导入解析记录保留。
- 清理脚本 dry-run：返回待清理数量，不改变 `Question` 与 `ImportParsedQuestion`。
- 清理脚本 `--apply`：清空 `Question.explanation/explanation_zh`，不改变 `ImportParsedQuestion.explanation`。

### 7. Wrong vs Correct

#### Wrong

```python
question = Question(
    bank_id=bank_id,
    content=full_content,
    options=options,
    correct_answer=correct_answer_str,
    explanation=parsed_question.explanation,
)
```

#### Correct

```python
question = Question(
    bank_id=bank_id,
    content=full_content,
    options=options,
    correct_answer=correct_answer_str,
    explanation=None,
    explanation_zh=None,
)
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
| D9 | 场景题正式题干合并到 `Question.content`，不新增 `Question.scenario` | 现有答题页、错题本、复制、翻译等功能只读 `Question.content`，合并可零前端迁移获得完整题干 |
| D10 | `build_full_question_content()` 是正式题干唯一构造入口 | 防止自动入库、reparse、review accept、历史回填规则漂移 |
| D11 | 第一个题号前导材料采用保守归属 | 优先修复明显场景/阅读材料丢失，同时降低吞入页眉、广告、上一题解析或答案段落的风险 |
| D12 | 历史回填默认 dry-run，显式 `--apply` 才写 | 避免一次性脚本误改历史正式题，尤其保护人工编辑过的内容 |
| D13 | 智能导入默认按可用性自动处理，不再按置信度阈值进入人工复核 | 用户对常规待复核项缺少有效选择；结构完整题自动入库，不可用题自动跳过并保留追溯记录 |
| D14 | 文件 hash 不作为同题库重复导入硬阻断，去重边界下沉到题目级 | 保留每次导入任务的可追溯性，同时通过题目签名 duplicate/skipped 防止正式题库重复增长 |
| D15 | 正式题目的 `explanation/explanation_zh` 只表示用户主动生成的 AI 解析 | 避免导入解析占用正式题目解析字段，导致 AI 解析按钮误判已有缓存 |

---

## 参考

- 任务 PRD：`.trellis/tasks/05-04-smart-import-cipt-283-pdf/prd.md`
- 诊断报告：`.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/diagnosis-step0.md`
- PR 设计文档：`.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/pr{1,2,3,4}-design-*.md`
- 场景题完整题干任务：`.trellis/tasks/05-12-fix-smart-import-incomplete-scenario-stems/prd.md`
- 场景题实现研究：`.trellis/tasks/05-12-fix-smart-import-incomplete-scenario-stems/research/smart-import-scenario-stems.md`
