# smart-import 准确率优化（CIPT 283 PDF）

## Goal

把 `backend/app/services/smart_import_service.py` 的 PDF 题库识别准确率从当前的 ~95.4%（CIPT 283 题 PDF 实测 270/283）提升到 **≥98%（≥277/283）**，并使该提升在其他规整 PDF 题库（IAPP / ExamTopics 同类格式）上稳健可复现。

## What I already know（已实证 / 含 Step 0 诊断结果）

完整诊断报告：[`research/diagnosis-step0.md`](research/diagnosis-step0.md)。摘要如下：

* **PDF 文件**：`reference/CIPT 283题.pdf`，178 页，pdfplumber 抽取后总字符 332,573（清洗后），单页 min/max/avg = 15/3,951/1,868。
* **题号 100% 命中**：`Question\s+#(\d+)\s+Topic\s+\d+` 在抽取文本里命中 **283 次**。
* **当前实际链路**：FastAPI `banks.py:226` → `create_smart_import_job()` → `smart_import_service` 走 LLM 解析。Flask 旧版 `_parse_exam_dump` 仅 `build_bank_word_frequencies` 被复用。
* **既有 ImportJob (`id=7`) 数据**（来自 PostgreSQL `quiz` DB）：
    * `total_chunks=31, parsed_questions=275, imported_questions=274, failed_chunks=1`
    * **真实唯一题号入库 = 259**（`imported_questions` 含 15 行 reparse 重复入库的"虚胖"，命中题号 174–180、182–188、265、266）。
    * 真实缺口 = `283 - 259 = 24`，全部为题号 **222–245**。
    * 这 24 道题号正好等于 `chunk_no=27` 全集，该 chunk `status='failed', issues_json.error='timed out'`，`len(chunk_text)=11,848`。
* **静态层失血点全部为 0**（候选 ①③④⑥⑦⑧）：chunking 切分无 crossover、无超长；`_extract_answer_key` 未触发；`\x00` 残留 0、Unicode ligature 残留 0；`review_status='duplicate'` 行 = 0；30 个成功 chunk 的 LLM 输入/输出题号集严格相等。
* **关键约束**：`_build_cache_key = sha256(PROMPT_VERSION + chunk_hash)`（`smart_import_service.py:1245-1248`），仅缓存成功响应；timeout 失败不入缓存，故重跑 chunk 27 不会被旧失败结果污染。

## Assumptions（已验证 / 已收敛）

* ✅ "270 道"是用户对 `imported=274` 的口头近似；准确丢失数为 24 而非 13。
* ✅ 失血主因是 LLM **单点 timeout**，不是抽取/chunking/dedup/prompt 任何一项。
* ✅ pdfplumber 抽取完整，本任务**不需要 OCR**。

## Open Questions

✅ 全部已收敛（参见 Decision 1/2）：
1. ~~是否先做诊断 dump？~~ ✅ 是 → 已完成。
2. ~~改造的优先级？~~ ✅ MVP 限定到 CIPT 这份 PDF 的真因（chunk 失败重试 + reparse 卫生），其他题库另立任务。
3. ~~预算约束？~~ ✅ 不引入 chunk 1-题-1-call 的全量改造；仅在 chunk 失败时降级单题，正常路径成本不变。
4. ~~OCR 依赖？~~ ✅ 不引入。

## Decision (ADR-lite)

### 决策 1：诊断优先（已完成）

**Context**：283 道丢 13 道的根因分布（自动入库 / 复核队列 / DUPLICATE 误杀 / LLM 真正漏题）尚未量化。

**Decision**：选方案 A——先做诊断 dump，再据此决定改造范围。

**Outcome**：诊断已完成（`research/diagnosis-step0.md`）。结论刷新了认知——真实缺口 24 题（不是 13），单一根因 chunk 27 LLM timeout，静态层全部健康。

### 决策 2：MVP 收敛到"重试 + reparse 卫生"（待用户确认）

**Context**：诊断证明 8 个候选失血点中 6 个在本 PDF 上 0 失血，仅 chunk timeout 与 reparse 虚胖两个真实问题。

