# Composables 模式

> 自定义 Composition API hooks 的编写约定。

---

## 概述

目录：`frontend/src/composables/`，共 3 个文件。

| 文件 | 模式 | 说明 |
|------|------|------|
| `useDarkMode.js` | 模块级单例 | 深色模式切换 |
| `useToast.js` | 模块级单例 | Toast 通知 |
| `useBackgroundJob.js` | 实例级 | 后台任务轮询 + generation 防竞态 |

---

## 命名规则

`use` 前缀 + camelCase + `.js`，导出函数名为 `use*`。

---

## 模式 1：模块级单例

模块顶层声明响应式状态，所有调用 `use*()` 的组件共享同一份状态。

```javascript
// useToast.js — 模块顶层
const toasts = ref([])
let nextId = 0

// 导出函数直接返回同一份状态
export function useToast() {
  function show(message, type = 'info', duration = 3000) { /* ... */ }
  function remove(id) { /* ... */ }
  function success(message) { show(message, 'success') }
  function error(message) { show(message, 'error') }
  return { toasts, show, remove, success, error }
}
```

真实示例：`frontend/src/composables/useToast.js` 行1-24

```javascript
// useDarkMode.js — 同样模式
const isDark = ref(false)  // 模块顶层
export function useDarkMode() {
  function toggle() { /* ... */ }
  return { isDark, toggle }
}
```

真实示例：`frontend/src/composables/useDarkMode.js` 行1-27

---

## 模式 2：实例级 hook

每次调用创建独立实例，绑定组件生命周期，`onUnmounted` 自动清理。

```javascript
export function useBackgroundJob() {
  const job = ref(null)
  const polling = ref(false)
  let timerId = null
  let generation = 0          // 每个实例独立的 generation 计数器

  // ... 内部方法 ...

  onUnmounted(stopPolling)    // 组件卸载时自动清理

  return { job, polling, createJob, restoreActiveJob, stopPolling, clearJob }
}
```

真实示例：`frontend/src/composables/useBackgroundJob.js` 行1-136

---

## generation 计数器防竞态

`useBackgroundJob` 使用递增 `generation` 计数器防止组件卸载后的异步回调污染：

1. 每次 `createJob` / `restoreActiveJob` / `stopPolling` 调用时，`generation += 1`
2. 异步回调执行前检查 `isCurrentGeneration(currentGeneration)`，不匹配则跳过
3. `setJobSafely(nextJob, currentGeneration)` 只在 generation 匹配时写入 `job.value`

```javascript
function beginGeneration() {
  generation += 1
  clearTimer()
  polling.value = false
  return generation
}

function isCurrentGeneration(currentGeneration) {
  return currentGeneration === generation
}

function setJobSafely(nextJob, currentGeneration) {
  if (!isCurrentGeneration(currentGeneration)) return null
  job.value = nextJob
  return job.value
}
```

真实示例：`frontend/src/composables/useBackgroundJob.js` 行17-32（generation 核心）、行43-91（startPolling 中 tick 使用 generation）

---

## 使用方式

### 单例 composable：任意组件调用同一实例

```javascript
// 组件 A
const toast = useToast()
toast.success('保存成功')

// 组件 B（同一实例）
const toast = useToast()
// toast.toasts 与组件 A 共享
```

### 实例 composable：每个组件独立状态

```javascript
// 在 View 组件中使用
const { job, polling, createJob, restoreActiveJob } = useBackgroundJob()

onMounted(async () => {
  await restoreActiveJob({ job_type: 'bulk_translate' }, { onFinished: refreshData })
})
```
