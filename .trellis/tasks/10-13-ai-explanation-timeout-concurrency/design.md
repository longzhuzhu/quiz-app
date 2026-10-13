# 技术设计：AI 解析超时与并发优化并移除历史解析展示

## 1. 关键约束与冲突分析

### 1.1 租约与超时的冲突（必须同解）

解析任务由 worker 领取时租约固定为 `DEFAULT_JOB_LEASE_SECONDS=180s`，执行期间**没有心跳续约**。而解析失败格式校验时会追加纠正消息再调用一次（`ai_service.py:619` 的 `for attempt in range(2)`），单题最坏耗时 = 2 × 调用超时。

| 调用超时 | 最坏单题耗时 | 与 180s 租约关系 |
|---------|------------|----------------|
| 60s（现状） | 120s | 安全 |
| 120s（目标） | 240s | **超过租约 60s，必被误判中断** |

租约过期的后果：`recover_stale_jobs`（`job_service.py:283`）对解析任务直接 `fail_job(..., "执行已中断，请手动重试")`，用户看到"失败"，而实际模型可能正在返回。**调大超时若不处理租约，反而制造新的失败**，因此 R2 第 7 条与 R1 必须同一变更落地。

**方案选择：按任务类型区分租约，而非引入解析心跳。**

- 备选 A（心跳续约）：`generate_structured_explanation` 内部是同步阻塞的 `httpx.post`，续约需额外线程或把请求改成异步，改动面大且引入并发复杂度。
- 备选 B（按类型区分租约，采用）：解析任务领取时使用 `EXPLANATION_JOB_LEASE_SECONDS = 360s`（120×2 + 120 余量）。改动局限在 `try_claim_job_by_id`，无需新线程。

代价：worker 崩溃时解析任务从 180s 延长到 360s 才被回收。解析任务本身就是"不自动重试、需手动重试"的语义，且租约过期只影响异常崩溃路径，可接受。

### 1.2 连接池容量冲突（必须同解）

解析任务持有**两条**数据库连接：

1. `process_one_job` 的 `SessionLocal()` session 连接；
2. `_acquire_explanation_slot`（`job_service.py:37`）为 pg advisory lock 单独开的 AUTOCOMMIT 连接。

10 并发 = 10 session + 10 slot = **20 条连接**。当前 `database.py:10-16` 为 `pool_size=5, max_overflow=10`，上限 15 → 第 6 个 worker 线程就会在 `db.get_bind()` 或 session 获取上阻塞，表现为任务莫名挂起。

**方案：`pool_size=10, max_overflow=20`（上限 30）。**

容量核对：API 与 worker 是独立进程，各持有独立连接池。`max_connections=100`，两进程最坏 30 + 30 = 60，留有余额。当前 API 进程实际占用 5~10 条，worker 复用同一默认值即可，不为两类进程分别配置（避免引入部署分支）。

### 1.3 超时值的传递路径

超时不可在 `call_ai_api` 内部按 scene 兜底，否则会改动其"默认 60s"的既有契约（已有测试 `test_ai_service_call_api_timeout.py` TC-1 锁定该默认值）。因此显式下传：

```
settings.AI_EXPLANATION_TIMEOUT_SECONDS (默认 120)
  └─ explanation_service.execute_explanation
       └─ generate_structured_explanation(..., timeout=...)
            └─ call_ai_api(..., scene="explain", timeout=timeout)
```

`generate_structured_explanation` 新增关键字参数 `timeout: float`，内部两次调用共用同一值。仅 `explain` 场景受益；`translate`、`smart_import` 保持既有超时（60s / 120s）不变。

### 1.4 历史解析移除的边界

移除范围限定为"界面展示 + 其接口可用性字段"：

| 位置 | 处理 |
|------|------|
| `explanation_service.read_explanations` 的 `has_legacy_explanation` | 删除字段 |
| `useQuestionExplanations.js` 的 `legacyAvailable` ref、赋值、导出 | 删除 |
| `QuestionExplanation.vue` 的 `<details>` 折叠块、按钮 `displayed` 条件、解构 | 删除 |

**不动**的遗留面（保留，避免范围蔓延）：