**Decision（提议）**：
* MVP 仅做 **L4（chunk 失败重试 + 单题降级 + reconciliation）** 与 **L6（_question_signature 加 source_question_no 维度）** 两件事；
* 兼做工程加固：`call_ai_api` 显式 timeout/重试参数化、`PROMPT_VERSION` 提升机制说明文档化。
* OCR / Deterministic-First / Prompt 修订 / answer-key 加固 / 双阈值 auto-accept 全部移到 Out of Scope（候诊断对其他题库再启动新任务）。

**Consequences**：
* `+` 工作量从 ~3-5 天压到 1-1.5 天；
* `+` 改动收敛到 1 个文件 + 1 个 schema 字段（如需），回归风险低；
* `+` 直接命中数据驱动出来的真因，准确率可冲到 ≥98%（实跑测算 277/283）；
* `−` 不解决其他 PDF 题库可能存在的不同失血点——但属于不同任务的范围。

### 决策 3：移除 Flask 测试用例（用户口头决议）

**Context**：`pytest backend/tests/` 当前 12 个测试 collection error，根因是 commit `08bd8a7` 引入 FastAPI 包 `backend/app/` 屏蔽了 Flask `backend/app.py`。所有 12 个测试都是 Flask import（`from app import create_app` + `from flask_jwt_extended` + `from routes.*` + `from services.*` 等），全部为 Flask 旧版测试。

**Decision**：用户决议"Flask 后续不维护，移除相关用例"。新增 PR-0 删除 12 个测试文件，让基线归零。

**Consequences**：
* `+` 测试基线从"12 collection error"变成"0 collected"，PR-1 起的新 FastAPI 测试可以从干净环境出发；
* `+` 删除而非保留 = 明确传达 Flask 端进入"维持但不增量"模式；
* `−` 失去 Flask 端的回归保护——但用户已确认 Flask 后续不维护，可接受；
* `−` 与本任务"smart_import 准确率"主题略偏移——但属同一次操作的最小成本捎带，不另起任务。

### 决策 4：PR-2 重试 / 降级 / 时间预算（来自 `research/pr2-design-process-chunk-retry.md`）

**Context**：PR-2 细化设计揭示了 4 个原 PRD 未涵盖的新约束。

**Decision**：

1. **L1 重试策略简化**：原 PRD"1 次重试 + 指数退避 base=2s/cap=10s"内在矛盾（只重 1 次时 backoff 永不进位）。改为 **"最多 1 次重试，固定 2s sleep"**；指数退避常量 `RETRY_BASE_SECONDS=2 / RETRY_CAP_SECONDS=10` 仍以模块常量保留，PR-2 暂不消费，留作未来"多次重试"扩展。
2. **chunk 总耗时上限**：实测 `DEFAULT_JOB_LEASE_SECONDS=180s`（生效，定义于 `job_service.py:27`）；`settings.WORKER_LEASE_SECONDS=600` 是**未被引用的 dead config**。最坏路径 L1 (120+2+120=242s) + L2 (24×60=1440s) 共 ~28 分钟，远超 lease。引入 **`CHUNK_TOTAL_BUDGET_SECONDS=480`** 上限（约 2.7 个 lease 周期），超时把剩余单题写入 `per_question_failures.stage="L2_fallback_budget_exceeded"` 并跳出循环。
3. **必须加 heartbeat**：`_process_chunk` 签名加 `bg_job: BackgroundJob | None = None` 参数；L2 单题循环每 3 段调一次 `heartbeat_job(db, bg_job)` 续约（heartbeat 把 lease 续到 now + 180s）。`run_smart_import` 与 `run_reparse` 调用 `_process_chunk` 时必须传 `bg_job=background_job`（reparse 路径在 PR-3 一并改）。
4. **`chunk.status` 新增三态（无迁移）**：`String(32)` 字段无 enum 约束。
   - `parsed_retry`：L1 重试成功
   - `parsed_fallback`：L2 单题降级**全部成功**
   - `parsed_partial`：L2 单题降级**部分失败**（含 `per_question_failures`）
   `failed`（含未触发 fallback 的不可重试错误、L2 全部失败）含义不变。
