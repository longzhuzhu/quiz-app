# Vocabulary Background Job UI and Parallel Worker Design

## 背景

当前单词本后台任务中心已经支持：
- 专业词汇批量翻译后台化
- 高频词批量翻译后台化
- 页面刷新恢复任务状态
- 失败 3 次后终止，支持再次点击继续翻译剩余未翻译数据

但验收中暴露出三个具体问题：
1. 任务状态提示重复：后端 `status_message` 已经包含“已处理 X/Y”，前端又额外渲染了一次进度和尝试次数，导致信息重复。
2. 任务状态提示分成多行，阅读噪音较大。
3. 专业词汇与高频词汇任务不能并行：当前 worker 为单进程串行循环，导致不同卡片任务只能排队执行。

## 目标

在不引入 Redis / Celery 的前提下，完成以下行为修正：
- 专业词汇、高频词汇卡片的任务提示统一为单行展示。
- 去除重复状态信息，保留最关键的任务进度与重试信息。
- 允许不同 scope 的后台任务并行执行。
- 继续保持同一 scope 的互斥执行与任务复用语义。

## 非目标

本轮不处理以下内容：
- 不改动任务表模型与已有 API 语义。
- 不允许同一 scope 下多开任务。
- 不引入外部队列中间件。
- 不处理既有 `backend/test_high_frequency_vocab.py` 的基线失败。

## 用户确认的并行规则

采用规则 A：
- **允许并行**：专业词汇任务 与 高频词任务（不同 `scope_key`）
- **继续互斥**：同一 `scope_key` 仍然只允许一个活动任务

示例：
- `professional_vocab_translate` + `bank_frequent_translate(bank_id=1)` 可以同时运行
- `professional_vocab_translate` + `professional_vocab_translate` 不允许同时运行
- `bank_frequent_translate(bank_id=1)` + `bank_frequent_translate(bank_id=1)` 不允许同时运行

## 设计

### 1. 前端状态提示收敛为一行

`VocabularyView.vue` 中专业词汇与高频词汇的任务提示卡片改为统一格式化输出，不再拆成：
- 固定标题“后台异步翻译，刷新页面不会中断”
- `status_message`
- 独立的“已处理 / 第 N 次”行

改为单行文案：
- 运行中：`专业词汇翻译中 · 已处理 40/542 · 第 1/3 次 · 刷新页面不会中断`
- 等待中：`等待后台 worker 执行 · 已处理 0/542 · 第 0/3 次 · 刷新页面不会中断`
- 失败：`任务已自动执行 3 次仍失败，可重新点击继续翻译剩余未翻译内容`

实现原则：
- `failed` 状态继续复用现有失败文案追加逻辑。
- `queued/running` 不直接拼接后端 `status_message`，而是用前端 formatter 统一产出，避免与后端“已处理 X/Y”重复。
- 专业词汇卡片与高频词卡片共用同一格式化函数。

### 2. 后端 worker 支持有限并发

`job_worker.py` 从“单循环串行取任务”调整为“固定并发槽位 worker pool”。

约束：
- 默认并发数为 `2`。
- 通过环境变量配置，例如 `JOB_WORKER_CONCURRENCY`。
- 每个槽位重复执行：`recover stale -> claim next -> run job -> complete/requeue`。
- 仍复用数据库中的 `try_claim_job_by_id()` 原子 claim 语义，不新增额外锁。

这样可以保证：
- 不同 `scope_key` 的任务可同时被不同槽位 claim 并执行。
- 同一 `scope_key` 仍由 `active_scope_key` 和任务创建逻辑保证只有一个活动任务。

### 3. 运行与部署脚本

`scripts/start-worker.sh` 保持启动入口不变，只让其启动的新 worker 程序支持并发槽位。

默认部署行为：
- 不传环境变量时，worker 自动以并发 `2` 运行。
- 需要时可通过环境变量调整，例如：
  - `JOB_WORKER_CONCURRENCY=1` 回退到串行
  - `JOB_WORKER_CONCURRENCY=4` 增加并发槽位

### 4. 测试策略

#### 后端
新增/调整 worker 测试，覆盖：
- 不同 scope 的两个任务在并发 worker 下都能被处理完成。
- 单次 `process_one_job()` 现有语义保持不变。
- worker 主循环在并发模式下不会破坏重试与完成状态更新。

#### 前端
优先将状态文案格式化逻辑抽成独立纯函数，再做最小测试或可验证实现。
如果当前仓库缺少现成前端单测基建，则至少：
- 将 formatter 独立成局部纯函数，便于未来补测。
- 通过构建验证确保模板与脚本改动可编译。

## 影响文件

### 后端
- `backend/workers/job_worker.py`
- `backend/tests/test_background_job_worker.py`
- `scripts/start-worker.sh`（如需最小文档/参数说明调整）
- `README.md`（如需补充 worker 并发配置说明）

### 前端
- `frontend/src/views/VocabularyView.vue`
- 如有必要：`frontend/src/composables/useBackgroundJob.js`（仅在状态展示逻辑需要抽离时）

## 验证

最小验收标准：
1. 专业词汇卡片状态提示为单行，且不再出现重复“已处理 X/Y”。
2. 高频词卡片状态提示为单行，且不再出现重复“已处理 X/Y”。
3. 同时点击两个卡片的翻译按钮后，两个任务都能进入运行/排队并被并发处理，而不是严格串行等待。
4. 既有定向回归验证继续通过：
   - `pytest backend/tests/test_background_jobs_api.py backend/tests/test_background_job_worker.py backend/tests/test_bank_import_api.py -q`
   - `npm --prefix frontend run build`
