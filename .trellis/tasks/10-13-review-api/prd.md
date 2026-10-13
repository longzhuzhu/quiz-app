# 复盘详情 API 与统计口径统一

## Goal

让 `GET /quiz/session/{session_id}` 在会话**已完成**时返回可复盘的数据：按原场顺序的完整题目（含未答）、最终作答、判定与**当场正确答案**；同时统一本场正确率口径，并确保已完成会话的作答写入被后端拒绝。模拟考试**结束前**的隔离不能被新分支绕过。

## Background

父任务：`.trellis/tasks/10-13-quiz-review-retry`（Issue #63）。

现状（证据见父任务 `research/current-implementation.md`）：

- `session_detail` 只按 `mode == "exam"` 隐藏字段，**不区分完成态**（`backend/app/api/routes/quiz.py:554,571-575`）。这就是「模拟结果全部显示错误」的根因：前端对缺失的 `is_correct` 走错误分支（`frontend/src/views/QuizResultView.vue:62-64`）。
- 已完成会话不返回完整题目（`quiz.py:578-604` 仅在 `not session.is_completed` 时返回）。
- 答案查询无 `order_by`（`quiz.py:556`），而结果页按数组下标编号（`QuizResultView.vue:60,66`）——跳题、改答、随机模式会题号错位。
- 正确率统一为 `round(correct_count / max(answered_count, 1) * 100, 1)`（`quiz.py:416,468,617`），不分模式。
- `/quiz/answer` 已拒绝已完成会话（`quiz.py:279-280`），但缺少测试锁定。

## 依赖

**前置子任务：`10-13-snapshot-model`**（提供 `question_snapshot`、`final_answers` 列与写入逻辑）。开始前确认该子任务已合入，或至少确认列已存在且新会话会写入快照。

本子任务冻结**响应契约**，`10-13-review-ui` 与 `10-13-result-page` 依赖它。契约定稿后若需变更，必须同步通知这两个子任务。

## Requirements

### R1 — 按完成态分支的响应契约

`GET /quiz/session/{session_id}`：

**已完成（复盘态）** —— 返回完整题目列表：

- 元素按 `session.question_ids` 的**原场顺序**，包含始终未答的题。
- 每题字段：`id`、`index`（1-based 原场题号）、`question_type`、`content`、`options`、`user_answer`、`is_correct`、`correct_answer`、`status`（`correct` / `wrong` / `unanswered`）、`status_unknown`（bool）。
- 完成态的**模拟考试释放** `is_correct` 与 `correct_answer`（修复根因）。
- `has_snapshot`（bool）：会话是否有本场快照。

**进行中** —— 保持现有行为：返回完整题目供刷新恢复，模拟考试继续隐藏 `is_correct`、`correct_answer`、解析与可推导成绩的统计。**不得**因新增分支而提前暴露。

### R2 — 统计口径

设总题数 T、已答数 A、正确数 C：错误数 E = A − C，未答数 U = T − A，C + E + U = T。

- 普通练习本场正确率 = C / A；模拟考试 = C / T；`accuracy_basis` 标明用的是 `answered` 还是 `total`。
- 分母为 0 时返回 `0.0`，不产生 `NaN` 或除零异常。
- 百分比保留一位小数，末尾 `.0` 可省略。
- 响应同时给出 `wrong_count`、`unanswered_count`。

替换 `quiz.py` 三处调用点：`/finish`（416 行）、`/history`（468 行）、`session_detail`（617 行）。

### R3 — 「错误」的定义与旧记录

**保存的 `is_correct` 为 `false` 才是错误。** 缺失字段、请求失败或旧记录不完整都**不是**错误结果。

旧会话（无快照）或记录不完整时：

- 保留可核实的用户选择与已保存判定，**不**用当前正确答案重新判分。
- 无法确认的状态置 `status_unknown=true`，前端据此显示「未知／不可用」。
- 保留原场题号（`index`），不因缺失而重排。

### R4 — 只读写入拒绝

`/quiz/answer` 对已完成会话的拒绝保持有效并**补测试锁定**。前端隐藏按钮不是约束，后端拒绝才是。

### R5 — 历史列表口径同步

`/quiz/history` 的比例文案使用与 R2 一致的分母（模式决定）。首页 `recent-accuracy`、练习日、当日作答量口径**不变**。

## Acceptance Criteria

- [ ] 已完成模拟考试会话的响应含每题 `is_correct` 与 `correct_answer`，不再被模式隐藏。
- [ ] 进行中模拟考试会话的响应仍不含 `is_correct`、`correct_answer`、解析，也不含可推导成绩的统计。
- [ ] 已完成会话返回的题目按 `question_ids` 顺序，含未答题（`status="unanswered"`、无 `user_answer`）。
- [ ] 跳题、改答、随机模式下 `index` 与原场题号一致，不按答案数组下标编号。
- [ ] 模拟 10 题 7 对 3 错：`correct_count=7`、`wrong_count=3`、`unanswered_count=0`、`accuracy=70.0`、`accuracy_basis="total"`。
- [ ] 10 题只答 2 题全对：普通练习 `accuracy=100.0`（basis `answered`）、模拟 `accuracy=20.0`（basis `total`），两者均为 2 对 0 错 8 未答。
- [ ] 未提交任何答案就结束：不抛异常，`accuracy=0.0`，`unanswered_count == total_questions`，错误数为 0。
- [ ] 旧会话（`question_snapshot IS NULL`）返回 `has_snapshot=false`，保留已保存判定，`status_unknown` 正确置位，不重新判分。
- [ ] 已完成会话提交答案返回错误，记录不被修改。
- [ ] `/quiz/history` 的比例与 `session_detail` 口径一致。
- [ ] 首页 `recent-accuracy` 与练习日相关接口的行为未改变。

## 非目标

不实现原题重做端点（属 `10-13-retry-api`）；不改前端；不新增数据库列（属 `10-13-snapshot-model`）；不修改首页滚动正确率、练习日、当日作答量口径；不新增多次尝试轨迹。

## Notes

- 前端复盘页与完成页都消费本契约，定稿后变更需通知 `10-13-review-ui` 与 `10-13-result-page`。
- 详细设计见父任务 `design.md` 第 4.3、4.4、4.5 节。
