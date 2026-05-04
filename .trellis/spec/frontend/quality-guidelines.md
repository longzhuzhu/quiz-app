# Quality Guidelines

> Code quality standards for frontend development.

---

## Testing Framework

### Design Decision: Vitest + Vue Test Utils

**Context**: 项目需要前端测试能力覆盖纯函数、组合函数、Pinia store 逻辑和 Vue 组件行为。

**Options Considered**:
1. Node.js 内置 test runner — 零依赖但仅支持纯函数测试，无法 mount 组件
2. Jest + Vue Test Utils — 成熟稳定但配置复杂，与 Vite 集成需额外 babel 转译
3. Vitest + Vue Test Utils — Vite 原生集成，配置极简，支持组件 mount 和 jsdom

**Decision**: 选择 **Vitest + Vue Test Utils + jsdom**。理由：
- Vitest 直接复用 Vite 配置（别名、插件、转换），零额外配置
- Vue Test Utils 是 Vue 3 官方组件测试库，可 `mount` 组件并模拟用户交互
- jsdom 提供浏览器 API 模拟，组件测试必需

### 测试层级与工具映射

| 测试层级 | 工具 | 适用范围 |
|---------|------|---------|
| 单元测试 | Vitest | 纯函数（`utils/*.js`）、组合函数（`composables/*.js`） |
| Store 测试 | Vitest + Pinia 测试工具 | Pinia store 逻辑（state / action / getter） |
| 组件测试 | Vitest + Vue Test Utils | Vue 组件渲染、用户交互、事件触发 |

### 依赖与配置

**devDependencies**（需添加到 `package.json`）：

```
vitest: ^2.1.8
@vue/test-utils: ^2.4.6
jsdom: ^25.0.1
```

**scripts**：

```json
{
  "test": "vitest",
  "test:run": "vitest run"
}
```

**vitest.config.ts**：

```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.{test,spec}.{js,ts}'],
  },
})
```

> `globals: true` 允许在测试文件中直接使用 `describe` / `it` / `expect` / `vi` 而无需显式 import。

### 测试文件组织

```
frontend/tests/
├── unit/               # 纯函数 / composables
│   ├── jobStatus.test.js
│   └── formatXxx.test.js
├── stores/             # Pinia store 测试
│   └── auth.test.js
└── components/         # 组件测试
    └── QuestionCard.test.js
```

### 测试模式

#### 纯函数测试

```javascript
// tests/unit/jobStatus.test.js
import { describe, it, expect } from 'vitest'
import { formatJobBannerMessage } from '@/utils/jobStatus'

describe('formatJobBannerMessage', () => {
  it('running job formats single-line progress', () => {
    const result = formatJobBannerMessage(
      { status: 'running', status_message: '翻译中，已处理 40/542', progress_done: 40, progress_total: 542, attempt_count: 1, max_attempts: 3 },
      { idleMessage: '任务正在后台执行' },
    )
    expect(result).toBe('翻译中 · 已处理 40/542 · 第 1/3 次 · 刷新页面不会中断')
  })
})
```

#### Pinia Store 测试

```javascript
// tests/stores/auth.test.js
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('isLoggedIn returns false when user is null', () => {
    const store = useAuthStore()
    expect(store.isLoggedIn).toBe(false)
  })
})
```

#### 组件测试

```javascript
// tests/components/QuestionCard.test.js
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import QuestionCard from '@/components/QuestionCard.vue'

describe('QuestionCard', () => {
  it('renders question content', () => {
    const wrapper = mount(QuestionCard, {
      props: {
        question: { content: 'What is IAPP?', options: ['A', 'B', 'C', 'D'], type: 'single' },
      },
    })
    expect(wrapper.text()).toContain('What is IAPP?')
  })
})
```

### Mock 约定

- **API 请求**：用 `vi.mock('@/api/client')` 拦截，不发起真实请求
- **路由**：用 `vi.mock('vue-router')` 模拟 `useRoute` / `useRouter`
- **定时器**：用 `vi.useFakeTimers()` 替代 `setTimeout` / `setInterval`

### Lint 工具

项目**未配置** lint 工具（无 eslint、prettier、stylelint 等）。代码格式和风格主要通过代码审查保障。

---

## Required Patterns

### 1. 组合式 API + `<script setup>`

所有 Vue 组件必须使用 `<script setup>` 语法：

```vue
<!-- Correct -->
<script setup>
import { ref } from 'vue'
const count = ref(0)
</script>

<!-- Wrong - Options API -->
<script>
export default {
  data() { return { count: 0 } }
}
</script>
```

### 2. Pinia 状态管理

跨组件共享状态必须使用 Pinia store，不允许通过 props/events 多层传递：

```javascript
// stores/auth.js
export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const isLoggedIn = computed(() => !!user.value)
  return { user, isLoggedIn }
})
```

### 3. API 调用统一走 Axios 实例

所有 API 调用必须通过 `src/api/client.js` 的 Axios 实例，确保 JWT 拦截和 401 自动登出生效：

```javascript
// Correct
import client from '@/api/client'
const res = await client.get('/api/banks')

// Wrong - 绕过拦截器
import axios from 'axios'
const res = await axios.get('/api/banks')
```

---

## Forbidden Patterns

### 1. 直接操作 DOM

```vue
<!-- Wrong -->
<div ref="el"></div>
<script setup>
const el = ref(null)
el.value.style.color = 'red'  // 直接操作 DOM
</script>

<!-- Correct - 用响应式绑定 -->
<div :style="{ color: 'red' }"></div>
```

### 2. 在模板中写复杂逻辑

```vue
<!-- Wrong -->
<div v-if="items.filter(i => i.active).map(i => i.name).join(', ')">

<!-- Correct - 用 computed -->
<div v-if="activeItemNames">
<script setup>
const activeItemNames = computed(() =>
  items.value.filter(i => i.active).map(i => i.name).join(', ')
)
</script>
```

---

## Code Review Checklist

- [ ] 新增 API 调用是否通过 `client.js` Axios 实例
- [ ] 组件是否使用 `<script setup>` 语法
- [ ] 共享状态是否使用 Pinia store
- [ ] 纯工具函数是否可测试（无 DOM / Vue 依赖）
- [ ] Tailwind 类名是否遵循项目风格一致性
- [ ] 路由是否有正确的 `meta.auth` 守卫
