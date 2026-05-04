# 重构题库导入能力以及框架选型

## Goal

将当前题库导入从 Flask + SQLite 下的同步规则解析，重构为设计文档中定义的 FastAPI + PostgreSQL/pgvector + Python Worker + LLM 智能导入链路。目标是提升不同题库格式的兼容性、导入可观测性、失败可恢复性，并通过置信度与人工复核保证入库质量。

## What I already know

* 用户指定的 spec 文档是 `docs/trellis/quiz-app-fastapi-postgresql-smart-import-design.md`。
* spec 明确最终技术选型：FastAPI、PostgreSQL、pgvector、SQLAlchemy 2.x、Alembic、Pydantic、PostgreSQL 任务表 + Python Worker、OpenAI-compatible LLM、本地文件存储。
* spec 明确不使用 Flask、SQLite、Redis、MQ、Celery、RQ、ARQ、Dramatiq、RabbitMQ、Kafka、Qdrant、Milvus、Java。
* 当前项目仍是 Flask 后端：`run.py` 启动 Flask debug server，`backend/app.py` 注册 Flask blueprints 并直接 `db.create_all()`。
* 当前默认数据库仍是 SQLite：`backend/config.py` 默认 `sqlite:///backend/quiz.db`。
* 当前导入接口是 `POST /api/banks/<bank_id>/import`，位于 `backend/routes/banks.py`，同步解析上传文件并直接写入 `questions`。
* 当前解析逻辑位于 `backend/services/import_service.py`，以 pdfplumber/openpyxl/python-docx 抽文本，再用正则/固定格式解析题目。
* 当前已有一个 Flask/SQLite 风格的 `BackgroundJob` 和 worker 相关服务，主要服务高频词/专业词汇翻译，不支持智能导入任务、ImportJob、Chunk、Review、pgvector 或 LLM parse cache。
* 当前前端导入入口位于 `frontend/src/views/AdminBanksView.vue` 和 `frontend/src/components/FileUpload.vue`，弹窗上传后等待同步导入结果，仅额外创建高频词翻译后台任务。

## Assumptions (temporary)

* 本任务会以 spec 为准进行框架迁移与导入能力重构，不继续扩展旧规则导入。
* 为降低单次变更风险，实际实现应拆成多个小任务/PR，而不是一次性完成全量迁移、智能导入、复核 UI 和 pgvector 增强。
* 旧 quiz/auth/questions/wrong/ai 功能需要在新 FastAPI/PostgreSQL 架构下保持可用，不能只实现导入链路而破坏现有学习流程。

## Open Questions

* None.

## Requirements (evolving)

* 第一阶段 API 覆盖范围采用全核心 API 迁移：迁移 auth、account、admin users、banks、questions、quiz、wrong、ai、settings、vocab、jobs，目标是让前端尽量可直接跑通并接近替换 Flask 后端。
* 数据迁移策略采用新 schema 优先：第一阶段只建立 PostgreSQL schema，不提供 `backend/quiz.db` 到 PostgreSQL 的一次性数据迁移脚本，允许开发数据重新创建/重新导入。
* MVP 第一阶段采用基础迁移优先：先建立 FastAPI + PostgreSQL + SQLAlchemy 2.x + Alembic 基础架构，并保持现有核心学习/管理功能的 API 行为可迁移、可验证。
* 第一阶段不实现完整智能导入链路；智能导入 API、Worker、LLM 解析、复核 UI 和 pgvector 增强作为后续阶段交付。
* 第一阶段应尽量保持前端 `/api/*` 调用路径和响应形状稳定，避免把前端大改与后端框架迁移混在同一阶段。
* 废弃旧同步规则导入作为未来扩展方向，不再继续强化 `backend/services/import_service.py` 的正则解析能力。
* 新导入入口应创建 ImportJob + BackgroundJob，由 Python Worker 异步处理。
* Worker 应基于 PostgreSQL 任务表抢占任务、心跳续租、失败重试和进度更新。
* 文件抽取应统一输出 `DocumentText`，覆盖 PDF、DOCX、XLSX。
* LLM 解析输出必须经过 Pydantic/程序校验，低置信度题目进入人工复核，高置信度题目可自动入库。
* 前端应从“导入题目”同步弹窗演进为“智能导入”任务视图，展示状态、进度、解析数量、自动入库数量、待复核数量和失败 chunk。

