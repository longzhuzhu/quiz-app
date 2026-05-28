# Sync Long-Lived Branch with Origin

## Goal

把 `origin/feat/user-owned-exams-backend-foundation` 的 21 个新 commit 同步到本地同名分支，结束当前 ahead 30 / behind 21 的分歧状态。

## Background

- 当前 HEAD 落后远端 21 个 commit，超前 30 个 commit。
- 远端 21 个新 commit 来自其它 worktree / session 的 PR 合并（PR #22 #24 #25 #26 等），都是已经 ship 的工作。
- 本地 30 个 commit 中相当一部分是 trellis archive / journal / 任务 bookkeeping；今天三个 UI 修复（add per-bank resume entry、icon、height）已经通过 PR #28、#29 进入 main，不在这个长期分支同步链路上。
- 之前尝试过 `git pull --rebase`，在 `chore: record journal` 类 commit 上撞了 `.trellis/workspace/longzhuzhu/journal-1.md` 和 `index.md` 冲突；24 个 commit 还有 23 个没 rebase。

## Requirements

- 不丢失本地任何 archive / 任务 bookkeeping / journal commit。
- 不 force push，不覆盖远端 21 个 commit。
- working tree 上未追踪的 trellis 元工具变更（`.trellis/scripts/*`、`workflow.md`、`AGENTS.md`、`storage/` 等）不卷入本次同步 commit。

## Acceptance Criteria

- [ ] `git status -sb` 显示 `ahead X` (X 可以是任意正数，但不再有 `behind`)。
- [ ] 本地 HEAD 包含远端 21 个 commit 的全部内容。
- [ ] 本地原有 30 个 commit 仍然在 HEAD 可达。
- [ ] working tree 上的 trellis 元工具未追踪变更原状保留。
- [ ] 同步成功后 push 到 origin，远端跟随更新。

## Definition of Done

- 本地与远端同步，可以 push（fast-forward 或带一个 merge commit）。
- working tree dirty 文件未被误提交。

## Technical Approach

**方案 A: merge** (Recommended)

```bash
git merge --no-ff origin/feat/user-owned-exams-backend-foundation -m "Merge origin/feat/user-owned-exams-backend-foundation into feat/user-owned-exams-backend-foundation"
```

- 优点：一次性收尾，冲突点集中在一次（主要是 journal-1.md / workspace/index.md）。
- 缺点：留一个 merge commit，分支历史不是线性。但这条本来就是长期分支，merge commit 可接受。

**方案 B: rebase** (备选)

```bash
git stash push -u -m "trellis meta dirty"
git rebase origin/feat/user-owned-exams-backend-foundation
# 逐个解决 24 个 commit 的冲突
git stash pop
```

- 缺点：之前已经验证会撞多次冲突，工作量大且每次都要判断 journal 哪一份保留。

**方案 C: reset + cherry-pick**

```bash
git reset --hard origin/feat/user-owned-exams-backend-foundation
# 然后挑本地有价值的 commit cherry-pick
```

- 缺点：destructive，没 user 明确同意不能做。

**采用 A**：一次 merge，集中处理冲突。

## Decision (ADR-lite)

- **Context**: 长期分支双向分歧，且本地 30 个 commit 大多是 trellis bookkeeping。
- **Decision**: 用 `git merge --no-ff` 一次性同步。
- **Consequences**: 多一个 merge commit；冲突集中在 trellis workspace 文件，可保留双方内容（journal 合并、workspace/index 取并集）。

## Out of Scope

- 不处理 working tree 上的 trellis 元工具 untracked / modified 文件（属于另一项工作）。
- 不删已 merged 的 `feat/per-bank-resume-entry-pr` 分支（独立的清理任务）。
- 不动 main 分支。

## Technical Notes

- 冲突文件预期：`.trellis/workspace/longzhuzhu/journal-1.md`、`.trellis/workspace/longzhuzhu/index.md`。
- 解决策略：journal 类文件按行合并双方内容；index 类按时间顺序合并条目。
- 同步前先 `git stash -u`，同步后 `git stash pop`，保护元工具未追踪变更。
