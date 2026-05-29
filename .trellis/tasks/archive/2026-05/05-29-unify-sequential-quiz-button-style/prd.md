# Unify Sequential Quiz Button Style

## Goal

统一首页题库卡片中的练习入口按钮视觉风格，让“顺序练习”与“随机练习”“模拟考试”保持一致，降低同组操作的视觉不一致。

## Requirements

* 将题库卡片中的“顺序练习”按钮样式调整为与“随机练习”“模拟考试”一致。
* 保持按钮文案、图标、点击行为、禁用条件不变。
* 不调整“继续答题”按钮样式，因为它表示恢复未完成会话，优先级与新建练习入口不同。

## Acceptance Criteria

* [ ] 首页题库卡片中“顺序练习”“随机练习”“模拟考试”三个新建练习入口使用一致的按钮风格。
* [ ] “顺序练习”点击后仍以 sequential 模式开始答题。
* [ ] 题库题目数为 0 时，“顺序练习”仍保持禁用。
* [ ] 前端生产构建通过。

## Definition of Done

* 最小范围修改完成。
* 构建验证通过。
* 如能运行前端，则在浏览器中检查按钮视觉一致性。

## Technical Approach

修改 `frontend/src/views/HomeView.vue` 中“顺序练习”按钮的 `BaseButton` variant，使其与同组的“随机练习”“模拟考试”一致。

## Decision (ADR-lite)

**Context**: 同一题库卡片里三个新建练习入口应表达同级操作，但“顺序练习”当前使用 primary，另外两个使用 secondary。

**Decision**: 仅将“顺序练习”改为 secondary，不改动恢复会话的“继续答题”。

**Consequences**: 新建练习入口视觉统一；恢复会话入口继续保持突出，避免改变现有信息层级。

## Out of Scope

* 不重构 `BaseButton`。
* 不调整题库卡片布局。
* 不改变任一按钮行为或路由逻辑。

## Technical Notes

* 入口按钮位于 `frontend/src/views/HomeView.vue`。
* `BaseButton` 的 `secondary` variant 已由“随机练习”“模拟考试”使用。
