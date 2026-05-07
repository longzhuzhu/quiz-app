# 代码质量

> API 调用组织、错误处理体系与路由守卫的实际模式。

---

## API 调用组织

无独立 API 函数层。Store 和 View 直接使用 `client`（`frontend/src/api/client.js`）。

```javascript
// Store 内直接调用
const res = await client.get('/banks')

// View 内直接调用
const res = await client.get('/wrong/stats')
```

不创建 `api/banks.js`、`api/quiz.js` 等封装模块。

---

## Axios 配置

`frontend/src/api/client.js` 全文 28 行，配置要点：

- `baseURL: '/api'`，无 timeout 设置
- 请求拦截器：自动注入 Bearer Token

```javascript
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})
```

真实示例：`frontend/src/api/client.js` 行8-14

- 响应拦截器：认证失效清理 + 跳转登录页

```javascript
client.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    const message = err.response?.data?.msg || ''
    const isInvalidToken = status === 422 && (
      message.includes('Invalid header') ||
      message.includes('Not enough segments') ||
      message.includes('Signature verification failed') ||
      message.includes('Subject must be a string')
    )

    if (status === 401 || isInvalidToken) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      router.push('/login')
    }
    return Promise.reject(err)
  }
)
```

真实示例：`frontend/src/api/client.js` 行21-38

**Why**: Flask-JWT-Extended 对缺失/过期 token 返回 401，但对 malformed/旧密钥 token 可能返回 422 + `msg`。全局拦截器只能把明确的 JWT 无效类 422 当作登录失效，不能把所有业务 422 都清登录态。

---

## 错误处理三级体系

### 第 1 级：全局拦截器（认证失效）

Axios 响应拦截器处理 401，以及明确 JWT malformed/invalid 的 422，清理 token 并跳转登录。其他错误 `Promise.reject(err)` 继续传递。

### 第 2 级：Store 层（不 catch）

Store action 不 catch 异常，只负责 loading 管理（try/finally）：

```javascript
async function fetchBanks() {
  loading.value = true
  try {
    const res = await client.get('/banks')
    banks.value = res.data
  } finally {
    loading.value = false
  }
}
```

真实示例：`frontend/src/stores/bank.js` 行9-17

唯一例外：`auth.fetchMe` 自行 catch 后 logout。

### 第 3 级：View/Component 层（try/catch + toast）

View 和智能组件捕获错误，用 toast 展示：

```javascript
// View 层
try {
  await quizStore.startQuiz(bank.id, mode)
} catch (e) {
  toast.error(e.response?.data?.error || '开始答题失败')
}

// 智能组件层
try {
  const res = await client.post('/ai/translate', { question_id: props.questionId })
  emit('translated', res.data)
} catch (e) {
  toast.error(e.response?.data?.error || '翻译失败')
}
```

真实示例：`frontend/src/views/HomeView.vue` 行159-166、`frontend/src/components/TranslateButton.vue` 行34-41

---

## 静默处理变体

### 独立 catch + Promise.allSettled

多个独立 API 调用不应使用 `Promise.all`，避免一个失败导致全部丢失：

```javascript
// 正确：各自独立 catch，互不干扰
const wrongP = client.get('/wrong/stats').then(r => { wrongStats.value = r.data }).catch(() => {})
const accP = client.get('/quiz/recent-accuracy').then(r => {
  recentAccuracy.value = r.data.accuracy
  recentTotal.value = r.data.total
}).catch(() => {})
await Promise.allSettled([wrongP, accP])

// 错误：一个失败全部丢失
const [wrongRes, accuracyRes] = await Promise.all([
  client.get('/wrong/stats'),
  client.get('/quiz/recent-accuracy'),
])
```

**Why**: 首页聚合页有多个指标卡片，单个 API 失败不应拖垮其他指标。`Promise.all` 任一 reject 会导致整个 `catch` 分支执行，两个 API 的数据都无法写入。

Store action 返回的 Promise 也要按同样规则处理，不能裸调用后让失败变成未处理 Promise：

```javascript
const bankP = bankStore.fetchBanks().catch((e) => {
  toast.error(e.response?.data?.error || '获取题库失败')
})
const lastSessionP = client.get('/quiz/history', { params: { page: 1, per_page: 1 } }).then(r => {
  const items = Array.isArray(r.data?.items) ? r.data.items : []
  lastIncompleteSession.value = items[0]?.is_completed === false ? items[0] : null
}).catch(() => {
  lastIncompleteSession.value = null
})
await Promise.allSettled([bankP, wrongP, accP, lastSessionP])
```

**Why**: View 层聚合 Store action 和直接 `client` 请求时，错误边界仍在 View；所有独立数据源都应显式降级，避免首页部分数据失败影响其它模块或产生未处理 Promise。

### catch {} 空块

部分非关键 API 调用使用空 catch 块静默忽略错误：

```javascript
// HomeView.vue — 错题统计获取失败不影响页面
try {
  const res = await client.get('/wrong/stats')
  wrongStats.value = res.data
} catch {}
```

### 设置 error 标记

部分场景用 `ref` 标记错误状态，不弹 toast：

```javascript
// useBackgroundJob.js — 轮询失败时设置 status
catch {
  setJobSafely(
    job.value ? { ...job.value, status: 'unknown', status_message: '任务状态获取失败' } : null,
    currentGeneration,
  )
}
```

---

## 路由 meta 分类

| meta 类型 | 含义 | 校验方式 |
|-----------|------|---------|
| `{ guest: true }` | 仅游客可访问 | 有 token 则跳转首页 |
| `{ auth: true }` | 需登录 | 无 token 则跳转登录 |
| `{ auth: true, admin: true }` | 需管理员 | 无 token 或非 admin 则跳转首页 |

路由守卫直接读 `localStorage`，不读 Pinia Store：

```javascript
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.auth && !token) {
    next('/login')
  } else if (to.meta.guest && token) {
    next('/')
  } else if (to.meta.admin) {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    if (!user?.is_admin) next('/')
    else next()
  } else {
    next()
  }
})
```

真实示例：`frontend/src/router/index.js` 行27-43

---

## 路由懒加载

所有页面组件均使用动态 `import()` 懒加载：

```javascript
{ path: '/login', component: () => import('../views/LoginView.vue') }
{ path: '/admin/banks', component: () => import('../views/AdminBanksView.vue') }
```

真实示例：`frontend/src/router/index.js` 行4-20