5. **L2 单题失败不写 ImportParsedQuestion 占位行**：仅在 `chunk.issues_json["per_question_failures"]: [{source_question_no, stage, error}]` 记题号；占位行会污染前端复核列表与 PR-4 reconciliation。
6. **`chunk.issues_json` 最终 schema**（与 PR-4 reconciliation 兼容）：
   ```jsonc
   {
     "chunk_issues": [...],          // 原有，LLM 返回的 issues
     "retry_count": 0,               // L1 实际重试次数 (0 或 1)
     "fallback_used": false,         // L2 是否触发
     "per_question_failures": [
       {"source_question_no": "222", "stage": "L2_fallback",
        "error": "TimeoutException after 60.0s"}
     ],
     "fallback_meta": {"total_segments": 24, "succeeded": 22, "failed": 2,
                       "elapsed_seconds": 1320.5}
   }
   ```
7. **不写 LlmParseCache 的两个分支**：(a) timeout / 失败一律不写（PR-1 已确认）；(b) **L2 单题降级即使全部成功也不写**——因为缓存键按整 chunk hash，写单题响应会破坏 chunk 级一致性，将来 reparse 同一 chunk 命中缓存会拿到不完整的 chunk_text 解析。
8. **异常分类与重试**：`httpx.TimeoutException` / 5xx / `httpx.HTTPError` → 重试候选；`ValueError(API Key 未配置)` / 4xx ValueError / Pydantic ValidationError → **不重试**直接失败。

**Consequences**：

* `+` 时间预算明确，避免单 chunk 卡死整个 worker；
* `+` chunk.status 取值扩展无 schema 迁移成本；
* `+` per_question_failures schema 已预先与 PR-4 reconciliation 对齐；
* `−` `_process_chunk` 签名加 `bg_job` 参数会传染到 reparse 路径——PR-3 也得同步改；
* `−` `WORKER_LEASE_SECONDS=600` dead config 不在本任务范围（候后续单独 PR 清理或对齐到 180）。

### 决策 5：PR-3 reparse 卫生具体方案（来自 `research/pr3-design-reparse-hygiene.md`）

**Context**：PR-3 细化设计在 PRD L6-a/b/c 三条骨架基础上，给出具体函数签名、归一化规则、DUPLICATE 区分接口与 helper 抽取。

**Decision**：

1. **最终签名**：
   * `_save_parsed_question(..., seen_signatures=None, imported_qnos: set[str] | None = None)` —— 新增第 8 个参数。
   * `_process_chunk(..., seen_signatures=None, bg_job=None, imported_qnos: set[str] | None = None)` —— PR-2 已加 `bg_job`，PR-3 再加 `imported_qnos`。`_process_chunk_cached` 同步加。
2. **`imported_qnos` 来源**：直接查 `ImportParsedQuestion` 按 `import_job_id == this_job AND import_status == 'imported'` 的 `source_question_no` 集合；**不**反查 Question 表（避免无谓的 join 与跨表语义混乱）。
3. **题号归一化**：新增私有 helper `_normalize_qno(qno) = (qno or "").strip().lstrip("#").strip() or None`；构建 `imported_qnos` 与查询 `parsed_q.source_question_no` 时双方都过同一函数。处理 `" #222 "` / `"#222"` / `"222"` 等历史/未来 LLM 输出格式漂移。
4. **DUPLICATE 区分接口（PR-3 → PR-4 稳定契约）**：主 `code` 保持 `"DUPLICATE"`（前端 / `serialize_parsed_question` 零兼容代价），在 `details[0]` 增加 `reason: "qno" | "content"` 子字段。PR-3 同步给现有内容签名 DUPLICATE 路径补上 `reason: "content"`，一次对齐 PR-4 reconciliation 接口。
5. **抽 `_persist_duplicate_parsed_question` helper**：两条 DUPLICATE 路径（题号去重 + 内容签名）80%+ 字段相同（content/options_json/correct_answer/llm_confidence/review_status/import_status 全同），抽出 helper 杜绝双写漂移、单测点收敛。
6. **`run_reparse` 增量改动**：行 737-742 现有 `seen_signatures` 重建逻辑保留（向后兼容），增加 `imported_qnos = {_normalize_qno(pq.source_question_no) for pq in db.query(ImportParsedQuestion).filter_by(import_job_id=import_job_id, import_status="imported").all()}` 一段；同时把 `bg_job=background_job`（PR-2 留的尾巴）与 `imported_qnos=imported_qnos` 传给 `_process_chunk`。
7. **初次导入路径不动**：`run_smart_import` 入口的 `imported_qnos` 永远为 None（默认值）或空集——所有题号都是首次见，去重逻辑等价于 noop，不影响现有 happy path。

