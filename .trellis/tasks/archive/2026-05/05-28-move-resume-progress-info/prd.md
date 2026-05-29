# Move Resume Quiz Progress Info to Bank Meta Line

## Goal

把题库卡片中"继续答题"按钮下方的进度小字（`已答 5/30｜顺序练习`）挪到题库 micro-info 行末尾，跟 `XX 道题目` 用 `｜` 分隔，消除按钮下方孤儿小字。语义归属仍属于"继续答题入口"，只是视觉位置改变。

## Background

- 当前结构：`<div class="flex flex-col gap-1">` wrapper 把"继续答题"按钮和进度小字 `<span>` 包成两行。即使 wrapper 顶部对齐了，进度小字这一行仍像视觉孤儿，跟同组按钮无关联。
- 经过 grill-with-docs 收敛：进度信息（动态会话状态）跟"30 道题目"（静态题库元信息）虽然语义不同，但通过 `｜` 分隔符放在同一行不会让用户混淆——题库 micro-info 行就是"卡片摘要"性质，可容纳多类信息。
- 同时 wrapper 删除后，按钮组所有按钮 100% 平级等长，达成真正的视觉一致。

## Requirements

- "继续答题"按钮自身只保留 `▶ 继续答题` 文案（去掉下方小字）。
- 当题库有未完成普通会话时，题库 micro-info 行追加 `｜ 已答 x/y ｜ 模式名`，其中 x = answered_count，y = total_questions，模式名走现有 `modeLabel()`。
- 无未完成会话时，micro-info 行只显示 `XX 道题目`，不出现 dangling 分隔符。
- 按钮组 wrapper（`<div class="flex flex-col gap-1">`）和小字 `<span>` 完全删除，外层 flex 不再需要 `items-start`（4 个按钮自然等高）。
- 排除 `wrong_practice` 会话的现有逻辑不变。
- 全局"继续上次答题"卡片不变。

## Acceptance Criteria

- [ ] 有未完成普通会话的题库卡片 micro-info 行显示三段：`30 道题目 ｜ 已答 5/30 ｜ 顺序练习`。
- [ ] 无未完成普通会话的题库卡片 micro-info 行只显示 `30 道题目`，无 dangling `｜`。
- [ ] "继续答题"按钮跟同组按钮（顺序/随机/模拟）完全等长等高、平级排列。
- [ ] 点击"继续答题"仍跳转到原会话恢复路由。
- [ ] `wrong_practice` 未完成会话不在 micro-info 行出现。
- [ ] 前端构建通过。

## Definition of Done

- 前端构建通过。
- `.trellis/spec/frontend/quality-guidelines.md` 中"首页题库级继续答题入口前端契约"段更新进度信息的视觉位置说明（从"按钮下方"改为"题库 micro-info 行末尾"）。
- `.trellis/spec/frontend/component-guidelines.md` 的"同组操作按钮视觉语言"段不需要新增（按钮组现在天然等高，wrapper 已删除）；可以追加一条 anti-pattern：避免给单个按钮附加 wrapper subtitle，进度类信息应放卡片信息流而非按钮 wrapper。

## Technical Approach

### 模板改动（`frontend/src/views/HomeView.vue` 行 100-113）

**Before**:
```vue
<div class="min-w-0">
  <h3>{{ bank.name }}</h3>
  <p>{{ bank.description || '暂无描述' }}</p>
  <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">{{ bank.question_count }} 道题目</p>
</div>
<div class="flex gap-2 flex-wrap flex-shrink-0 items-start">
  <div v-if="incompleteSessionByBankId[bank.id]" class="flex flex-col gap-1">
    <BaseButton variant="primary" size="sm" @click="continueSession(incompleteSessionByBankId[bank.id])">
      ▶ 继续答题
    </BaseButton>
    <span class="text-xs text-gray-500 dark:text-gray-400">
      已答 {{ ... }}/{{ ... }}｜{{ modeLabel(...) }}
    </span>
  </div>
  <BaseButton ...>▶ 顺序练习</BaseButton>
  ...
</div>
```

**After**:
```vue
<div class="min-w-0">
  <h3>{{ bank.name }}</h3>
  <p>{{ bank.description || '暂无描述' }}</p>
  <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">
    {{ bank.question_count }} 道题目<template v-if="incompleteSessionByBankId[bank.id]"> ｜ 已答 {{ incompleteSessionByBankId[bank.id].answered_count || 0 }}/{{ incompleteSessionByBankId[bank.id].total_questions || 0 }} ｜ {{ modeLabel(incompleteSessionByBankId[bank.id].mode) }}</template>
  </p>
</div>
<div class="flex gap-2 flex-wrap flex-shrink-0">
  <BaseButton v-if="incompleteSessionByBankId[bank.id]" variant="primary" size="sm" @click="continueSession(incompleteSessionByBankId[bank.id])">
    ▶ 继续答题
  </BaseButton>
  <BaseButton variant="primary" size="sm" @click="startQuiz(bank, 'sequential')" :disabled="bank.question_count === 0">
    ▶ 顺序练习
  </BaseButton>
  ...
</div>
```

净改动：
- 删除按钮组 wrapper `<div class="flex flex-col gap-1">`
- 删除按钮下方 `<span>` 小字
- 删除外层 flex 的 `items-start`（不再需要）
- micro-info 行 `<p>` 内追加条件性后缀

### Spec 改动

- `quality-guidelines.md` 段"首页题库级继续答题入口前端契约"中关于"轻量进度信息"位置的描述更新为 micro-info 行末尾。
- 可选：`component-guidelines.md` 加一条 anti-pattern 提示（按钮 wrapper subtitle 容易孤儿）。

## Decision (ADR-lite)

- **Context**: "继续答题"按钮下方小字独立成行像孤儿，按钮组视觉不协调。
- **Decision**: 把会话进度信息从按钮 wrapper 挪到题库 micro-info 行末尾，按钮组保持平级等高。语义归属仍是"继续答题入口"的辅助状态。
- **Consequences**: 视觉协调度大幅提升；语义边界依赖 `｜` 分隔符表达"题库元信息 + 会话状态"两段。如果用户期望进度信息跟按钮**紧邻**（提示 "继续点这里恢复 5/30 进度"），这个方案分离了信息和入口，但 grill 评估认为现代卡片设计中信息汇集到一行更易扫描。

## Out of Scope

- 不改全局"继续上次答题"卡片。
- 不改 `/quiz/history` API 或 store 逻辑。
- 不引入新的 chip / badge 组件。

## Technical Notes

- 现有 `incompleteSessionByBankId[bank.id]` 状态保留，只是消费位置从按钮 wrapper 改为 micro-info 行。
- `modeLabel()` 复用，不变。
- 之前由 `fix-resume-quiz-button-icon-consistency` 加的 `▶` 图标保留。
- 之前由 `fix-resume-quiz-button-height` 加的 `items-start` 删除（不再需要，因为 wrapper 没了）。
