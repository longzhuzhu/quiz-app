# 后台任务中心与异步翻译设计

## 概要

本设计为当前 Flask 项目引入一个可持久化的后台任务中心（background job center），统一承载需要“提交后异步执行、页面刷新不中断、失败可重试、结果可恢复”的后台任务。

首批只接入两类批量翻译任务：

- 专业词汇批量翻译
- 高频词批量翻译

目标不是只修掉单个按钮，而是把当前“前端 `while true` 连续发请求”的临时方案替换为标准的后端异步任务模型：

- 前端提交任务
- 后端持久化任务
- 独立 worker 异步执行
- 前端按任务 ID 或按作用域查询状态
- 失败自动重试，达到上限后结束任务
- 用户再次点击时，只继续处理仍未翻译的数据

本次设计保持任务中心本身通用，但首阶段只落地到上述两类批量翻译，不扩散到题目翻译、题目解析和其它 AI 场景。

## 背景与现状

当前实现存在以下问题：

### 1. 专业词汇批量翻译依赖前端循环

`frontend/src/views/VocabularyView.vue` 中，专业词汇批量翻译通过前端 `while (true)` 连续调用后端接口实现。每次请求只处理一小批数据，前端负责循环直到剩余数量为 0。

### 2. 高频词批量翻译也依赖前端循环

`frontend/src/views/VocabularyView.vue` 和 `frontend/src/components/FileUpload.vue` 中，高频词翻译同样通过前端循环调用 `/api/banks/<bank_id>/translate-frequencies` 实现。

### 3. 当前实现的根本缺陷

这种实现方式的核心问题不是“批次大小不合适”，而是职责放错了位置：

- 页面刷新后，循环立即中断
- 网络抖动或单次请求失败后，整体流程停止
- 任务状态只保存在页面内存中，不可恢复
- 任务无法脱离当前浏览器页面独立执行
- 没有统一的失败重试与任务回收机制
- 难以扩展到更多后台任务类型

### 4. 项目约束

- 当前项目技术栈是 Flask + SQLAlchemy + SQLite，未引入 Redis、Celery、消息队列等基础设施
- 当前项目没有正式迁移体系，数据库变更依赖 `db.create_all()` 和运行时 schema ensure
- 生产环境已使用 systemd 启动主应用，适合增加独立 worker 服务

## 目标

### 功能目标

1. 专业词汇批量翻译改为后台异步执行
2. 高频词批量翻译改为后台异步执行
3. 页面刷新后能够恢复任务状态，不中断后台执行
4. 任务失败后自动重试，最多执行 3 次后结束任务
5. 用户再次点击时，只继续处理当前仍未翻译的数据
6. 前端明确展示任务状态、进度、失败原因与继续操作方式

### 设计目标

1. 任务状态持久化到数据库，不依赖前端页面内存
2. 任务执行脱离 Web 请求生命周期
3. 同一翻译范围同一时间只允许一个活动任务，避免重复翻译和进度冲突
4. 任务中心本身可扩展，后续可挂接更多任务类型
5. 在不引入 Redis/Celery 的前提下，达到当前项目可接受的稳定性与可维护性

## 非目标

本次不包含以下范围：

- 题目单题翻译改为后台任务
- 题目解析改为后台任务
- 个人单词自动翻译改为后台任务
- WebSocket / SSE 实时推送
- 分布式调度、跨多机任务分片
- 复杂的单条降级重试策略
- 完整通用任务管理后台页面

## 总体架构

采用“数据库任务表 + 独立常驻 worker”的轻量异步方案。

### 运行流

1. 前端点击“批量翻译”按钮
2. 前端调用 `POST /api/jobs` 创建或复用任务
3. 后端将任务写入 `background_jobs`
4. 独立 worker 轮询数据库，抢占待执行任务
5. worker 按任务类型逐批处理并持续更新进度
6. 前端轮询任务状态接口展示进度
7. 任务成功、失败或达到重试上限后进入终态
8. 页面刷新后，前端通过“查询当前活动任务”接口恢复状态

### 首阶段接入的任务类型

- `professional_vocab_translate`
- `bank_frequent_translate`

其中：

- 专业词汇任务作用域是全局专业词汇集合
- 高频词任务作用域是单个 `bank_id` 下的高频词集合

## 数据模型设计

新增通用任务表：`background_jobs`。

### 字段设计

