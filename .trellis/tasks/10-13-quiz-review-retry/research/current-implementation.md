# 答题复盘现状调查（Issue #63）

日期：2026-10-13
分支：`feat/quiz-review-retry`（基于 `origin/main` = `324c2af`）
证据等级：源码与文档静态核查。另有纯内存 `MagicMock` 函数级检查（前序会话执行）验证已完成模拟会话仍缺 `is_correct`。**未执行浏览器端到端复现，未运行产品回归测试。**

## 1. 数据模型现状

`backend/app/models/quiz.py`

- `QuizSession`（12-44 行）：`user_id`、`bank_id`、`mode`、`topic_id`、`total_questions`、`answered_count`、`correct_count`、`is_completed`、`question_ids`（Text，JSON 字符串）、`created_at`、`completed_at`。
- `QuizAnswer`（47-72 行）：`session_id`、`question_id`、`user_answer`、`is_correct`、`answer_duration_ms`、`answered_at`；唯一约束 `(session_id, question_id)`。
- **没有题目内容快照。** 会话只存题目 ID 列表与作答记录，题干、选项、正确答案全部实时读取 `questions` 表。
- `Question`（`backend/app/models/question.py`）：`question_type`、`content`、`content_zh`、`options`（JSONB）、`correct_answer`、`explanation`、`explanation_zh`、`order_index`。

## 2. 后端接口现状

`backend/app/api/routes/quiz.py`

### `/quiz/start`（181-256 行）

- `is_exam = mode == "exam"`（192 行）。
- 随机/考试按 `func.random()` 排序（203 行），专项按随机且限定考点（201 行），其余按 `Question.order_index`（205 行）。
- 创建 `QuizSession` 时只写 `question_ids`（214-224 行）。
- 模拟考试不返回解析与 `ai_explanations`（230-244 行）。

### `/quiz/answer`（259-387 行）

- `with_for_update=True` 锁定会话（273 行）；已完成会话拒绝提交（279-280 行：`"答题已结束"`）。
- 题目必须属于会话 `question_ids`（282-284 行）。
- 判分：`user_answer.strip().upper() == question.correct_answer.strip().upper()`（298 行）。**判分依据取自当前题库，不是快照。**
- 同题重复提交覆盖记录并调整 `correct_count`（304-314 行）；首次提交递增 `answered_count`（325 行）。
- 答错时 upsert `WrongAnswer`（332-343 行）。
- 模拟考试响应只返回 `submitted`、耗时、计数（370-377 行），**不返回对错与正确答案**——进行中隔离是明确设计。

### `/quiz/finish`（390-418 行）

- 不要求全部题已答，直接置 `is_completed = True`（405-406 行）。
- 正确率不分模式：`round(correct_count / max(answered_count, 1) * 100, 1)`（416 行）。

### `/quiz/history`（421-478 行）

- 分页，按最后作答时间或创建时间倒序（446-449 行）。
- 同样使用「已答数为分母」的正确率（468 行）。

### `/quiz/session/{session_id}`（540-626 行）

- 权限与项目隔离：`_ensure_session_in_exam`（551 行）+ `session.user_id != user_id` 403（552-553 行）。
- `is_exam = session.mode == "exam"`（554 行）；**只按模式隐藏字段，不区分是否已完成**（571-575 行）。
- 答案查询无 `order_by`（556 行），输出顺序即数据库返回顺序。
- 只有未完成会话才返回完整 `questions`（578-604 行）；已完成会话**不返回完整题目列表**。
- 正确率仍按已答数为分母（617 行）。

### 其他

- `backend/app/api/routes/wrong.py`：`GET /wrong`（49-86 行）只返回当前题目内容与 `wrong_count`，**不返回 `user_answer`、`session_id`**；错题本以考试项目为边界，题库只是筛选（57-60 行）。`POST /wrong/practice`（89-150 行）可跨题库，`session.bank_id` 只是 `first_bank_id`（114 行）。
- `backend/app/api/routes/questions.py`：`PUT /{question_id}/correct-answer`（155-168 行）→ `update_question_correct_answer`（`backend/app/services/question_service.py:71`）只重算当前会话该题对错，不动错题本与其他会话。
- `backend/app/api/routes/questions.py:178-193` **删除题目时直接删除该题全部 `QuizAnswer`**，不调整 `QuizSession.question_ids`、`answered_count`、`correct_count`。
- `backend/app/services/exam_service.py`：`delete_bank_data`（217-248 行）删除题库时按题目子查询清 `QuizAnswer`，并按 `bank_id` 删除 `QuizSession`（228 行）；`delete_exam_data`（251-265 行）逐题库调用。项目删除边界见 `docs/adr/0002-exam-project-deletion.md`。

