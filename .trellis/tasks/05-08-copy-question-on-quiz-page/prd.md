# Copy Question on Quiz Page

## Goal

在答题页面的答题卡操作区增加“复制”功能，允许用户一键复制当前题目的题干和全部选项，便于记录、分享或向外部工具提问，同时保持与现有翻译、AI 解析、收藏单词等按钮一致的视觉和交互体验。

## Requirements

* 答题卡按钮行新增复制按钮。
* 按钮文案为“复制”。
* 按钮带 `ClipboardDocumentIcon` 图标。
* 复制按钮放在按钮行最后，且样式与翻译、AI 解析、收藏单词等功能按钮保持一致。
* 点击复制时，将当前题目的题干和选项一起写入系统剪贴板。
* 复制内容应包含英文题干、选项；如页面当前题目对象包含中文翻译内容，也可在不影响主要功能的前提下保留既有展示语义。
* 复制成功后通过 toast 展示成功提示。
* 复制失败后通过 toast 展示失败提示，不影响答题、翻译、AI 解析、收藏单词等其他功能。
* 仅修改前端答题卡交互，不改后端 API、数据库模型或答题会话逻辑。

## Acceptance Criteria

* [ ] 答题页面每道题的答题卡按钮行最后展示“复制”按钮。
* [ ] “复制”按钮展示 `ClipboardDocumentIcon`，视觉样式与翻译、AI 解析、收藏单词按钮一致。
* [ ] 点击“复制”后，剪贴板内容包含当前题目题干和全部选项。
* [ ] 复制成功时出现成功 toast。
* [ ] 浏览器不支持剪贴板或写入失败时出现失败 toast。
* [ ] 复制功能不改变当前答题进度、已选答案、提交结果、翻译结果、AI 解析结果或收藏单词状态。
* [ ] 前端生产构建通过。

## Definition of Done

* 前端代码遵循 Vue 3 `<script setup>`、纯 JavaScript、Tailwind 内联样式约定。
* 不新增不必要依赖。
* 不引入后端 API 或数据模型变更。
* 若无法在浏览器中完整验证剪贴板行为，应明确说明。

## Technical Approach

* 在答题卡组件中实现复制按钮，复用现有按钮行和 Tailwind 样式模式。
* 从当前 `question` 对象读取题干与选项，拼接成适合复制的纯文本。
* 使用浏览器 `navigator.clipboard.writeText()` 写入剪贴板。
* 使用项目现有 toast 模式处理成功和失败提示。
* 复制逻辑保持在前端组件内，不新增 Store、API 封装或后端接口。
* 如需处理选项结构差异，应遵循现有 `QuestionCard` 对 `question.options` 的访问方式，避免引入额外数据转换抽象。

## Decision (ADR-lite)

**Context**: 用户在答题过程中经常需要复制题目内容进行笔记整理、检索或外部辅助分析。现有答题卡已有翻译、AI 解析、收藏单词等辅助按钮，复制功能属于同一类轻量前端辅助能力。

**Decision**: 在答题卡按钮行末尾增加前端本地复制按钮，使用 `ClipboardDocumentIcon` 和“复制”文案，通过 Clipboard API 复制当前题干与选项，并用 toast 反馈结果。

**Consequences**: 功能范围集中在前端交互层，不影响答题会话、题库数据、错题练习、AI 功能或后端接口；复制能力依赖浏览器剪贴板权限，失败时以 toast 提示用户。

## Out of Scope

* 不新增后端复制接口或审计记录。
* 不修改数据库模型、题目模型或答题会话模型。
* 不改变题目展示顺序、答题提交逻辑、进度计算或历史记录逻辑。
* 不改变翻译、AI 解析、收藏单词按钮的既有行为。
* 不新增复制格式配置、用户偏好或富文本复制能力。

## Technical Notes

* 适用规范：`.trellis/spec/frontend/component-guidelines.md`、`.trellis/spec/frontend/type-safety.md`、`.trellis/spec/frontend/quality-guidelines.md`、`.trellis/spec/guides/code-reuse-thinking-guide.md`。
* 组件应继续使用 Vue 3 `<script setup>` 与纯 JavaScript，不引入 TypeScript 类型声明。
* 样式继续使用 Tailwind 内联类，不新增 `<style>` 块。
* 错误处理应遵循 View/Component 层 toast 模式。
* 复制功能是纯前端能力，不需要新增依赖。

## Follow-up: Home Continue Session UX Fix

### Goal

修复首页“继续上次答题”卡片在最新未完成会话为错题练习时展示错题练习进度（例如 `0/21`），导致用户误以为题库练习进度与题库总题数不一致的问题。

### Requirements

* 首页“继续上次答题”只展示最近的未完成普通题库会话。
* 排除 `mode: "wrong_practice"` 的未完成错题练习会话。
* 历史记录请求覆盖最近多条记录，确保最新记录是错题练习时仍能找到后续普通题库会话。
* 保持首页独立 API 静默降级模式：请求失败时 `lastIncompleteSession` 置空，不影响题库、错题统计、正确率等其他指标。
* 不改后端、不新增抽象、不影响开始错题练习和错题页。

### Acceptance Criteria

* [ ] 最新未完成会话为错题练习时，首页不展示该错题练习作为“继续上次答题”。
* [ ] 最近多条历史中存在未完成普通题库会话时，首页展示该普通会话。
* [ ] 历史记录请求失败时，“继续上次答题”不显示，其他首页指标照常降级加载。
* [ ] 前端生产构建通过。

### Technical Approach

在 `frontend/src/views/HomeView.vue` 的首页聚合加载逻辑中调整 `/quiz/history` 请求参数，将 `per_page` 从 `1` 提高到 `20`，并在前端使用 `find` 选择第一条 `is_completed === false && mode !== 'wrong_practice'` 的会话。

### Decision (ADR-lite)

**Context**: 首页“继续上次答题”面向普通题库练习恢复；错题练习有独立入口和进度语义，混在首页题库卡片中会造成题库总量与会话总量不一致的困惑。

**Decision**: 仅在首页筛选历史记录时排除 `wrong_practice`，保持后端历史接口、错题练习启动和错题页行为不变。

**Consequences**: 修复范围集中，避免影响答题会话模型；如果最近 20 条历史内没有未完成普通题库会话，则首页不展示“继续上次答题”。

### Out of Scope

* 不改后端 API、数据库模型或历史排序逻辑。
* 不改变错题练习入口、错题页或错题练习会话恢复能力。
* 不新增首页筛选配置或用户偏好。

### Technical Notes

* 已检查 `frontend/src/views/HomeView.vue`：首页通过多个独立 Promise 加载题库、错题统计、近期正确率和最近会话，使用 `Promise.allSettled` 保持独立降级。
* 该 follow-up 是同一任务下的反馈修复记录，用于保留用户反馈背景，同时避免覆盖原“答题页面复制题目”需求。
