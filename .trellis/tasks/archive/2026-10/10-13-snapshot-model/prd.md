# 答题会话本场题目快照模型与迁移

## Goal

为 `QuizSession` 增加**本场题目快照**与**完成冻结**持久化，使已完成会话的复盘内容与本场判分依据不再随题库后续编辑漂移。本子任务只交付数据层与迁移；复盘接口与前端由后续子任务承担。

## Background

父任务：`.trellis/tasks/10-13-quiz-review-retry`（Issue #63）。本任务是其依赖链的起点。

现状（证据见父任务 `research/current-implementation.md`）：

- `QuizSession` 只存 `question_ids`（Text，JSON 字符串）与计数（`backend/app/models/quiz.py:12-44`），**没有题目内容快照**。
- 复盘详情实时读取当前 `questions` 表（`backend/app/api/routes/quiz.py:562-575`），题目被改或删后历史与当时成绩不一致。
- 删除单道题目会直接删除该题全部 `QuizAnswer`（`backend/app/api/routes/questions.py:186-191`），不修会话计数——已完成会话的判定会随题目删除而丢失。

## 依赖

**无前置子任务。** 本任务必须先于 `10-13-review-api`、`10-13-retry-api` 完成，因为它定义这两个子任务依赖的数据结构。

## Requirements

### R1 — 会话级题目快照

`QuizSession` 新增 `question_snapshot`（JSONB，nullable）。数组元素与 `question_ids` 同序，每题包含：

- `question_id`
- `question_type`
- `content`
- `options`（`[{"key": ..., "text": ...}]`）
- `correct_answer`（即**当场正确答案**）

**不含** `content_zh`、`explanation`、`explanation_zh`：翻译与 AI 解析不纳入冻结的判分依据（父任务 R1），按现有机制实时提供。

**不含** `order_index`：顺序由数组下标表达。

### R2 — 完成冻结

`QuizSession` 新增 `final_answers`（JSONB，nullable），形如
`{ "<question_id>": {"user_answer": "A", "is_correct": true} | null }`。

- 完成时写入，冻结每题最终选择与判定。
- 显式的 `null` 表示**该题未答**，与「字段缺失」区分。
- 未完成会话该列为 `NULL`。
- 存在的意义：删除单道题目会删除该题 `QuizAnswer`，冻结副本保证已完成会话的判定仍可读（父任务 R8）。

### R3 — 快照写入时机

- **创建会话**（`/quiz/start`、`/wrong/practice`）：按最终题目列表写入完整快照。
  - `/wrong/practice` 是容易遗漏的第二个入口；跨题库错题会话必须**逐题**取各自题目内容，不能只查 `first_bank_id`。
- **进行中更正答案**（`update_question_correct_answer`）：更新当前会话快照中该题的 `correct_answer`，与既有「重算当前会话该题对错」保持一致；**不动其他会话**。
- **完成**（`/quiz/finish`）：写入 `final_answers`。

### R4 — 迁移

新增 `backend/alembic/versions/012_*.py`（`down_revision = "011"`），新增 `question_snapshot`、`final_answers` 两列，均为 nullable，**不回填存量行**。`downgrade()` 可删列。

同时为 `WrongAnswer` 新增 `last_wrong_answer`（String(20), nullable）与 `last_wrong_session_id`（Integer, nullable），并在 `/quiz/answer` 判错分支写入本次 `user_answer` 与 `session_id`；改答答对时**不清空**（错误证据保留）。这两列供父任务 R6「最近一次错误答案」使用。

### R5 — 旧会话不回填

`question_snapshot IS NULL` 即「无快照」，这是父任务 R2 的兼容边界。**不得**用当前题库数据回填旧会话——那会把历史伪装成当时快照。

## Acceptance Criteria

- [ ] `question_snapshot`、`final_answers` 两列存在于 `quiz_sessions`；`last_wrong_answer`、`last_wrong_session_id` 存在于 `wrong_answers`。
- [ ] `alembic upgrade head` 在真实 PostgreSQL 上实际执行通过（不能只检查 import）。
- [ ] `alembic downgrade 011` 可执行且不报错。
- [ ] 新建顺序练习会话后，`question_snapshot` 元素数与 `question_ids` 一致、顺序一致、每题含五个必需字段。
- [ ] 新建随机／模拟／专项／错题练习会话同样写入快照；跨题库错题会话每题内容取自各自题库。
- [ ] 未完成会话 `final_answers IS NULL`；完成后每道题都有键，未答题值为 `null`。
- [ ] 完成会话后再修改题干、选项或正确答案，复查快照内容不变。
- [ ] 完成会话后再删除原题，`final_answers` 仍可读出该题判定。
- [ ] 进行中更正答案后，当前会话快照该题的 `correct_answer` 更新，其他会话快照不变。
- [ ] 旧会话（迁移前创建）`question_snapshot IS NULL`，未被回填。
- [ ] 答错时 `last_wrong_answer` 记录本次选择；同题后来答对不覆写该列。
- [ ] JSONB 字段以整字段重新赋值写入，不依赖就地 mutate（`.trellis/spec/backend/database-guidelines.md`）。

## 非目标

不实现复盘接口与前端页面；不新增多次尝试轨迹表；不做快照版本号或哈希比对；不回填旧会话；不改变题目、题库、考试项目的既有删除语义。

## Notes

- 模型改动后确认 `backend/app/models/__init__.py` 仍正确导出（`QuizSession`、`WrongAnswer` 已在导出列表，无新增模型类则无需改动）。
- 迁移必须遵守 `.trellis/spec/backend/database-guidelines.md` 的 JSONB 约定。
- 具体技术选型与字段语义见父任务 `design.md` 第 3 节。
