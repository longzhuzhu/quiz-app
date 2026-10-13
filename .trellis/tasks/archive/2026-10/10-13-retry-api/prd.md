# 原题原序重开答题会话 API

## Goal

新增端点，从**已完成的**原会话创建一场新会话，复用**全部**原题 ID、原顺序、原模式与题数，包含原场未答题；任一原题不可用则整场失败，不留部分会话。这修复「再来一次」重新抽题、丢失原题集合与题数的现状。

## Background

父任务：`.trellis/tasks/10-13-quiz-review-retry`（Issue #63）。

现状（证据见父任务 `research/current-implementation.md`）：

- 「再来一次」调用 `quizStore.startQuiz(bank_id, mode)`（`frontend/src/views/QuizResultView.vue:134`），只传两个参数，重新执行题库选题（`frontend/src/stores/quiz.js:11-21`），丢失原题集合、题数与考点范围。
- 跨题库错题会话的 `session.bank_id` 只是 `first_bank_id`（`backend/app/api/routes/wrong.py:114`），无法据此重建原题集合。

## 依赖

**前置子任务：**

1. `10-13-snapshot-model` —— 新会话需要写入自己的 `question_snapshot`。
2. `10-13-review-api` —— 复用其响应构造（原题当前内容、模式、题数）与既有会话响应格式，避免两套实现。

若 `10-13-review-api` 尚未完成，本任务至少要用到它的响应形态；开始前确认契约，否则新会话返回值会与结果页预期不一致。

**本任务冻结 `POST /quiz/retry` 契约**，`10-13-result-page` 依赖它。

## Requirements

### R1 — 端点与请求

`POST /quiz/retry`，body `{"session_id": <int>}`。

### R2 — 校验

按顺序：

1. 原会话存在 → 否则 404。
2. 属于当前考试项目（沿用 `_ensure_session_in_exam`）→ 否则 404。
3. 属于当前用户 → 否则 403。
4. `is_completed` 为真 → 否则 400（不能从未结束会话重开）。
5. `question_ids` 可解析且非空 → 否则 400，**不通过查询题库猜原范围**。

### R3 — 原题复用语义

- 复用**全部**原题 ID 与**原顺序**，包括原场未答题。
- 保留**原模式**（含 `exam`、`wrong_practice`、`topic`）与题数。
- 保留**仍有效的考点上下文**（`topic_id`）；考点已删除而题目仍有效时，保留原题集合照常创建。
  **不提示**「原考点已不可用」——`quiz_sessions.topic_id` 的外键是 `ondelete="SET NULL"`，
  考点删除后该列变 `NULL`，与「练未分类题目」同形，数据上无法反推；生产上恒为假的提示
  比没有提示更糟。详见下方「已知限制」。
- **不**按当前考点重新筛选，**不**重新抽题，**不**因错题已标记掌握而排除原题。
- 跨题库错题会话**逐题**复用，不能只查首个题库。
- 「原题」指成员与顺序，**不是**恢复题库旧版本：新会话使用这些原题**当前**可用的题干、选项与正确答案，并建立自己的新快照。

### R4 — 失败语义

任一原题已删除、不可用或不再可访问：

- **整场失败**，返回 400 并明确列出不可用题目。
- **不**跳过、**不**补抽、**不**自动恢复原题、**不**留下部分新会话（事务必须原子）。

### R5 — 新会话初始状态

- 答案为空、进度为起点、`answered_count = 0`、`correct_count = 0`、`is_completed = False`。
- 不复制旧选择、耗时或完成态。
- 不覆盖原会话。
- 在新提交发生前不增加作答统计（不写 `UserQuestionStat`、不写练习日）。
- 服务端校验用户、考试项目与每道题的可访问性；客户端**不能**靠提交任意题目列表跨项目或越权创建。

## Acceptance Criteria

- [ ] 从已完成的顺序练习会话重开：新会话题目 ID 列表与顺序与原会话**完全一致**。
- [ ] 原场有未答题：未答题同样包含在新会话中。
- [ ] 原场题库后来新增了额外题目：新会话**不**包含这些额外题目。
- [ ] 原考点成员已变化（题目增删或重新打标）：新会话题目集合不变。
- [ ] 模拟考试会话重开：模式仍为 `exam`，题数与原场一致。
- [ ] 跨题库错题练习会话重开：保留**所有**原题，不缩成首个题库；已标记掌握的题也在其中。
- [ ] `topic` 会话重开：保留 `topic_id`；原考点已删除时保留原题集合并照常创建（不提示原考点不可用，理由见 R3）。
- [ ] 任一原题已删除：返回 400 并列出不可用题目；数据库中**没有**新建部分会话。
- [ ] 原会话 `question_ids` 为 NULL 或为空：返回 400，不查询题库猜测范围。
- [ ] 未完成的原会话：返回 400。
- [ ] 原会话属于其他用户：返回 403，不返回任何题目内容。
- [ ] 原会话属于其他考试项目：返回 404。
- [ ] 新会话 `answered_count=0`、`correct_count=0`、`is_completed=false`、`final_answers IS NULL`，且写入了自己的 `question_snapshot`。
- [ ] 重开后原会话记录（`is_completed`、计数、`final_answers`）**未改变**。
- [ ] 重开不产生 `UserQuestionStat` 或练习日记录。
- [ ] 新会话首次加载、刷新、提交与原会话历史互不污染。

## 非目标

不实现前端入口与按钮（属 `10-13-result-page`）；不实现复盘页面（属 `10-13-review-ui`）；不恢复已删除题目；不复制旧作答；不新增多次尝试轨迹；不改变原会话内容。

## 已知限制

### 考点已删除无法提示（规格与实现一致，非静默降级）

原 R3 曾要求「考点已删除而题目仍有效时明确提示原考点已不可用」，实施与检查阶段判定在**当前模型下不可实现**：

- `quiz_sessions.topic_id` 外键为 `ondelete="SET NULL"`（`backend/app/models/quiz.py:25`）。考点被删除时
  PostgreSQL 把该列置为 `NULL`（已在真实 PostgreSQL 上实测），与「练未分类题目」的会话**同形**，
  数据上无法反推原考点是否存在过。
- 项目没有删除单个考点的 API（只有 `exams` 与 `bank_id` 两个 CASCADE 入口）。删考试项目会连同题库、
  会话一起删除，所以「考点消失但会话还在」只可能来自**父域考点被级联删除**。
- 生产库有 33 个带 `topic_id` 的会话，场景真实但罕见。

因此响应**不输出** `topic_unavailable` 这类标记：生产上恒为假，比没有信号更糟。考点仍有效时照常保留
`topic_id` 并返回 `topic_short_name`。

若后续确需该提示，须在 `question_snapshot` 或会话上冻结考点名——那属于 `10-13-snapshot-model`
的模型边界，需新开子任务并配套迁移。

**测试注意**：`quiz_sessions.topic_id` 的 `SET NULL` 只在 PostgreSQL 生效，SQLite 默认不强制外键。
`backend/tests/test_quiz_retry.py` 的夹具已开 `PRAGMA foreign_keys=ON`，并用
`test_retry_with_removed_topic_keeps_questions` 兼作金丝雀（关掉 PRAGMA 该用例立即失败）。

## Notes

- 设计要求见父任务 `design.md` 第 4.6 节。
- 端点不要求幂等，但前端需在请求期间禁用重复点击（属 `10-13-result-page`）。
