# 技术设计：答题复盘与原题重做

规格来源：`docs/plans/2026-10-13-quiz-review-retry-design.md`；现状见 `research/current-implementation.md`。

## 1. 设计目标

1. 已完成会话的复盘内容与本场判分依据**冻结**，不随题库后续编辑漂移。
2. 复盘详情按**原场顺序**返回完整题目，含始终未答的题。
3. 统计口径按模式取分母，正确／错误／未答三者可区分且合计等于总题数。
4. 「原题重做」复用原题成员与顺序，任一题不可用则整场失败。
5. 模拟考试**结束前**的隔离不被新接口绕过。

## 2. 领域词汇与既有约束

- 术语以 `CONTEXT.md` 为准：答题复盘、本次错题、未答题、本场正确率、本场题目快照、当场正确答案、原题重做、最近一次错误答案、「更正答案」。
- 「本场正确率」不得写成「准确率」，也不得与首页「滚动正确率」混用。
- `CONTEXT.md:288`：更正答案只在尚未结束、已提交、非模拟考试的答题卡片出现；已完成复盘与累计错题详情不提供。
- `docs/adr/0008-completed-quiz-snapshots.md`：快照 + 冻结；旧会话不回填伪造历史；重做任一题不可用则拒绝。
- `docs/adr/0002-exam-project-deletion.md`：删除项目仍清除项目历史与快照。
- 项目使用纯 JavaScript，不用 TypeScript（`.trellis/spec/frontend/index.md`）。

## 3. 数据模型设计

### 3.1 快照存放位置：为什么随 `QuizAnswer` 而不是单独一张表

每题快照只在该题有最终作答时才有内容吗？不是——**未答题也要在复盘里出现**。因此快照不能挂在 `QuizAnswer` 上（未答题没有 `QuizAnswer` 行）。

也不能把题干塞进 `QuizSession.question_ids` JSON：那会让「题目 ID 列表」这个已被多处消费的字段（`quiz.py:282,557,580`、`wrong.py:120`）变成异构结构，回归面过大。

**采用会话级 JSONB 快照数组**，与 `question_ids` 平行：

```python
# QuizSession 新增
question_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)
```

每个元素对应 `question_ids` 的同一序号：

```json
{
  "question_id": 123,
  "question_type": "single",
  "content": "...",
  "options": [{"key": "A", "text": "..."}],
  "correct_answer": "A"
}
```

- 不含 `content_zh`、`explanation`、`explanation_zh`：翻译与 AI 解析**不纳入冻结判分依据**（R1），按现有机制实时提供。
- 不含 `order_index`：顺序由数组下标表达，与 `question_ids` 一致。
- `nullable=True`：旧会话没有快照，这正是 R2 的兼容边界，不需要回填。

### 3.2 完成冻结

