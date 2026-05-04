# 状态管理

> Pinia Store 与异步错误处理的实际模式。

---

## Store 风格

全量 **Pinia Setup Store**（函数式 `defineStore`），不使用 Options Store。

```javascript
export const useAuthStore = defineStore('auth', () => {
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const token = ref(localStorage.getItem('token') || '')
  const isLoggedIn = computed(() => !!token.value)
  // ...
  return { user, token, isLoggedIn, login, register, logout, fetchMe }
})
```

真实示例：`frontend/src/stores/auth.js` 行1-42

---

## 三个 Store

| Store | 职责 | 持久化 |
|-------|------|--------|
| `auth.js` | 认证状态 + 用户信息 | localStorage（token + user JSON） |
| `quiz.js` | 答题会话 + 当前题目索引 | 无 |
| `bank.js` | 题库列表 + loading 状态 | 无 |

---

## Store 之间无直接 import

Store 不互相 import，依赖通过 View 组件层编排：

```javascript
// HomeView.vue — View 层同时使用两个 Store
const bankStore = useBankStore()
const quizStore = useQuizStore()
```

真实示例：`frontend/src/views/HomeView.vue` 行132-133

---

## 异步操作与错误处理分层

### Store 层：try/finally 管理 loading，不 catch 错误

Store 内 action 不 catch 异常，错误直接抛出。只负责 loading 状态管理：

```javascript
// bank.js — try/finally 管理 loading
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

```javascript
// quiz.js — 不 catch，错误抛给调用方
async function startQuiz(bankId, mode, questionCount) {
  const res = await client.post('/quiz/start', { bank_id: bankId, mode, question_count: questionCount })
  session.value = res.data.session
  questions.value = res.data.questions
  currentIndex.value = 0
}
```

真实示例：`frontend/src/stores/quiz.js` 行10-19

### View 层：try/catch + toast.error() 展示错误

View 组件捕获 Store 抛出的错误，用 toast 展示给用户：

```javascript
async function startQuiz(bank, mode) {
  try {
    await quizStore.startQuiz(bank.id, mode)
    router.push(`/quiz/${quizStore.session.id}`)
  } catch (e) {
    toast.error(e.response?.data?.error || '开始答题失败')
  }
}
```

真实示例：`frontend/src/views/HomeView.vue` 行159-166

### 例外：auth.fetchMe 自行处理 401

`fetchMe` 是唯一在 Store 内 catch 的 action，401 时自行 `logout()`：

```javascript
async function fetchMe() {
  try {
    const res = await client.get('/auth/me')
    user.value = res.data
    localStorage.setItem('user', JSON.stringify(user.value))
  } catch {
    logout()
  }
}
```

真实示例：`frontend/src/stores/auth.js` 行31-39

---

## 路由守卫读 localStorage，不读 Store

路由守卫直接读 `localStorage.getItem('token')` 和 `localStorage.getItem('user')`，不使用 `useAuthStore()`，因为 Pinia 可能尚未初始化：

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

## auth Store localStorage 持久化

登录成功时写入，logout 时清除：

```javascript
// 写入
localStorage.setItem('token', token.value)
localStorage.setItem('user', JSON.stringify(user.value))

// 清除
localStorage.removeItem('token')
localStorage.removeItem('user')
```

Store 初始化时从 localStorage 恢复：

```javascript
const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
const token = ref(localStorage.getItem('token') || '')
```

真实示例：`frontend/src/stores/auth.js` 行6-7
