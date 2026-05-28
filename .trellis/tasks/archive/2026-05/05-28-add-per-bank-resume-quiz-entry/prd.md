# Add Per-Bank Resume Quiz Entry

## Goal

在考试项目首页的题库列表中，为每个存在未完成普通答题会话的题库显示“继续答题”入口，让用户能直接从对应题库恢复上次进度，同时保持现有全局“继续上次答题”卡片不变。

## Requirements

- 全局“继续上次答题”卡片保持当前行为和位置不变。
- 每个题库卡片最多显示一个题库级“继续答题”入口。
- 题库级入口只在该题库存在未完成会话时显示。
- 题库级入口排除 `wrong_practice` 会话。
- 当同一题库存在多个未完成普通会话时，使用现有历史列表顺序中的第一个会话作为入口目标。
- 复用现有 `/quiz/history` 数据，不新增后端 API。
- 首页拉取历史数量从当前 20 提高到 100，降低题库级入口遗漏概率。
- 题库级按钮文案为“继续答题”。
- 题库级入口显示轻量进度信息：`已答 x/y｜模式`。
- 有未完成会话时，仍允许用户点击“顺序练习 / 随机练习 / 模拟考试”新开答题会话。

## Acceptance Criteria

- [ ] 当前考试项目存在未完成普通会话的题库卡片显示“继续答题”按钮。
- [ ] 点击题库卡片中的“继续答题”跳转到该会话的现有答题恢复路由。
- [ ] 没有未完成普通会话的题库卡片不显示题库级“继续答题”按钮。
- [ ] `wrong_practice` 未完成会话不会触发题库级入口。
- [ ] 全局“继续上次答题”卡片行为不变。
- [ ] 原有新开顺序练习、随机练习、模拟考试入口仍可用。

## Definition of Done

- 前端构建或可用检查通过。
- 若能启动应用，手动验证首页题库卡片继续入口的显示与跳转。
- 行为变更已记录到 `CONTEXT.md` 的领域语言中。

## Technical Approach

在 `frontend/src/views/HomeView.vue` 复用现有 `/quiz/history` 请求结果：

- 将历史拉取参数 `per_page` 提高到 100。
- 保留 `lastIncompleteSession` 的现有赋值逻辑，避免改变全局卡片行为。
- 新增 `incompleteSessionByBankId` 状态或计算映射，以 `bank_id` 为 key 保存每个题库第一个未完成且非 `wrong_practice` 的会话。
- 在题库卡片按钮组前按 `bank.id` 查找对应会话，存在时显示“继续答题”按钮和 `已答 x/y｜模式` 文案。
- 新增题库级跳转函数，复用 `currentExamPath(route, 'quiz', { sessionId })`。

## Decision (ADR-lite)

**Context**: 现有 `QuizSession` 绑定单个 `bank_id`，恢复答题能力已经由 `/quiz/history` 和 `/quiz/session/{session_id}` 支撑；当前缺口主要是首页只展示一个全局继续入口。

**Decision**: 本次只在题库列表中增加题库级继续入口，复用现有历史接口和答题恢复路由，不新增后端 API 或跨题库会话模型。

**Consequences**: 实现范围小、回归风险低；但受 `/quiz/history` 分页限制，超过拉取数量的历史未完成会话可能不会显示入口。本次将 `per_page` 提高到 100 作为低成本缓解，严格不遗漏留待未来专门 API 处理。

## Out of Scope

- 不新增后端 API。
- 不改变 `QuizSession` 单题库模型。
- 不实现跨题库或考试项目级混合答题恢复。
- 不阻止用户在已有未完成会话时新开练习。
- 不改变全局“继续上次答题”卡片行为。

## Technical Notes

- `frontend/src/views/HomeView.vue` 当前渲染全局继续卡片和题库列表。
- `frontend/src/views/HomeView.vue` 当前通过 `/quiz/history` 获取最近历史，并用第一个未完成非 `wrong_practice` 会话设置全局继续入口。
- `frontend/src/views/QuizView.vue` 已支持通过 `/quiz/session/{session_id}` 恢复未完成会话。
- `backend/app/api/routes/quiz.py` 的历史接口返回 `bank_id`、`mode`、`answered_count`、`total_questions`、`is_completed` 等前端所需字段。
- `CONTEXT.md` 已记录“继续答题入口”的全局入口与题库级入口含义。