## 3. 前端现状

`frontend/src/views/QuizResultView.vue`

- 直接 `client.get('/quiz/session/:id')`，不走 store（118-126 行）。
- 统计：正确 = `correct_count`（47 行）；错误 = `answered_count - correct_count`（51 行）；**没有未答统计**。
- 详情列表：`max-h-64 overflow-y-auto`（59 行），题干 `truncate` 单行截断（66 行），无选项、无解析、不可展开。
- 只有三个按钮（76-80 行）：返回首页、查看错题（跳 `'wrong'`，即项目累计错题本）、再来一次。
- 「再来一次」调用 `quizStore.startQuiz(bank_id, mode)`（134 行），**只传两个参数**，丢失原题集合、题数、考点。
- 缺失 `is_correct` 时走错误分支渲染（62-64 行）——这就是「全部显示错误」的直接原因。
- 容器固定 `max-w-lg`（16 行）。

`frontend/src/stores/quiz.js`

- Actions：`startQuiz(bankId, mode, questionCount, topicId = null)`（11 行）、`submitAnswer`（23 行）、`finishQuiz`（35 行）、`nextQuestion`、`prevQuestion`、`reset`。
- **不存在 `fetchSessionDetail`。**

`frontend/src/views/QuizView.vue`

- 一题一页：只渲染 `questions[currentIndex]`（172 行）。
- 桌面左侧题号侧栏 `hidden md:block w-48`（38-99 行）；移动端底部 `md:hidden fixed bottom-14` 横向题号（102-111 行）。
- `loadSession`（262-288 行）：已完成会话直接 `router.replace` 到结果页（271-274 行）；无 `questions` 时回首页（282-284 行）。
- `restoreSessionState`（223-260 行）重建 `questionAnswerMap` / `questionResultMap` / `answerResults`。
- 模拟模式恢复时只标记 `{ submitted: true }`，不含对错（232-233 行）。
- 未在 `QuizView` 消费 `accuracy`。

`frontend/src/components/QuestionCard.vue`

- Props（131-141 行）：`question, currentIndex, total, hideProgress, initialAnswer, initialResult, examMode, answerCount, sessionId`。**无只读模式。**
- Emits（143 行）：`submit, next, prev, finish, translated, answer-corrected`。
- 已答后点击选项退回编辑态（280-283 行）。
- 「更正答案」显示条件：`answered && !examMode`（68 行）且 `!correctionMode`（81 行）。
- 提交/完成按钮：101-103 行；翻译与收藏 61-64 行；`QuestionExplanation` 在 `!examMode` 时渲染（94-95 行）。

`frontend/src/views/WrongAnswersView.vue`

- 折叠展开式只读展示（103-145 行）：题干、选项（正确项高亮，193-195 行）、翻译/收藏、`QuestionExplanation`。内联实现，**不是可复用组件**。
- 错题练习入口复用答题页（245-260 行）。

`frontend/src/views/HistoryView.vue`：已完成会话 `router-link` 到 `quizResult`（27 行）；消费 `s.accuracy`（34-51 行）。

`frontend/src/router/index.js`：`ExamQuiz` 与 `ExamQuizResult` 路由（16-17 行）。**无独立复盘路由。**

`frontend/src/utils/examRoutes.js`：`examPath` 支持 `quizResult` kind。

## 4. 关联机制（影响快照与辅助内容设计）

- **输入指纹**：`explanation_service.input_fingerprint(question)`（`backend/app/services/explanation_service.py:40-41`）基于 `input_snapshot`（31-37 行）= `content` + `question_type` + `options` 的 `key`/`text`。**不含 `correct_answer`。**
- `summaries_for_questions`（80-104 行）与 `_result_payload`（59 行起）用指纹判断解析是否仍适用于当前题目；题干、选项或题型变化即失效。
- **正确答案变更不影响指纹判定**，但 `update_question_correct_answer` 会 `clear_question_explanation`（`question_service.py:98`）。
- `QuestionExplanation`（`backend/app/models/question_explanation.py`）：`question_id` 外键 `ondelete="CASCADE"`，每题每模型一条。

