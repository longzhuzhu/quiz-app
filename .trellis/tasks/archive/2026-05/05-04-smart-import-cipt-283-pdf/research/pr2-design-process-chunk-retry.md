# PR-2 Design — _process_chunk retry & per-question fallback

> 研究子代理产出，仅做静态分析；未修改任何源代码、未发起 LLM 调用。
> 数据源：`backend/app/services/smart_import_service.py`、`backend/app/services/job_service.py`、
> `backend/app/services/ai_service.py`、`backend/app/workers/job_worker.py`、`backend/app/core/config.py`、
> `backend/app/models/import_chunk.py`、`backend/app/models/import_job.py`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/diagnosis-step0.md`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/pr1-design-call-ai-api-timeout.md`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/prd.md`。

---

## A. 当前控制流

### A.1 `_process_chunk` 状态机（`smart_import_service.py:354-442`，PR-1 已 commit `5ab8125`）

```
┌─ chunk.status="pending"（_split_into_chunks 后写入，行 279）
│
└─► _process_chunk 入口（354）
     │
     │ 363 chunk.status = "parsing"
     │ 364 db.commit()
     │
     ├── (cache hit) ──► 377-380 写 llm_response_json + status="parsed_cached"  ⇢ ⓢ
     │
     └── (cache miss) ──► 383-385 chunk.llm_request_json = ...  +  db.commit()
                          │
                          │ 387-388 response_text = call_ai_api(..., timeout=120.0)
                          │
                          ├──[Exception]──► 389-393  status="llm_failed"; issues_json={"error": ...}; commit; raise   ⇢ ⓕ-llm
                          │
                          ├──[parse OK]
                          │   ├─ 395-403 _parse_llm_response → status 在 except 分支变 "parse_failed"; raise          ⇢ ⓕ-parse
                          │   ├─ 405      llm_response_json = json.loads(response_text)
                          │   └─ 406      chunk.status = "parsed"                                                     ⇢ ⓢ
                          │
                          └─ 409-414 _store_llm_cache（仅成功路径写缓存）

  ⓢ（共享尾段，缓存命中 / cache miss 成功）
       417-424 (cache 路径才走) 再次 _parse_llm_response（如失败 → status="parse_failed"; raise）
       427-428 if llm_result.chunk_issues: chunk.issues_json = {"chunk_issues": ...}
       430     db.commit()
       433-442 for parsed_q: _save_parsed_question(...)
                  └─ 内部各自 db.commit()（行 486 / 556 / 604-606 等）
```

### A.2 所有 `db.commit()` / `chunk.status =` 写点（按行号）

| 行号 | 写点 | 当前事务边界 |
|---|---|---|
| 279 | `chunk.status="pending"`（在 run_smart_import 中） | 与 chunks 批量 add 同一事务 |
| 282 | `db.flush()` after addAll chunks | run_smart_import |
| 292 | `db.commit()`（保存 total_chunks + answer_key_text + chunks） | run_smart_import |
| 363 | `chunk.status="parsing"` | _process_chunk |
| 364 | `db.commit()` | _process_chunk |
| 380 | `chunk.status="parsed_cached"` | _process_chunk（cache 路径，未单独 commit；与 430 合并）|
| 384 | `chunk.llm_request_json = ...` | _process_chunk |
| 385 | `db.commit()`（持久化 prompt，便于事后调试）| _process_chunk |
| 390 | `chunk.status="llm_failed"`；391 `chunk.issues_json={"error": ...}` | _process_chunk |
| 392 | `db.commit()` | _process_chunk |
| 399 | `chunk.status="parse_failed"` | _process_chunk |
| 400-401 | `chunk.issues_json` + `chunk.llm_response_json` | _process_chunk |
| 402 | `db.commit()` | _process_chunk |
| 405-406 | `llm_response_json` + `chunk.status="parsed"` | _process_chunk（未单独 commit；并入 430）|
| 414 | `_store_llm_cache` 内部 `db.flush()`（无 commit） | _process_chunk |
| 421 | `chunk.status="parse_failed"`（cache 二次解析失败分支）；422 issues；423 commit | _process_chunk |
| 428 | `chunk.issues_json={"chunk_issues":...}` | _process_chunk |
| 430 | `db.commit()`（关键：把 status="parsed"/"parsed_cached" 与 issues 一并落盘） | _process_chunk |
| 433-442 | `_save_parsed_question` 循环（每题各自 commit） | _process_chunk → _save_parsed_question |
| 334-337 | run_smart_import 顶层 except：status="failed", issues_json={"error":...}, failed_chunks+=1, commit | run_smart_import |

> **关键事实 1**：行 392/402 已经把状态分别写为 `llm_failed` / `parse_failed` 并 commit，然后 `raise`；run_smart_import 的 except 又把 status 覆盖成 `failed`（行 334-337）。最终 DB 落盘的 chunk.status 是 `failed`，前面那两个中间状态对外不可见——只在故障期短暂存在。这意味着 PR-2 重试时**必须把 chunk.status 重置为 `parsing`**（已被 392 / 402 改写过），否则 status 状态机会"前进-倒退"显得混乱。
>
> **关键事实 2**：行 384-385 在 LLM 调用前就 commit 了 `llm_request_json`。意图是事后便于事后审计 prompt。PR-2 重试时也应保持该不变量（或改为只在最后一次成功后 commit）。

### A.3 `_lookup_llm_cache` 命中 vs miss 在重试场景下的行为

* **缓存键**：`sha256(PROMPT_VERSION + chunk_hash)`（`_build_cache_key` 行 1245-1248）。**仅在成功路径写入**（行 409-414，受 `if use_llm_cache` 控制）；timeout / 4xx / parse_failed 都**不写缓存**（与 diagnosis Step 0 对照表 C.6 一致）。
* **首次进入 _process_chunk**（cache miss）→ 走 LLM；**首次失败（timeout）后再次进入**（例如 reparse 或 PR-2 的 L1 重试）→ 因为没写缓存，仍 cache miss，重新发 LLM。
* **PR-2 关注点**：L1 整 chunk 重试时，**不应**重新查 `_lookup_llm_cache`——一来同 chunk_hash 不会突然出现新缓存（除非并发 reparse），二来重新查只会徒增 DB 读压力。L1 重试**直接复用**原 `messages` 重新 `call_ai_api` 即可。
* **L2 单题降级**：每个单题 prompt 与 chunk 级 prompt 不同，自然不会与 chunk_hash 缓存冲突。

### A.4 上层 `run_smart_import` 对 `_process_chunk` 异常的处理

`run_smart_import` 行 322-346：

```python
for index, chunk in enumerate(chunks, start=1):
    import_job = db.get(ImportJob, import_job_id)
    bg_job = db.get(BackgroundJob, background_job.id)

    try:
        _process_chunk(db=db, chunk=chunk, import_job=import_job, ...)
    except Exception as exc:                                         # 行 332
        logger.error("Chunk %d 解析失败: %s", chunk.chunk_no, exc)
        chunk.status = "failed"                                       # 行 334
        chunk.issues_json = {"error": str(exc)}                       # 行 335
        import_job.failed_chunks = (import_job.failed_chunks or 0)+1  # 行 336
        db.commit()                                                   # 行 337
        # 单个 chunk 失败不中断整个导入

    heartbeat_job(db, bg_job, success_increment=1, ...)               # 行 341
