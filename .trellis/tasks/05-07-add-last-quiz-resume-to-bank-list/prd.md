# 题库列表增加上次答题与继续答题

## Goal

在首页题库列表区域展示当前用户全局最后一次答题记录，并在该记录未完成时提供继续入口，让用户能从上次答题进度恢复，而不是只能重新开始练习。

## What I already know

* 用户希望在题库列表增加“上次答题”功能。
* 需要展示用户最后一次答题记录。
* 需要支持进入并继续上次答题记录。
* 首页题库列表位于 `frontend/src/views/HomeView.vue`。
* 前端答题状态管理位于 `frontend/src/stores/quiz.js`。
* 答题页 `frontend/src/views/QuizView.vue` 已在挂载时调用 `/api/quiz/session/<session_id>`，未完成 session 会恢复 `session`、`questions`、已答答案、导航状态，并定位到第一道未答题。
* 后端 `backend/routes/quiz.py` 已提供 `/api/quiz/session/<session_id>`，会校验当前用户权限；未完成 session 会返回完整题目列表用于恢复。
* 后端 `backend/routes/quiz.py` 已提供 `/api/quiz/history`，该接口按 `created_at desc` 返回当前用户全局答题历史，理论上可用第一条作为最后一次答题记录。
* 用户已确认不需要每个题库各展示一条上次记录，只需要全局最后一次答题记录。
* `QuizSession` 已有 `bank_id`、`mode`、`total_questions`、`answered_count`、`correct_count`、`is_completed`、`created_at`、`completed_at` 字段，可支持“上次答题”摘要。

## Assumptions (temporary)

* “继续上次答题记录”只展示并继续未完成的全局最后一次答题记录。
* 如果全局最后一次记录已完成，MVP 不展示上次答题模块，也不回退到更早的未完成记录，以避免“最后一次记录”和“继续入口”语义不一致。
* 数据应只返回当前登录用户自己的 session 摘要，继续详情仍复用现有 `/api/quiz/session/<id>` 权限校验。

## Open Questions

* 无。

## Requirements

* 首页题库列表区域仅在当前用户全局最后一次答题记录未完成时展示“继续上次答题”模块。
* 模块至少包括题库名称、模式、已答/总题数、正确率、开始时间。
* 点击继续后进入 `/quiz/<session_id>`，由现有答题页恢复会话。
* 如果全局最后一次记录已完成，隐藏该模块。
* 不在每个题库卡片分别展示上次答题记录。

## Acceptance Criteria

* [ ] 首页能获取当前用户全局最后一次答题记录。
* [ ] 全局最后一次记录未完成时，首页题库列表区域展示题库、模式、进度、正确率和开始时间。
* [ ] 全局最后一次记录未完成时显示“继续答题”按钮，点击后进入对应 session 并恢复到未答题位置。
* [ ] 全局最后一次记录已完成、没有记录时隐藏“继续上次答题”模块；仍保留顺序练习、随机练习、模拟考试入口。
* [ ] 不同用户只能看到自己的最后答题记录，不能访问他人 session。
* [ ] 没有记录、空题库、已删除题库关联记录等边界不导致首页加载失败。

## Definition of Done

* 后端相关接口返回结构稳定并覆盖基础测试。
* 前端题库列表展示和继续入口可用。
* 构建通过；如涉及 UI，需要用浏览器验证首页展示与继续答题主路径。
* 不引入额外权限绕过或跨用户数据泄漏风险。

## Technical Approach

推荐复用或轻量扩展现有答题历史能力，获取当前用户按时间倒序的第一条全局 session 摘要。前端在 `HomeView.vue` 的题库列表上方或列表区域内渲染“上次答题”卡片，继续操作直接 `router.push(`/quiz/${session.id}`)`。

## Decision (ADR-lite)

**Context**: 首页题库列表只需要当前用户全局最后一次答题记录，不需要按题库聚合。

**Decision**: 不在每个题库卡片展示记录；优先复用 `/api/quiz/history?per_page=1` 或新增语义更明确的单条最近记录接口，前端只渲染一个“上次答题”模块。

**Consequences**: 范围更小、界面更清晰；如果未来要按题库展示进度，需要另行设计聚合接口。

## Out of Scope (explicit)

* 不重做答题页恢复机制。
* 不实现多设备实时同步或自动保存之外的新机制；答题提交仍沿用现有 session/answer 数据。
* 不修改答题模式逻辑、计分规则或错题规则。
* 不新增“查看已完成历史详情”的入口，除非后续明确纳入范围。

## Implementation Plan

* 在 `HomeView.vue` 挂载时并行请求题库、错题统计、近期正确率和 `/quiz/history?page=1&per_page=1`。
* 将历史第一条作为全局最后一次记录，仅当 `is_completed === false` 时保存为可展示的继续记录。
* 在题库列表区域上方新增轻量卡片，展示题库、模式、进度、正确率、开始时间，并提供“继续答题”按钮。
* 点击继续按钮直接跳转 `/quiz/<session_id>`，沿用 `QuizView.vue` 的恢复逻辑。
* 运行前端构建；如环境可用，启动开发服务器并用浏览器验证首页继续入口和恢复主路径。

## Technical Notes

* `frontend/src/views/HomeView.vue`: 题库列表卡片与开始练习按钮。
* `frontend/src/views/QuizView.vue`: 已支持 session 恢复，未完成 session 会载入题目、答案和第一道未答题位置。
* `frontend/src/stores/quiz.js`: `startQuiz` 只创建新 session；继续可不经过 store 方法，直接进入路由后由页面拉取详情。
* `backend/routes/banks.py`: `list_banks()` 当前返回 `bank_to_dict()`。
* `backend/routes/quiz.py`: `history()` 返回用户所有 session；`session_detail()` 支持未完成 session 恢复。
* `backend/models.py`: `QuizSession` 足够支撑上次记录摘要。
