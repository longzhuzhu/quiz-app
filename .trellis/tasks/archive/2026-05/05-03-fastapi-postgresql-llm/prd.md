# 重构题库导入：FastAPI + PostgreSQL + LLM 智能导入

## Goal

将当前管理员题库导入从同步规则解析，演进为 FastAPI + PostgreSQL + Python Worker 驱动的异步智能导入流程，让 PDF/DOCX/XLSX 题库上传后可跟踪进度、可复核低置信度解析结果，并最终稳定写入现有 `questions` 表。

## What I already know

* 项目当前后端已迁移到 FastAPI 入口：`backend/app/main.py`，API 前缀保持 `/api/*`。
* 数据库层已使用 SQLAlchemy 2.x + Alembic + PostgreSQL 方言；当前工作区已有智能导入相关模型和迁移草稿。
* 旧导入入口仍在 `backend/app/api/routes/banks.py` 的 `POST /api/banks/{bank_id}/import`，当前同步调用 `parse_file()` 并立即写入题目。
* 旧解析逻辑在 `backend/app/services/import_service.py`，包含 PDF/DOCX/XLSX 文本抽取、规则解析、高频词统计；其中高频词统计仍被题库词频功能复用。
* `backend/app/api/routes/import_jobs.py`、`backend/app/api/routes/import_review.py` 目前还是 stub，仅声明后续端点。
* 现有后台任务框架在 `backend/app/services/job_service.py`、`backend/app/services/job_handlers.py`、`backend/app/workers/job_worker.py`，已有 `professional_vocab_translate` 和 `bank_frequent_translate` 两类任务。
* 现有 AI 调用入口是 `backend/app/services/ai_service.py::call_ai_api(messages, db, scene="default")`，可通过 `scene` 使用不同 AI 设置。
* `backend/app/schemas/llm_parse.py` 已有 `ParsedOption`、`ParsedQuestion`、`LlmParseResult` 作为 LLM 结构化输出基础 schema。
* 前端当前通过 `frontend/src/components/FileUpload.vue` 在 Modal 内同步上传 `/banks/{bankId}/import`，成功后只显示导入结果和高频词后台翻译状态。
* 前端路由 `frontend/src/router/index.js` 当前没有导入任务列表、详情、复核页面。
* 设计参考文档已存在：`docs/trellis/quiz-app-fastapi-postgresql-smart-import-design.md`。
* `origin/main:reference/questions` 下有 5 个目标 PDF 样本，智能导入需要支持它们的识别与导入：
  * `reference/questions/CIPT 283题.pdf`
  * `reference/questions/CIPT Dumps-50pages.pdf`
  * `reference/questions/CIPT Passing Score 800 Time Limit 120 Min File Version 1.pdf`
  * `reference/questions/CIPT Questions-102pages.pdf`
  * `reference/questions/IAPP Examquestions CIPT v2020-02-14 by Willow 45q.pdf`

## Assumptions (temporary)

* 本任务以“核心导入闭环”为优先：上传 → 创建 ImportJob/BackgroundJob → Worker 解析 → 自动入库或进入复核 → 前端查看进度与处理复核。
* 本任务保留旧 `import_service.py` 的高频词统计能力，不删除该文件。
* 本任务不引入 Redis/Celery/MQ，沿用 PostgreSQL 任务表 + Python Worker。
* 本任务默认继续支持 PDF、DOCX、XLSX 三类文件。
* PDF 智能识别必须覆盖 `origin/main:reference/questions` 中新增的 5 个 CIPT 题库样本。
* 5 个 PDF 样本的验收强度为“高准确导入”：除基础抽取、切片、解析不崩溃外，解析题数与文件标称题数偏差应 ≤10%；超过 10% 时必须在导入报告中解释原因；自动入库占比应 ≥85%，人工复核占比应 ≤15%。
* 本任务默认管理员才能创建导入任务和执行复核操作。
* 本任务不实现 pgvector/embedding；向量召回、向量去重和自动标签推荐后续独立迭代。
* 智能导入成功入库题目后，只构建题库高频词，不自动触发高频词 AI 翻译。

## Open Questions

* 待最终确认后进入实现准备。

## Requirements (evolving)

### Backend

