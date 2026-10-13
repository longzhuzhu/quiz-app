# 统一只读复盘页面

## Goal

新增只读复盘页面，让用户查看已完成会话的完整题干、选项、最终选择与**当场正确答案**，区分正确／错误／未答，并支持按状态筛选。沿用答题页的一题一页与题号导航，但不提供任何作答或改判操作。

## Background

父任务：`.trellis/tasks/10-13-quiz-review-retry`（Issue #63）。

现状（证据见父任务 `research/current-implementation.md`）：

- 没有复盘路由，没有只读题目组件。
- `QuestionCard.vue` 无 `readonly` prop，已答后点击选项会退回编辑态（`:280-283`），且始终渲染「提交答案」；「更正答案」在 `answered && !examMode` 时出现（`:68,81-84`）。直接复用会把作答与改判能力带进复盘。
- 结果页的详情是截断列表（`max-h-64` + `truncate`，`QuizResultView.vue:59,66`），无选项、不可展开。
- 错题本的只读展示是内联实现（`WrongAnswersView.vue:103-145`），不是可复用组件。

## 依赖

**前置子任务：`10-13-review-api`** —— 本页消费其已冻结的响应契约（`index`、`status`、`status_unknown`、`has_snapshot`、完成态释放 `is_correct` 与 `correct_answer`）。契约未定稿前不要开始对接。

同批的 `10-13-result-page` 也从完成页跳转到本页。两任务都改前端，**必须约定归属**：建议本任务负责新页面与新组件，`10-13-result-page` 拥有 `stores/quiz.js` 与 `utils/examRoutes.js` 的改动；若需新增路由常量或 store action，由本任务提出、`result-page` 落地，或明确只由一方改动该文件。

## Requirements

### R1 — 路由

新增 `ExamQuizReview`：`/exams/:examSlug/quiz/:sessionId/review`，`meta: { auth: true, examScoped: true }`。

遵守 `docs/adr/0003-url-exam-slug-and-active-exam.md` 与 `0004-no-legacy-routes-for-multi-exam.md`：沿用 exam slug，不保留旧路由。

### R2 — 只读题目呈现

新增独立组件 `frontend/src/components/ReviewQuestionCard.vue`：

- 渲染题干（完整，不截断）、选项、最终选择、当场正确答案、判定标记。
- **不**渲染：提交答案、下一题（作答意义上的）、完成答题、更正答案；**不**提供编辑态——点击选项不改变任何状态。
- **保留**：翻译按钮、AI 解析、词汇收藏。
- 未答题显示「未答」且不显示用户选择，**不**显示「回答错误」。
- 最终选择与当场正确答案在视觉上可区分。

**不给 `QuestionCard.vue` 加 `readonly` prop。** 该组件的 props/emits 已被答题与错题练习两条链路消费，加只读分支会让既有条件判断继续膨胀，回归面覆盖答题主流程。

### R3 — 一题一页与题号导航

沿用答题页结构（参考 `frontend/src/views/QuizView.vue:36-140`）：

- 桌面：左侧题号侧栏。
- 手机：单列 + 可访问的底部题号导航。
- 上一题／下一题。
- 长题干与选项完整可读，**不被固定导航遮挡**。

### R4 — 筛选

支持全部／正确／错误／未答四种筛选：

- 筛选只改变**可见集合**，题号始终显示**原场题号**（来自响应的 `index`），**不按筛选数组重新编号**。
- 通过 query 参数表达初始筛选，使「本次错题」可直达错误筛选（如 `?filter=wrong`）。
- 筛选结果为空时展示明确空状态；**不得**跳到累计错题本补内容。

### R5 — 旧会话兼容提示

- `has_snapshot === false`：显示「历史题目未保存快照，当前内容可能已变更」。
- `status_unknown === true`：该题显示「未知／不可用」，**不**推断成错误或未答。
- 记录不完整时保留原场题号占位。

### R6 — 只读约束

页面不发起任何改变作答状态的请求：不调 `/quiz/answer`，不调 `/questions/:id/correct-answer`。后端拒绝是最终约束，前端不得提供入口。

## Acceptance Criteria

- [ ] `/exams/{slug}/quiz/{sessionId}/review` 可访问；未登录跳登录，跨项目 slug 按既有守卫处理。
- [ ] 已完成会话的复盘页完整渲染题干与选项，无截断。
- [ ] 页面上**没有**「提交答案」「完成答题」「更正答案」按钮。
- [ ] 点击任意选项不改变选中状态、不发起请求。
- [ ] 保留翻译、AI 解析与词汇收藏功能。
- [ ] 未答题显示「未答」，不显示用户选择，不显示为错误。
- [ ] 桌面显示题号侧栏，手机显示题号导航；上一题／下一题可用。
- [ ] 长英文题干与多选题在桌面与手机均可完整阅读，不被固定导航遮挡。
- [ ] 四种筛选可用；筛选后题号仍为原场题号，不重新编号。
- [ ] `?filter=wrong` 直达错误筛选。
- [ ] 筛选为空时显示空状态，不跳转累计错题本。
- [ ] `has_snapshot=false` 时显示兼容提示，已保存判定仍展示。
- [ ] `status_unknown=true` 的题显示「未知／不可用」。
- [ ] 模拟考试已完成会话在本页可看到每题对错与当场正确答案。
- [ ] 前端测试与构建通过：`cd frontend && npm test && npm run build`。

## 非目标

不改造完成页（属 `10-13-result-page`）；不改造答题页；不改造累计错题本（其详情统一呈现由父任务后续评估，不在本子任务）；不给 `QuestionCard` 加只读模式；不新增后端接口。

## Notes

- 设计要求见父任务 `design.md` 第 5.1、5.2 节。
- 本页是「查看详情」「本次错题」与历史已完成会话的共同目标（父任务 R7）。
- 项目使用纯 JavaScript，不用 TypeScript。
