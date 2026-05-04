# State Management

> How state is managed in this project.

---

## Overview

Vue 3 + Pinia 管理全局状态，组件内部使用 `ref`/`reactive` 管理局部状态。服务端状态通过 Axios API 获取，对长时间运行的任务使用轮询保持同步。

---

## State Categories

| 类型 | 管理方式 | 示例 |
|------|---------|------|
| **全局认证状态** | Pinia store (`auth.js`) | 用户信息、JWT token |
| **领域状态** | Pinia store (`bank.js`, `quiz.js`) | 题库列表、答题会话 |
| **页面局部状态** | 组件 `ref`/`reactive` | 表单输入、展开/折叠 |
| **异步任务状态** | 组件内轮询 `setInterval` | 导入任务进度、后台任务状态 |
| **URL 状态** | Vue Router params/query | 当前题库 ID、分页参数 |

---

## When to Use Global State

- 多个页面/组件共享的数据（用户认证、活跃题库）
- 需要跨页面持久化的状态
- 不需要用 Pinia 的场景：仅单个页面使用的列表数据，直接在组件内管理

---

## Server State

### 短请求：一次性获取

```javascript
const jobs = ref([])
const loading = ref(true)
try {
  const { data } = await apiClient.get('/api/import-jobs')
  jobs.value = data
} finally {
  loading.value = false
}
```

### 长任务：轮询模式

对 `running`/`parsing` 等进行中状态的任务，使用 `setInterval` 轮询：

```javascript
const pollTimer = ref(null)

function startPolling(jobId) {
  stopPolling()
  pollTimer.value = setInterval(async () => {
    const { data } = await apiClient.get(`/api/import-jobs/${jobId}`)
    Object.assign(job.value, data)
    if (['completed', 'failed', 'cancelled'].includes(data.status)) {
      stopPolling()
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

// 组件卸载时清理
onBeforeUnmount(stopPolling)
```

**关键约定**：
- 轮询间隔 3 秒（平衡实时性与服务器负载）
- 必须在 `onBeforeUnmount` 中清理定时器，避免内存泄漏
- 任务进入终态（completed/failed/cancelled）后立即停止轮询
- 初始加载时先做一次同步请求，再启动轮询

---

## Common Mistakes

### Don't: 忘记清理轮询定时器

```javascript
// Wrong - 组件卸载后定时器仍在执行
setInterval(fetchJobStatus, 3000)
```

### Do: 组件卸载时清理

```javascript
const timer = setInterval(fetchJobStatus, 3000)
onBeforeUnmount(() => clearInterval(timer))
```

### Don't: 可能为 null 的属性不加 optional chaining

```javascript
// Wrong - file_type 可能为 null 导致 TypeError
job.file_type.toUpperCase()
```

### Do: 使用 optional chaining

```javascript
job.file_type?.toUpperCase() ?? ''
```
