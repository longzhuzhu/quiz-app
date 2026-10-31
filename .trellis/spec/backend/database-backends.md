# 数据库后端可选部署契约

修改数据库连接、ORM 列类型、迁移、后台任务锁或部署配置时读取本契约。PostgreSQL 默认部署与 SQLite 单机部署共用一套 API、模型与迁移链。

## 1. Applicability

- 新增或修改 ORM 列类型、JSON 字段、索引、约束或外键。
- 新增迁移、调整历史迁移，或更换迁移执行方式。
- 修改后台任务领取、租约、恢复、导入 ownership 或人工复核互斥。
- 修改 `DATABASE_URL` 解析、engine/session 创建、worker 并发或部署文档。

## 2. Required behavior

### 配置与启动

- 默认后端仍是 PostgreSQL。只有 `DATABASE_URL` 显式使用 SQLite 才切换；配置错误必须启动失败，不得静默回退到其他数据库或遗留文件。
- SQLite 只支持绝对路径的文件库。`:memory:` 只用于测试，不作为部署方式。
- SQLite 每个连接都必须 `PRAGMA foreign_keys=ON`，并设置有限的 `busy_timeout`；不得只在建库时执行一次。
- SQLite 会话在事务开始前使用 `BEGIN IMMEDIATE` 取得写权限；只读请求使用 deferred 事务。HTTP 写请求与 worker 会话语义保持一致。
- 网络请求（AI 调用等）前必须结束本地数据库事务；不得跨 HTTP 或模型调用持有 SQLite 写锁。
- 运行库低于 SQLite 3.38 时拒绝启动。不默认启用 WAL；启用前必须单独验证版本、checkpoint、备份恢复与崩溃行为。

### 数据类型

- 跨后端 JSON 列使用 `app/core/db_types.py` 的 `JSONType`（PostgreSQL 编译为 JSONB）。新增模型不得直接 `from sqlalchemy.dialects.postgresql import JSONB`。
- 迁移文件保持自包含：在文件内定义 `JSONType` 与默认值分支，不导入会随应用演进的模型或运行时常量。
- 不为已存在的 PG 列做 JSONB↔JSON 的物理类型转换；SQLite 建表使用 `JSON`。
- 保留整字段重新赋值／`flag_modified` 的既有 JSON 更新约定。

### 迁移

- 保持单一 revision 链；不要为 SQLite 复制独立迁移树，也不要用 `create_all` + stamp 代替升级。
- 历史迁移按 `op.get_bind().dialect.name` 分支；PG 分支的数据语义与提示词字面量必须保持不变。
- SQLite 的 `ALTER` 约束／删列使用 `op.batch_alter_table`；已有迁移不会因 `render_as_batch` 自动修好。
- 迁移 `003` 的固定管理员校验只允许在「真正空库」时走 schema-only；非空旧库仍必须校验 owner，禁止任选用户回填归属。
- 迁移连接可临时关闭外键以重建表，但必须只限该专用连接、在事务外受控设置，结束后恢复并执行 `foreign_key_check`。不要关闭应用所有连接的外键。
- 已在生产执行过的 PG 迁移不得修改其 revision 身份、数据含义或已生效字面量。

### 并发与后台任务

- PostgreSQL 的长生命周期互斥继续使用 advisory lock；SQLite 使用同机原生文件锁（`filelock`），不得使用 `SoftFileLock`，也不得用进程内线程锁替代 API/worker 跨进程互斥。
- 锁目录由数据库绝对路径派生，API 与 worker 必须指向同一锁域；不能把锁文件存在与否当作锁状态。
- SQLite 没有 `FOR UPDATE`／`SKIP LOCKED`：任务恢复使用条件 `UPDATE`（CAS），关键读改写依赖 `BEGIN IMMEDIATE`、唯一约束或原有 SAVEPOINT 兜底。
- 导入 `require_execution`／`review_writer` 在所有后端都必须执行 ownership／fencing；不得保留「非 PostgreSQL 直接放行」的分支。
- SQLite 的 worker 业务并发强制为 1；`JOB_WORKER_CONCURRENCY` 配置值本身不改写，API 与 worker 仍是两个进程。
- `database is locked` 只允许在无外部副作用的短事务边界做有界重试；不得自动重跑 AI 或整个 HTTP 请求，不得吞错返回成功。

### 查询

- 使用两种后端语义一致的写法。禁止依赖只有 PostgreSQL 支持的 `DISTINCT ON`；需要「每组最新一行」时用相关子查询。
- 方言专用 SQL（advisory lock、`pg_locks`、`jsonb_*`、`SET LOCAL`）必须收敛到明确的方言分支或 `core/` 内部模块。
- `ilike`、`func.random()`、`FILTER` 等可按现有方言能力使用，但至少由真实 SQLite 与真实 PostgreSQL 测试各验证一次关键路径。

## 3. Forbidden behavior

- 根据启动目录解析 SQLite 相对路径，或自动接受工作区遗留的 `backend/quiz.db`。
- 为通过空库迁移随意选择第一个用户、跳过 owner 校验或修改历史数据归属。
- SQLite 部署宣称支持高并发、多应用实例共享数据库文件或网络文件系统。
- 使用测试中的 `@compiles(JSONB, "sqlite")` 钩子作为生产兼容方案。
- 为了兼容 SQLite 删减功能、跳过锁／lease／checkpoint，或把专用离线判重 CLI 纳入在线应用。
- 在同一部署中同时连接两种数据库、双写或自动切换。

## 4. Required validation

- 配置：文件型临时 SQLite 建库、逐连接外键、拒绝相对路径、拒绝不支持的后端且错误消息不泄露凭据。
- 迁移：临时 SQLite 空库 `upgrade head`、`downgrade base` 再升级；非空旧库缺 owner 必须失败、有 owner 必须正确回填；PG 侧提示词迁移字面量与 tripwire 保持。
- 并发：文件型 SQLite 上验证跨进程文件锁、同一任务双领被拒、人工复核忙返回 409、旧 attempt 失权后不能提交。
- 业务：SQLite 上验证答题／改答／错题、导入执行、AI 调用前的只读事务结束及后台任务恢复。
- 回归：现有 PostgreSQL 全量套件继续通过。SQLite 文件库验证不能由内存库或 `create_all` 单独替代迁移／锁证明。
- 不在未显式覆盖 URL 的情况下运行 Alembic 或业务 pytest，避免连接生产配置。

## 5. Related contracts

- [导入执行恢复](import-recovery.md) — ownership、lease、checkpoint 与失租不写入。
- [上下文治理](../context-curation.md) — 规格叶子拆分与任务清单。
- [部署说明](../../docs/deployment.md#sqlite-单机部署可选)。