```

* `failed_chunks` 计数仅在外层 except 触发；
* `heartbeat_job` 不论成功/失败都调用，但**只在 chunk 级颗粒度**（不在 chunk 内部）。
* PR-2 必须保证**正常成功路径下不进外层 except**（否则 `failed_chunks++`）。L1 重试成功 / L2 全部成功 应当**不抛出**到上层。

---

## B. 异常分类与重试决策

### B.1 `call_ai_api` 抛出的异常类型清单（PR-1 design A.1 已罗列）

| 异常类型 | 触发条件 | 行 # | PR-2 决策 |
|---|---|---|---|
| `httpx.TimeoutException`（含 `ConnectTimeout`/`ReadTimeout`/`WriteTimeout`/`PoolTimeout`） | httpx 网络层超时 | — | **L1 重试候选** ✅ |
| `httpx.ConnectError` / `httpx.NetworkError`（`HTTPError` 子类） | 连接被拒、DNS 失败、TLS reset | — | **L1 重试候选** ✅ |
| `httpx.HTTPError` 其它子类（`ProtocolError`、`StreamError`） | 不常见网络瑕疵 | — | **L1 重试候选** ✅ |
| `ValueError("AI API Key 未配置...")` | 行 96-97 | 配置缺失 | **不重试** ❌（无意义；直接失败）|
| `ValueError("AI API 错误 (4xx): ...")` | 行 119-121；status_code ∈ [400,500) | 请求结构问题 | **不重试** ❌ |
| `ValueError("AI API 错误 (5xx): ...")` | 行 119-121；status_code ∈ [500,600) | provider 暂时性故障 | **L1 重试候选** ✅ |
| 隐式 `KeyError` / `IndexError` | 行 122 `data["choices"][0]...` 解析失败 | provider 返回结构异常 | **不重试** ❌（重试无意义）|

### B.2 `_parse_llm_response`（行 1106-1130）抛出的异常

| 异常 | 触发条件 | PR-2 决策 |
|---|---|---|
| `ValueError("LLM 响应不是合法的 JSON")` | 既非纯 JSON 也无 `{...}` 大花括号 | **不重试**（LLM 已返回内容但格式错；二次 prompt 修正不在本 PR 范围）|
| `pydantic.ValidationError` | Pydantic 校验失败 | **不重试**（同上）|
| `json.JSONDecodeError` | 大花括号匹配后仍非合法 JSON | **不重试** |

### B.3 重试逻辑封装（伪代码）

```python
import httpx

# 仅这两类视为可重试
RETRYABLE_EXC: tuple = (httpx.TimeoutException, httpx.HTTPError)

def _is_retryable_value_error(exc: ValueError) -> bool:
    """4xx 不重试；5xx 重试；其它（API key 未配置）不重试"""
    msg = str(exc)
    if "AI API 错误 (5" in msg:        # "AI API 错误 (5xx): ..."
        return True
    return False