* 新增或补齐智能导入所需持久化模型和 Alembic 迁移：`import_jobs`、`import_chunks`、`import_parsed_questions`、`import_review_items`、`llm_parse_cache`，以及可选的 `vector_index` 预留表。
* PDF 抽取、切片和 LLM prompt 需要针对 `reference/questions` 的 5 个 CIPT PDF 样本做格式兼容，支持不同命名、分页、题号/答案位置和题干/选项排版差异。
* 将 `POST /api/banks/{bank_id}/import` 从同步规则导入改为创建异步 ImportJob，并关联一个 `question_import_llm` BackgroundJob 后立即返回。
* 实现导入任务查询接口，至少支持查询任务状态、进度统计、chunk 列表、待复核题目。
* 扩展 Worker job dispatcher，支持 `question_import_llm`。
* 实现 smart import service 层：文件抽取、文本规范化、chunk 切片、prompt 构建、LLM 调用、LLM JSON 解析、Pydantic 校验、质量评分、缓存、入库/复核分流。
* 高置信度解析结果自动写入现有 `Question`；低置信度或存在严重问题的结果进入人工复核。
* 智能导入写入题目后，需要更新题库高频词统计；本任务不自动创建 `bank_frequent_translate` 任务。
* LLM 调用失败、非法 JSON、单个 chunk 解析失败不得导致整个 Worker 进程崩溃；任务状态需要可诊断。
* 保留旧规则解析代码作为可复用抽取/词频能力来源，但新上传入口不再使用规则解析直接入库。

### Frontend

* 管理员题库页的“导入题目”入口调整为智能导入体验。
* 上传文件后跳转或进入导入任务详情视图，展示任务状态、进度、统计和错误信息。
* 新增全局独立导入任务列表页 `/import-jobs`，管理员可查看所有题库导入任务，并跳转任务详情或复核。
* 提供人工复核界面，展示原始 chunk、LLM 解析结果、issues，并支持只读接受、跳过、异步后台重新解析；本阶段接受前不支持编辑题目字段。
* 进行中任务需要轮询刷新，避免用户误以为上传请求仍在同步执行。

## Acceptance Criteria (evolving)

* [ ] `alembic upgrade head` 可创建智能导入相关表，`alembic downgrade -1` 可回滚这些表。
* [ ] 管理员上传 PDF/DOCX/XLSX 到 `/api/banks/{bank_id}/import` 后，接口立即返回 `import_job_id`、`background_job_id` 和初始状态。
* [ ] `origin/main:reference/questions` 中 5 个 CIPT PDF 样本均可完成文本抽取、chunk 切片、LLM 解析，并产生可自动入库或可人工复核的解析结果。
* [ ] 5 个 PDF 样本的解析题数与文件标称题数偏差 ≤10%；若偏差超过 10%，导入报告必须说明失败 chunk、低置信度原因或格式异常。
* [ ] 5 个 PDF 样本达到高准确导入标准：自动入库占比 ≥85%，人工复核占比 ≤15%；未自动入库的题目必须有可解释的 issue 或低置信度原因。
* [ ] Worker 可领取 `question_import_llm`，并更新 BackgroundJob 与 ImportJob 的进度和状态。
* [ ] 文件被抽取并切成 chunks，每个 chunk 有状态、hash、原文和可追踪的 LLM 请求/响应或错误信息。
* [ ] LLM 输出经过 schema 校验和程序质量检查；非法 JSON 或字段缺失被记录为 issue，而不是未捕获异常。
* [ ] 满足自动入库条件的题目写入 `questions` 表，并更新题库题目数量。
* [ ] 智能导入完成后构建/更新题库高频词统计，但不自动触发高频词 AI 翻译后台任务。
* [ ] 低置信度或有严重 issue 的题目可在复核接口和前端复核页看到。
* [ ] 接受复核题目会按 LLM 解析结果原样写入 `questions`，不提供编辑；跳过复核题目不会入库；重新解析 chunk 会创建或复用后台任务异步执行，页面通过轮询展示状态。
* [ ] LLM 缓存命中时跳过外部 LLM 调用，并复用缓存结果。
* [ ] 前端上传后不再等待完整解析完成，而是跳转到可轮询的导入任务详情页；全局 `/import-jobs` 页面可查看所有导入任务。
* [ ] 旧同步导入路径不再从 UI 暴露。

## Definition of Done

* 后端 Pydantic request/response schema 覆盖新增 API。
* 后端服务层边界清晰：route 只负责鉴权/参数/响应，长任务逻辑只由 Worker 执行。
* 导入失败、部分 chunk 失败、LLM 配置缺失、文件格式不支持、任务不存在等边界行为明确。
* 前端桌面端和移动端核心流程可用。
* 运行项目现有可执行验证命令；若无测试/lint 配置，至少完成后端 import/启动级检查与前端 build。

