# Research: smart import scenario stems

- **Query**: 研究任务 `.trellis/tasks/05-12-fix-smart-import-incomplete-scenario-stems` 的实现上下文：smart import PDF 抽取、chunk 切分、LLM prompt、保存 `ImportParsedQuestion`、写入 `Question` 链路；reparse 和 review accept 是否复用 `_write_question_to_bank`；现有测试模式与 fixtures；历史回填脚本位置与 DB session 接入；风险点和建议测试。
- **Scope**: internal
- **Date**: 2026-05-12

## Findings

### Files Found

| File Path | Description |
|---|---|
| `backend/app/services/smart_import_service.py` | 智能导入核心服务：任务创建、文件抽取、chunk 切分、LLM prompt/解析、`ImportParsedQuestion` 保存、`Question` 写入、reparse、review accept/skip、序列化和 reconciliation。 |
| `backend/app/schemas/llm_parse.py` | LLM 解析结果 schema，`ParsedQuestion` 已包含 `scenario` 与 `content` 两个字段。 |
| `backend/app/models/import_parsed_question.py` | `ImportParsedQuestion` 模型，包含 `scenario_text`、`content`、`options_json`、`correct_answer`、`imported_question_id`。 |
| `backend/app/models/question.py` | 正式题目模型；没有 `scenario` 字段，正式展示题干只能落在 `Question.content`。 |
| `backend/app/models/import_chunk.py` | `ImportChunk` 模型，保存 `chunk_text`、`normalized_text`、LLM request/response、issues。 |
| `backend/app/models/import_job.py` | `ImportJob` 模型，保存导入状态、统计、`config_json`（answer key、expected qnos、reconciliation 等）。 |
| `backend/app/api/routes/banks.py` | 管理员上传题库入口，调用 `create_smart_import_job()` 创建异步导入任务。 |
| `backend/app/api/routes/import_review.py` | 复核 API；accept 调 `accept_review_item()`，reparse 调 `create_reparse_job()`。 |
| `backend/app/api/routes/import_jobs.py` | 导入任务、chunk、parsed question 查询 API。 |
| `backend/app/services/job_handlers.py` | 后台任务分派；智能导入与 reparse 分别调用 `run_smart_import()` / `run_reparse()`。 |
| `backend/app/workers/job_worker.py` | 后台 worker 通过 `SessionLocal()` 创建 DB session 并执行 `run_job()`。 |
| `backend/app/core/database.py` | `SessionLocal` 和 FastAPI `get_db()` 定义。 |
| `backend/scripts/import_iapp_glossary.py` | 现有一次性/管理脚本样例：在 `backend/scripts/` 下，`main()` 中导入 `SessionLocal()` 并 `finally db.close()`。 |
| `backend/tests/test_smart_import_process_chunk_retry.py` | `_process_chunk()` 单元测试模式：MagicMock DB、monkeypatch LLM/cache/save、构造 chunk text/response。 |
| `backend/tests/test_smart_import_reparse_hygiene.py` | reparse 卫生单元测试模式：轻量 `_FakeDB`/`_FakeQuery`，直接断言 `_save_parsed_question()` 和 `run_reparse()` 行为。 |
| `backend/tests/test_smart_import_e2e_reconciliation.py` | in-memory SQLite + 真 ORM 的智能导入 E2E 测试模式，包含 JSONB→JSON 编译钩子和 31 chunk fixture。 |
| `.trellis/spec/backend/import-pipeline.md` | 智能导入流水线规范，记录 `_process_chunk`、reparse、reconciliation 的现有契约。 |
| `.trellis/tasks/05-12-fix-smart-import-incomplete-scenario-stems/prd.md` | 当前任务 PRD，明确正式 `Question.content = scenario_text\n\ncontent`、不新增 `Question.scenario`、历史回填脚本 dry-run/apply。 |

### Code Patterns

#### 1) smart import 入口与 PDF 抽取链路

- 上传入口在 `backend/app/api/routes/banks.py:206-242`：`POST /api/banks/{bank_id}/import` 读取上传文件后调用 `create_smart_import_job()`。
- `create_smart_import_job()` 位于 `backend/app/services/smart_import_service.py:178-275`：
  - 按文件名后缀识别 `pdf` / `xlsx` / `docx`（`197-205`）。
  - `save_upload_file()` 保存文件并计算 `file_hash`（`208-209`）。
  - 创建 `ImportJob`，`config_json` 初始包含 `auto_import`、`use_llm_cache`（`227-240`）。
  - 创建 `BackgroundJob`，`job_type=JOB_TYPE_QUESTION_IMPORT_LLM`，payload 包含 `import_job_id`、`bank_id`、`file_path`、`file_type` 等（`244-264`）。