**Consequences**：

* `+` 直接按题号拒绝重复入库，根除 reparse 虚胖（诊断证据：题号 174-180、182-188、265、266 共 16 处历史虚胖）；
* `+` 不改 schema、不改 prompt、不改 Question 表语义；
* `+` `details[0].reason` 字段为 PR-4 reconciliation 提供稳定 lookup key；
* `+` `_persist_duplicate_parsed_question` helper 让 PR-4 / 未来如需第三种 DUPLICATE（如向量相似度去重）时只动 helper；
* `−` `_save_parsed_question` 签名又长一格（已有 9 个参数），可读性轻微下降——可接受。

### 决策 6：PR-4 reconciliation 报告 / logger 补齐 / 集成测试（来自 `research/pr4-design-reconciliation.md`）

**Context**：PR-4 是收尾 PR，需要把 PR-2/PR-3 留下的可观测性、对账数据、E2E 验证一起补齐。

**Decision**：

1. **expected 题号集存储位置**：在 `run_smart_import` 切完 chunk 后，用 `_split_by_single_question(chunk_data["chunk_text"])` 遍历每个 chunk 取题号，归一化后排序写入 `import_job.config_json["expected_qnos"]`。单点单源、与 `answer_key_text` 同语义层；reparse 不污染该字段。
2. **reconciliation schema**（`import_job.config_json["reconciliation"]`）：
   ```jsonc
   {
     "expected": ["1", "2", ..., "283"],           // 字符串数组（已归一化）
     "imported_unique": ["1", ..., "283"],
     "missing_qnos": [],
     "duplicates_in_db": [],                       // PR-3 details[0].reason=="qno" 过滤
     "per_question_failures_count": 0,
     "computed_at": "2026-05-04T12:34:56Z"
   }
   ```
   AC2 字段从整数改为题号字符串数组（便于诊断）。
3. **JSONB 字段 dirty 检测**：用 `import_job.config_json = {**(import_job.config_json or {}), "reconciliation": recon}` 触发 setter；不依赖 `flag_modified`。
4. **logger 补齐 5 处**（PR-2/PR-3 留的建议项）：
   - L1 重试（`_call_llm_with_l1_retry` sleep 前）`logger.warning`
   - L2 启动（`_run_per_question_fallback` 入口）`logger.warning`
   - L2 budget 超时（kill switch break 前）`logger.warning`
   - heartbeat 失败（try/except 内）`logger.warning`
   - DUPLICATE 命中（`_persist_duplicate_parsed_question` add 前）`logger.info`
5. **集成测试技术选型**：方案 c（纯 chunk fixture + MagicMock + monkeypatch）。**不依赖 pdfplumber**，按诊断报告 B.2 表的题号分布构造 31 个 chunk fixture；用 caplog 捎带验证 logger。AC1 从"全 PDF E2E"放宽为"基于诊断题号分布的 fixture E2E"。
6. **`serialize_import_job` 暴露 reconciliation**：作为可选顶层字段（不影响前端不依赖此字段时的行为）。便于运维直查浏览器开发者工具。前端 UI 仍不动（PRD Out of Scope）。
7. **集成测试 7 个 TC**：
   - TC-1 `test_smart_import_e2e_full_success`（全成功 → missing=[]）
   - TC-2 `test_smart_import_e2e_chunk_27_recovers_via_l1_retry`
   - TC-3 `test_smart_import_e2e_chunk_27_recovers_via_l2_fallback`
   - TC-4 `test_smart_import_e2e_chunk_27_l2_partial_failure`（部分失败 → missing=部分题号）
   - TC-5 `test_run_reparse_recovers_partial_chunk`（reparse 后 missing=[]）
   - TC-6 `test_finalize_import_does_not_clobber_existing_config_json`（验证 dict spread 不破坏其他键）
   - TC-7 `test_serialize_import_job_exposes_reconciliation_field`（serialize 暴露字段）

