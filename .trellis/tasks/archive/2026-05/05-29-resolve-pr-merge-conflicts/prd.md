# Resolve PR Merge Conflicts

## Goal

修复 PR #32（`feat/user-owned-exams-backend-foundation` → `main`）的合并冲突，使该 PR 可以合并，同时保留“顺序练习”按钮与“随机练习”“模拟考试”一致的 secondary 样式。

## Requirements

* 将当前分支与最新 `origin/main` 合并或等效同步，解决 GitHub 标记的冲突。
* 冲突文件仅限 `frontend/src/views/HomeView.vue` 时，保留当前任务的业务意图：`顺序练习` 使用 `variant="secondary"`。
* 不引入额外 UI 行为变更。
* 推送冲突修复提交到 PR #32 的 head 分支。

## Acceptance Criteria

* [ ] `gh pr view 32 --json mergeable` 不再返回 `CONFLICTING`。
* [ ] `frontend/src/views/HomeView.vue` 中“顺序练习”“随机练习”“模拟考试”均使用 `variant="secondary"`。
* [ ] `npm --prefix frontend run build` 通过。
* [ ] 工作区干净，冲突修复提交已推送。

## Definition of Done

* 冲突已解决并推送到远端 PR 分支。
* 构建验证通过。
* Trellis 任务归档并记录 session journal。

## Technical Approach

使用最新 `origin/main` 与当前 PR 分支合并，解决 `frontend/src/views/HomeView.vue` 的 variant 冲突。最终结果应保留 main 的其他内容，同时保持“顺序练习”按钮为 secondary。

## Decision (ADR-lite)

**Context**: PR #32 的唯一业务变更是将“顺序练习”按钮从 primary 调整为 secondary；GitHub 报告与 main 存在合并冲突。

**Decision**: 解决冲突时保留 `variant="secondary"`，因为这是 PR #32 的用户可见目标。

**Consequences**: PR 可合并，并保持首页三个新建练习入口视觉一致；不改变恢复答题按钮的 primary 视觉优先级。

## Out of Scope

* 不重构首页题库卡片。
* 不修改其他按钮样式或答题逻辑。
* 不处理与 PR #32 无关的历史任务或其他 active task。

## Technical Notes

* `gh pr view 32` 显示 `mergeable: CONFLICTING`。
* `git merge-tree` 预览显示冲突位于 `frontend/src/views/HomeView.vue`：`顺序练习` 按钮 variant 在 `primary` 与 `secondary` 之间冲突。