## Acceptance Criteria (evolving)

* [ ] 后端框架选型与导入架构决策记录清晰，和 spec 保持一致。
* [ ] 第一阶段范围明确为 FastAPI/PostgreSQL/Alembic 基础迁移，不把完整智能导入链路塞进同一阶段。
* [ ] 现有 auth、account、admin users、banks、questions、quiz、wrong、ai、settings、vocab、jobs 等核心 API 完成迁移或有明确兼容策略。
* [ ] 前端现有主要页面在 FastAPI/PostgreSQL 后端下可完成登录、题库管理、题目管理、答题、错题、AI 功能、设置、词汇和后台任务相关基础流程。
* [ ] PostgreSQL schema 可通过 Alembic 从空库创建；第一阶段不要求迁移现有 SQLite 数据。
* [ ] 任务拆解能按可交付顺序推进，不要求一个 PR 完成所有智能导入能力。
* [ ] 新导入 API 不在请求线程执行长耗时解析/LLM 调用。
* [ ] 导入任务状态、进度、失败信息可通过 API 查询。
* [ ] 自动入库与人工复核边界有明确置信度/issue 规则。
* [ ] 旧导入 UI 的替换路径明确，用户能看到异步任务结果。

## Definition of Done (team quality bar)

* Tests added/updated where the project gains test infrastructure or where implementation touches deterministic logic.
* Build/type checks that exist in the repo pass.
* Docs/notes updated if behavior changes.
* Rollout/rollback considered for Flask/SQLite → FastAPI/PostgreSQL migration risk.
* No security regression in auth, admin authorization, file upload handling, or LLM input/output boundaries.

## Research References

* External research sub-agent attempt was blocked by upstream 502 provider errors in this session. The current PRD therefore treats the provided design spec as authoritative for framework selection.

## Research Notes

### Constraints from our repo/project

* Frontend is Vue 3 + Vite and can keep using `/api/*` with proxy/fallback behavior if FastAPI preserves compatible API prefixes.
* Current backend has no Alembic migrations and creates tables at startup; PostgreSQL migration requires replacing this with explicit migrations.
* Current `Question.options` is a JSON string in SQLite-era model; PostgreSQL-era design should use JSONB-compatible schemas while preserving frontend response shape.
* Current import also rebuilds bank word frequencies and may start high-frequency translation jobs; the new design needs an explicit decision on whether this remains part of import finalization or moves to a separate job.
* Current background job status names are `queued/running/completed/failed`; spec uses `pending/running/succeeded/failed/cancelled`, so migration must normalize job status contracts.

### Feasible approaches here

**Approach A: Foundation-first migration** (Recommended for lowest regression risk)

* How it works: first establish FastAPI + PostgreSQL + SQLAlchemy 2.x + Alembic skeleton and migrate existing auth/banks/questions/quiz/wrong/ai behavior, then add smart import tables and worker in subsequent tasks.
* Pros: reduces risk of breaking existing app; creates stable base for import work; makes later PRs easier to review.
* Cons: users do not get the new smart import capability in the first delivery.

**Approach B: Import vertical slice first**

* How it works: introduce enough FastAPI/PostgreSQL scaffolding to create ImportJob/BackgroundJob and show status for uploads, with a minimal worker that can extract/chunk before adding full LLM/review.
* Pros: validates the new import architecture early; demonstrates user-visible progress quickly.
* Cons: requires partial coexistence with current Flask/SQLite or a larger migration boundary; higher integration risk.

