# Hook Guidelines

> How hooks are used in this project.

---

## Overview

Vue 3 `<script setup>` + Composition API。自定义逻辑通过组合函数（composables）或内联响应式逻辑实现。

---

## Async Job Polling Pattern

长时间运行的后台任务使用轮询模式，页面刷新后恢复进度。

### 核心约定

1. **创建任务**: `POST /jobs` → 返回 `{ result, job, message }`
2. **轮询进度**: `GET /jobs/active?job_type=...` → 3 秒间隔
3. **页面加载恢复**: `onMounted` 中调用 `checkXxxJobOnLoad()`
4. **清理**: `onUnmounted` 中调用 `stopXxxPolling()` 清除 timer
5. **状态**: `reactive({ progressDone, progressTotal })` + `ref` for error

```javascript
// 状态声明
const jobState = reactive({ progressDone: 0, progressTotal: 0 })
const jobError = ref('')
let pollTimer = null

// 创建任务并开始轮询
async function startJob() {
  translating.value = true
  const res = await client.post('/jobs', { job_type: 'xxx' })
  const { result, job, message } = res.data
  if (result === 'no_work') { translating.value = false; return }
  startPolling()
}

// 轮询
function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollJob, 3000)
  pollJob()
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function pollJob() {
  const res = await client.get('/jobs/active', { params: { job_type: 'xxx' } })
  const job = res.data.job
  if (!job || job.status === 'completed') {
    stopPolling()
    translating.value = false
    await refreshData()
    return
  }
  if (job.status === 'failed') {
    stopPolling()
    jobError.value = job.last_error
  }
  jobState.progressDone = job.progress_done
  jobState.progressTotal = job.progress_total
}

// 页面加载恢复
async function checkJobOnLoad() {
  const res = await client.get('/jobs/active', { params: { job_type: 'xxx' } })
  if (res.data.job?.status === 'running') {
    translating.value = true
    startPolling()
  }
}

// 清理
onUnmounted(() => { stopPolling() })
```

---

## Common Mistakes

### Don't: 同步循环批量操作

```javascript
// Wrong - 阻塞页面，刷新后丢失进度
while (true) {
  const res = await client.post('/batch-translate')
  if (res.data.remaining <= 0) break
}
```

### Do: 异步轮询

```javascript
// Correct - 立即返回，后台处理，进度持久化
const res = await client.post('/jobs', { job_type: 'xxx' })
startPolling()
```

(To be filled by the team)