```

> 注意：`httpx.TimeoutException` 是 `httpx.HTTPError` 的子类。先 catch `TimeoutException` 再 catch `HTTPError` 顺序无关紧要，因为两者都进 retryable 桶。但**不要**用 broad `except Exception` 把 `ValueError` / `pydantic.ValidationError` 也吃进去。

### B.4 PRD "L1 重试 1 次" + 指数退避 base=2s/cap=10s 的内在矛盾

* 单次重试时 backoff 序列只用 1 项 `[2s]`；指数退避 base/cap 在该单值上**没有意义**。
* 选项分析：
    * **(α) 严格按 PRD 字面：1 次重试，固定 sleep 2s**。简单、可测；但放弃了 backoff 语义。
    * **(β) 改为最多 2 次重试**（共 3 次调用，sleep `[2s, 4s]`，cap=10s 防御未来扩展）。最坏 3×120s = 360s，仍小于单 chunk 的 8 分钟预算（见 I 节）。
    * **(γ) 完全不指数，只 1 次 sleep 2s**。同 α。

> **推荐：α**。理由：
> 1. PRD 数据驱动假设——chunk 27 是 OpenAI/兼容服务**临时拥塞**，2s 后重发概率高；多 1 次更不会大幅提高命中率，反而把"L1 不行就赶紧 L2"的语义稀释；
> 2. PRD 锁定 MVP 只解 24 题缺口，避免过度工程；
> 3. backoff 公式可在 docstring 中注明"为未来扩展预留 base=2s, cap=10s 的参数面，但本 PR 仅消费 1 次重试间隔"。
> 4. 同时**回填 PRD**：将 "L1 整 chunk 重试 1 次（重试间隔 2s）" 写得更精确——"最初 1 次调用 + 最多 1 次重试 = 共 2 次调用；重试前 sleep 2s；指数退避参数预留但本 PR 不消费"。

---

## C. 单题降级（L2）拆分策略

### C.1 复用 `_split_by_question_markers`（行 978-1017）

* 当前函数签名 `def _split_by_question_markers(text: str) -> list[dict]`，返回 `[{"text": str, "start_page": None, "end_page": None}, ...]`。
* **关键陷阱**：函数末尾（行 1004-1015）有"过小片段合并"逻辑，把单题片段按 `CHUNK_MAX_CHARS` 上限**重新合并**，使返回值仍是"多题为一组"——这与 L2 "每题一段"目标**正相反**。
* 因此 PR-2 **不能**直接调 `_split_by_question_markers(chunk.chunk_text)`；要么：
    * **方案 A**：在 PR-2 内**抽出新私有函数** `_split_by_single_question(text: str) -> list[dict]`，复用 `QUESTION_SPLIT_PATTERNS` finditer 流程，但**跳过合并步骤**。≈10-15 行。
    * **方案 B**：给 `_split_by_question_markers` 加 `merge_small: bool = True` 参数，L2 传 `merge_small=False`。改动面更小，但是给现有正常路径（`_split_into_chunks`）引入新参数，需要回归测试。
* **推荐：方案 A**。新函数职责单一、不破坏现有路径、易于在 PR-2 单测中独立 mock。

### C.2 chunk 内只含 1 道题时的退化情形

* CIPT chunk_no=31 含 4 题（280-283），最尾 chunk 字符数 2,617，远小于上限。即使尾部 chunk 也不会出现"1 道题独占 chunk"的情况；但通用性仍要保证：
    * 若 `_split_by_single_question` 仅返回 1 个 segment（原 chunk 只 1 题），L2 等价于"再发一次单 chunk LLM 调用"；与 L1 重试相比仅"timeout 上限不同（60s vs 120s）"。逻辑上正确——**timeout 收紧到 60s 是合理的**，因为单题输入文本比 chunk 小 ≥10 倍。
    * 若 `_split_by_single_question` 返回 0 个（题号正则未命中），说明该 chunk 根本没有题号标记——这种 chunk 进入 L2 也无法降级。**回退策略**：保留 chunk.status="failed"，issues_json={"error":..., "fallback_skipped":"no_question_markers"}。

### C.3 segments 的 page 字段

* `_split_by_question_markers` 当前在每个 segment 上写死 `start_page=None, end_page=None`（行 1002）；上层 `_split_into_chunks`（行 966-973）也透传 None。即 chunk 27 的 `start_page` / `end_page` 在 DB 里就是 NULL（与诊断报告 A 一致）。
* 因此 L2 单题降级**不需要**新算 page，沿用 chunk.start_page / chunk.end_page 即可（或保持 None）。

### C.4 单题 prompt 复用 `_build_llm_prompt`

* 复用 `_build_llm_prompt(single_q_text, answer_key_text)`（行 1044-1103）。System Prompt 第 2 条明确写 "一个文本片段可能包含一道题或多道题"——单题输入是其特殊情形，LLM 仍会按 `{"questions":[{...}]}` 格式返回。
* **理由**：减少 prompt 维护点（PROMPT_VERSION 已锁 v1，缓存兼容）；不改动 prompt 即不需 bump prompt 版本。
* **风险**：单题输入下 LLM 可能误判 "questions" 为空数组（罕见）→ 该题进 per_question_failures，与超时同等处理。

### C.5 单题 timeout=60s 合理性

| 参数 | chunk 27（24 题）| 单题（典型）|
|---|---|---|
| 输入字符数 | 11,848 | ~500-800（CIPT 题干 + 4 选项 + Correct Answer 行） |
| 输入 tokens 估算 | ~3,500 | ~150-250 |
| 输出 tokens 估算（24 q × 250 t/q）| ~6,000 | ~250 |
| 60s 是否够 | **不够**（PR-1 提到 60s 实测 timeout） | **够**（输入/输出量约 1/15-1/24）|

→ **60s/题 合理**，与 PR-1 设计 G.1 "smart_import 显式 120s, 其它默认 60s" 默认值一致；L2 显式传 `timeout=60.0` 即可（即让 ai_service 用默认值）。

---

## D. 状态机与持久化

### D.1 单题降级响应如何 merge 到 `chunk.llm_response_json`

| 选项 | 描述 | 评估 |
|---|---|---|
| **(a)** 合并所有单题响应为 `{"questions":[...合并题...], "chunk_issues":[]}`，结构与初次 chunk 级响应一致 | 兼容下游 `_parse_llm_response` 的 `LlmParseResult` 校验；reparse / 缓存命中查询的下游代码不必区分 chunk 级 / 单题级 | ✅ **推荐**。结构一致 = 下游零改动。|
| (b) 不写 `chunk.llm_response_json`，仅写 `chunk.issues_json["fallback_used"]=True` | 简化写入路径，但破坏"chunk 解析后必有响应"的不变量；事后审计无法看到 LLM 真返回内容 | ❌ |
| (c) 新增 `chunk.fallback_responses_json` 字段 | **违反 PRD"不改 schema"约束** | ❌（PRD AC6 / Requirements 显式禁止）|

> **推荐：选项 (a)**。在 L2 完成后构造：
> ```python
> chunk.llm_response_json = {
>     "questions": [parsed.dict() for parsed in successful_per_q_parses],
>     "chunk_issues": [],
>     "_fallback_meta": {"per_question_count": N, "succeeded": K, "failed": N-K},
> }
> ```
> `_fallback_meta` 是命名约定（下划线前缀），不会被 `LlmParseResult` Pydantic schema 校验拒绝（pydantic 默认忽略未知字段除非配 `extra="forbid"`，而 `LlmParseResult` 未配）。

### D.2 单题失败时是否写 `ImportParsedQuestion` 占位行？

| 选项 | 评估 |
|---|---|
| **(α) 不写占位行**，仅在 `chunk.issues_json["per_question_failures"]` 记题号 | ✅ **推荐**。理由：① `ImportParsedQuestion` 当前 schema 字段（`content`、`options_json` 等）非空必填；占位行需要构造无意义文本，污染前端复核列表；② PRD AC2 reconciliation 用 `set(ImportParsedQuestion.source_question_no) ⊕ {1..283}` 算 missing_qnos，占位行反而搅乱算账；③ `failed_chunks` 计数 + per_question_failures 已足够 PR-4 reconciliation 报告。 |
| (β) 写"假占位行" `import_status='failed', review_status='failed'` | ❌。需要在所有读取 ImportParsedQuestion 的地方加过滤（前端列表、reparse、reconciliation），改动面大；与"不改 schema"精神冲突（虽不改字段但改语义）。|

### D.3 `chunk.status` 取值约束 + PR-2 新增取值

* `ImportChunk.status` 字段是 `String(32)`（`import_chunk.py:28`），**无 enum / Check 约束**——任意 ≤32 字符的字符串均可写入。
* 现有取值（grep 出）：`pending`、`parsing`、`parsed`、`parsed_cached`、`llm_failed`、`parse_failed`、`failed`。
* PR-2 推荐**新增 2 个取值**（`String(32)` 容量足够，无需迁移）：

| chunk.status | 触发场景 | failed_chunks 计数 | imported 题号贡献 |
|---|---|---|---|
| `parsed`（已有）| 一次性成功 | 否 | 全部 |
| `parsed_cached`（已有）| 缓存命中 | 否 | 全部 |
| **`parsed_retry`**（新）| L1 重试后成功 | 否 | 全部 |
| **`parsed_fallback`**（新）| L2 全部单题成功 | 否 | 全部 |
| **`parsed_partial`**（新）| L2 部分单题成功 | **是**（语义"有缺口"）| 仅成功部分 |
| `failed`（已有）| L2 全部失败 / 不可重试错误 | 是 | 0 |
| `llm_failed`/`parse_failed`（已有）| 中间瞬态，最终被 332-337 覆盖为 `failed` | — | — |

> 前端列表（如有 chunk 状态过滤器）会显示新值，但当前 `backend/app/api/routes/banks.py` / 前端 `ChunkList.vue` 等都是直接展示 `chunk.status` 字符串无白名单过滤——零兼容代价（已通过 `Grep "chunk.status"` 复核过：无 enum 校验在 API/前端层）。

### D.4 L1 重试前 status 重置流程

```
进入 _process_chunk (status=pending)
  → 363 status=parsing; commit
  → 387 call_ai_api → 抛 timeout
  → 390 status=llm_failed; commit          ← PR-2 改：不写 llm_failed，改为捕获后准备重试
  → (PR-2) sleep 2s
  → (PR-2) status=parsing 不变（重试前不再倒退一格写）
  → call_ai_api 第 2 次 → 成功
  → 406 status="parsed_retry"（PR-2 改）
  → 缓存写入 + _save_parsed_question 循环