- 后台分派在 `backend/app/services/job_handlers.py:27-37` 和 `101-110`：智能导入 job 调 `run_smart_import(db, job)`，reparse job 调 `run_reparse(db, job)`。
- `run_smart_import()` 第一阶段位于 `backend/app/services/smart_import_service.py:281-310`：将状态置为 `extracting`，调用 `_extract_pages_from_file(file_path, file_type)`。
- 文件抽取函数位于 `backend/app/services/smart_import_service.py:1328-1389`：
  - `_extract_pages_from_file()` 按 `file_type` 分派到 PDF/XLSX/DOCX（`1328-1337`）。
  - `_extract_pdf_pages()` 使用 `pdfplumber.open(file_path)`，逐页 `page.extract_text()`，非空时保存 `{page_no, text: _clean_text(text)}`（`1340-1350`）。
  - `_clean_text()` 复用 `app.services.import_service._clean_text`（`1385-1389`）。

#### 2) 文本规范化、答案键、chunk 切分

- `run_smart_import()` 第二阶段位于 `backend/app/services/smart_import_service.py:312-366`：
  - `full_text = "\n".join(p["text"] for p in pages)`，再 `_normalize_text(full_text)`（`314-315`）。
  - `_extract_answer_key()` 在规范化全文中提取答案键；若找到，使用 `ANSWER_KEY_PATTERN.sub("", normalized_text)` 从正文移除，并将答案键格式化后放入 `answer_key_text`（`317-323`）。
  - `_split_into_chunks(pages, normalized_text, answer_key_text)` 生成 chunks（`325`）。
  - 每个 chunk 写入 `ImportChunk.chunk_text`、`normalized_text`、`chunk_hash`、`status="pending"`（`331-345`）。
  - 切完 chunk 后用 `_split_by_single_question(chunk_data["chunk_text"])` 计算 `expected_qnos` 并写入 `import_job.config_json`（`349-365`）。
- `_normalize_text()` 位于 `backend/app/services/smart_import_service.py:1395-1403`：去控制字符、合并连续空白行、合并行内连续空格。
- `_split_into_chunks()` 位于 `backend/app/services/smart_import_service.py:1430-1457`：
  - 先 `_split_by_question_markers(normalized_text)`，无题号模式时 `_split_by_char_count(normalized_text)`（`1440-1445`）。
  - 当前参数 `pages` 和 `answer_key_text` 不参与实际页面边界/答案键拼接逻辑；返回的 `start_page`、`end_page` 来自 segment，但题号切分路径中为 `None`。
- `_split_by_question_markers()` 位于 `backend/app/services/smart_import_service.py:1460-1499`：
  - 从 `QUESTION_SPLIT_PATTERNS` 中选命中最多的题号正则（`1462-1475`）。
  - 从每个题号 match 起点切到下一个题号 match 起点；第一个题号之前的前导文本没有进入任何 segment（`1478-1485`）。
  - 小片段按 `CHUNK_MAX_CHARS` 合并（`1486-1499`）。
- `_split_by_single_question()` 位于 `backend/app/services/smart_import_service.py:1502-1535`：类似题号切分但不合并，用于 L2 fallback 与 expected qnos；同样从题号 match 起点开始切段。

#### 3) LLM prompt 与解析 schema

- `ParsedQuestion` schema 位于 `backend/app/schemas/llm_parse.py:12-22`：字段包括 `source_question_no`、`question_type`、`scenario`、`content`、`options`、`correct_answer`、`explanation`、`references`、`confidence`、`issues`。
- `_build_llm_prompt()` 位于 `backend/app/services/smart_import_service.py:1562-1621`：
  - system prompt 第 4 条明确“如果是场景题，把案例背景放入 scenario 字段”（`1578`）。
  - JSON 格式要求中 `scenario` 与 `content` 分开输出（`1595-1599`）。
  - user message 为 `请解析以下题库文本片段：\n\n{chunk_text}`（`1616`）。
