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

## 考试项目上下文 API 契约

### 1. Scope / Trigger

- Trigger: 前端考试项目上下文跨越 router、Pinia、Axios header 和后端 `/api/exams`、`/api/account/active-exam` 响应契约。
- Scope: 只适用于用户自有考试项目上下文，不适用于管理员全局配置页。

### 2. Signatures

- `GET /api/exams` → 当前用户拥有的考试项目列表。
- `POST /api/exams` → 创建考试项目，并由后端设置为 active exam。
- `PATCH /api/exams/{slug}` → 更新当前用户拥有的考试项目。
- `DELETE /api/exams/{slug}` → 删除当前用户拥有的考试项目。
- `POST /api/account/active-exam` → 切换 active exam。

### 3. Contracts

`GET /api/exams` 返回包装对象，不是裸数组：

```javascript
const res = await client.get('/exams')
myExams.value = Array.isArray(res.data?.items) ? res.data.items : []
```

`POST /api/account/active-exam` 返回 `{ active_exam: Exam }`，不是裸 Exam：

```javascript
const res = await client.post('/account/active-exam', { slug })
current.value = res.data?.active_exam || null
```

考试项目范围 API 的请求头必须来自 `useExamStore.current.slug`：

```javascript
if (examStore.current?.slug) {
  config.headers['X-Exam-Slug'] = examStore.current.slug
}
```

不要用 `active_exam_id` 作为 header，也不要从 `localStorage.user.active_exam` 隐式兜底生成 header。

### 4. Validation & Error Matrix

| 条件 | 前端行为 |
|------|----------|
| 未登录访问 `/exams`、`/onboarding`、`/exams/:examSlug/*` | 路由守卫跳转 `/login` |
| 登录后 `auth/me.active_exam` 为空 | 跳转 `/onboarding` |
| `GET /api/exams` 返回非数组 `items` | `myExams` 降级为空数组 |
| 切换不存在或无权限的 `examSlug` | 切换失败后回到 `/exams` |
| 全局认证失效 401 / JWT invalid 422 | 清理 token、user、exam store，并跳转 `/login` |

### 5. Good/Base/Bad Cases

- Good: 已登录且有 active exam，`/` 跳转 `/exams/{slug}/dashboard`，exam-scoped API 带 `X-Exam-Slug: {slug}`。
- Base: 已登录但没有 active exam，进入 `/onboarding` 创建第一个项目。
- Bad: 把 `GET /api/exams` 当数组或把 `POST /api/account/active-exam` 当裸 Exam，会导致项目列表为空或 `current.slug` 丢失。

### 6. Tests Required

- Store 测试或手工验证：`fetchExams()` 读取 `res.data.items`，`switchTo()` 读取 `res.data.active_exam`。
- Router 手工验证：未登录访问 `/exams`、`/onboarding` 重定向 `/login`；有 active exam 时 `/` 进入 `/exams/{slug}/dashboard`。
- Axios 手工验证：调用 `/banks`、`/quiz/*`、`/wrong`、`/vocab`、`/ai`、`/import-jobs` 时带当前项目 `X-Exam-Slug`。

### 7. Wrong vs Correct

#### Wrong

```javascript
const res = await client.get('/exams')
myExams.value = Array.isArray(res.data) ? res.data : []

const switchRes = await client.post('/account/active-exam', { slug })
current.value = switchRes.data
```

#### Correct

```javascript
const res = await client.get('/exams')
myExams.value = Array.isArray(res.data?.items) ? res.data.items : []

const switchRes = await client.post('/account/active-exam', { slug })
current.value = switchRes.data?.active_exam || null
```

---

## 首页题库级继续答题入口前端契约

### 1. Scope / Trigger

- Trigger: `HomeView` 基于 `/quiz/history` 同时驱动全局继续入口和题库卡片级继续入口。
- Scope: 只适用于考试项目首页题库列表；不改变答题页恢复逻辑，也不新增后端 API。