```

> **关键**：把 392 的 commit 推迟到"L1 全失败"再写。当前的"先写 llm_failed 再 raise"在 PR-2 重试场景下显得多余（status 反复横跳）。具体：在 try 内 catch retryable_exc，进入重试 loop；只在重试用尽后才写 `chunk.status="llm_failed"` + commit。

---

## E. LlmParseCache 写入策略

| 路径 | 写缓存？ | 推荐理由 |
|---|---|---|
| 一次性成功（status=`parsed`）| ✅（现状不变）| 与 PR-1 注释一致 |
| L1 重试 1 次后成功（status=`parsed_retry`）| ✅ **写**（key 与初次相同，因 chunk_hash 不变）| 下次同 chunk_hash 来访（如 reparse）直接命中、避免再 timeout |
| L2 单题降级全部成功（status=`parsed_fallback`）| ❌ **不写** | cache_key 是按整 chunk hash，但 `llm_response_json` 是单题响应**拼装**，非真实 chunk 级 LLM 响应；下次 cache 命中后走 `_parse_llm_response(response_text)` 时仍能解析（结构兼容），**但**单题路径的 confidence/issues 与 chunk 级不可比，缓存进去会让"反复 reparse"的题号计数变得诡异。 |
| L2 部分成功（status=`parsed_partial`）| ❌ **不写** | 同上，且本身就有缺口，不应把"残缺响应"作为缓存 |
| 任何路径全失败（status=`failed`）| ❌（现状不变）| 已是当前行为 |

> 实现：在 `_process_chunk` 末尾根据"是否进过 L2"开关决定是否调 `_store_llm_cache`。最简单的实现是新增一个本地 `bool fallback_used`，与 `use_llm_cache` 一起决定。

---

## F. 上层 ImportJob 计数对接

### F.1 `chunk.issues_json` schema 扩展

`ImportChunk.issues_json` 字段是 PG `JSONB`（`import_chunk.py:32`），可任意扩展。当前已有键：
* `{"error": "..."}` — chunk 级失败错误
* `{"chunk_issues": [...]}` — LLM 返回的 chunk_issues

PR-2 扩展：

```jsonc
{
  // 原有键保留
  "chunk_issues": [...],

  // PR-2 新增
  "retry_count": 1,                      // L1 实际重试次数（0 = 未重试，1 = 重试 1 次后成功）
  "fallback_used": true,                 // L2 是否触发
  "per_question_failures": [
    {
      "source_question_no": "222",
      "stage": "L2_fallback",            // "L1_retry"（不会出现，L1 失败必进 L2）/ "L2_fallback"
      "error": "TimeoutException after 60.0s"
    }
  ],
  "fallback_meta": {
    "total_segments": 24,                 // L2 切出多少段
    "succeeded": 22,
    "failed": 2,
    "elapsed_seconds": 1320.5             // 该 chunk L1+L2 累计耗时（用于 PR-4 决策 review_required vs imported）
  }
}
```

> 该 schema 已与 PR-4 reconciliation 兼容：`per_question_failures[*].source_question_no` 直接 set-union 到 `missing_qnos`。

### F.2 `import_job.failed_chunks` 计数策略

| chunk 最终 status | failed_chunks++? | _finalize_import 决策 |
|---|---|---|
| `parsed_retry` / `parsed_fallback` | **不计入** | 视同成功 |
| `parsed_partial` | **计入**（有缺口）| 触发 partial_imported / review_required |
| `failed` | 计入（现状）| 触发 partial_imported |

**实现位置**：

* PR-2 不动 `run_smart_import` 行 332-337 的 except 分支（保留 catch-all 兜底，防御 PR-2 本身有 bug 漏 catch）。
* PR-2 在 `_process_chunk` 内**正常 return**（不 raise）当 status ∈ {parsed_retry, parsed_fallback, parsed_partial}；
* L2 部分成功的 `failed_chunks++` 在 `_process_chunk` 内显式自增，**不依赖外层 except**：

```python
if status == "parsed_partial":
    import_job.failed_chunks = (import_job.failed_chunks or 0) + 1