**Consequences**：

* `+` AC1/AC2 双双闭环；
* `+` 5 处关键节点可观测；
* `+` reconciliation 字段对线上诊断价值高；
* `+` `expected_qnos` 一次写入、永久不变（reparse 不污染），保证 reconciliation 可重复计算；
* `−` `serialize_import_job` 输出多一个字段，前端虽不依赖但需要确认无 schema 校验（手工核查 OK）；
* `−` 集成测试 fixture 复杂度比 PR-2/PR-3 单测略高（要构造 31 chunk + 真 ORM）。

## Requirements（最终）

## Requirements（最终）

详见下方 "Requirements（最终）" 段（位于 Technical Approach 之后），此处保留位锚以维持 PRD 大纲层级。

## Out of Scope（最终）

承接上文 Technical Approach 的 Out of Scope 段；本次任务**仅做 L4 + L6 + L9**，其余候选改造移到未来工作（视其他 PDF 题库的实测失血点而定）。同时排除：

* 重写题库前端 UI / 复核界面交互。
* 把 deterministic parser 也搬去支持 XLSX/DOCX（仅 PDF 双轨即可）。
* 引入向量检索做内容近似去重（已有 `vector_index` 模型，但本任务不动）。
* 把 LLM 调用切到不同 provider（沿用现有 `call_ai_api`）。
* OCR 引入：本 PDF 0 失血。
* deterministic parser 适配新格式（ExamTopics v2 等）：本任务仅兼容 CIPT 的 `Question #N Topic N` 格式。

## Technical Approach（已锁定 = 方案 X）

### L4 — Chunk 失败重试 + 单题降级 + Reconciliation 报告

**位置**：`backend/app/services/smart_import_service.py::_process_chunk`、`run_smart_import` 的 finalize 段、`backend/app/services/ai_service.py::call_ai_api`。

* **L4-a 显式 timeout 参数化**：
    * `call_ai_api(messages, db, scene, timeout=60.0)` 增加 `timeout` 参数；smart_import 场景下用更宽松的 timeout（建议 120s）；不改默认值（保持其他场景兼容）。
    * httpx 调用改为 `httpx.post(..., timeout=timeout, ...)`。
* **L4-b chunk 失败时的两级重试策略**（只在 `_process_chunk` 内）：
    1. **L1 整 chunk 重试 1 次**：失败时间隔 2s 再调一次（指数退避 base=2s，cap=10s）。
    2. **L2 单题降级**：仍失败时，把 `chunk_text` 用 `_split_by_question_markers` 重新切成"每题一段"，每段单独发起 LLM 调用（timeout 60s/题）。
    3. 单题级失败的题号写入 `chunk.issues_json["per_question_failures"]: [222, 234, ...]`，**不算成功**，进入 reconciliation 缺口集。
* **L4-c Reconciliation 报告**：
    * 在 `run_smart_import` 的 finalize 段（`_finalize_import` 附近）：从 `_split_by_question_markers` 切分阶段保存的"输入题号集"，与 `ImportParsedQuestion.source_question_no` 实际入库集做 set diff。
    * 写到 `ImportJob.error_log`（如已存在字段）或 `ImportJob.config_json["reconciliation"] = {expected: 283, imported_unique: N, missing_qnos: [...], duplicates_in_db: [...]}` —— 优先复用现有字段。
    * 失败 chunk 的 `per_question_failures` 也合并进 `missing_qnos`。

### L6 — Reparse 卫生（不改 schema）

**位置**：`smart_import_service.py::run_reparse`（行 689–760）+ `_save_parsed_question`（行 445–556）。

