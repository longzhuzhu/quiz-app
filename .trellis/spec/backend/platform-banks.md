# 平台题库与个人副本契约

修改平台题库来源、草稿、发布快照、目录、个人副本选用，或判断「某次正式内容写入是否允许」时读取本契约。决策背景见 [ADR-0016](../../docs/adr/0016-platform-question-bank-copies.md)。

## 1. Scope / Trigger

- 新增/修改 `PlatformBank`、`PlatformDraftQuestion`、`PlatformBankRelease`。
- 修改 `QuestionBank.source_platform_*`、`Question.source_topics`、`ImportJob.platform_bank_id`、`ImportParsedQuestion.imported_platform_question_id` / `inserted_new`、`BackgroundJob.platform_bank_id`。
- 新增任何能写正式题目内容的入口（增题、整题 PUT、删题、再导入、批量考点、后台打标）。

## 2. 数据模型不变量

- 平台来源不归属 `Exam`/`User`；`Exam` 侧不新增「平台类型」分支，`QuestionBank.exam_id` 保持 `NOT NULL`。
- `QuestionBank` 的来源与版本**同时为空或同时存在**（`ck_question_banks_source_pair`）。
- 组合外键 `(source_platform_release_id, source_platform_bank_id) → (id, platform_bank_id)` 保证版本确属该来源；`uq_platform_bank_releases_id_bank` 是支撑它的显式唯一约束。**不要删除该唯一约束**，否则组合外键无法建立。
- `UNIQUE(exam_id, source_platform_bank_id)` 以来源而非发布版本保证副本唯一；自建库的 NULL 来源不受限制，副本物理删除后唯一键自然释放。
- `ImportJob` 必须恰有一个目标（`ck_import_jobs_single_target`）；`ImportParsedQuestion` 的两个题指针不得同时有值。
- `inserted_new` 是「平台任务确实新增过题目」的历史证据：草稿题被删除后**不清标记**，新增计数不得退化为「当前草稿指针数量」。
- `BackgroundJob.created_by` 可为空，但个人任务必须有作者（`ck_background_jobs_platform_author`）。

## 3. 锁顺序（跨后端统一）

```text
平台写者：PlatformBank → ImportJob → BackgroundJob
选用副本：Exam → PlatformBank → 个人 QuestionBank
删除项目：先锁 Exam，再枚举清理
```

禁止出现 `PlatformBank → Exam` 的反向取锁。平台管理/导入不锁个人 `Exam`。

- PostgreSQL 用行锁 `with_for_update()`；SQLite 由写会话的 `BEGIN IMMEDIATE` 提供互斥，不要为 SQLite 加 `FOR UPDATE`。
- 平台落题必须在**首次写入/flush 前**进入来源协调，不能只在最后 `commit` 前补锁。
- 活动写者 = 该来源全部 `queued`/`running` 的 `BackgroundJob`，不能只看 `ImportJob.background_job_id`，也不能把 `ImportJob.status` 提前终态当作「已经停止写入」。

## 4. 发布与选用

### 发布（单事务）

锁来源 → 确认无活动写者 → 读取全部草稿并稳定排序 `(order_index, id)` → 逐题校验（题型、题干长度、选项、答案属于选项、题量至少 1）→ 构造完整快照 → 插入新版本 → 上架 → 提交。任一步失败整体回滚；**不静默过滤坏题**，不提供自动发布。

历史导入任务即使有跳过/失败记录，只要当前草稿全部合法且无活动写者，管理员仍可发布。

### 下架

只置 `is_listed = false`，保留快照与草稿，不触碰个人副本。目录不显示下架来源；已有副本继续可练。

### 选用（单事务）

1. 显式解析当前用户的 `X-Exam-Slug`，先锁 `Exam` 并复核所有权。
2. 锁来源。
3. **先查本项目现有副本**：存在则直接返回（即使来源刚下架）。
4. 无副本时检查 `is_listed` 与最新完整版本，否则 409。
5. 按快照整库复制，只在最后统一 `flush`，不在题目循环内 `commit`。
6. 数据库唯一约束是最终兜底：**只捕获项目+来源唯一键冲突**并回滚后读取胜出副本，其他 `IntegrityError` 必须整体回滚上抛，不能当成并发成功。

## 5. 正式内容写保护

按操作判断，不按整行判断。复用 `platform_bank_service.ensure_bank_accepts_formal_writes` / `ensure_question_accepts_formal_writes`。