### 2. Signatures

- 首页历史请求：
  ```javascript
  client.get('/quiz/history', { params: { page: 1, per_page: 100 } })
  ```
- 恢复跳转：
  ```javascript
  router.push(currentExamPath(route, 'quiz', { sessionId }))
  ```

### 3. Contracts

`/quiz/history` 的 `items` 中，首页继续入口依赖这些字段：

| 字段 | 用途 |
|------|------|
| `id` | 恢复会话路由参数 |
| `bank_id` | 建立题库卡片到未完成会话的映射 |
| `mode` | 过滤 `wrong_practice`，并显示模式文案 |
| `answered_count` | 显示 `已答 x/y` 中的已答数量 |
| `total_questions` | 显示 `已答 x/y` 中的总题数 |
| `is_completed` | 只展示未完成会话 |

全局入口和题库级入口必须复用同一批历史数据；全局入口仍取历史列表中第一个未完成且非 `wrong_practice` 的会话。

题库级会话的进度信息（`已答 x/y` + 模式名）**显示在题库 micro-info 行末尾**，跟 `XX 道题目` 用 `｜` 分隔为三段（`XX 道题目 ｜ 已答 x/y ｜ 模式`），**不挂在"继续答题"按钮下方做 wrapper subtitle**——避免按钮组下沿不齐与小字视觉孤立。"继续答题"按钮跟"顺序练习 / 随机练习 / 模拟考试"在按钮组中平级排列，4 个按钮自然等高。

### 4. Validation & Error Matrix

| 条件 | 前端行为 |
|------|----------|
| `items` 不是数组 | 当作空列表 |
| 会话 `is_completed !== false` | 不作为继续入口 |
| 会话 `mode === 'wrong_practice'` | 不作为首页继续入口 |
| 会话缺少 `bank_id` | 不显示在题库卡片级入口中 |
| 同一题库有多个未完成普通会话 | 使用历史列表顺序中的第一个 |
| `/quiz/history` 请求失败 | 全局入口为空，题库级入口映射为空，不影响题库列表和统计卡片 |
| `session.id == null` | 点击恢复时不跳转 |

### 5. Good/Base/Bad Cases

- Good: 一个题库有未完成 `sequential` 会话，题库卡片 micro-info 行显示 `30 道题目 ｜ 已答 x/y ｜ 顺序练习`，按钮组同时显示"继续答题 / 顺序练习 / 随机练习 / 模拟考试"四个平级按钮，点击"继续答题"进入现有 quiz session 路由。
- Base: 没有未完成普通会话时，micro-info 行只显示 `30 道题目`（无 dangling 分隔符），按钮组只有"顺序练习 / 随机练习 / 模拟考试"。
- Bad: 把 `wrong_practice` 未完成会话显示成题库级继续入口，会把错题练习语义混入普通题库练习恢复。
- Bad: 把会话进度信息挂在"继续答题"按钮下方做 wrapper subtitle，wrapper 整体高度高于其他按钮，造成按钮组下沿不齐且小字视觉孤立。

### 6. Tests Required

- Build: `cd frontend && npm run build`。
- Browser smoke: 有未完成普通会话的题库卡片显示“继续答题”，点击后 URL 进入对应考试项目下的 quiz session 路由。
- Browser smoke: 只有 `wrong_practice` 未完成会话的题库不显示题库级“继续答题”。
- Regression smoke: 全局“继续上次答题”卡片仍显示同一历史列表中的第一个未完成普通会话，新开练习按钮仍可点击。

### 7. Wrong vs Correct

#### Wrong

```javascript
lastIncompleteSession.value = items.find(item => item.is_completed === false) || null
incompleteSessionByBankId.value[item.bank_id] = item
```

#### Correct

```javascript
const incompleteSessions = items.filter(item => item.is_completed === false && item.mode !== 'wrong_practice')
lastIncompleteSession.value = incompleteSessions[0] || null
for (const session of incompleteSessions) {
  if (session.bank_id == null || sessionsByBankId[session.bank_id]) continue
  sessionsByBankId[session.bank_id] = session
}
```