- `_process_chunk()` 在 `backend/app/services/smart_import_service.py:501-504` 构建 prompt 并把 `messages` 持久化到 `chunk.llm_request_json`。
- L1 整 chunk 调用在 `backend/app/services/smart_import_service.py:513-535`，通过 `_call_llm_with_l1_retry(messages, db, timeout=120.0)`；底层 `call_ai_api(messages, db, scene="smart_import", timeout=timeout)` 在 `721`。
- L2 单题 fallback 在 `backend/app/services/smart_import_service.py:740-829`：先 `_split_by_single_question(chunk_text)`，每段 `_build_llm_prompt(seg["text"], answer_key_text)` 后调用 `call_ai_api(... timeout=L2_PER_QUESTION_TIMEOUT)`（`761-796`）。
- `_parse_llm_response()` 位于 `backend/app/services/smart_import_service.py:1624-1649`：去除 markdown code fence，解析 JSON，并用 `LlmParseResult.model_validate(data)` 校验。

#### 4) 保存 `ImportParsedQuestion` 与写入 `Question`

- `_process_chunk()` LLM 解析成功后遍历 `llm_result.questions`，调用 `_save_parsed_question()`（`backend/app/services/smart_import_service.py:629-644`）；缓存命中路径 `_process_chunk_cached()` 也调用同一 helper（`646-694`）。
- `_save_parsed_question()` 位于 `backend/app/services/smart_import_service.py:902-1015`：
  - reparse 题号去重优先：`imported_qnos` 命中时走 `_persist_duplicate_parsed_question(reason="qno")`，不写 `Question`（`925-932`）。
  - 内容签名重复走 `_persist_duplicate_parsed_question(reason="content")`（`934-946`）。
  - 质量检查 `_quality_check(parsed_q, chunk_text)`（`951-952`）。
  - 创建 `ImportParsedQuestion` 时将 `parsed_q.scenario` 写入 `scenario_text`，`parsed_q.content` 写入 `content`，options/correct answer/explanation/references 分别入对应字段（`960-977`）。
  - 自动入库条件满足时调用 `_write_question_to_bank(db, parsed_question, import_job.bank_id)`（`981-990`），随后标记 `import_status="imported"`、`review_status="auto_accepted"`、`imported_question_id=question.id`（`991-994`）。
  - 不自动入库时创建 `ImportReviewItem`（`996-1012`）。
- `_write_question_to_bank()` 位于 `backend/app/services/smart_import_service.py:1018-1087`：
  - 读取 `parsed_question.options_json`、`parsed_question.correct_answer` 并转成正式 `Question` 所需格式（`1024-1038`）。
  - 以 `parsed_question.question_type`、`parsed_question.content`、options、answer 计算签名并在 `Question` 表做重复检查（`1040-1067`）。
  - 创建正式 `Question` 时当前 `content=parsed_question.content`，`explanation=parsed_question.explanation`，没有使用 `parsed_question.scenario_text`（`1071-1079`）。
  - 回写 `parsed_question.imported_question_id = question.id`（`1083-1085`）。
- `Question` 模型位于 `backend/app/models/question.py:12-27`，字段包含 `content`、`options`、`correct_answer`、`explanation` 等；没有 `scenario` 字段。

#### 5) reparse 与 review accept 对 `_write_question_to_bank()` 的复用情况

- reparse 入口：`backend/app/api/routes/import_review.py:78-98`，通过 review item 找到 parsed question 的 `chunk_id`，调用 `create_reparse_job()`。
- `create_reparse_job()` 位于 `backend/app/services/smart_import_service.py:1093-1145`：创建 `JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE` 的 `BackgroundJob`。
- `run_reparse()` 位于 `backend/app/services/smart_import_service.py:1148-1242`：
  - 删除该 chunk 下未导入的 `ImportParsedQuestion` 和关联 `ImportReviewItem`，保留 `import_status="imported" and imported_question_id` 的行（`1163-1180`）。
  - 重置 chunk 的 LLM request/response/issues（`1183-1188`）。
  - 构建 `seen_signatures`（`1195-1201`）与本 import job 已入库题号集合 `imported_qnos`（`1203-1217`）。
  - 调 `_process_chunk(..., bg_job=background_job, imported_qnos=imported_qnos)`（`1219-1228`）。因此 reparse 自动入库路径复用 `_process_chunk()` → `_save_parsed_question()` → `_write_question_to_bank()`。
  - reparse 后更新 import job 状态、题库统计、reconciliation（`1230-1242`）。
- review accept 入口：`backend/app/api/routes/import_review.py:48-60` 调 `accept_review_item()`。
- `accept_review_item()` 位于 `backend/app/services/smart_import_service.py:1248-1288`：直接调用 `_write_question_to_bank(db, parsed_question, import_job.bank_id)`（`1270-1272`），然后更新 parsed/review/import job 状态。因此人工接受路径也复用 `_write_question_to_bank()`。

