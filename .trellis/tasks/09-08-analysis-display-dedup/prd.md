# 统一解析展示并避免重复

## Goal

让用户在答题页和错题本中获得简洁、一致的中文 AI 解析体验：解析正文只展示中文，同一道题的同一份 AI 解析只出现一次。

## Background

当前界面存在两项问题：

- AI 解析会同时展示英文和中文正文，英文内容对当前用户体验没有必要。
- 提交答案后，答题反馈区域会展示解析；再次点击“AI 解析”后，页面又会出现独立解析区域，造成内容重复。

代码证据表明，两个区域展示的是同一份 AI 解析，而不是两个独立的数据源：

- `frontend/src/components/QuestionCard.vue:75-82` 的独立 AI 解析区域和 `frontend/src/components/QuestionCard.vue:97-104` 的答题反馈解析都读取 `explanation` / `explanation_zh`。
- `frontend/src/components/ExplainButton.vue:34-39` 会直接复用题目已有的同一组解析字段。
- `backend/app/services/ai_service.py:298-302` 将 AI 生成结果写入 `Question.explanation` / `Question.explanation_zh`；`backend/app/api/routes/quiz.py:276-283` 在提交答案后返回同一组字段。
- `backend/app/services/smart_import_service.py:1280-1282` 明确不将导入解析写入正式题目的解析字段。

本任务保持现有单一“AI 解析”领域模型，不新增独立的答案解析数据源。

## Requirements

### R1. 解析仅展示中文

- 答题页和错题本中的 AI 解析区域只展示 `explanation_zh`，不展示 `explanation` 英文正文。
- 保留现有英文解析数据和后端字段，不进行数据删除、迁移或接口调整。
- 题干和选项现有的中英文展示行为不受影响。

### R2. 使用唯一的 AI 解析区域

- 同一道题只使用一个独立的“AI 解析”区域展示解析正文。
- 答题反馈区域只展示回答是否正确和正确答案，不再展示解析正文。
- 提交答案后，如果已有中文 AI 解析，则在答题反馈区域之后的独立区域中显示。
- 用户点击“AI 解析”获得的中文内容也显示在同一个独立区域，不创建第二个解析区域。
- 错题本同样只保留一个中文 AI 解析区域，不重复显示已有解析和按钮返回的解析。

### R3. 按钮状态

- 中文 AI 解析尚未显示时，按钮沿用现有“AI 解析”或“解析中...”状态。
- 中文 AI 解析显示后，按钮保留但禁用，文字变为“解析已显示”。
- 加载期间不清空页面上已经可见的解析；请求失败时也保留已有解析。

### R4. 术语统一

- 用户可见界面统一使用“AI 解析”表示 `Question.explanation` / `Question.explanation_zh` 内容。
- 不将答题反馈区域中的同一份内容命名为另一类“答案解析”或“答题解析”。

## Acceptance Criteria

- [ ] AC1：答题页和错题本均不再展示 AI 解析的英文正文。
- [ ] AC2：题干和选项仍维持原有中英文展示行为。
- [ ] AC3：提交答案后，已有中文 AI 解析显示在答题反馈区域之后的独立“AI 解析”区域。
- [ ] AC4：答题反馈区域只显示对错和正确答案，不再包含解析正文。
- [ ] AC5：点击“AI 解析”后，中文解析显示在同一个独立区域，页面不会出现第二个解析区域。
- [ ] AC6：错题本展开题目时，已有或新获取的中文 AI 解析只显示一次。
- [ ] AC7：中文 AI 解析可见后，按钮处于禁用状态并显示“解析已显示”。
- [ ] AC8：AI 解析加载或请求失败时，页面上已有解析不会被提前清空。
- [ ] AC9：现有英文解析数据、AI 生成流程、后端接口和缓存复用行为不受影响。

## Out of Scope

- 新增独立的标准答案解析字段、数据模型或题库导入链路。
- 删除或迁移数据库中的英文解析数据。
- 修改题干、选项或翻译内容的中英文展示规则。
- 修改 AI 解析提示词、生成质量、后端接口或缓存策略。
- 调整模拟考试模式中的答案和解析可见性。

## Technical Notes

- 当前实际需要调整的前端边界为 `frontend/src/components/QuestionCard.vue`、`frontend/src/components/ExplainButton.vue` 和 `frontend/src/views/WrongAnswersView.vue`。
- `frontend/src/components/QuestionCard.vue` 已有与提交按钮 loading 状态有关的未提交修改；实现时必须保留该修改，不得覆盖。
- 项目没有测试框架和 lint 配置，完成后至少运行前端生产构建，并针对答题页与错题本执行交互检查。