* **L6-a 题号级去重集合**（与内容签名并行）：
    1. 在 `run_reparse` 行 737 之前/之后，新增构建 `imported_qnos = {pq.source_question_no for pq in ImportParsedQuestion if import_job_id == this_job and import_status == 'imported'}`。
    2. 把 `imported_qnos` 作为新参数传给 `_process_chunk` → `_save_parsed_question`。
    3. `_save_parsed_question` 入口判断：若 `parsed_q.source_question_no` 已在 `imported_qnos` 中，则将该 ImportParsedQuestion 写为 `review_status='duplicate', import_status='skipped'`（沿用现有 DUPLICATE 路径），**不再写 Question 表**。
* **L6-b 初次导入路径不改**：`run_smart_import` 入口的 `seen_signatures` 维持 `_question_signature` 内容签名行为（保留"内容相同但题号不同"题目的去重能力）。
* **L6-c 不引入 schema 变更**：`Question.source_question_no` 字段不加；保持当前数据模型；避免 Alembic 迁移连带成本。

### L9 — 工程加固（小工作量、随手做）

* `PROMPT_VERSION` 当前 = `"v1"`：本次不改 prompt，**保持 v1 不动**，避免缓存全失效；如未来改 prompt 须文档化"必须 bump 到 v2"流程。
* `LlmParseCache` 失败 chunk 不写缓存策略已是当前行为，仅在 docstring 内显式注明。
* 单元测试：覆盖 ① `_process_chunk` chunk timeout 后单题降级 ② `_save_parsed_question` 在 `imported_qnos` 命中时走 DUPLICATE 路径 ③ Reconciliation 在缺口为空 / 非空两种情形下的输出。
* 集成测试：mock `call_ai_api`（前 27 个 chunk 正常返回，第 27 个抛 httpx.TimeoutException，单题重试时返回正常）→ 断言入库唯一题号 = 283、reconciliation `missing_qnos=[]`。

### Out of Scope（明确划清）

* OCR / `pytesseract`：本 PDF 0 失血，移出。
* Deterministic-First（旧版正则与 LLM 双轨）：留作未来方案；MVP 不引入。
* Prompt 修订（规则 #11/#12）：本任务 30 个成功 chunk 输入/输出题号严格相等，证明 prompt 在本 PDF 上未漏题；不改。
* `_extract_answer_key` 末尾贪婪匹配修复：本 PDF 未触发，移出。
* `AUTO_ACCEPT_CONFIDENCE` 双阈值：当前 0.90 在本 PDF 上仅 1 条 STEM_TOO_SHORT skipped + 2 条 LOW_CONFIDENCE 已 accepted，无系统性误杀，不改。
* `_question_signature` 加 `source_question_no` 维度（schema 变更版）：被 L6-a 的"无 schema"方案取代。
* 前端复核页 UI：不改。
* **PR-1 不引入 `max_retries` 参数**：重试链路 100% 留在 PR-2 的 `_process_chunk` 两级策略；call_ai_api 维持单次调用语义。
* **PR-1 不新增 `LlmTimeoutError` / `LlmCallError` 自定义异常**：保留 `httpx.TimeoutException` 原生类型直接冒泡，PR-2 在 `_process_chunk` 内 `except httpx.TimeoutException` 精准 catch。
* **PR-1 不新增 `settings.AI_API_TIMEOUT_*` env 配置**：60s / 120s 用函数默认值 + 显式传值表达即可，避免双重事实源。
* **PR-1 不改 `backend/app/services/ai_service.py:190` `translate_term` 内的独立 httpx.post**：它是 db=None 兼容分支下的代码债务，与 `call_ai_api` 无 cross-call；后续单独 PR 清理。
* **不动 Flask 旧版 `backend/services/ai_service.py`**：仅改 FastAPI 一侧，PRD Goal 已声明。

## Requirements（最终）