```

* 完全失败 → 仍 raise，由外层 except 处理（保持向后兼容）。

### F.3 `_finalize_import` 影响（仅供 PR-4 参考）

`_finalize_import`（行 1318-1351）当前看 `total_review` 与 `total_failed`：
* `review > 0 && imported > 0` → `partial_imported`
* `review > 0 && imported == 0` → `review_required`
* `review == 0 && failed > 0` → `partial_imported`
* 否则 `imported`

PR-2 让 `parsed_partial` 走 `failed_chunks++` 后 `_finalize_import` 自动落到 `partial_imported`。PR-4 再叠加 reconciliation 算出"真实唯一题号 vs expected"决定是否升格 `review_required`。

---

## G. 测试策略

### G.1 必备单元测试 case 清单

| TC | 名字 | 路径 | 关键断言 |
|---|---|---|---|
| TC-1 | `test_process_chunk_normal_path_no_retry_no_regression` | 正常成功 | call_ai_api 调用次数 = 1；chunk.status="parsed"；no per_question_failures；issues_json 不含 "retry_count" |
| TC-2 | `test_process_chunk_l1_retry_succeeds` | L1 重试 1 次成功 | call_ai_api 调用次数 = 2；chunk.status="parsed_retry"；issues_json["retry_count"]=1；imported 题号集 = chunk 全集；写入了 LlmParseCache（mock _store_llm_cache 被调用）|
| TC-3 | `test_process_chunk_l1_exhausted_l2_all_succeed` | L1 重试用尽，L2 全部单题成功 | call_ai_api 总调用次数 = 2 (L1) + N (单题数)；chunk.status="parsed_fallback"；fallback_used=True；imported 题号集 = chunk 全集；**未**写入 LlmParseCache |
| TC-4 | `test_process_chunk_l2_partial_failure` | L2 部分失败 | chunk.status="parsed_partial"；per_question_failures 含正确题号；imported_questions 计数 = 成功题数；import_job.failed_chunks += 1 |
| TC-5 | `test_process_chunk_l2_all_fail` | L2 全部失败 | chunk.status="failed"（沿外层 except 通道，或 _process_chunk 内显式写）；failed_chunks += 1；per_question_failures 包含全部题号 |
| TC-6 | `test_process_chunk_4xx_value_error_no_retry` | 4xx ValueError 不重试 | call_ai_api 调用次数 = 1；chunk.status="failed"；no fallback；no per_question_failures |
| TC-7 | `test_process_chunk_5xx_value_error_does_retry` | 5xx ValueError 走重试 | call_ai_api 调用次数 = 2；行为同 TC-2 |
| TC-8 | `test_process_chunk_pydantic_failure_no_retry` | _parse_llm_response 抛 ValidationError | 不重试；chunk.status="parse_failed"；不进 L2（PRD 范围外）|
| TC-9 | `test_process_chunk_l2_segment_zero` | chunk 内题号正则未命中（极端） | L2 无段可切 → chunk.status="failed", issues_json["fallback_skipped"]="no_question_markers" |
| TC-10 | `test_process_chunk_l1_retry_does_not_recheck_cache` | L1 重试时不再查缓存 | mock `_lookup_llm_cache` 仅被调 1 次 |
| TC-11 | `test_process_chunk_status_resets_on_retry` | L1 失败 → 重置为 parsing → 重试 | DB 中观察到的中间状态不是 "llm_failed"（即不应在重试期间短暂 commit `llm_failed`）|
| TC-12 | `test_process_chunk_l2_fallback_does_not_write_cache` | TC-3 的负面断言：未调 _store_llm_cache | mock _store_llm_cache 0 次调用 |

> 测试文件建议放 `backend/tests/test_smart_import_process_chunk_retry.py`。沿用 PR-1 的 fixture 风格（无 conftest.py，每文件自带 DB session fixture）。

### G.2 mock 策略

直接 mock `app.services.smart_import_service.call_ai_api`（PR-1 测试已验证可行；详见 `tests/test_ai_service_call_api_timeout.py:TC-4`）。**不进 httpx**——避免依赖 httpx 内部行为，且与 PR-1 测试风格一致。

参考代码片段（伪代码，PR-2 实现时填充）：

```python
import httpx
import pytest
from unittest.mock import MagicMock