| 入口 | 平台副本 |
| --- | --- |
| `POST /api/questions` | 403 |
| `PUT /api/questions/{id}`（含仅带答案） | 403 |
| `DELETE /api/questions/{id}` | 403 |
| `POST /api/banks/{id}/import` | 403（读文件前拒绝） |
| `POST /api/jobs {question_topic_tag}` | 403 |
| 导入 accept/reparse 最终写者 | 拒绝目标写入 |
| `PUT /api/questions/{id}/correct-answer` | 允许 |
| `PUT /api/banks/{id}`（名称/简介） | 允许 |
| 翻译、AI 解析、词汇、练习、错题 | 允许 |
| `DELETE /api/banks/{id}` | 允许（按现有删库语义） |

- HTTP 前置检查用于尽早拒绝，**最终写者检查用于防旁路**；不能只检查按钮。
- 来源/版本/`is_platform_copy` 是只读字段：伪造写请求必须显式失败，不能靠 Pydantic `extra=ignore` 静默丢弃后返回成功。
- 不要把整个 `options` JSON 设为不可写：翻译会写 `options[].text_zh` 与 `content_zh`。

## 6. 导入双目标

- 目标只取自已持久化的 `ImportJob`，不信任客户端 payload。个人/平台共用抽取、LLM、校验、缓存、checkpoint、fencing。
- 平台目标只写 `PlatformDraftQuestion`，不写任何个人 `Question`/`QuestionBank`/词频/学习数据，也不复制原生解析到个人 AI 缓存字段。
- 平台落题与 `imported_platform_question_id`、`inserted_new`、审计、checkpoint 同事务。
- **reparse fail-closed**：若目标分块存在 `inserted_new = true` 且 `imported_platform_question_id IS NULL` 的记录（草稿题被手工删除），该分块的 reparse 在**入队与执行两处**都必须拒绝，并提示改用新的追加导入。不论历史题号是否存在，新模型响应都可能改变题号或措辞，不能靠题号/文本签名猜测成员身份。
- 同来源并行导入的签名与 `max(order_index)` 必须在来源锁内重新读取，不能用模型调用前的内存集合决定是否新增。
- 统计必须分开：任务实际新增（`inserted_new` 计数）、当前草稿题数、发布可发布题数。不要用 `imported_questions` 冒充实际新增。

## 7. 生命周期

- 平台来源、发布快照、已结束任务与结果审计**不随导入管理员账号删除**，只解除 `created_by` 署名。
- 删除个人项目/账号只清理个人目标；不级联删除平台内容或他人副本。
- 保留既有「仍有运行中后台任务则拒绝删除账号」保护，不放宽。
- 已有副本的练习不依赖来源是否上架或发布作者是否仍存在。

## 8. 静态文件与上传边界

- SPA fallback 必须在 `realpath` 后验证仍位于 `frontend/dist` 内，越界（编码路径、双编码、`..`、越界符号链接、NUL）一律 404，**不得回退成 SPA 页面**；合法静态资源、SPA 客户端路由、HEAD 空正文与 `/api` 404 保持不变。
- 上传物理文件名由服务端生成（哈希 + 随机后缀 + 白名单扩展名），用户 `filename` 只提供扩展名，不参与磁盘路径。
- 私有存储根目录不得落在 `frontend/dist` 内；否则拒绝保存。

## 9. 迁移与回滚

- 单一后继 revision；存量个人数据不自动回填为平台来源，也不自动公开管理员既有题库。
- SQLite 约束/可空变更用 `batch_alter_table`；JSON 列用 `app/core/db_types.py` 的 `JSONType`（迁移文件内自包含同名定义）。
- 存在平台来源/发布版/平台任务/副本时，`downgrade` 必须**显式拒绝**破坏性回退；不得自动删除副本、清空 provenance 或把副本「洗成」自建库。
- 已有副本后不能直接切回不识别来源限制的旧应用。

## 10. Tests Required

- `backend/tests/test_platform_banks_api.py`：真实 Bearer 身份、管理/目录/选用/D01–D04/权限矩阵/跨用户跨项目。
- `backend/tests/test_platform_banks_import.py`：只写草稿、`inserted_new` 历史计数、reparse fail-closed、个人导入回归。
- `backend/tests/test_platform_banks_concurrency.py`：真实 PostgreSQL，并发选用、复制中途失败、发布/下架/导入交错。
- `backend/tests/test_platform_banks_migrations.py`：双后端迁移、约束生效、受控降级。
- `backend/tests/test_platform_banks_study.py`：副本练习/错题/翻译与重发下架后的学习回归。
- `backend/tests/test_static_file_boundaries.py`：静态与上传路径边界，只用无敏感 fixture。

运行须走 `backend/tests/run_isolated_suite.py`，不能对业务配置数据库执行迁移或业务测试。
