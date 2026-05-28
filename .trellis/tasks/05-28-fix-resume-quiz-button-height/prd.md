# Fix Resume Quiz Button Height Alignment

## Goal

让首页题库卡片中的题库级"继续答题"按钮与同组的"顺序练习/随机练习/模拟考试"按钮高度一致，消除当前因 wrapper + 进度文案导致的视觉高低差。

## What I already know

- `frontend/src/views/HomeView.vue` 行 105-123 是题库卡片按钮组。
- 外层 `<div class="flex gap-2 flex-wrap flex-shrink-0">` 默认 `align-items: stretch`。
- 题库级"继续答题"被包在 `<div class="flex flex-col gap-1">` 里：上面是 `<BaseButton size="sm">▶ 继续答题</BaseButton>`，下面是 `<span class="text-xs">已答 x/y｜模式</span>`。
- 其他练习按钮（顺序/随机/模拟考试）是直接的 `<BaseButton size="sm">`。
- 副作用：`flex stretch` 把直接按钮拉伸到 wrapper 高度（约 button+gap+span 总和），但 wrapper 内的"继续答题"按钮自身只占 sm padding 高度（`py-1.5`）→ "继续答题"按钮在视觉上比同组其他按钮矮一截。

## Open Questions

- 修复方向：保留按钮下方进度文案（仅修高度）还是把进度文案并进按钮 label？

## Requirements (evolving)

- 题库卡片按钮组里所有按钮（继续答题 / 顺序练习 / 随机练习 / 模拟考试）视觉高度一致。
- 不改变按钮的颜色、文案前缀（▶/🔀/📝）和点击行为。
- 全局"继续上次答题"卡片不变。

## Acceptance Criteria (evolving)

- [ ] 同一题库卡片按钮组里所有按钮渲染高度一致。
- [ ] "继续答题"仍可展示进度信息（位置由实现方案决定）。
- [ ] 点击"继续答题"仍跳转到原会话恢复路由。
- [ ] 前端构建通过。

## Definition of Done

- 前端构建通过。
- 手动验证题库卡片按钮组按钮高度一致。
- 把"同组按钮高度对齐"的判定收敛到 `component-guidelines.md` 现有"同组操作按钮视觉语言"段。

## Out of Scope

- 不改变其他视图的按钮组布局。
- 不重构 BaseButton。
- 不调整全局"继续上次答题"卡片。

## Technical Notes

- 题库 2 (`fix-resume-quiz-button-icon-consistency`) 已经把 ▶ 图标补齐，但 wrapper 引入的高度差当时未捕获。
- 方案 A 候选：外层 flex 加 `items-start`，按钮顶部对齐，进度文案在 wrapper 下方延伸 — 按钮等高，但 wrapper 整体比其他按钮高，按钮组下沿不齐。
- 方案 B 候选：移除 `<span>` 文案，把进度合并进按钮 label，如 `▶ 继续答题 · 5/30 顺序` — 按钮组完全等高、下沿对齐，但按钮内容变长，可能挤占布局。
- 方案 C 候选：保留 wrapper 但把按钮 size 在 wrapper 里改为 `md` 或加 `min-h-*` 把 wrapper 整高度等分给按钮，让按钮被拉伸 — 改动小，但破坏 sm 尺寸的全局一致。

## Research References

(不涉及外部技术调研，纯 Tailwind/flex 布局选择)