def test_process_chunk_l1_retry_succeeds(monkeypatch, db_session, sample_chunk, sample_import_job):
    call_count = {"n": 0}

    def fake_call_ai_api(messages, db, scene, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("timed out")
        # 第 2 次返回正常 JSON
        return json.dumps({
            "questions": [
                {"source_question_no": "222", "question_type": "single",
                 "content": "...", "options": [...], "correct_answer": ["A"],
                 "confidence": 0.95, "issues": []},
                # ... 24 题
            ],
            "chunk_issues": []
        })

    monkeypatch.setattr(
        "app.services.smart_import_service.call_ai_api",
        fake_call_ai_api,
    )
    monkeypatch.setattr(
        "app.services.smart_import_service.time.sleep",  # 防止 backoff 拖慢测试
        lambda _s: None,
    )

    _process_chunk(db=db_session, chunk=sample_chunk,
                   import_job=sample_import_job, auto_import=True,
                   use_llm_cache=False, seen_signatures=set())

    assert call_count["n"] == 2
    db_session.refresh(sample_chunk)
    assert sample_chunk.status == "parsed_retry"
    assert sample_chunk.issues_json["retry_count"] == 1
```

> 关键：`monkeypatch.setattr("app.services.smart_import_service.time.sleep", ...)` 把 backoff 时间归零；如 PR-2 用 `time.sleep` 实现 backoff，PR-2 在 import 时显式 `import time` 即可让该 mock 生效（避免 `from time import sleep` 局部绑定）。

### G.3 集成测试范围

PR-2 不写"全 PDF 跑通"的集成测试（留给 PR-4）。PR-2 单元测试足够覆盖 retry/fallback 状态机；E2E 集成留待 PR-4 做 reconciliation 时一并补。

---

## H. 与 PR-3 / PR-4 的接口

### H.1 `chunk.issues_json["per_question_failures"]` 与 PR-4

PR-2 schema（详见 F.1）：
```jsonc
{
  "per_question_failures": [
    {"source_question_no": "222", "stage": "L2_fallback", "error": "TimeoutException after 60.0s"}
  ],
  "retry_count": 1,
  "fallback_used": true
}
```

PR-4 在 `_finalize_import` 末尾消费：

```python
# PR-4 伪代码
missing_qnos = set()
for chunk in db.query(ImportChunk).filter_by(import_job_id=import_job.id).all():
    if chunk.issues_json:
        for f in chunk.issues_json.get("per_question_failures", []):
            missing_qnos.add(f["source_question_no"])

# Reconciliation 写入 config_json
import_job.config_json = (import_job.config_json or {}) | {
    "reconciliation": {
        "expected": <input_qno_set>,
        "imported_unique": <imported set>,
        "missing_qnos": sorted(missing_qnos | (expected - imported)),
        "duplicates_in_db": [...],
    }
}
```

→ **schema 评估通过**，PR-4 无须扩展 issues_json 字段。

### H.2 PR-3（reparse 卫生）与 PR-2 的冲突点

`run_reparse`（行 689-751）当前流程：
1. 删除该 chunk 下未导入的 ImportParsedQuestion + 关联 ReviewItem；
2. 重置 `chunk.status="pending"`、`llm_request_json=None`、`llm_response_json=None`、`issues_json=None`（**关键：会清空 `per_question_failures`**）；
3. 重新调 `_process_chunk`。

**冲突分析**：
* reparse 一个 `parsed_partial` chunk 时，`issues_json["per_question_failures"]` 被清空 — 这是**正确的**：reparse 意图就是给该 chunk 一次"全新"机会，残留题号失败应被忘掉；
* PR-2 的 _process_chunk 重新跑会重新生成 issues_json（成功就 unset，部分成功就重写）；
* PR-3 不需要为 PR-2 做特殊处理。

**PR-3 关注的问题**（与 PR-2 解耦）：
* PR-3 的 `imported_qnos` 集合用来防止 reparse 时同题号被二次入库为 Question；
* 与 PR-2 的 `per_question_failures` 不交叉（一个是"失败题号"，一个是"已成功入库题号"）。

→ **无冲突**。PR-3 可在 PR-2 之后独立推进。

---

## I. 性能与时间预算

### I.1 worker lease 实测值

`backend/app/core/config.py:38` 有 `WORKER_LEASE_SECONDS=600`，但**实际未被消费**——`claim_next_job`（行 246）默认 `lease_seconds=DEFAULT_JOB_LEASE_SECONDS=180`（`job_service.py:27`），`heartbeat_job`（行 303）也默认 180s。`run_smart_import` 调 `heartbeat_job(db, bg_job, success_increment=1, ...)` 也未传 `lease_seconds`，即每次 heartbeat 把 lease 续到 180s 之后。

> ⚠️ **回填 PRD 的新约束**：PR-1 design 文档 B.3 行 84 把 lease 描述为 `WORKER_LEASE_SECONDS=600`，与代码不符。实测 lease=**180s**。该认知偏差对 PR-2 影响重大，必须更正。

### I.2 chunk 27 最坏情况估算

| 阶段 | 时长 |
|---|---|
| L1 第 1 次 timeout | 120s |
| 退避 sleep | 2s |
| L1 重试 timeout | 120s |
| L2 24 题 × 60s（全部 timeout 极端情况）| 1,440s |
| **合计最坏** | **1,682s ≈ 28 分钟** |

* 单 lease 180s 完全不够；即便扩到 600s 也只够 10 分钟；
* 当前 `run_smart_import` 的 heartbeat 仅在 chunk 间隙调用，chunk 内部超过 180s 即 lease 到期，`recover_stale_jobs`（job_service.py:222）会把 job 状态置回 `queued`、被另一个 worker 抢走 → **同 chunk 被重复处理 / 重复入题** 风险。

### I.3 PR-2 必须做的对策

#### I.3-a 单题降级循环内插入 heartbeat

```python
# 伪代码 — L2 循环
for idx, segment in enumerate(single_q_segments, start=1):
    try:
        single_response = call_ai_api(_build_llm_prompt(segment["text"], answer_key_text),
                                      db, scene="smart_import", timeout=60.0)
        ...
    except RETRYABLE_EXC:
        per_question_failures.append({...})
    finally:
        # 每 N 题或每 X 秒续约一次 lease
        if idx % 3 == 0 or _elapsed_since_last_heartbeat() > 90:
            heartbeat_job(db, bg_job, success_increment=0,
                          status_message=f"Chunk {chunk.chunk_no} L2 fallback {idx}/{N}")
```

> 注意：现有 `_process_chunk` 签名**没有** `bg_job` 参数。PR-2 必须给 `_process_chunk` 加 `bg_job: BackgroundJob | None = None` 参数（仅用作 heartbeat 续约，None 时跳过续约 → 兼容 reparse 路径）。`run_smart_import` 行 324 调用时多传一个 `bg_job=bg_job`；`run_reparse` 行 744 也补上 `bg_job=db.get(BackgroundJob, background_job.id)`（BackgroundJob 是 reparse 的承载者）。

#### I.3-b chunk 总耗时上限（kill switch）

PRD 没有显式要求该 cap，但生产可靠性需要：

```python
CHUNK_TOTAL_BUDGET_SECONDS = 480.0   # 8 分钟，留 2 分钟给 chunk 间收尾
chunk_started_at = time.monotonic()

# 在 L2 循环里每题前判断
if time.monotonic() - chunk_started_at > CHUNK_TOTAL_BUDGET_SECONDS:
    # 把剩余题号全部记入 per_question_failures，跳出 L2
    for remaining_seg in single_q_segments[idx:]:
        per_question_failures.append({
            "source_question_no": _extract_qno_from_segment(remaining_seg["text"]),
            "stage": "L2_fallback_budget_exceeded",
            "error": "chunk total budget 480s exceeded",
        })
    break
```

> **回填 PRD**：建议加一条 Requirements："`_process_chunk` 单 chunk 总耗时（L1 + L2 累计）上限 480s（= 8 分钟）；超时把剩余单题写入 per_question_failures 后立即返回，由 PR-4 reconciliation 决策是否标记 review_required。"

#### I.3-c CHUNK_TOTAL_BUDGET 与 lease 的关系

| 情形 | lease（180s 续约）| budget（480s 强制截断）|
|---|---|---|
| L1 + L2 在 480s 内完成 | heartbeat 至少 3 次（每 90s 一次）| 不触发 |
| L1 + L2 超 480s | heartbeat 续约工作正常 | 截断 |

→ heartbeat 频率 ≥ 每 90s 一次即安全；budget 是上限保护。

---

## J. 推荐落地方案 + 关键代码骨架

### J.1 改动文件清单

| 文件 | 变更 | 估算行数 |
|---|---|---|
| `backend/app/services/smart_import_service.py` | `_process_chunk` 重写为支持 L1+L2 + 新增私有函数 `_split_by_single_question` + `_call_llm_with_retry` 帮助函数 | +120 / -30 |
| `backend/tests/test_smart_import_process_chunk_retry.py` | 新文件，TC-1 ~ TC-12 | +250 |

> **不改**：`call_ai_api`（PR-1 已完成）、`_build_llm_prompt`、`_save_parsed_question`、`run_smart_import`（仅 1 行加 `bg_job` 透传，详见 I.3-a）。

### J.2 关键代码骨架（伪代码）

```python
# ─── 新增常量 ───────────────────────────
L1_RETRY_BACKOFF_SECONDS = 2.0
L1_MAX_RETRIES = 1                   # 共 2 次调用（α 方案）
L2_PER_QUESTION_TIMEOUT = 60.0
CHUNK_TOTAL_BUDGET_SECONDS = 480.0
HEARTBEAT_EVERY_N_SEGMENTS = 3

RETRYABLE_HTTP_EXC = (httpx.TimeoutException, httpx.HTTPError)


def _is_retryable_value_error(exc: ValueError) -> bool:
    return "AI API 错误 (5" in str(exc)


def _split_by_single_question(text: str) -> list[dict]:
    """与 _split_by_question_markers 类似但**不合并**短片段，每段恰含 1 道题。
    返回 [{"text": ..., "source_question_no": "222"}]
    """
    best_pattern, best_count = None, 0
    for pattern in QUESTION_SPLIT_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) > best_count:
            best_count, best_pattern = len(matches), pattern
    if best_count == 0 or not best_pattern:
        return []
    matches = list(best_pattern.finditer(text))
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg_text = text[start:end].strip()
        if seg_text:
            qno_match = re.search(r"#?(\d+)", m.group(0))
            out.append({
                "text": seg_text,
                "source_question_no": qno_match.group(1) if qno_match else None,
            })
    return out