- `id`
- `job_type`：任务类型
- `scope_key`：任务逻辑作用域
- `active_scope_key`：活动态互斥键；终态时设为 `NULL`
- `payload_json`：JSON 字符串，存放任务参数
- `status`：`queued` / `running` / `completed` / `failed`
- `attempt_count`：当前已执行次数
- `max_attempts`：固定为 `3`
- `progress_total`：任务开始时待处理总量
- `progress_done`：已完成处理数量，定义为 `success_count + skipped_count`
- `success_count`：成功翻译数量
- `skipped_count`：跳过数量（例如执行时发现该条已被其它操作补齐翻译）
- `last_error`：最后一次失败信息
- `status_message`：给前端展示的简短状态说明
- `next_run_at`：允许下次重试的时间
- `heartbeat_at`：最后心跳时间
- `lease_until`：当前 worker 的租约到期时间
- `created_by`
- `created_at`
- `started_at`
- `finished_at`

### 作用域设计

本阶段使用以下 `scope_key` 规则：

- 专业词汇：`professional_vocab`
- 高频词：`bank_frequent:<bank_id>`

示例：

- `professional_vocab`
- `bank_frequent:12`

### 互斥策略

系统按作用域限制“同范围单任务运行”：

- 专业词汇：同一时间只允许 1 个活动任务
- 高频词：同一 `bank_id` 只允许 1 个活动任务

实现方式：

- 创建任务时先查找同 `scope_key` 的活动任务（`queued` 或 `running`）
- 若存在，直接返回该任务，不重复创建
- 若不存在，创建新任务
- 数据库层面对 `active_scope_key` 做唯一约束；活动态写入作用域值，终态改为 `NULL`

这样可以同时防住：

- 用户连续点击按钮
- 页面重复提交
- 多个请求并发命中创建接口

### 索引建议

新增索引：

- `active_scope_key` 唯一索引
- `status + next_run_at` 普通索引，用于 worker 取可执行任务
- `status + lease_until` 普通索引，用于回收超时任务
- `job_type + created_at` 普通索引，用于后续排查和管理

## 状态机设计

### 状态集合

- `queued`：已入队，等待 worker 执行
- `running`：worker 已抢占并正在执行
- `completed`：任务完成
- `failed`：任务失败且达到最大尝试次数

### 状态流转

- `queued -> running`
- `running -> completed`
- `running -> queued`：执行失败但还未达到最大尝试次数
- `running -> failed`：执行失败且已达到最大尝试次数

### 尝试次数语义

为避免歧义，本设计中：

- `max_attempts = 3` 表示**总执行尝试次数上限为 3 次，包含首次执行**
- 不是“首次执行 + 3 次额外重试”

即：

- 第 1 次执行失败：可继续
- 第 2 次执行失败：可继续
- 第 3 次执行失败：标记 `failed`

### stale running 任务回收

如果 worker 崩溃，任务可能停留在 `running`。

为避免任务永久卡死，worker 必须在执行中持续更新：

- `heartbeat_at`
- `lease_until`

约定：

- worker 抢占任务时，设置 `lease_until = now + 60 秒`
- 每处理完一批数据后续租一次，再次写入 `lease_until = now + 60 秒`
- 新 worker 在轮询时，若发现 `status = running` 且 `lease_until < now`，则将任务回收为 `queued`

回收任务时：

- 不额外增加 `attempt_count`
- 保留已有进度和错误信息
- 下次执行仍只扫描当前未翻译的数据

## 创建任务与重复点击语义

### 创建接口的行为

当用户点击按钮调用创建任务接口时：

1. 先计算当前范围内是否有待处理数据
2. 若无待处理数据：返回 `no_work` 响应，不创建任务
3. 若已有活动任务：直接返回该任务
4. 若没有活动任务：创建新任务并返回

### “重新点击继续翻译”的语义

用户再次点击时，不恢复旧任务，而是：

- 若同范围已有活动任务：复用该任务
- 若旧任务已完成或失败：新建一个新任务
- 新任务重新扫描当前数据库，只处理仍未翻译的数据

这样可以确保：

- 已成功翻译的数据不重复处理
- 旧任务状态保持稳定，便于追踪
- “继续翻译”语义清晰

## API 设计

新增独立任务中心蓝图：`/api/jobs`。

首阶段所有翻译任务接口都要求：

- 已登录
- 管理员权限

### 1. 创建任务

`POST /api/jobs`

请求体示例：

#### 专业词汇翻译

```json
{
  "job_type": "professional_vocab_translate"
}
```

#### 高频词翻译

```json
{
  "job_type": "bank_frequent_translate",
  "bank_id": 12
}
```

响应规则：

- 新建任务成功：`201`
- 已有活动任务：`200`
- 当前没有待处理数据：`200`

返回体统一包含：

- `result`：`created` / `existing` / `no_work`
- `job`：任务详情；`no_work` 时为 `null`
- `message`

### 2. 查询单个任务

`GET /api/jobs/<job_id>`

返回字段至少包括：

- `id`
- `job_type`
- `scope_key`
- `status`
- `attempt_count`
- `max_attempts`
- `progress_total`
- `progress_done`
- `success_count`
- `skipped_count`
- `last_error`
- `status_message`
- `payload`
- `created_at`
- `started_at`
- `finished_at`

