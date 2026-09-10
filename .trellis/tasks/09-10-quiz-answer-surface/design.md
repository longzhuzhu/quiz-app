# 答题面：更新解析、复制图标、更正答案 — 技术设计

## 架构与边界

三块独立改动，共用答题卡片，不改表：

1. **文案与复制**：只动 `ExplainButton` / `QuestionCard` 模板。
2. **更正答案**：所有者更新 `Question.correct_answer`，并只重判本场该题 `QuizAnswer` + `session.correct_count`。不走 `/quiz/answer` 全量提交。
3. **解析脱钩库内答案**：user 提示词去掉正确答案；JSON 增 `judged_answer`；干扰项校验改认模型认定；冲突由服务端写入展示文本文首。

预热仍走 `explain_question()`，自动获得新提示词与冲突段。

## 数据流

### 复制 / 更新解析

```
页眉图标点击 → 现有 copyQuestion()（题干+选项）
ExplainButton displayed=true → 文案「更新解析」→ 现有 POST /ai/explain { force: true }
```

### 更正答案

```
提交后点击「更正答案」
  → correctionMode=true
  → 预选：解析含【答案冲突】则用 AI 认定 key，否则用当前 result.correct_answer
  → 点选项只改 pendingCorrectKeys，不改 selectedAnswers / answered
  → ConfirmDialog 确认
  → PUT /api/questions/{id}/correct-answer
        { correct_answer, session_id }
  → 写 Question.correct_answer；若与旧值不同则 clear_question_explanation
  → 若 session 属于当前考试且已有该题 QuizAnswer：
        用已存 user_answer 与新 correct_answer 比，更新 is_correct
        按旧/新正确性调整 session.correct_count
        不碰 WrongAnswer / UserQuestionStat / answered_count
        刷新当天 accuracy snapshot（正确率读的是这些作答记录）
  → 返回 { correct_answer, is_correct, explanation, explanation_zh }
  → 卡片用返回值替换 result，清空 explainData；侧栏对错跟 questionResultMap
```

不得调用 `POST /quiz/answer`：同一题再提交会在仍错时再加 `wrong_count`（`quiz.py:295-306`）。

### AI 解析

```
explain_question
  → system = persona + EXPLANATION_OUTPUT_CONTRACT + EXPLANATION_INDEPENDENT_JUDGMENT_CONTRACT
  → user = 题目 + 选项   // 禁止「正确答案：」
  → JSON + validate_structured_explanation
        干扰项期望集合 = 全部 option key − judged_answer keys
        judged_answer 必填且 key 均存在于选项
  → 结构失败：现有一次纠正重试（仍不把库内答案写入纠正消息）
  → 结构通过：compose_explanation_zh(result, question)
        judged_answer 规范化后 != 库内正确答案 → 文首插入【答案冲突】段
        相等 → 不插入
  → 冲突不是校验错误，不占用重试
```

## 契约变更

| 端点 / 符号 | 变更 |
|---|---|
| `POST /api/ai/explain` 请求 | 不变 |
| `explain_question` user 消息 | 删除 `正确答案：{question.correct_answer}` |
| 平台 JSON | 增 `judged_answer`（字符串，逗号分隔 key） |
| `validate_structured_explanation` | 按 `judged_answer` 划对错选项，不再用 `question.correct_answer` 划干扰项 |
| `compose_explanation_zh(result, question)` | 冲突时前置固定段 |
| `PUT /api/questions/{id}/correct-answer` | **新增**。body：`correct_answer: str`，`session_id: int \| null`。考试项目上下文与现有改题相同。 |
| 现有 `PUT /api/questions/{id}` | 保留给题目管理整题编辑，本任务答题面不调用 |

### 更正答案请求 / 响应

```
Request:  { "correct_answer": "C", "session_id": 12 }
Response: {
  "correct_answer": "C",
  "is_correct": true,          # 本场该题；无 session 或尚未作答则为 null
  "explanation": null,
  "explanation_zh": null
}
```

校验：`correct_answer` 拆出的 key 非空、都属于该题选项；单选/判断恰好 1 个；多选至少一个。400 返回 `detail`。无操作（与当前值规范化后相同）返回当前答案，不清解析、不重判。

权限：`Depends(get_exam_context)`，与 `update_question` 相同。不另加 `require_admin`。

## Prompt 与 004 tripwire

`EXPLANATION_OUTPUT_CONTRACT` 字面量保持不动，以免改写 004 锁住的契约正文。