def _call_llm_with_l1_retry(messages, db, *, max_retries: int, backoff: float, timeout: float):
    """整 chunk 调用 + L1 重试。成功返回 response_text；耗尽抛最后一次异常。"""
    last_exc = None
    for attempt in range(max_retries + 1):  # 最初 1 次 + max_retries 次重试
        try:
            return call_ai_api(messages, db, scene="smart_import", timeout=timeout)
        except ValueError as exc:
            if not _is_retryable_value_error(exc):
                raise   # 不重试
            last_exc = exc
        except RETRYABLE_HTTP_EXC as exc:
            last_exc = exc
        if attempt < max_retries:
            time.sleep(backoff)
    raise last_exc   # 用尽


def _process_chunk(db, chunk, import_job, auto_import, use_llm_cache,
                   seen_signatures=None, bg_job: BackgroundJob | None = None):
    """处理单个 chunk：cache → L1 → L1 重试 → L2 单题降级 → 入库。"""

    chunk.status = "parsing"
    db.commit()

    chunk_text = chunk.chunk_text
    config = import_job.config_json or {}
    answer_key_text = config.get("answer_key_text", "")
    cache_key = _build_cache_key(chunk.chunk_hash)
    chunk_started_at = time.monotonic()

    # 1) 缓存命中
    cached = _lookup_llm_cache(db, cache_key) if use_llm_cache else None
    if cached:
        response_text = cached.get("response_text", "")
        chunk.llm_request_json = cached.get("request_json")
        chunk.llm_response_json = json.loads(response_text) if response_text else None
        chunk.status = "parsed_cached"
        llm_result = _parse_llm_response(response_text)   # raise → 外层 except 兜底
        _commit_chunk_and_save(db, chunk, llm_result, import_job, chunk_text,
                               auto_import, seen_signatures)
        return

    # 2) L1（含 1 次重试）
    messages = _build_llm_prompt(chunk_text, answer_key_text)
    chunk.llm_request_json = {"messages": messages}
    db.commit()

    retry_count = 0
    fallback_used = False
    per_question_failures: list[dict] = []

    try:
        response_text = _call_llm_with_l1_retry(
            messages, db,
            max_retries=L1_MAX_RETRIES,
            backoff=L1_RETRY_BACKOFF_SECONDS,
            timeout=120.0,
        )
        # L1 成功（可能是首次或重试后）
        # —— 如何区分？_call_llm_with_l1_retry 可改为返回 (response_text, attempts_used)
        ...
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        # 不可重试错误（4xx / API key / parse） → 跳过 L2，直接失败
        chunk.status = "llm_failed"
        chunk.issues_json = {"error": str(exc), "retry_count": retry_count}
        db.commit()
        raise
    except RETRYABLE_HTTP_EXC:
        # L1 用尽 → 进 L2
        fallback_used = True
        retry_count = L1_MAX_RETRIES
        merged_questions, per_question_failures = _run_per_question_fallback(
            chunk_text, answer_key_text, db, bg_job, chunk, chunk_started_at,
        )
        # 拼装 chunk.llm_response_json
        response_text = json.dumps({
            "questions": merged_questions,
            "chunk_issues": [],
            "_fallback_meta": {
                "total_segments": len(merged_questions) + len(per_question_failures),
                "succeeded": len(merged_questions),
                "failed": len(per_question_failures),
            },
        }, ensure_ascii=False)

    # 3) Parse + status 终态
    if fallback_used and not merged_questions:
        chunk.status = "failed"
    elif fallback_used and per_question_failures:
        chunk.status = "parsed_partial"
        import_job.failed_chunks = (import_job.failed_chunks or 0) + 1
    elif fallback_used:
        chunk.status = "parsed_fallback"
    elif retry_count > 0:
        chunk.status = "parsed_retry"
    else:
        chunk.status = "parsed"

    chunk.llm_response_json = json.loads(response_text)
    chunk.issues_json = (chunk.issues_json or {}) | {
        "retry_count": retry_count,
        "fallback_used": fallback_used,
        "per_question_failures": per_question_failures,
    }

    # 4) 缓存（仅非 fallback 路径）
    if use_llm_cache and not fallback_used:
        _store_llm_cache(db, cache_key, chunk.chunk_hash,
                         request_json=chunk.llm_request_json,
                         response_text=response_text)

    db.commit()

    # 5) 入库
    llm_result = _parse_llm_response(response_text)
    for parsed_q in llm_result.questions:
        _save_parsed_question(db=db, parsed_q=parsed_q, import_job=import_job,
                              chunk=chunk, chunk_text=chunk_text,
                              auto_import=auto_import, seen_signatures=seen_signatures)