#### 6) 质量检查与当前场景题相关行为

- `_quality_check()` 位于 `backend/app/services/smart_import_service.py:1654-1741`：评分和 issues 基于 `parsed_q.content`、options、answers、source_question_no、noise patterns。
- 与场景题相关的当前事实：`combined_text = parsed_q.content + " " + ...options`（`1718`），没有把 `parsed_q.scenario` 纳入内容长度、噪声、答案证据等检查。
- `_auto_accept_check()` 位于 `backend/app/services/smart_import_service.py:1744-1757`：`final_confidence >= 0.90`、无 HIGH issue、无答案缺失/冲突即可自动接受。

### Existing Tests / Reusable Fixtures

#### `backend/tests/test_smart_import_process_chunk_retry.py`

- 适合复用的模式：直接测试 `_process_chunk()`，用 `MagicMock` DB、chunk、import_job，不依赖真实数据库。
- 现有 fixture/工具：
  - `_make_response_text(qno_list)` 构造合法 LLM JSON（`42-66`）。
  - `_make_chunk_text(qno_list)` 构造带 `Question #N` 标记的 chunk text（`69-79`）。
  - `fake_db_factory`、`chunk_factory`、`import_job_factory` 分别构造 DB/chunk/job mock（`93-137`）。
  - `patch_io` monkeypatch 掉 `sleep`、cache、`_save_parsed_question()`、heartbeat，并记录调用（`139-172`）。
- 适合覆盖：prompt 调用、L1/L2 流程、`_process_chunk()` 是否把 parsed questions 交给 `_save_parsed_question()`；如果要检查真正 `ImportParsedQuestion` 和 `Question` 写入，则该文件当前默认把 `_save_parsed_question()` stub 掉，需要另起测试或调整局部 patch。

#### `backend/tests/test_smart_import_reparse_hygiene.py`

- 适合复用的模式：轻量 `_FakeDB` 捕获 `add()` 对象和 query 路由，直接验证 `_save_parsed_question()`、`run_reparse()` 的分支。
- 现有工具：
  - `_make_parsed_question()` 生成 `ParsedQuestion`（`41-64`）。
  - `_FakeDB` 捕获 `added`、`deleted`、flush/commit 次数，并用 `set_query_result()` 配置查询结果（`67-113`）。
  - `_FakeQuery` 支持 `filter_by()`、`all()`、`first()`、`scalar()`（`115-141`）。
  - `_make_import_job()`、`_make_chunk()` 构造基础对象（`144-168`）。
- 适合覆盖：`_save_parsed_question()` 是否创建含 `scenario_text` 的 `ImportParsedQuestion`、自动入库是否调用 `_write_question_to_bank()`、reparse 是否传 `imported_qnos`/`bg_job`。

#### `backend/tests/test_smart_import_e2e_reconciliation.py`

- 适合复用的模式：in-memory SQLite + 真 ORM + `Base.metadata.create_all()`，用于验证 `ImportParsedQuestion`、`Question`、`ImportReviewItem` 等真实写入关系。
- 现有关键 fixture/工具：
  - `@compiles(JSONB, "sqlite")` 将 PostgreSQL JSONB 在 SQLite 下编译为 JSON（`42-50`）。
  - `db_session()` 创建 `sqlite:///:memory:`、`Base.metadata.create_all(engine)`、`sessionmaker(expire_on_commit=False)`（`198-209`）。
  - `patch_runtime()` 屏蔽 sleep 和 heartbeat（`212-217`）。
  - `make_chunk_text(start, end)` 构造每题一段 chunk text（`91-104`）。
  - `make_response_text(qnos)` 构造 LLM JSON（`107-134`）。
  - `make_fake_call_ai_api(behavior)` 支持 `ALL_OK`、`L1_RETRY_THEN_OK`、`L2_FALLBACK`、`L2_PARTIAL_FAILURE`（`144-192`）。
  - `setup_bank_and_job()` 创建 `QuestionBank` + `ImportJob` + 31 chunks（从 `220` 起）。
- 适合覆盖：真实 `_write_question_to_bank()` 对 `Question.content` 的写入、review accept 状态流、history backfill 脚本的安全条件（可用真 ORM 数据构造）。

### Historical Backfill Script Context

- 现有项目中 `backend/scripts/` 是业务管理脚本位置，当前有 `backend/scripts/import_iapp_glossary.py`；`backend/scripts/__init__.py` 存在。
- `backend/scripts/import_iapp_glossary.py:86-103` 的 DB session 接入模式：
  - 在 `main()` 中延迟导入 `from app.core.database import SessionLocal`（`93`）。
  - `db = SessionLocal()`（`94`）。
  - 调业务函数执行导入（`96`）。
  - `finally: db.close()`（`98-99`）。