* `[必须]` `call_ai_api` 增加 `timeout` 参数（默认 60s 保持向后兼容，smart_import 显式传 120s）。
* `[必须]` `_process_chunk` 在 LLM 调用失败（含 timeout）时执行：整 chunk 重试 1 次 → 单题降级 → 单题级失败题号写入 chunk 元数据。
* `[必须]` `_finalize_import` / `run_smart_import` 终结阶段写出 reconciliation 数据到 `ImportJob.config_json["reconciliation"]`，含 `expected / imported_unique / missing_qnos / duplicates_in_db` 字段。
* `[必须]` `run_reparse` 构建 `imported_qnos` 并贯穿到 `_save_parsed_question`；命中时按 DUPLICATE 路径处理。
* `[必须]` 不改 `Question` / `ImportJob` 等 ORM 模型，不引入 Alembic 迁移。
* `[必须]` 不改 `PROMPT_VERSION`（保持 `v1` 让现有缓存继续生效）。

## Acceptance Criteria（最终）

* [ ] **AC1**：用 `reference/CIPT 283题.pdf` 的 chunk 题号分布（31 chunk fixture，按诊断报告 B.2 表）走完整 smart_import（mock chunk 27 timeout 一次、第二次成功），自动入库唯一题号集 = `{1..283}`，`imported_questions ≥ 283`。
* [ ] **AC2**：`ImportJob.config_json["reconciliation"]` 含 `expected`/`imported_unique`/`missing_qnos`/`duplicates_in_db`/`per_question_failures_count`/`computed_at` 六字段；`expected` 为长度 283 的题号字符串数组；`missing_qnos == []`；`duplicates_in_db == []`。
* [ ] **AC3**：跑 `run_reparse` 对一个已成功入库的 chunk，重新运行后 `ImportParsedQuestion` 中**不出现新增已 imported 题号的重复行**（命中题号去重路径，状态 = `review_status='duplicate'`）。
* [ ] **AC4**：单元测试 + 集成测试新增覆盖率 ≥ 上面 3 条路径，CI 全绿。
* [ ] **AC5**：`backend/tests/` 目录下不再有 import 失败：`pytest backend/tests/` 输出 "0 collected, 0 errors"（PR-0 移除全部 Flask 测试）；PR-1 新增的 `test_ai_service_call_api_timeout.py` 4 个 case 全绿。后续 PR 按需追加 FastAPI 端测试。
* [ ] **AC6**：未引入 `pytesseract` / OCR / 新 ORM 字段；`PROMPT_VERSION` 维持 `v1`；未引入 `pytest-httpx` / `respx` 等新测试依赖。

## Implementation Plan（小 PR 拆分）

* **PR-0**（前置清理）：移除 12 个 Flask 旧版测试文件（`backend/tests/test_*.py` 全部为 Flask import）；让 `pytest backend/tests/` 从"12 collection error"变成"0 collected, 0 errors"，为 PR-1 起见的新 FastAPI 测试腾出干净基线。**Flask 后端后续不维护**（用户决议），测试用例失去维护对象一并删除。约 0.1 天。
* **PR-1**（铺路）：`call_ai_api` 加 `timeout` 参数 + smart_import 显式传 120s + 单元测试。约 0.3 天。
* **PR-2**（核心 L4）：`_process_chunk` 重试 + 单题降级 + 失败题号记录到 `chunk.issues_json` + 单元测试。约 0.5 天。
* **PR-3**（核心 L6）：`run_reparse` 加 `imported_qnos` + `_save_parsed_question` 题号去重路径 + 单元测试。约 0.3 天。
* **PR-4**（收尾 L9）：reconciliation 写入 `ImportJob.config_json` + 集成测试（mock LLM）+ 文档化 PROMPT_VERSION 升级流程。约 0.4 天。

## Definition of Done（最终）

* PR-1..PR-4 全部合并；
* 集成测试用 CIPT 283 PDF 跑通且断言唯一题号 = 283；
* `_process_chunk` 重试链路在测试中被显式 cover（不只是 happy path）；
* PRD 的 AC1–AC6 全部勾选；
* `.trellis/spec/backend/` 的相应文档（如 `quality-guidelines.md` 或新增 `import-pipeline.md`）记录"chunk 失败两级重试 + reconciliation 报告"约定；
* 没有新增 lint/类型/导入错误（项目暂无 lint 工具，至少 `python -m py_compile` 通过 + 手工 import 检查）；
* 回滚预案：所有改动用既有 `ImportJob.config_json` 字段承载新数据；如需回退仅 revert 4 个 PR，无数据库迁移连带影响。