新增运行时后缀 `EXPLANATION_INDEPENDENT_JUDGMENT_CONTRACT`（要求独立判断、返回 `judged_answer`、干扰项相对该认定、禁止把外部给出的题库答案当已知条件）。`build_explanation_system_prompt` 拼在契约之后。

`test_migration_004_new_prompt_matches_current_service_constants` 改为断言 `004 NEW == persona + EXPLANATION_OUTPUT_CONTRACT`，不再等于「含后续后缀的当前全文」。004 锁的是当时写入值；006 仍锁 persona。不新增 Alembic：Profile 仍只存 persona，新规则全是运行时追加。

`DEFAULT_EXPLANATION_SYSTEM_PROMPT` 变为含后缀的组装结果。依赖 `endswith(EXPLANATION_OUTPUT_CONTRACT)` 的测试改为以新后缀结尾。

## 冲突段版式

常量 `SECTION_ANSWER_CONFLICT = "【答案冲突】"`。仅冲突时插入，且永远在文首：

```
【答案冲突】
题库答案：B
AI 认定：C

【题干拆解】
...
```

多选 key 按现网 `correct_answer` 惯例拼接（如 `A,C`），比较前 split+strip+大小写不敏感+排序。前端用固定前缀解析「AI 认定：」一行得到预选 key；解析失败则退回预选库内答案。不把冲突段做成第二个按钮。

存量解析没有该段 → 不标冲突，首次获取仍返回缓存。

## 前端

### ExplainButton

已显示时文案「更新解析」。错题本自动跟着改。

### QuestionCard 复制

页眉右侧「已答 n 次」旁放图标按钮（`ClipboardDocumentIcon`，无文字）。`aria-label="复制题目"`。按钮行删除复制。逻辑仍用 `copyQuestion()`。

### QuestionCard 更正答案

- 新 prop：`sessionId`（来自 `QuizView` 的 `quizStore.session.id`）。
- 对错反馈内、`正确答案: X` 同一行或紧下行放「更正答案」。
- `correctionMode`：开启时 `optionClass` 按 pending 新答案高亮，不按对错红绿；`toggleOption` 在该模式下只改 pending keys。
- 确认用现有 `ConfirmDialog`（`AdminQuestionsView.vue` 等同款），文案：「将正确答案从 B 改为 C？」
- 成功 toast：「答案已更正」。失败读 `detail`。
- emit `answer-corrected`，payload 含接口返回，供 `QuizView` 更新 `questionResultMap` / 侧栏对错。

模拟考试：现有 `v-if="answered && !examMode"` 反馈区本身不出现，按钮自然没有。

### QuizView

把 `session.id` 传入卡片；监听更正成功后写回 `questionResultMap[questionId]` 的 `is_correct` / `correct_answer`，并清 `explanation*`。

## 错误与事务

- 更正答案：校验失败 400；题目不属于当前考试 404。写答案与本场重判同一事务，`commit` 一次。
- 解析：结构失败路径不变（rollback、不写半成品）。冲突成功路径必须 `commit`。

## 兼容与迁移

- 无表结构变更，无新 Alembic。
- 旧客户端不传 `judged_answer` 的模型输出会校验失败并重试一次；两次都没有则生成失败，与现网不合格解析相同。
- 题目管理整题编辑行为保持：改 `correct_answer` 仍清解析。

## 权衡记录

- **专用 `PUT .../correct-answer` 而不是复用整题 PUT + 再提交**：避免走 `/quiz/answer` 误加错次；本场重判与改答案原子完成。
- **冲突写入 `explanation_zh` 而不是新列**：刷新、错题本、历史只要展示该字段就能看到冲突；预选靠固定版式解析。避免为本任务加列。
- **干扰项按模型认定校验**：否则模型按自己的判断写会被判不合格并重试，冲突永远出不来。
- **004 测试改锁「当时契约」而不是「当前全文」**：才能在不改 004 历史字面量、不写 Profile 迁移的前提下追加独立判断规则。

## 未决 / 已知风险

- 模型可能把 `judged_answer` 写成 `B.` 或中文「B」。校验前对 key 做 strip，去掉末尾 `.`；仍对不上选项则走纠正重试。
- 更正态与现网「提交后再点选项=改答」必须分模式，否则会清掉反馈。
- 更正后清空解析，用户需再点「AI 解析」；产品已接受不自动再生成。