def _run_per_question_fallback(chunk_text, answer_key_text, db, bg_job, chunk, started_at):
    segments = _split_by_single_question(chunk_text)
    merged: list[dict] = []
    failures: list[dict] = []

    if not segments:
        # 没法切 → 整 chunk 失败
        return merged, [{
            "source_question_no": None,
            "stage": "L2_fallback_skipped",
            "error": "no_question_markers",
        }]

    for idx, seg in enumerate(segments, start=1):
        # budget kill switch
        if time.monotonic() - started_at > CHUNK_TOTAL_BUDGET_SECONDS:
            for rem in segments[idx - 1:]:
                failures.append({
                    "source_question_no": rem.get("source_question_no"),
                    "stage": "L2_fallback_budget_exceeded",
                    "error": "chunk total budget 480s exceeded",
                })
            break

        msgs = _build_llm_prompt(seg["text"], answer_key_text)
        try:
            txt = call_ai_api(msgs, db, scene="smart_import",
                              timeout=L2_PER_QUESTION_TIMEOUT)
            parsed = _parse_llm_response(txt)
            for q in parsed.questions:
                merged.append(q.model_dump())
        except (ValueError, RETRYABLE_HTTP_EXC, ValidationError, json.JSONDecodeError) as exc:
            failures.append({
                "source_question_no": seg.get("source_question_no"),
                "stage": "L2_fallback",
                "error": f"{type(exc).__name__}: {exc}",
            })

        # heartbeat 续约
        if bg_job and (idx % HEARTBEAT_EVERY_N_SEGMENTS == 0):
            heartbeat_job(db, bg_job, success_increment=0,
                          status_message=f"Chunk {chunk.chunk_no} L2 {idx}/{len(segments)}")

    return merged, failures
```

> ⚠️ 上面 `_call_llm_with_l1_retry` 需要返回 attempts_used 才能让 `_process_chunk` 区分"首次成功"/"重试后成功"。简化版：

```python
def _call_llm_with_l1_retry(...) -> tuple[str, int]:
    """返回 (response_text, attempts_after_first)；attempts_after_first=0 表示首次成功"""
```

### J.3 端到端验证清单

* [ ] `python -m py_compile backend/app/services/smart_import_service.py`
* [ ] `cd backend && python -m pytest tests/test_smart_import_process_chunk_retry.py -v`（TC-1 ~ TC-12 全绿）
* [ ] `cd backend && python -m pytest tests/test_ai_service_call_api_timeout.py -v`（PR-1 不回归）
* [ ] `cd backend && python -m pytest tests/ -v`（既有测试不回归；项目当前状态：PR-0 已清空 Flask 测试，PR-1 加了 4 个）
* [ ] 手工跑 `_split_by_single_question(chunk_27_chunk_text)` 断言返回 24 段、每段 source_question_no ∈ {222..245}（可在 PR-2 自测时通过 ad-hoc 脚本 `research/scripts/verify_split.py` 验证）

---

## K. 不做事项 / 留作后续 PR

| 项 | 原因 / 留给哪个 PR |
|---|---|
| Reconciliation 报告写入 `ImportJob.config_json["reconciliation"]` | **PR-4** 的核心职责；PR-2 只输出原料（`per_question_failures`）|
| `run_reparse` 加 `imported_qnos` 去重 | **PR-3** L6 的核心职责 |
| 把单题失败的题号写为 `ImportParsedQuestion` 占位行 | 拒绝（D.2 已论证）|
| 引入二次 prompt 让 LLM 修正 JSON 格式 | 超出 MVP（PRD Out of Scope）|
| 改 `PROMPT_VERSION` | 拒绝（PRD 锁 v1）|
| 引入 `LlmTimeoutError` / `LlmCallError` 自定义异常 | 直接 `except httpx.TimeoutException` / `except ValueError`(过滤 5xx) 已够；PR-2 不预先创建 API 表面 |
| 改 `WORKER_LEASE_SECONDS=600` 让它真正生效 | 与 PR-2 主线无关（lease 实际仍是 180s，靠 heartbeat 续约即可）；如未来想统一可单独 PR-X 把 `claim_next_job` 默认值绑到 settings |
| 引入异步 `httpx.AsyncClient` 并发跑单题 L2 | 性能优化，不改正确性，超出 MVP |
| 给 `chunk.status` 加 enum / Check 约束 | 当前 `String(32)` 自由值已够；新增 enum 需 Alembic，违反 PRD AC6 |

---

## 给主代理的总结（< 250 字）

1. **L1 重试次数推荐 1 次**（α 方案）：最初 1 次调用 + 最多 1 次重试 = 共 2 次；重试前 sleep 2s 固定值；指数 backoff 参数（base=2/cap=10）保留为常量但本 PR 不消费——**回填 PRD**：建议 PRD 把 "L1 重试 1 次 + 指数退避 base=2s/cap=10s" 改为 "L1 最多 1 次重试，固定 2s 退避，base/cap 留作未来扩展"。
2. **L2 单题失败不写 ImportParsedQuestion 占位行**：仅在 `chunk.issues_json["per_question_failures"]` 记题号；理由是占位行需构造无意义 content/options，污染前端复核列表 + 搅乱 PR-4 reconciliation 算账。
3. **`chunk.issues_json` 最终 schema**：`{retry_count: int, fallback_used: bool, per_question_failures: [{source_question_no, stage, error}], fallback_meta: {...}}`；新增 chunk.status 取值 `parsed_retry` / `parsed_fallback` / `parsed_partial`（`String(32)` 无 enum，零迁移代价）。
4. **必须有 heartbeat + 总耗时上限**：实测 lease=180s 而非 PR-1 文档说的 600s；L2 循环每 3 段调一次 `heartbeat_job` 续约；新增常量 `CHUNK_TOTAL_BUDGET_SECONDS=480`，超时把剩余单题标 `L2_fallback_budget_exceeded` 后立即返回。`_process_chunk` 签名加 `bg_job: BackgroundJob | None = None` 参数（reparse 路径也要透传）。
5. **回填 PRD 的新约束**（共 4 条）：(a) L1 退避语义见上；(b) 单 chunk 总耗时上限 480s；(c) 新增 chunk.status 三态；(d) PR-1 文档关于 lease=600s 的描述需更正为 180s（heartbeat 续约模型）。