### 3. 查询某范围当前活动任务

`GET /api/jobs/active`

查询参数：

- `job_type`
- `bank_id`（仅高频词任务需要）

返回规则：

- 有活动任务：返回 `job`
- 无活动任务：返回 `job: null`

此接口主要用于页面刷新后的状态恢复。

## worker 设计

新增独立 worker：`backend/workers/job_worker.py`。

### 主循环

worker 常驻运行，循环执行：

1. 回收超时的 `running` 任务
2. 查找一个满足以下条件的任务：
   - `status = queued`
   - `next_run_at is null` 或 `next_run_at <= now`
3. 抢占任务并改为 `running`
4. 按 `job_type` 调用对应处理器
5. 根据结果标记 `completed`、重新入队或 `failed`
6. 若当前无任务可执行，sleep 2 秒后继续轮询

### 分发器

新增 `backend/services/job_handlers.py`，按 `job_type` 分发到具体任务处理器：

- `handle_professional_vocab_translate(job)`
- `handle_bank_frequent_translate(job)`

### 任务处理器约束

所有处理器都必须遵守以下规则：

1. 只能处理当前 `job.payload_json` 和 `job.scope_key` 对应的数据
2. 每完成一批就提交一次数据库事务
3. 每完成一批就更新任务进度和心跳
4. 失败时抛出明确异常，由统一 job service 负责重试和状态转换

## 两类翻译任务的处理规则

### 1. 专业词汇批量翻译

任务类型：`professional_vocab_translate`

#### 待处理数据定义

扫描 `Vocabulary`，满足以下任一条件即为待翻译：

- `is_system = true` 且 `term_zh` 为空
- `is_system = true` 且 `definition` 非空但 `definition_zh` 为空

#### 批次大小

每批 `10` 条，延续当前专业词汇接口的批次规模。

#### 处理逻辑

1. 在任务首次开始执行时统计当前待翻译总量，写入 `progress_total`；后续重试不重置该值
2. 每轮查询下一批仍未翻译的专业词汇
3. 调用现有 AI 翻译服务批量翻译
4. 成功后立即 `commit`
5. 更新：
   - `progress_done`
   - `success_count`
   - `status_message`
   - `heartbeat_at`
   - `lease_until`
6. 若已无剩余待翻译数据，任务完成

### 2. 高频词批量翻译

任务类型：`bank_frequent_translate`

#### 待处理数据定义

扫描指定 `bank_id` 的 `BankWordFrequency`，满足以下条件即为待翻译：

- `term_zh` 为空
- 该词未被 `BankWordExclusion` 排除

#### 批次大小

每批 `100` 条，延续当前高频词接口的批次规模。

#### 处理逻辑

1. 在任务首次开始执行时统计该 `bank_id` 下待翻译总量，写入 `progress_total`；后续重试不重置该值
2. 每轮查询下一批仍未翻译且未被排除的高频词
3. 调用现有 AI 翻译服务批量翻译
4. 成功后立即 `commit`
5. 更新任务进度与心跳
6. 若已无剩余待翻译数据，任务完成

## 错误处理与重试策略

### 重试粒度

重试粒度为**任务级**，不是单条记录级。

即：

- 某次执行中，前面已经成功提交的批次保留
- 当前失败批次所在的这次执行结束
- 任务进入下一次尝试
- 下次尝试重新扫描“当前仍未翻译”的数据继续跑

### 重试次数

- `max_attempts = 3`
- 第 3 次执行仍失败，则标记 `failed`

### 重试间隔

为了避免连续瞬时打爆上游 AI 接口，失败后采用固定退避：

- 第 1 次失败后：`next_run_at = now + 15 秒`
- 第 2 次失败后：`next_run_at = now + 15 秒`
- 第 3 次失败后：终止任务，不再重试

本阶段不引入指数退避，保持实现简单和可预测。

### 错误信息

失败时记录：

- `last_error`：保留错误摘要，供页面展示
- `status_message`：例如“第 2/3 次执行失败，15 秒后自动重试”

错误信息需尽量短且面向排查，不直接堆叠超长堆栈到前端页面。

## 前端交互设计

本阶段不引入 WebSocket 或 SSE，使用轮询即可。

### 统一前端行为

无论是专业词汇还是高频词，前端统一采用：

1. 点击按钮时调用 `POST /api/jobs`
2. 若返回 `created` 或 `existing`，保存 `job_id`
3. 以 2 秒一次的频率轮询 `GET /api/jobs/<job_id>`
4. 页面初始化时调用 `GET /api/jobs/active` 恢复当前范围的活动任务
5. 任务完成或失败后停止轮询，并刷新列表与未翻译计数

### 页面刷新恢复

以下页面刷新后都要能恢复任务状态：