## Out of Scope (explicit)

* OCR 图片题识别。
* Redis、Celery、MQ 或外部队列系统。
* 删除旧 `import_service.py`。
* 普通用户自助导入题库。
* 人工复核时编辑题干、选项、答案、解析或 issue 标记。
* 智能导入后自动翻译高频词。
* 大规模批量并发导入优化。
* pgvector/embedding、相似样例召回、向量去重和自动标签推荐；本阶段只保留后续扩展空间。

## Technical Approach (draft)

### Approach A: 核心闭环优先，pgvector 延后（已确认）

* 本阶段实现异步导入、LLM 解析、质量评分、自动入库、人工复核和缓存。
* `vector_index` 可只作为预留普通表，暂不启用 pgvector 扩展、不生成 embedding、不做相似召回。
* 优点：交付风险较低，先解决同步导入和复核缺失的核心问题。
* 缺点：本阶段重复题检测和相似样例召回能力较弱。

### Approach B: 完整智能导入，包含 pgvector/embedding

* 在本阶段同时启用 pgvector、embedding 生成、相似样例召回和向量辅助去重。
* 优点：更接近设计文档的完整架构，解析质量与去重能力更强。
* 缺点：迁移、依赖、配置、成本和回归风险明显增加，前后端闭环交付周期更长。

## Expansion Sweep

### Future evolution

* 后续可加入向量召回、重复题检测、自动标签、OCR、导入报告导出。
* smart import service 应避免把 pgvector 逻辑写死在 MVP 主流程中，以便后续插入增强模块。

### Related scenarios

* 高频词统计仍依赖导入后的题目内容；智能导入完成后只构建高频词统计，不自动翻译，管理员后续可通过独立流程处理翻译。
* 管理员题库详情页、题库列表页、导入任务页需要在题目数量和导入状态上保持一致。

### Failure and edge cases

* 文件过大、格式不支持、LLM 配置缺失、LLM 超时、非法 JSON、答案不在选项中、重复接受复核、Worker 中断恢复都需要定义状态。
* 需要避免同一个复核项重复入库；接受/跳过接口应考虑幂等或明确拒绝重复操作；重新解析 chunk 必须走后台任务，避免 API 请求超时。
* 5 个目标 PDF 样本可能存在题号格式、答案表位置、跨页题、页眉页脚、水印或广告文本差异；chunker、prompt、质量评分和复核分流阈值需要以这些样本作为兼容性和准确率基准。
* PDF 样本高准确导入阈值：解析题数与标称题数偏差 ≤10%，自动入库占比 ≥85%，人工复核占比 ≤15%。

## Decision (ADR-lite)

**Context**: 设计文档描述了完整的 LLM + pgvector 智能导入，但当前仓库已有 Worker、stub route、schema 和表结构草稿，实施范围需要先收敛，避免一次性引入过多风险。

**Decision**: 本阶段选择 Approach A：实现异步导入、LLM 解析、缓存、自动入库和人工复核；不实现 pgvector/embedding、相似样例召回或向量去重。

**Consequences**: 本阶段可以优先交付稳定闭环，降低迁移、依赖、配置和回归风险；重复题检测和相似样例召回能力留到后续阶段独立迭代。

## Technical Notes

* 设计文档：`docs/trellis/quiz-app-fastapi-postgresql-smart-import-design.md`。
* FastAPI 入口与路由注册：`backend/app/main.py`。
* 当前同步导入端点：`backend/app/api/routes/banks.py`。
* 旧解析/抽取/词频逻辑：`backend/app/services/import_service.py`。
* 现有后台任务服务：`backend/app/services/job_service.py`、`backend/app/services/job_handlers.py`、`backend/app/workers/job_worker.py`。
* 现有 AI 调用：`backend/app/services/ai_service.py`。
* LLM parse schema：`backend/app/schemas/llm_parse.py`。
* stub routes：`backend/app/api/routes/import_jobs.py`、`backend/app/api/routes/import_review.py`。
* 前端上传组件：`frontend/src/components/FileUpload.vue`。
* 管理员题库页：`frontend/src/views/AdminBanksView.vue`。
* 前端路由：`frontend/src/router/index.js`；需要新增 `/import-jobs` 全局列表页和导入任务详情/复核路由。
* 目标 PDF 样本位于 `origin/main:reference/questions`，当前工作树尚未包含该目录；实施或验证前需要从 `origin/main` 获取这些样本。