- 后台 worker 也直接使用 `SessionLocal()`：`backend/app/workers/job_worker.py:21-41` 中 `process_one_job()` 创建 session，执行后 `finally db.close()`。
- 数据库配置在 `backend/app/core/database.py:10-18`：全局 `engine = create_engine(settings.DATABASE_URL, ...)`，`SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)`。
- 当前 PRD 明确历史回填脚本要求：一次性管理脚本、dry-run 默认、显式 apply、无需自动备份、只处理 `ImportParsedQuestion.imported_question_id` 可关联且 `scenario_text` 非空、正式 `Question.content` 与 parsed short `content` 等价/匹配的记录（`.trellis/tasks/05-12-fix-smart-import-incomplete-scenario-stems/prd.md:24-27`, `65-67`）。

### Related Specs

- `.trellis/spec/backend/import-pipeline.md` — 智能导入流水线契约：
  - `_process_chunk()` 签名包含 `bg_job`、`imported_qnos`（`17-37`）。
  - L1/L2 retry/fallback、chunk statuses、issues_json schema（`39-103`）。
  - reparse 卫生：`imported_qnos` 来自 `ImportParsedQuestion` 表，初次导入传 `None`（`166-254`）。
  - reconciliation：`expected_qnos` 只在首次切 chunk 后写入，reparse 不重写（`258-363`）。
- `.trellis/spec/backend/database-guidelines.md` — 被 import-pipeline spec 引用，说明测试中 JSONB on SQLite 的方式（import-pipeline `343`）。本次未展开读取全文。
- `.trellis/tasks/05-12-fix-smart-import-incomplete-scenario-stems/prd.md` — 当前任务的实现要求和验收标准，尤其是正式 `Question.content` 合成规则、PDF 前导材料保守归属、prompt/质量检查轻量强化、历史回填脚本保护条件。

### External References

- 无。本次请求为项目内部实现上下文研究，未使用外部文档。

## Caveats / Not Found

- 未发现现有 `conftest.py`；测试 fixture 多为各测试文件内局部定义。
- 当前 `_split_by_question_markers()` / `_split_by_single_question()` 都从第一个题号 match 开始切段；题号前的 PDF 前导材料在现有逻辑中不会自动归属到第一题。
- 当前 `_write_question_to_bank()` 写正式题目时只使用 `parsed_question.content`，没有合并 `parsed_question.scenario_text`。
- 当前 `_quality_check()` 主要检查 `parsed_q.content` 和 options，未把 `parsed_q.scenario` 纳入检查。
- `pages` 参数传入 `_split_into_chunks()` 但现有题号切分路径未使用页码信息；`ImportChunk.start_page/end_page` 在题号切分路径中通常为 `None`。

## Risks and Suggested Tests

1. **正式题干合成一致性风险**：自动入库和人工 accept 都经 `_write_question_to_bank()`，但 duplicate signature、quality check、history backfill 也可能需要同一合成规则参与；建议测试 `_write_question_to_bank()` 对 `scenario_text + content` 的真实 `Question.content` 写入。
2. **reparse 重复入库风险**：reparse 会经 `_process_chunk()` 重新自动入库，且依赖 `imported_qnos` 防重复；建议保留/扩展 `test_smart_import_reparse_hygiene.py`，覆盖含 `scenario` 的 reparse 不重复写 Question 且新写入时使用完整题干。
3. **review accept 回归风险**：`accept_review_item()` 直接调 `_write_question_to_bank()`；建议用真 ORM 或 `_FakeDB` 覆盖 pending review item 含 `scenario_text` 时 accept 后 `Question.content` 为 `scenario_text\n\ncontent`。
4. **PDF 前导材料归属风险**：现有切分会丢弃第一个题号前文本；建议针对 `_split_into_chunks()` / `_split_by_question_markers()` 增加包含 `SCENARIO` 前导段 + `Question #247` 的单元测试，同时增加页眉/广告/上一题解析/答案段落不归属的负例。
5. **历史回填误改风险**：建议用 SQLite 真 ORM 构造 `ImportParsedQuestion(imported_question_id, scenario_text, content)` 与 `Question`，分别覆盖 dry-run 不写、apply 写、`scenario_text` 空不写、`imported_question_id` 缺失不写、`Question.content` 已人工编辑/不等价不写、已包含 scenario 不重复拼接。
