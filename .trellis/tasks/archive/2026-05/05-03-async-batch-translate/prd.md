# async-batch-translate

## Goal

将词汇批量翻译从同步阻塞模式改为异步后台任务模式，用户点击翻译后立即返回，后台 Worker 逐步执行，前端轮询进度，页面刷新后进度不丢失。

## What I already know

- 项目已有完整的 BackgroundJob 基础设施：模型、JobService（创建/认领/心跳/完成/重试）、Worker 进程、API 路由
- 已有 `professional_vocab_translate` 和 `bank_frequent_translate` 两种 job_type 及对应 handler
- Worker 进程 `job_worker.py` 支持 `--once` 模式和常驻轮询模式
- 当前前端批量翻译是同步循环：`while(true)` 调用 `/vocab/professional/batch-translate`，页面刷新后进度丢失
- 同样高频词汇翻译 `batchTranslateFrequent()` 也是同步循环模式

## Assumptions (temporary)

- Worker 进程需要与 FastAPI 一起启动（或作为独立进程）
- 前端需要新增轮询逻辑查询 Job 进度

## Decision (ADR-lite)

**Context**: 批量翻译当前是同步阻塞模式，页面刷新后进度丢失
**Decision**: 改为异步后台任务模式，利用已有 BackgroundJob + Worker 基础设施，前端轮询进度
**Consequences**: 需要独立启动 Worker 进程，前端需新增轮询逻辑；翻译不再阻塞页面操作

## Open Questions

(已全部解决)

## Requirements

1. **专业词汇批量翻译改为异步**：点击"批量翻译"按钮 → 调用 `POST /jobs` 创建后台任务 → 前端开始轮询进度 → Worker 逐步翻译
2. **高频词汇批量翻译改为异步**：同理，`POST /jobs` 创建 `bank_frequent_translate` 任务
3. **进度持久化**：翻译进度存储在 BackgroundJob 表中，页面刷新后可恢复显示
4. **防重复提交**：同一 scope 只允许一个活跃任务，已有任务时按钮显示进度
5. **错误处理**：翻译出错时任务重试（最多 3 次），最终失败时显示错误信息

## Acceptance Criteria

- [ ] 点击"批量翻译"后按钮立即变为进度状态，不再阻塞页面
- [ ] 翻译进度显示：已翻译 X / 总数 Y
- [ ] 页面刷新后，进度状态恢复显示（从 Job 表读取）
- [ ] 同一类型翻译不可重复创建（已有活跃任务时显示进度）
- [ ] Worker 进程可正常执行翻译任务
- [ ] 翻译完成后列表自动刷新
- [ ] 高频词汇翻译同样改为异步模式

## Definition of Done

- 功能验证通过
- 前后端代码一致性检查
- 不引入新的 bug

## Out of Scope

- 题目翻译（translate/explain）改为异步 — 这是独立功能
- Worker 自动启动机制 — 本阶段手动启动
- WebSocket 实时推送 — 轮询足够

## Technical Approach

### 后端

已有 `POST /jobs` 端点和 Worker handler，只需确保：
1. `POST /jobs` 对 `professional_vocab_translate` 和 `bank_frequent_translate` 类型正常工作
2. Worker 进程 (`job_worker.py`) 能正常 claim 和执行翻译任务
3. `GET /jobs/active` 返回当前活跃任务状态（含 progress_total/progress_done）

### 前端

1. `batchTranslate()` 函数改为：调用 `POST /jobs` 创建任务 → 开始轮询 `GET /jobs/active`
2. 页面加载时检查是否有活跃翻译任务，如有则恢复进度显示
3. 轮询间隔 3 秒，任务完成后停止轮询并刷新词汇列表
4. 同样改造 `batchTranslateFrequent()`

### Worker 启动

提供启动脚本 `run_worker.py`，与 FastAPI 独立运行。

## Technical Notes

- 已有模型：`backend/app/models/background_job.py`
- 已有服务：`backend/app/services/job_service.py`、`backend/app/services/job_handlers.py`
- 已有 Worker：`backend/app/workers/job_worker.py`
- 已有 API：`backend/app/api/routes/jobs.py`
- 前端文件：`frontend/src/views/VocabularyView.vue`