- `questions.explanation` / `questions.explanation_zh` 数据列，以及 `quiz.py` 在答题/会话接口里返回这两个字段——前端 `QuizView.vue`、`QuestionCard.vue` 仍在读写它们。
- `ai_service.explain_question` 与 `has_question_explanation`——被 `job_service.count_pending_items` 的 `ai_prewarm` 分支与既有测试引用。
- `invalidate_explanations` 清理旧文本的行为。

按钮文案影响：`displayed` 由 `models.some(m => m.result)` 单独决定。移除 `|| legacyAvailable` 后，仅当存在具名模型结果时按钮显示"更新全部解析"，否则显示"AI 解析"——与预期语义一致。

## 2. 变更点清单

### 后端

| 文件 | 变更 |
|------|------|
| `app/core/config.py` | 新增 `AI_EXPLANATION_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)`；`AI_EXPLANATION_CONCURRENCY` 默认 3 → 10 |
| `app/core/database.py` | `pool_size=10, max_overflow=20` |
| `app/services/ai_service.py` | `generate_structured_explanation` 新增 `timeout` 参数并透传 |
| `app/services/explanation_service.py` | `execute_explanation` 传入超时；`read_explanations` 移除 `has_legacy_explanation` |
| `app/services/job_service.py` | 新增 `EXPLANATION_JOB_LEASE_SECONDS=360`；`try_claim_job_by_id` 对解析任务使用该租约 |
| `app/workers/job_worker.py` | `DEFAULT_CONCURRENCY` 2 → 10 |

### 前端

| 文件 | 变更 |
|------|------|
| `composables/useQuestionExplanations.js` | 移除 `legacyAvailable` |
| `components/QuestionExplanation.vue` | 移除历史解析折叠块与相关绑定 |

### 测试

| 文件 | 变更 |
|------|------|
| `backend/tests/test_multi_model_explanation_api.py:275` | 移除 `has_legacy_explanation` 断言 |
| 新增超时与租约断言 | 解析调用超时 120s；解析任务租约长于最坏耗时 |

### 配置与文档

| 文件 | 变更 |
|------|------|
| `/etc/systemd/system/quiz-app-worker.service` | 增加 `Environment=JOB_WORKER_CONCURRENCY=10` |
| `backend/.env` | 增加 `AI_EXPLANATION_CONCURRENCY=10`（`JOB_WORKER_CONCURRENCY` 由 service 提供） |
| `README.md`、`docs/deployment.md` | 更新解析并发、超时、历史解析说明 |
| `CONTEXT.md` | 删除"历史解析单独折叠展示"的领域不变量与相关表述 |

## 3. 兼容性与回滚

- **向后兼容**：新增配置项均有默认值，旧 `.env` 不配置也能启动。降低并发只需改配置，无需回退代码。
- **部署顺序**：配置项与代码同版本发布。重启 worker 会让在途解析任务的租约不再续期，随后被 `recover_stale_jobs` 判为"执行已中断，请手动重试"——这是既有部署语义（`docs/deployment.md` 已声明），实施时需在重启前确认无在途解析任务。
- **回滚形状**：代码回滚需同时回滚 `.env` 与 systemd 配置；解析结果表结构未变更，无数据迁移，回滚不丢数据。
- **前端回滚**：历史解析折叠块移除属于纯展示删减，回滚只需重新构建旧产物。

## 4. 风险登记

| 风险 | 影响 | 缓解 |
|------|------|------|
| 租约延长掩盖 worker 卡死 | 崩溃任务多占 180s 才回收 | 解析任务本就需手动重试，且槽位在异常路径会释放；接受 |
| 10 并发打满上游模型配额 | 上游 429/限流 | 上游错误不自动重试、按失败展示；并发数可在 `.env` 下调 |
| 连接池上调后 PostgreSQL 连接紧张 | 其他客户端被拒 | 上限 60 < 100，且 `pool_pre_ping` 已开启回收空闲连接 |
| 移除 legacy 字段影响外部调用方 | 接口契约变更 | 该字段仅本仓库前端消费，已全量检索确认无其他调用点 |
