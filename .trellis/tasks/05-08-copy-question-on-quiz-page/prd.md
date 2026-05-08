# Copy Question on Quiz Page

## Goal

在答题页面为当前题目增加复制能力，方便用户把题干和选项粘贴到其他地方查看、整理或提问。

## Requirements

* 在答题卡操作区增加“复制题目”入口。
* 点击后复制当前题目的题干和所有选项。
* 复制文本保持可读格式：题干在前，选项按现有顺序逐行输出，例如 `A. ...`。
* 复制成功后展示成功提示；复制失败时展示失败提示。
* 功能应适用于顺序、随机、错题练习、模拟考试等复用 `QuestionCard` 的答题场景。

## Acceptance Criteria

* [ ] 答题页当前题目显示“复制题目”按钮。
* [ ] 点击按钮后，剪贴板内容包含当前题干和所有选项文本。
* [ ] 切换题目后点击复制，复制的是切换后的当前题目。
* [ ] 复制成功和失败都有用户可见反馈。
* [ ] 前端生产构建通过。

## Definition of Done

* 前端代码遵循 Vue 3 `<script setup>`、纯 JavaScript、Tailwind 内联样式约定。
* 不新增不必要依赖。
* 不引入后端 API 或数据模型变更。
* 若无法在浏览器中完整验证，应明确说明。

## Technical Approach

在 `frontend/src/components/QuestionCard.vue` 内实现本地复制逻辑：基于 `props.question` 生成纯文本，使用浏览器 Clipboard API 写入剪贴板，并通过现有 `useToast` 显示结果。按钮放在现有 AI 按钮区，避免改动父级页面和 store。

## Decision (ADR-lite)

**Context**: 复制内容完全来自当前题卡已持有的 `question` 数据，不需要跨层数据流或后端参与。

**Decision**: 在 `QuestionCard` 内直接实现复制按钮和格式化逻辑，不新增全局 utility 或 API 封装。

**Consequences**: 实现范围小、复用所有答题场景；若未来多个页面都需要复制同类题目文本，再考虑抽取 shared helper。

## Out of Scope

* 不复制答案、解析、用户选择结果或答题统计。
* 不新增批量复制或复制整套题功能。
* 不改变题目数据结构或后端接口。
* 不新增键盘快捷键。

## Technical Notes

* 已检查 `frontend/src/views/QuizView.vue`：答题页通过 `QuestionCard` 渲染当前题目。
* 已检查 `frontend/src/components/QuestionCard.vue`：已有按钮区可放置复制入口。
* 已搜索 `frontend/src`：当前没有现成 clipboard / 复制逻辑可复用。
* 适用规范：`.trellis/spec/frontend/component-guidelines.md`、`.trellis/spec/frontend/quality-guidelines.md`、`.trellis/spec/frontend/type-safety.md`、`.trellis/spec/guides/code-reuse-thinking-guide.md`。