## 5. 领域文档与决策

- `CONTEXT.md` 已收录：答题复盘（83-85 行）、本次错题（87-89 行）、未答题（91 行）、本场正确率（95-97 行）、本场题目快照（99-101 行）、当场正确答案（103-105 行）、原题重做（107-109 行）、最近一次错误答案（111-113 行）。
- `CONTEXT.md:288`：更正答案只在尚未结束、已提交、非模拟考试的答题卡片出现；已完成会话复盘与累计错题详情不提供。
- `docs/adr/0008-completed-quiz-snapshots.md`：新会话保存本场快照，完成后冻结；旧会话不回填伪造历史；原题重做任一题不可用则拒绝。
- `docs/plans/2026-10-13-quiz-review-retry-design.md`：完整规格与 15 条验收场景。
- 旧设计边界：`docs/plans/2026-03-04-quiz-redo-design.md` 的「最后一次作答生效」只适用未结束会话；`2026-03-01-ui-ux-redesign-*` 的结果页内嵌详情、完成页跳累计错题、同题库重新抽题规则已被替代。

## 6. 测试基础设施

### 后端

- `backend/tests/`：`pytest` 风格；`run_isolated_suite.py` 用临时 PostgreSQL（`postgres_support.isolated_postgres`）跑全量回归，不连接业务库。
- 相关既有测试：`test_quiz_answer_duration.py`（含 150-169 行「模拟过程中不泄露答案」、187-192 行「已完成会话拒绝提交」）、`test_quiz_resume_index.py`、`test_quiz_history_order.py`、`test_topic_question_selection.py`、`test_correct_answer.py`、`test_practice_day.py`。
- 在既有测试目录中**未发现**结果页复盘、完成后模拟对错释放、原题集合重开、快照冻结的测试。

### 前端

- `node --test`（`frontend/package.json` 的 `test` 脚本），无 vitest。
- E2E 基础设施：`frontend/tests/helpers/studyBrowser.js`（Vite + `agent-browser` 驱动真实浏览器）、`studyBackend.js`（`spawn` `.venv/bin/python` 启动隔离后端，等待 `/api/auth/me` 返回 401 判定就绪）。
- 样例：`frontend/tests/vocabularyStudyE2E.test.js` 演示「隔离 PostgreSQL + 真实后端 + 浏览器」的完整链路，含通过 `browser('eval', ...)` 直接断言 API 契约与权限状态码的做法。
- 既有 quiz 相关前端测试：`questionTimer.test.js`、`questionTimerPresentation.test.js`。

## 7. 迁移与配置

- `backend/alembic/versions/` 现有 11 个迁移，head 为 `011_multi_model_explanations.py`（`revision = "011"`）。
- 迁移风格参考 `009_quiz_answer_duration.py`：模块 docstring、`revision`/`down_revision`、`upgrade()`/`downgrade()`。
- `backend/alembic/env.py` 从 `app.core.config.settings` 取 `DATABASE_URL`，并 `from app.models import *` 注册全部模型。
- 新增模型必须在 `backend/app/models/__init__.py` 导出，否则 `Base.metadata` 与 autogenerate 不完整。

## 8. 已知缺口汇总（本任务要解决的）

1. 模拟考试完成后仍隐藏对错与正确答案 → 前端把缺失字段渲染成「答错」。
2. 已完成会话不返回完整题目，无法逐题复盘；结果页容器限制 + 题干截断。
3. 漏答不可见；答案输出顺序与 `question_ids` 不一致，结果页却按数组下标编号。
4. 「查看错题」跳项目累计错题本，不是本场错误题。
5. 「再来一次」重新抽题，丢失原题集合、题数、考点；跨题库错题会话无法只靠 `bank_id` 重建。
6. 正确率分母不分模式；普通练习与模拟考试共用 `answered_count` 分母。
7. 历史内容实时读取当前题库：改题干、改答案、删题目都会让历史与当时成绩不一致。
8. 删除题目会删除 `QuizAnswer` 但不修会话计数；已删除题目的历史无法还原。