---

## 题目 AI 产物预热前端契约

### 1. Scope / Trigger

- Trigger: `QuizView` 展示或切换当前题时，静默请求后端预热当前题和下一题的翻译与 AI 解析。
- Scope: 只适用于正式答题页；不适用于系统设置页以外的管理页面、题库预览、导入复核或题目编辑。
- 预热不能改变 `TranslateButton` / `ExplainButton` 的点击、loading、toast 和展示语义。

### 2. Signatures

- 答题页请求：
  ```javascript
  client.post('/ai/prewarm', { session_id: sessionId, question_ids: ids }).catch(() => {})
  ```
- 设置页读取：
  ```javascript
  const res = await client.get('/settings/quiz')
  form.value.quiz_ai_prewarm_enabled = res.data.quiz_ai_prewarm_enabled !== false
  ```
- 设置页保存：
  ```javascript
  await client.put('/settings/quiz', {
    quiz_ai_prewarm_enabled: form.value.quiz_ai_prewarm_enabled,
  })
  ```

### 3. Contracts

- `question_ids` 由前端按当前 `quizStore.currentIndex` 组装，最多包含当前题和下一题。
- 前端不读取普通答题页的系统设置；是否入队由后端 `POST /api/ai/prewarm` 统一判断。
- 预热请求必须是 fire-and-forget，不阻塞答题、切题、提交答案或结束答题。
- 预热失败不 toast、不设置页面错误状态、不显示任何“预热”文案。
- `QuizView` 生命周期内可以用 `Set` 做轻量本地去重；刷新页面后不持久化。
- 管理员系统设置页新增“答题设置”分组，开关文案为“是否启用答题预热”。

### 4. Validation & Error Matrix

| 条件 | 前端行为 |
|------|----------|
| `quizStore.session.id` 不存在 | 不请求预热 |
| 当前题不存在 | 不请求预热 |
| 有下一题 | 传 `[currentQuestion.id, nextQuestion.id]` |
| 没有下一题 | 只传 `[currentQuestion.id]` |
| 同一生命周期内相同 `session_id + question_ids` 已请求 | 不重复请求 |
| `POST /api/ai/prewarm` 返回 `accepted: false` | 静默忽略 |
| `POST /api/ai/prewarm` 返回 403/404/500 | 静默 catch，除全局认证拦截外不提示 |
| 401 或 JWT invalid 422 | 由全局 Axios 拦截器处理登录失效 |

### 5. Good/Base/Bad Cases

- Good: 进入第 3 题时静默发送当前题和第 4 题 ID；用户界面没有任何预热状态。
- Base: 预热未完成时用户点击“翻译”，按钮仍按现有同步接口显示 loading 并生成结果。
- Bad: 在答题页先调用 `/settings/quiz` 再决定是否预热，增加普通答题链路依赖。
- Bad: 预热失败时 `toast.error('预热失败')`，把可丢弃优化暴露给用户。

### 6. Tests Required

- Build: `cd frontend && npm run build`。
- Browser smoke: 未登录访问设置页应重定向登录且无 console error；登录后设置页应显示“答题设置”与“是否启用答题预热”。
- Manual/API smoke: 答题页切换题目时 network 中出现 `/api/ai/prewarm`，且页面无预热状态文案。
- Manual/API smoke: 禁用设置后答题页仍可点击“翻译”和“AI 解析”同步生成。

### 7. Wrong vs Correct

#### Wrong

```javascript
try {
  const res = await client.post('/ai/prewarm', payload)
  toast.success(res.data.accepted ? '预热中' : '未启用预热')
} catch (e) {
  toast.error('预热失败')
}
```

#### Correct

```javascript
client.post('/ai/prewarm', { session_id: sessionId, question_ids: ids }).catch(() => {})
```

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