```python
# QuizSession 新增
final_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

完成时写入 `{str(question_id): {"user_answer": "A", "is_correct": true} | null}`。

为什么要冗余这一份，而不直接用 `QuizAnswer` 行？因为**删除单道题目会删除该题的 `QuizAnswer`**（`questions.py:186`），但不修会话计数（R8 要求删除题目不破坏已完成会话的快照）。冻结副本保证已完成会话的判定与最终作答在题目被删后依然可读。

- `null` 值显式表示「该题未答」，与「字段缺失」区分。
- 未完成会话该字段为 `NULL`，详情接口据此判断是否走复盘分支。
- JSONB 写入必须**整字段重新赋值**，不做就地 mutate（`.trellis/spec/backend/database-guidelines.md`「JSONB 字段写入：必须重新赋值」）。

### 3.3 需要新增的标记

`QuizSession.is_completed` 已存在（`models/quiz.py:30`），足够表达完成态。**不新增** `snapshot_version` 之类的字段：`question_snapshot is None` 就是「无快照」，这是单布尔判断，再加版本号是投机复杂度。

### 3.4 迁移

新增 `backend/alembic/versions/012_quiz_session_snapshots.py`（`revision = "012"`，`down_revision = "011"`）：

```python
def upgrade() -> None:
    op.add_column("quiz_sessions", sa.Column("question_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("quiz_sessions", sa.Column("final_answers", postgresql.JSONB(), nullable=True))

def downgrade() -> None:
    op.drop_column("quiz_sessions", "final_answers")
    op.drop_column("quiz_sessions", "question_snapshot")
```

两列均可空，存量行不受影响，无需回填。**必须实际执行 `alembic upgrade head` 验证**，不能只检查 import（迁移验证是硬要求）。

新增模型字段后，`backend/app/models/__init__.py` 无需改动（`QuizSession` 已导出）。

## 4. 后端设计

### 4.1 快照写入时机

- **创建会话时**（`/quiz/start`、`/wrong/practice`）：按最终题目列表写 `question_snapshot`。
- **进行中改答案**（`correct-answer`）：`update_question_correct_answer` 已重算当前会话该题对错（`question_service.py:71-116`）。规格要求「进行中现有更正答案同步更新当前会话该题的判分依据与对错」——因此该路径也要更新快照中对应题的 `correct_answer`。
- **完成时**（`/quiz/finish`）：写 `final_answers` 冻结每题的最终选择与判定。

`wrong/practice` 是快照写入的第二个入口，容易漏。跨题库错题会话的快照必须逐题收集各自题目内容，不能只查 `first_bank_id`。

### 4.2 快照内容来源与「当场正确答案」语义

快照的 `correct_answer` 取创建会话那一刻的 `Question.correct_answer`，即**当场正确答案**（CONTEXT.md:103-105）。题库后续修改不影响已冻结的复盘。

### 4.3 复盘详情响应契约

`GET /quiz/session/{session_id}` 按 `is_completed` 分两态：

**已完成（复盘）**：

```
{
  "session": { ..., "answered_count", "correct_count", "wrong_count", "unanswered_count",
               "accuracy", "accuracy_basis": "answered" | "total", "has_snapshot": bool },
  "questions": [ { "id", "index", "question_type", "content", "options",
                   "user_answer", "is_correct", "correct_answer", "status": "correct"|"wrong"|"unanswered",
                   "status_unknown": bool, ... } ]   // 按 question_ids 顺序，含未答
}
```

- `index` 为**原场题号**（1-based），筛选后不重编号。
- 完成态模拟考试**释放** `is_correct` 与 `correct_answer`（修复「全显示错误」根因）。
- `status_unknown`：旧会话记录不完整、无法核实时为 `true`。前端据此显示「未知／不可用」，不推断成错误或未答（R2）。
- `has_snapshot: false`：旧会话，前端显示「历史题目未保存快照，当前内容可能已变更」。

**进行中**：保持现有行为——返回完整题目供恢复答题，模拟考试继续隐藏 `is_correct`、`correct_answer`、解析（`quiz.py:599-603`）。**不得**因为新增复盘分支而提前暴露。

### 4.4 统计口径

统一到一个共享函数（建议放 `backend/app/services/`，供 `finish`、`session_detail`、`history` 复用）：

```python
def session_stats(total, answered, correct, mode):
    wrong = answered - correct
    unanswered = total - answered
    basis = "total" if mode == "exam" else "answered"
    denominator = total if basis == "total" else answered
    accuracy = round(correct / denominator * 100, 1) if denominator else 0.0
    return wrong, unanswered, basis, accuracy
```

- 分母为 0 时返回 `0.0`，不产生 `NaN` 或除零。
- 现有 `round(correct / max(answered, 1) * 100, 1)` 在三个调用点（`quiz.py:416,468,617`）全部替换。
- 首页 `recent-accuracy`（`practice_service.recent_accuracy_for`）口径**不变**（R7）。

### 4.5 只读写入拒绝

`/quiz/answer` 已有 `if session.is_completed: raise HTTPException(400, "答题已结束")`（`quiz.py:279-280`）。保持不变并补测试锁定。前端隐藏按钮是体验，后端拒绝才是约束（R3）。

### 4.6 原题重做端点

新增 `POST /quiz/retry`（body：`{session_id}`）：

1. 校验原会话存在、属于当前用户、属于当前考试项目、`is_completed` 为真 → 否则 404/403/400。
2. 读取 `question_ids`；为空或缺失 → 400 拒绝（不查题库猜原范围）。
3. 逐题校验存在且在项目内且可访问；任一不可用 → **400 并列出不可用题目**，不做部分创建。
4. 按原顺序、原模式、原 `topic_id` 创建新会话；`total_questions` = 原题数。
5. 写入新会话自己的 `question_snapshot`（取这些原题**当前**内容与正确答案，即「原题指成员与顺序，不是恢复题库旧版本」，规格 R4）。
6. `final_answers = NULL`、`answered_count = 0`、`correct_count = 0`、`is_completed = False`。
7. 返回新会话，前端跳转答题页。

幂等性：不要求幂等，但前端需在请求期间禁用重复点击（R4）。

### 4.7 累计错题的「最近一次错误答案」

`GET /wrong` 当前不返回 `user_answer`（`wrong.py:67-85`）。规格 R6 要求展示**最近一次错误答案**，并明确「不冒充最近一次作答」。

- `WrongAnswer` 表不存错误选择（`models/wrong.py`）。新增列存最近一次错误选择是最小改动：

```python
# WrongAnswer 新增
last_wrong_answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
last_wrong_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- 在 `/quiz/answer` 判错分支（`quiz.py:332-343`）写入本次 `user_answer` 与 `session_id`。**改答答对时不清空该列**——错误证据按规格保留（「不因后来答对而覆写该错误选择」）。
- `WrongAnswer.last_wrong_answer` 与「当前题库正确答案」可能对应不同题目版本（规格 R6 最后两点）。旧数据该列为 `NULL` 时前端不展示猜测的选择。
- **模拟考试隔离**：未结束模拟会话产生的错误证据不能通过累计错题提前暴露。`/wrong` 在返回 `last_wrong_answer` 时需排除「来源会话仍未完成」的记录。

这两列也放进 `012` 迁移。

## 5. 前端设计

### 5.1 只读呈现的复用方式

现状没有只读题目组件：`QuestionCard.vue` 无 `readonly` prop，且已答后点击选项会退回编辑态（`QuestionCard.vue:280-283`）；错题本的只读展示是内联实现（`WrongAnswersView.vue:103-145`）。

**不新增 `readonly` prop 到 `QuestionCard`**。理由：该组件的 props/emits 已被答题与错题练习两条链路消费（`QuizView.vue`、`WrongAnswersView.vue:254-260`），加只读分支会让「提交、更正答案、编辑态」等条件判断继续膨胀，回归面覆盖答题主流程。

**抽出独立只读组件** `frontend/src/components/ReviewQuestionCard.vue`：渲染题干、选项、最终选择、当场正确答案、判定标记、翻译与 AI 解析按钮、词汇收藏。无提交、无完成、无更正答案、无编辑态。

### 5.2 复盘页面

新增路由 `ExamQuizReview`：`/exams/:examSlug/quiz/:sessionId/review`（沿用 `examScoped` 与既有权限边界，遵守 ADR-0003/0004，不保留旧路由）。

页面沿用答题页的一题一页结构：桌面左侧题号侧栏、移动端底部题号导航、上一题／下一题。筛选（全部／正确／错误／未答）只影响**可见集合**，题号始终显示原场号。

- 「查看详情」从完成页进入本页，默认「全部」筛选。
- 「本次错题」进入本页并默认选中「错误」筛选——用一个 query 参数（如 `?filter=wrong`）表达，避免两套页面。
- 历史入口的已完成会话也指向本页（R7 的「同一套复盘体验」）。

`QuizView.vue` 现有行为「已完成会话 `router.replace` 到结果页」（`QuizView.vue:271-274`）保留；结果页再提供进入复盘的入口。

### 5.3 完成页

`QuizResultView.vue` 重做：

- 统计改为**正确／错误／未答**三列（当前错误数按 `answered_count - correct_count` 推导，且无未答项）。
- `accuracy` 直接消费后端新口径，不在前端重算分母。
- 四个按钮：查看详情、本次错题、再来一次、返回首页。
- 「再来一次」改调新端点 `POST /quiz/retry`，不再传 `bank_id + mode` 重新抽题。失败时保留原页并提示不可用题目（不跳走）。
- 移除内嵌的截断详情列表（`max-h-64` + `truncate`，`:59,66`），完整内容交给复盘页。

### 5.4 Store 与错误处理

`stores/quiz.js` 新增 `retryQuiz(sessionId)`；`startQuiz` 签名不变（它仍被题库页等入口使用）。

错误处理遵循现有分层：store 抛错、view catch 后 toast（`.trellis/spec/frontend/state-management.md`）。`QuizResultView` 现在直接调 `client.get` 而不走 store，改造成新增调用点时保持一致的既有风格即可。

## 6. 边界条件与兼容性

| 边界 | 处理 |
| --- | --- |
| 旧会话无快照 | `has_snapshot=false` + 兼容提示；已保存的选择与判定仍展示；不按当前正确答案重判 |
| 旧会话记录不完整 | 保留原题号，`status_unknown=true`，标「未知／不可用」；不推断为错误或未答 |
| 未提交任何答案就结束 | `A=0`、`C=0`；分母为 0 → 0%；全部未答；本次错题为空 |
| 普通练习未答任何题 | 0% 且明确标识「未作答」 |
| 题目在完成后被删除 | 有快照仍可复盘（`final_answers` 冻结）；重做整场失败 |
| 考点已删除但题目仍有效 | 重做保留原题集合，明确原考点已不可用，不改练其他考点 |
| 跨题库错题会话重做 | 逐题复用，不缩成首个题库，已掌握原题不剔除 |
| 模拟考试未结束访问复盘 | 服务端按 `is_completed` 判定，继续隐藏答案与对错；不能借新接口提前查看 |
| 清空答题历史 | 随 `QuizSession` 删除，快照与冻结副本一并清除 |
| 删除考试项目 | 走既有 `delete_bank_data` 路径（按 `bank_id` 删 `QuizSession`），快照一并清除，不改 ADR-0002 边界 |
| 并发重复点击重做 | 前端禁用；后端不依赖幂等，但不会创建部分会话 |

## 7. 测试设计

### 后端（`backend/tests/`，`pytest` + 隔离 PostgreSQL）

- 快照：创建会话写入完整快照；完成冻结；完成后改题干／选项／正确答案不影响复盘；删除题目后复盘仍可读。
- 复盘详情：已完成模拟考试**释放**对错与正确答案；进行中模拟**继续隐藏**；`questions` 按 `question_ids` 顺序含未答题；旧会话 `has_snapshot=false`。
- 统计：`C + E + U = T`；普通练习用已答分母、模拟用总题数分母；分母为 0 返回 0 不抛异常。
- 只读：已完成会话提交答案被拒（补测锁定既有行为）。
- 重做：原题原序原模式；跨题库逐题复用；任一题不可用整场失败且无部分会话；越权／跨项目拒绝；旧会话缺 `question_ids` 拒绝。
- 累加错题：`last_wrong_answer` 记录最近一次错误；后来答对不覆写；未结束模拟会话的错误证据不在 `/wrong` 泄露。
- 迁移：`alembic upgrade head` 在真实 PostgreSQL 上执行通过。

### 前端（`frontend/tests/`，`node --test` + `agent-browser`）

复用 `helpers/studyBrowser.js` 与 `studyBackend.js` 的「隔离 PostgreSQL + 真实后端 + 真实浏览器」链路：

- 模拟 10 题 7 对 3 错完成后：完成页 70%，复盘 7 对 3 错且正确答案非空（回归 Issue #63 原始症状）。
- 10 题只答 2 题全对：普通 100% / 模拟 20%，均显示 2 对 0 错 8 未答。
- 未结束模拟直接访问复盘入口：不能提前看到答案与对错。
- 复盘页：只读、无提交／完成／更正按钮、筛选保留原场题号。
- 再来一次：走 `/quiz/retry`，新场题数与原场一致。

## 8. 发布与回滚

- **发布**：迁移先于应用（新增可空列，向后兼容）；应用上线后新会话即具备快照能力，旧会话走兼容分支。无需数据回填、无需停机。
- **回滚**：应用回滚到上一版即停止写快照，`question_snapshot` / `final_answers` / `WrongAnswer` 两列成为无用列，不影响旧逻辑；需要彻底回滚时执行 `alembic downgrade 011` 删列。
- **风险点**：`session_detail` 是答题页恢复与结果页共用的接口，改契约时两处消费方必须同步，否则刷新恢复或结果页会白屏。这是本任务最大的回归风险，检查阶段必须以真实浏览器覆盖「未完成会话刷新恢复」与「已完成会话结果页」。

## 9. 明确不做

- 不新增多次尝试轨迹（不做 `QuizAnswerAttempt` 之类历史表）。
- 不重算其他会话的历史判定，不因新答案回填旧会话的 `is_correct`。
- 不给 `QuestionCard` 加只读模式，不重构错题练习已有的答题页复用。
- 不引入 `snapshot_version`、快照哈希比对等投机机制。
- 不修改首页滚动正确率与练习日、当日作答量口径。
