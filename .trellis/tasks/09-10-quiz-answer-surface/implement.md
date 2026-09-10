# 答题面：更新解析、复制图标、更正答案 — 执行计划

## 实施顺序

分四段。每段后端单测可先跑；前端段完成后再浏览器验收。

### 第 1 段：解析提示词脱钩、judged_answer、冲突段

- [ ] `backend/app/services/exam_service.py` — 新增 `EXPLANATION_INDEPENDENT_JUDGMENT_CONTRACT`；`build_explanation_system_prompt` 拼在 `EXPLANATION_OUTPUT_CONTRACT` 之后。不改 004 契约字面量。
- [ ] `backend/app/services/ai_service.py` — user 消息只发题干+选项；纠正消息不补库内答案。
- [ ] `validate_structured_explanation` — 要求 `judged_answer`；干扰项期望集合改用认定 key；库内 `correct_answer` 不参与这项校验。
- [ ] `compose_explanation_zh(result, question)` — 认定与库内不一致时文首插入 `【答案冲突】` 固定段。
- [ ] `backend/tests/test_explanation_prompt_structure.py` — 004 NEW 改为锁 `persona + EXPLANATION_OUTPUT_CONTRACT`；组装全文含 `judged_answer` 且 user 侧用例不出现库内答案。
- [ ] `backend/tests/test_ai_explanation_refresh.py` — 冲突不重试、不掰正文；一致时无冲突段；缺 `judged_answer` 走纠正重试。

验证：`cd backend && python -m pytest tests/test_explanation_prompt_structure.py tests/test_ai_explanation_refresh.py -q`

### 第 2 段：更正答案 API 与本场重判

- [ ] `backend/app/schemas/question.py` — `CorrectAnswerUpdateRequest`：`correct_answer`、`session_id: int | None`
- [ ] `backend/app/api/routes/questions.py` — `PUT /{question_id}/correct-answer`：校验选项 key、更新答案、按现逻辑清解析、按 design 重判本场、不碰错题本。
- [ ] 新增 `backend/tests/test_correct_answer.py`（与现有 AI 单测同样无 DB 也可把纯函数抽到 service；若测路由则沿用项目现有风格）。优先把「规范化比较、重判 delta、不碰 WrongAnswer」抽成可单测函数。

验证：`cd backend && python -m pytest tests/test_correct_answer.py tests/test_ai_explanation_refresh.py -q`

### 第 3 段：答题卡片 UI

- [ ] `frontend/src/components/ExplainButton.vue` — 「更新AI解析」→「更新解析」
- [ ] `frontend/src/components/QuestionCard.vue` — 复制图标移到「已答 n 次」旁；删除按钮行复制文字；更正答案+更正态+ConfirmDialog；解析冲突段随 `explanation_zh` 展示；预选逻辑。
- [ ] `frontend/src/views/QuizView.vue` — 传入 `sessionId`；处理 `answer-corrected`，更新本场结果映射与侧栏。

验证：见下方浏览器清单。`cd frontend && npm run build`

### 第 4 段：领域文档核对

- [ ] `CONTEXT.md` — 与 PRD 一致，不回退本会话已写入的术语和关系。

## 测试

后端（无 conftest、无真 DB 的纯单测风格与 `test_ai_explanation_refresh.py` 对齐）：

- user 消息不含「正确答案」
- 组装 prompt 含独立判断后缀和 `judged_answer`
- 004 NEW == `DEFAULT_EXPLANATION_PERSONA + EXPLANATION_OUTPUT_CONTRACT`（不含后缀）
- 006 persona tripwire 仍通过
- 校验：缺 judged_answer 失败；干扰项按认定而不是库内答案；模型认定 B、库内 C 时 distractors 覆盖 A/C 即可
- `explain_question`：冲突样本只调模型 1 次（结构一次通过），`explanation_zh` 以【答案冲突】开头且含知识点/干扰项正文
- 认定与库内相同则无冲突段
- 更正答案：相同答案无操作；不同则清解析；重判只改本场 is_correct / correct_count

前端无单测框架。浏览器：

1. 未显示解析时按钮为「AI 解析」；显示后为「更新解析」。错题本同样。
2. 复制图标在「已答 n 次」旁，按钮行无「复制」；桌面与窄屏都能点；模拟考试可复制。
3. 提交后更正答案出现；未提交 / 模拟考试不出现。
4. 更正态点选项不掉对错反馈；确认后对错与「正确答案: X」更新；刷新本场结果仍对。
5. 更正后解析消失；已答次数不变。
6. 更新解析后，若模型认定与题库不同，文首有冲突段；点更正答案预选 AI 认定项。

## 风险点与回滚

| 风险 | 处理 |
|---|---|
| 改 004 断言范围导致历史迁移测试语义漂移 | 只把「当前全文」改成「004 当时写入的 persona+契约」；004 old/new 字面量与 upgrade 映射不动 |
| 更正态误走改答 | `correctionMode` 短路 `toggleOption` 清反馈分支 |
| 误调 `/quiz/answer` 加重错次 | 专用端点，单测断言不创建/不 increment WrongAnswer |
| 冲突段文案被模型写进 explanation_zh 正文 | 服务端 compose 插入；不让模型写该段 |
| 模型 judged_answer 格式不稳 | strip、去尾点、大小写；仍失败走一次纠正 |

回滚：还原代码即可，无迁移。

## 起工前确认

- [ ] 规划摘要已获用户确认，且 `task.py start` 已把本任务翻成 `in_progress`
- [ ] 实现前读 `.trellis/spec/frontend/component-guidelines.md`、`hook-guidelines.md`、`quality-guidelines.md` 与 `.trellis/spec/backend/error-handling.md`、`quality-guidelines.md`
- [ ] 本地可登录并打开非模拟考试答题页；改答案路径需要当前用户是该考试项目所有者（现网即练习者本人）