- `VocabularyView.vue` 中的专业词汇区域
- `VocabularyView.vue` 中的高频词区域
- `FileUpload.vue` 导入成功后的高频词翻译状态

### UI 文案

为了提升文档性和可用性，界面增加明确提示：

#### 默认说明

- “后台异步翻译，刷新页面不会中断”

#### 任务运行中

- “任务正在后台执行，可离开页面后稍后回来查看”
- 展示：已处理数量、总数量、当前状态、当前尝试次数

#### 自动重试中

- “任务执行失败，系统将在 15 秒后自动重试（第 2/3 次）”

#### 最终失败

- “任务已自动执行 3 次仍失败，可重新点击继续翻译剩余未翻译内容”

#### 成功完成

- “任务完成，已自动刷新未翻译数量”

### 旧接口迁移策略

本阶段前端停止使用以下同步式批量翻译接口：

- `/api/vocab/professional/batch-translate`
- `/api/banks/<bank_id>/translate-frequencies`

实现层面将批量翻译核心逻辑下沉到 job handler / service，避免前端继续依赖同步循环接口。

是否保留上述旧接口对外暴露不是本次核心目标；首阶段要求至少做到：

- 新前端不再调用它们
- 新后台任务实现不再依赖“由前端循环驱动”

## 文件与职责拆分

### 后端

- `backend/models.py`
  - 新增 `BackgroundJob` 模型
- `backend/app.py`
  - 注册 jobs blueprint
  - 运行时确保新表存在
- `backend/routes/jobs.py`
  - 创建任务
  - 查询单个任务
  - 查询活动任务
- `backend/services/job_service.py`
  - 任务创建、互斥、抢占、续租、完成、失败、回收、重试
- `backend/services/job_handlers.py`
  - 两类翻译任务的具体处理逻辑
- `backend/workers/job_worker.py`
  - 常驻 worker 主循环

### 启动与部署

- `scripts/start-worker.sh`
  - 本地/生产统一 worker 启动入口
- `deploy/systemd/quiz-app-worker.service`
  - 生产环境 worker 服务定义

### 前端

- `frontend/src/views/VocabularyView.vue`
  - 改为创建/恢复后台翻译任务
  - 展示任务状态、进度、失败提示
- `frontend/src/components/FileUpload.vue`
  - 导入成功后创建高频词翻译任务，而不是前端循环调用同步接口

如有必要，可抽出一个轻量 composable（如 `useBackgroundJob.js`）复用轮询和恢复逻辑，但这不是硬性要求。

## 安全与权限

本阶段所有翻译任务都限定为管理员可创建、管理员可查询。

原因：

- 两类批量翻译本来就是管理员域能力
- 任务会修改共享词汇数据
- 先按现有权限模型落地，避免把通用任务中心提前做成复杂的多租户任务系统

## 验证方案

### 自动化测试

重点新增后端 pytest 覆盖：

1. 创建同范围任务时返回已有活动任务
2. 无待处理数据时返回 `no_work`
3. worker 能执行专业词汇翻译任务并更新终态
4. worker 能执行高频词翻译任务并更新终态
5. 执行失败后能自动重试，达到第 3 次后标记 `failed`
6. 已成功提交的批次在后续失败时不会回滚丢失
7. stale `running` 任务可以被回收并重新排队
8. `GET /api/jobs/active` 能返回指定范围的当前活动任务

### 手工验证

1. 创建专业词汇翻译任务后刷新页面，进度仍能恢复
2. 创建高频词翻译任务后刷新页面，进度仍能恢复
3. 翻译执行中终止 worker，再重新启动 worker，任务能继续
4. 连续点击按钮不会生成多个同范围活动任务
5. 任务失败 3 次后页面显示可继续翻译剩余数据
6. 重新点击后只处理剩余未翻译数据，不重复翻译已完成数据

## 设计取舍说明

### 为什么不用前端 `while true`

因为前端页面不应承担后台任务编排职责。页面只适合发起任务和展示状态，不适合负责任务生命周期。

### 为什么不用 Flask 路由直接长时间同步执行

因为长时间同步执行会占住 Web 请求线程，难以支持稳定重试、任务恢复和跨页面持续执行。

### 为什么不用 Flask 进程内后台线程

因为进程内线程在重启、多实例和异常退出场景下可靠性较差，不适合作为“通用后台任务中心”的基础。

### 为什么当前阶段不用 Redis/Celery

因为本项目当前部署体量较小，优先选择无需新增基础设施的轻量方案；数据库任务表 + 独立 worker 已能满足本阶段稳定性要求。

## 后续扩展空间

本次任务中心完成后，后续可继续接入：

- 题目批量翻译
- 题目批量解析
- 导入后的异步后处理
- 更通用的任务管理页

但这些扩展不进入本次实现范围。