**Approach C: Big-bang rewrite to full spec**

* How it works: implement FastAPI, PostgreSQL, worker, LLM parsing, review UI and pgvector in one large change.
* Pros: aligns with final architecture immediately.
* Cons: very high regression/review risk; hard to test and roll back; not recommended.

## Expansion Sweep

### Future evolution

* pgvector can later support duplicate merge, similar-example prompt retrieval, auto tags, and knowledge-point recommendations.
* OCR can be added later for scanned PDFs; it should remain out of the initial non-OCR pipeline unless explicitly required.

### Related scenarios

* Import finalization should stay consistent with existing question ordering, bank `question_count`, AI translation/explanation cache, and high-frequency vocabulary flows.
* Admin authorization and file upload limits must remain consistent with existing bank management permissions.

### Failure & edge cases

* Worker crash should leave jobs recoverable through lease/heartbeat retry.
* Low-confidence, answer-conflict, answer-missing, duplicate, and noisy chunks should not silently auto-import.
* Unsupported or malformed files should fail the import job with inspectable errors, not fail a long-running request.

## Technical Approach

Use the provided design doc as the target architecture. Converge implementation into smaller stages: foundation migration, PostgreSQL models/migrations, smart import API/job creation, worker runner, extractor/chunker/LLM parser, quality gates/import writer/review APIs, frontend task/review UI, then pgvector enhancements.

For MVP 第一阶段, implement the foundation-first slice: create the FastAPI application structure, PostgreSQL configuration, SQLAlchemy 2.x session/dependency layer, Alembic migration baseline, JWT/auth compatibility, and migrate the full core API surface needed by the current Vue frontend. Keep frontend API prefixes and response shapes stable where practical.

## Decision (ADR-lite)

**Context**: The existing synchronous regex parser is brittle for real-world PDF/DOCX/XLSX exam banks and cannot provide progress, retry, review, LLM cache, or vector-assisted parsing.

**Decision**: Adopt FastAPI + PostgreSQL/pgvector + SQLAlchemy 2.x/Alembic + PostgreSQL task table + Python Worker + LLM smart import as specified in `docs/trellis/quiz-app-fastapi-postgresql-smart-import-design.md`.

**Consequences**: The app gains a scalable asynchronous import architecture without Redis/MQ operational complexity, but the Flask/SQLite migration and API compatibility must be managed carefully across small, reviewable stages.

**MVP scope decision**: User selected Approach A / Foundation-first migration for the first phase. The first phase should prioritize framework/database foundation and compatibility over delivering the full smart import feature immediately.

**Data migration decision**: User selected new PostgreSQL schema only for the first phase. Do not build a SQLite → PostgreSQL migration script in this task; existing development data can be recreated.

**API coverage decision**: User selected full core API migration for the first phase: auth, account, admin users, banks, questions, quiz, wrong, ai, settings, vocab, and jobs should move to FastAPI/PostgreSQL or have an explicit compatibility strategy.

## Out of Scope (explicit)

* OCR for scanned PDFs in the MVP.
* Redis/MQ/Celery or external vector database integration.
* Full auto-tagging/knowledge graph beyond schema/extension points unless included in a later task.
* Big-bang rewrite of all smart import features in a single implementation PR.
* Full LLM smart import, review UI, and pgvector retrieval in MVP 第一阶段.
* SQLite → PostgreSQL data migration script in MVP 第一阶段.

## Technical Notes

* Primary spec: `docs/trellis/quiz-app-fastapi-postgresql-smart-import-design.md`.
* Current backend entry: `run.py`, `backend/app.py`, `backend/config.py`.
* Current import API: `backend/routes/banks.py`.
* Current parser: `backend/services/import_service.py`.
* Current background job services: `backend/services/job_service.py`, `backend/services/job_handlers.py`.
* Current frontend import UI: `frontend/src/views/AdminBanksView.vue`, `frontend/src/components/FileUpload.vue`.