## Step 0：诊断 / 验证计划（已完成）

诊断已执行完毕，结果见 [`research/diagnosis-step0.md`](research/diagnosis-step0.md)；锁定 chunk 27 LLM timeout 为唯一根因，reparse 路径同题号重复入库为次要副作用。

## Research References

* [`research/diagnosis-step0.md`](research/diagnosis-step0.md) — 静态 + DB 实测诊断报告；锁定 chunk 27 LLM timeout 为唯一根因。
* [`research/pr1-design-call-ai-api-timeout.md`](research/pr1-design-call-ai-api-timeout.md) — PR-1 实施前细化设计：最终签名、4 个调用方耐受度、2 文件 + 1 测试文件的最小变更面。
* [`research/pr2-design-process-chunk-retry.md`](research/pr2-design-process-chunk-retry.md) — PR-2 实施前细化设计：状态机、异常分类、L1/L2 流程、heartbeat、chunk 总耗时预算、12 个 TC、伪代码骨架。
* [`research/pr3-design-reparse-hygiene.md`](research/pr3-design-reparse-hygiene.md) — PR-3 实施前细化设计：imported_qnos 来源/归一化、签名扩展、DUPLICATE_QNO 区分接口、`_persist_duplicate_parsed_question` helper、8 个 TC、伪代码骨架。
* [`research/pr4-design-reconciliation.md`](research/pr4-design-reconciliation.md) — PR-4 实施前细化设计：expected_qnos 存储、reconciliation schema、5 处 logger 插入点、集成测试方案 c、7 个 TC、伪代码骨架。
* `research/scripts/static_pdf.py` / `static_pdf.out.json` — pdfplumber 抽取 + chunking 静态分析数据。
* `research/scripts/db_diag.py` / `db_diag.out.json` — PG `import_jobs.id=7` 全量数据 dump。

> 本任务 MVP 收敛到 L4+L6 后已不再需要外网调研；如未来扩展到其他题库 PDF 出现新失血点，再单独派遣 `trellis-research` 子代理。

## Technical Notes

### 受影响文件
* `backend/app/services/smart_import_service.py`（主战场，1533 行）
* `backend/app/services/import_service.py`（deterministic parser 复用源）
* `backend/services/import_service.py`（Flask 旧版，参考逻辑）
* `backend/app/api/routes/banks.py:226`（入口）
* `backend/app/models/import_job.py` / `import_parsed_question.py` / `import_review_item.py`（数据模型，不期望改 schema）
* `backend/app/schemas/llm_parse.py`（LLM 输出 Pydantic，可能需加 `source_question_no` 强约束）

### 关键代码锚点
* `smart_import_service.py:47-49` 常量：`CHUNK_MAX_CHARS=12000` / `AUTO_ACCEPT_CONFIDENCE=0.90` / `PROMPT_VERSION="v1"`（改 prompt 时记得 bump 版本以失效缓存）
* `smart_import_service.py:87-109` `_question_signature`
* `smart_import_service.py:948-1017` `_split_into_chunks` / `_split_by_question_markers`
* `smart_import_service.py:1044-1103` `_build_llm_prompt`（System Prompt 12 条规则）
* `smart_import_service.py:1136-1223` `_quality_check`（6 因子打分公式）
* `smart_import_service.py:1226-1239` `_auto_accept_check`（0.90 阈值 + HIGH severity 拒绝清单）

### 约束
* 后端处于 Flask → FastAPI 迁移期，本任务**仅改 FastAPI 一侧**。
* `LlmParseCache` 表会缓存 `cache_key = sha256(PROMPT_VERSION + chunk_hash)`：改 prompt 必须升 `PROMPT_VERSION` 才能让缓存自然失效，否则要手动清表。
* 数据库已使用 PostgreSQL（迁移记录见近期 commit / Alembic），新增表/字段需走 Alembic 迁移并实跑 `upgrade head`（按用户记忆要求）。
* `pydantic-settings` 的 `env_file` 必须用绝对路径（用户记忆要求）。
