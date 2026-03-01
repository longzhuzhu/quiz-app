# UI/UX 重设计实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 CIPT 备考应用从基础功能型界面升级为清新现代、沉浸式的学习体验

**Architecture:** 基于现有 Tailwind CSS 4 + HeadlessUI + Heroicons 全面增强。先构建设计系统基础（CSS 变量 + 基础组件），再逐页重写样式和交互。不引入新依赖。

**Tech Stack:** Vue 3 + Tailwind CSS 4 (@theme) + @headlessui/vue (Dialog, Menu, TransitionRoot) + @heroicons/vue

**设计文档:** `docs/plans/2026-03-01-ui-ux-redesign-design.md`

---

### Task 1: Design Tokens & Dark Mode 基础

**Files:**
- Modify: `frontend/src/style.css`
- Create: `frontend/src/composables/useDarkMode.js`
- Modify: `frontend/index.html` (lang 属性改为 zh-CN)

**Step 1: 更新 style.css，添加 Tailwind CSS 4 @theme tokens 和 dark mode CSS 变量**

```css
@import "tailwindcss";

@theme {
  --color-primary-50: oklch(0.97 0.014 272);
  --color-primary-100: oklch(0.94 0.028 272);
  --color-primary-200: oklch(0.87 0.06 272);
  --color-primary-300: oklch(0.78 0.1 272);
  --color-primary-400: oklch(0.68 0.14 272);
  --color-primary-500: oklch(0.585 0.17 272);
  --color-primary-600: oklch(0.53 0.18 272);
  --color-primary-700: oklch(0.46 0.16 272);
  --color-primary-800: oklch(0.39 0.13 272);
  --color-primary-900: oklch(0.33 0.1 272);

  --radius-card: 0.75rem;
  --radius-card-lg: 1rem;
  --radius-button: 0.5rem;

  --shadow-card: 0 1px 3px 0 rgb(0 0 0 / 0.06), 0 1px 2px -1px rgb(0 0 0 / 0.06);
  --shadow-card-hover: 0 4px 6px -1px rgb(0 0 0 / 0.07), 0 2px 4px -2px rgb(0 0 0 / 0.07);
}

/* 自定义动画 */
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20%, 60% { transform: translateX(-4px); }
  40%, 80% { transform: translateX(4px); }
}
@keyframes count-up {
  from { --num: 0; }
}
.animate-shake { animation: shake 0.4s ease-in-out; }

/* 隐藏滚动条（用于移动端题号导航） */
.scrollbar-hide::-webkit-scrollbar { display: none; }
.scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
```

**Step 2: 创建 dark mode composable**

```js
// frontend/src/composables/useDarkMode.js
import { ref, watch, onMounted } from 'vue'

const isDark = ref(false)

export function useDarkMode() {
  onMounted(() => {
    const saved = localStorage.getItem('theme')
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      isDark.value = true
    }
    applyTheme()
  })

  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  function toggle() {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    applyTheme()
  }

  watch(isDark, applyTheme)

  return { isDark, toggle }
}
```

**Step 3: 修改 index.html**

将 `<html lang="en">` 改为 `<html lang="zh-CN">`。

**Step 4: 验证**

Run: `cd frontend && npm run dev`
预期: 开发服务器启动正常，无编译错误。

**Step 5: Commit**

```bash
git add frontend/src/style.css frontend/src/composables/useDarkMode.js frontend/index.html
git commit -m "feat: add design tokens, dark mode composable, and custom animations"
```

---

### Task 2: Toast 通知系统

**Files:**
- Create: `frontend/src/composables/useToast.js`
- Create: `frontend/src/components/ToastNotification.vue`
- Modify: `frontend/src/App.vue` (挂载 Toast 容器)

**Step 1: 创建 toast composable**

```js
// frontend/src/composables/useToast.js
import { ref } from 'vue'

const toasts = ref([])
let nextId = 0

export function useToast() {
  function show(message, type = 'info', duration = 3000) {
    const id = nextId++
    toasts.value.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => remove(id), duration)
    }
  }

  function remove(id) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  function success(message) { show(message, 'success') }
  function error(message) { show(message, 'error') }
  function info(message) { show(message, 'info') }

  return { toasts, show, remove, success, error, info }
}
```

**Step 2: 创建 ToastNotification.vue**

使用 `TransitionGroup` 实现滑入/滑出动画，固定在右上角。支持 success（绿色 CheckCircle 图标）、error（红色 XCircle 图标）、info（蓝色 InformationCircle 图标）三种类型。每条 toast 带关闭按钮。

**Step 3: 在 App.vue 挂载 ToastNotification**

在根 `<div>` 内添加 `<ToastNotification />`，使其全局可用。

**Step 4: 验证**

在浏览器控制台或临时代码中调用 `useToast().success('测试')` 确认通知弹出正常。

**Step 5: Commit**

```bash
git add frontend/src/composables/useToast.js frontend/src/components/ToastNotification.vue frontend/src/App.vue
git commit -m "feat: add toast notification system"
```

---

### Task 3: BaseButton 和 BaseModal 基础组件

**Files:**
- Create: `frontend/src/components/BaseButton.vue`
- Create: `frontend/src/components/BaseModal.vue`
- Create: `frontend/src/components/ConfirmDialog.vue`

**Step 1: 创建 BaseButton.vue**

Props: `variant` (primary/secondary/danger/ghost)、`size` (sm/md/lg)、`loading`、`disabled`。
- primary: `bg-primary-600 text-white hover:bg-primary-700`
- secondary: `border border-gray-300 text-gray-700 hover:bg-gray-50` (dark: `border-gray-600 text-gray-300 hover:bg-gray-800`)
- danger: `bg-rose-600 text-white hover:bg-rose-700`
- ghost: `text-gray-600 hover:bg-gray-100`
- 所有变体: `rounded-button transition-all duration-150` + loading 时显示旋转 spinner 替换文字

**Step 2: 创建 BaseModal.vue**

基于 `@headlessui/vue` 的 `Dialog`、`DialogPanel`、`TransitionRoot`、`TransitionChild`：
- Props: `open` (Boolean)、`title` (String)、`maxWidth` ('sm'/'md'/'lg'，默认 'md')
- Emit: `close`
- 遮罩: `bg-black/40 backdrop-blur-sm`，点击遮罩触发 close
- 面板: `rounded-card-lg bg-white dark:bg-slate-800 shadow-xl`，淡入 + 从下往上滑入动画
- 标题栏: 标题文字 + 右上角关闭按钮（XMarkIcon）
- 内容通过默认 slot 传入，底部操作区通过 `#actions` slot 传入

**Step 3: 创建 ConfirmDialog.vue**

基于 BaseModal 封装：
- Props: `open`、`title`、`message`、`confirmText`（默认 '确定'）、`danger`（Boolean，用于删除确认）
- Emit: `confirm`、`cancel`
- 底部两个 BaseButton: 取消(secondary) + 确认(danger 或 primary)

**Step 4: 验证**

在某个页面临时挂载 BaseModal 和 ConfirmDialog，确认打开/关闭动画正常，HeadlessUI 焦点陷阱正常工作。

**Step 5: Commit**

```bash
git add frontend/src/components/BaseButton.vue frontend/src/components/BaseModal.vue frontend/src/components/ConfirmDialog.vue
git commit -m "feat: add BaseButton, BaseModal, and ConfirmDialog components"
```

---

### Task 4: SkeletonLoader 组件

**Files:**
- Create: `frontend/src/components/SkeletonLoader.vue`

**Step 1: 创建 SkeletonLoader.vue**

Props: `type` ('text'/'card'/'list')、`count`（重复数量，默认 1）
- text: 几行不同宽度的圆角灰色条
- card: 带标题行 + 两行内容 + 按钮区的卡片骨架
- list: 多行条目骨架
- 动画: `animate-pulse` 脉动效果
- Dark mode: `bg-gray-200 dark:bg-slate-700`

**Step 2: Commit**

```bash
git add frontend/src/components/SkeletonLoader.vue
git commit -m "feat: add SkeletonLoader component"
```

---

### Task 5: NavBar 重设计 + MobileNav 底部 Tab Bar

**Files:**
- Rewrite: `frontend/src/components/NavBar.vue`
- Create: `frontend/src/components/MobileNav.vue`
- Modify: `frontend/src/App.vue` (挂载 MobileNav + 调整布局)

**Step 1: 重写 NavBar.vue**

桌面端导航栏：
- 外层: `sticky top-0 z-30 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-gray-200 dark:border-slate-700`
- 内层: `max-w-6xl` (从 5xl 扩大)
- 左侧: 品牌标识 `🎯 CIPT 备考`（RouterLink to="/"），`text-lg font-bold text-primary-600`
- 中部: 主导航链接（首页、错题本、历史、单词本），用 `router-link-active` 实现当前页底部指示条
- 右侧:
  - 管理员下拉菜单（使用 HeadlessUI `Menu`），包含「题库管理」「题目管理」「系统设置」
  - Dark mode 切换按钮（SunIcon / MoonIcon），调用 `useDarkMode().toggle()`
  - 用户下拉菜单（HeadlessUI `Menu`），显示用户名 + 退出选项
- 移动端: 隐藏中部导航链接（`hidden md:flex`），保留品牌 + 右侧按钮

**Step 2: 创建 MobileNav.vue**

移动端底部 Tab Bar (`md:hidden`)：
- 外层: `fixed bottom-0 left-0 right-0 z-40 bg-white dark:bg-slate-900 border-t border-gray-200 dark:border-slate-700 safe-area-bottom`
- 5 个 Tab: 首页(HomeIcon)、错题(ExclamationCircleIcon)、历史(ClockIcon)、单词(BookOpenIcon)、更多(EllipsisHorizontalIcon)
- 每个 Tab: 图标 + 文字标签，当前页 `text-primary-600` + 图标微上浮 `transform -translate-y-0.5`
- "更多" Tab 点击弹出浮层菜单，包含管理员入口 + Dark mode + 退出

**Step 3: 修改 App.vue**

```vue
<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors">
    <NavBar v-if="authStore.isLoggedIn" />
    <main class="mx-auto max-w-6xl px-4 py-6 pb-24 md:pb-6">
      <router-view />
    </main>
    <MobileNav v-if="authStore.isLoggedIn" />
    <ToastNotification />
  </div>
</template>
```

- `max-w-5xl` → `max-w-6xl`
- 添加 `dark:bg-slate-900 transition-colors`
- 添加 `pb-24 md:pb-6` 为移动端底部 Tab Bar 留空间
- 挂载 `MobileNav` 和 `ToastNotification`

**Step 4: 验证**

- 桌面端: 导航栏正常显示，毛玻璃效果生效，下拉菜单可用
- 移动端 (浏览器 DevTools 切换): 底部 Tab Bar 显示，顶部导航链接隐藏
- Dark mode 切换正常

**Step 5: Commit**

```bash
git add frontend/src/components/NavBar.vue frontend/src/components/MobileNav.vue frontend/src/App.vue
git commit -m "feat: redesign navbar with glassmorphism and add mobile tab bar"
```

---

### Task 6: 登录/注册页面重设计

**Files:**
- Rewrite: `frontend/src/views/LoginView.vue`
- Rewrite: `frontend/src/views/RegisterView.vue`

**Step 1: 重写 LoginView.vue**

- 外层: 全屏渐变背景 `min-h-screen bg-gradient-to-br from-primary-50 via-white to-sky-50 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900`
- 品牌标识: `🎯` 图标 + `CIPT 备考` 标题 + `认证信息隐私技术师考试` 副标题
- 卡片: `rounded-2xl bg-white dark:bg-slate-800 p-8 shadow-lg`
- 输入框: 增加图标前缀（UserIcon、LockClosedIcon），圆角加大 `rounded-lg`
- 密码框: 增加显示/隐藏切换（EyeIcon/EyeSlashIcon）
- 按钮: 使用 BaseButton variant="primary" size="lg"，全宽
- 焦点效果: `focus:ring-2 focus:ring-primary-500/40`
- 错误提示: 保留红色提示框
- 底部链接: 保留切换到注册的链接
- 逻辑不变，仅更新模板和样式

**Step 2: 重写 RegisterView.vue**

与 LoginView 相同的视觉风格，增加邮箱字段的图标（EnvelopeIcon）。
逻辑不变。

**Step 3: 验证**

- 访问 `/login` 和 `/register`，确认渐变背景、卡片样式、图标显示正常
- 测试表单提交功能正常
- 切换 dark mode 确认深色主题下外观正常

**Step 4: Commit**

```bash
git add frontend/src/views/LoginView.vue frontend/src/views/RegisterView.vue
git commit -m "feat: redesign login and register pages with gradient background"
```

---

### Task 7: 首页重设计

**Files:**
- Rewrite: `frontend/src/views/HomeView.vue`

**Step 1: 重写 HomeView.vue**

**统计仪表盘:**
- 4 列网格: `grid-cols-2 md:grid-cols-4 gap-4`
- 4 张统计卡片: 题库数(indigo)、总题目(sky)、正确率(emerald)、待攻克错题(rose)
- 每张卡片: `rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-5`
  - 顶部: 4px 圆角颜色条纹 `h-1 rounded-t-card-lg bg-{color}-500`
  - 图标: heroicons 对应图标 + 颜色背景圆圈
  - 数字: `text-3xl font-bold text-gray-900 dark:text-white`
  - 标签: `text-sm text-gray-500 dark:text-gray-400`
- "待攻克"卡片可点击（RouterLink to="/wrong"）

**题库列表:**
- 加载中显示 `<SkeletonLoader type="card" :count="2" />`
- 空状态带插图文案
- 每个题库卡片: `rounded-card-lg bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-shadow p-6`
  - 标题行: 题库名称（大号加粗）+ 题目数
  - 描述行: `text-gray-500`
  - 按钮行: 使用 BaseButton (顺序练习=primary, 随机练习=secondary with emerald icon)
  - 按钮 hover 微放大: `hover:scale-[1.02] transition-transform`
- 替换 `alert()` 为 `useToast().error()`

**Step 2: 验证**

- 首页加载时显示骨架屏
- 统计卡片 4 列显示（桌面），2 列（移动端）
- 题库卡片样式正常，按钮可用
- Dark mode 下样式正常

**Step 3: Commit**

```bash
git add frontend/src/views/HomeView.vue
git commit -m "feat: redesign home page with dashboard stats and improved bank cards"
```

---

### Task 8: QuestionCard 答题卡片重设计

**Files:**
- Rewrite: `frontend/src/components/QuestionCard.vue`

**Step 1: 重写 QuestionCard.vue**

**卡片容器:**
- `rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6`

**题目信息栏:**
- 合并 `hideProgress` 的两段重复代码为一段
- 题号 + 题型徽章 (多选=amber, 判断=blue)
- 如果 `!hideProgress`: 显示进度条 `h-1.5 rounded-full bg-gradient-to-r from-primary-500 to-sky-400`

**选项卡片:**
- 每个选项: `rounded-card border-2 p-4 transition-all duration-200`
- 未选中: `border-gray-200 dark:border-slate-600 hover:border-gray-300 hover:bg-gray-50 dark:hover:bg-slate-700`
- 选中: `border-primary-500 bg-primary-50 dark:bg-primary-900/30 ring-2 ring-primary-500/20`，左侧出现 CheckIcon
- 正确: `border-emerald-500 bg-emerald-50 dark:bg-emerald-900/30`
- 错误: `border-rose-500 bg-rose-50 dark:bg-rose-900/30` + `animate-shake` 动效
- 未选中但正确（答错后）: `border-emerald-500 bg-emerald-50` 高亮正确答案

**答题反馈区:**
- 正确: `bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200`，前缀 CheckCircleIcon
- 错误: `bg-rose-50 dark:bg-rose-900/20 border border-rose-200`，前缀 XCircleIcon
- 翻译和解析区域保留

**AI 按钮行:**
- TranslateButton、ExplainButton、AddVocabButton 样式保留不变（后续 Task 中统一）

**操作栏:**
- 使用 BaseButton: 上一题(secondary)、提交答案(primary)、下一题(primary)、完成答题(variant="primary" 使用 emerald 色)

**Step 2: 验证**

- 开始一次答题，确认选项选中/取消样式正常
- 提交答案后确认正确/错误动效正常
- Dark mode 下样式正常

**Step 3: Commit**

```bash
git add frontend/src/components/QuestionCard.vue
git commit -m "feat: redesign QuestionCard with enhanced option cards and feedback animations"
```

---

### Task 9: QuizView 答题页重设计

**Files:**
- Rewrite: `frontend/src/views/QuizView.vue`

**Step 1: 重写 QuizView.vue**

**顶部信息栏:**
- 题库名称 + 进度标签 `rounded-full bg-primary-100 dark:bg-primary-900/40 px-3 py-0.5 text-sm font-medium text-primary-700 dark:text-primary-300`
- 进度条: `h-1.5 rounded-full bg-gradient-to-r from-primary-500 to-sky-400 transition-all duration-300`
- 右侧: "自动下一题" checkbox + "结束答题" 按钮（BaseButton secondary + XMarkIcon）

**左侧导航面板:**
- `sticky top-20` (给 navbar 留空间)
- `rounded-card-lg bg-white dark:bg-slate-800 shadow-card overflow-hidden`
- 每个题号: 保留现有的状态颜色标记，更新为 design token 颜色
- 底部统计: 正确(emerald)/错误(rose)/未答(gray) 带圆点

**移动端底部题号导航:**
- 保留现有结构，更新颜色为 design token
- 当前题: `bg-primary-600 text-white ring-2 ring-primary-300`

**替换 alert() 为 toast:**
- `handleSubmit` 中的 `alert(...)` → `useToast().error(...)`
- `handleFinish` 中的 `alert(...)` → `useToast().error(...)`

**Step 2: 验证**

- 答题页布局正常，侧边栏 sticky 定位正常
- 移动端底部导航正常
- 答题提交失败时显示 toast 而非 alert

**Step 3: Commit**

```bash
git add frontend/src/views/QuizView.vue
git commit -m "feat: redesign quiz page with improved navigation and toast notifications"
```

---

### Task 10: 答题结果页重设计

**Files:**
- Rewrite: `frontend/src/views/QuizResultView.vue`

**Step 1: 重写 QuizResultView.vue**

**加载状态:** 使用 SkeletonLoader

**结果卡片:**
- `rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-8`
- 标题: `🎉 练习完成！` (≥80%) 或 `📊 练习完成` (<80%)
- 正确率圆环: CSS 实现的环形进度条，使用 `conic-gradient`，颜色: ≥80% emerald / ≥60% amber / <60% rose
- 三列统计: 总题数、正确数（emerald）、错误数（rose），`grid-cols-3 gap-4`
- 数字: `text-2xl font-bold`

**答题详情:**
- 每题一行: 正确=`bg-emerald-50 dark:bg-emerald-900/20`，错误=`bg-rose-50 dark:bg-rose-900/20`
- 前缀图标: CheckCircleIcon / XCircleIcon

**底部按钮:**
- 三个按钮: 返回首页(secondary)、查看错题(primary)、再来一次(secondary with emerald)
- "再来一次" 按钮: 调用 quizStore.startQuiz 同题库同模式重新开始

**Step 2: 验证**

- 完成一次答题后跳转到结果页
- 正确率圆环显示正常
- "再来一次" 按钮功能正常

**Step 3: Commit**

```bash
git add frontend/src/views/QuizResultView.vue
git commit -m "feat: redesign quiz result page with progress ring and retry button"
```

---

### Task 11: 错题本重设计

**Files:**
- Rewrite: `frontend/src/views/WrongAnswersView.vue`

**Step 1: 重写 WrongAnswersView.vue**

**顶部区域:**
- 标题 + 统计摘要: `12 道未掌握 · 8 道已掌握`
- 掌握率进度条: `h-2 rounded-full bg-gray-200 dark:bg-slate-700`，填充 `bg-emerald-500`
- 筛选: BaseButton secondary + 下拉菜单（HeadlessUI Menu）替代原生 `<select>`
- 错题练习: BaseButton primary

**加载状态:** SkeletonLoader

**空状态:** 带鼓励文案

**错题卡片列表:**
- 每张错题独立卡片: `rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-5`
- 展开/折叠保留，使用 `<Transition>` 包裹详情区域
- 标记掌握: BaseButton secondary size="sm"，点击后卡片 `transition-all duration-300 opacity-0 scale-95` 消失动效
- 展开详情内的选项/解析/AI 按钮保留现有逻辑

**替换 alert() 为 toast:**
- `practiceWrong` 中的 `alert(...)` → `useToast().error(...)`

**Step 2: 验证**

- 错题列表加载、展开/折叠正常
- 标记掌握后卡片消失动效正常
- 筛选下拉菜单正常

**Step 3: Commit**

```bash
git add frontend/src/views/WrongAnswersView.vue
git commit -m "feat: redesign wrong answers page with mastery progress and card layout"
```

---

### Task 12: 答题历史页重设计

**Files:**
- Rewrite: `frontend/src/views/HistoryView.vue`

**Step 1: 重写 HistoryView.vue**

**加载状态:** SkeletonLoader

**历史记录列表:**
- 每条记录: `rounded-card bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-5`
- 左侧增加小圆环正确率图标 (CSS mini ring，颜色编码)
- 保留现有信息布局

**清空历史:**
- 使用 ConfirmDialog 替代原生 `confirm()`，danger 模式
- 替换 `alert(...)` 为 `useToast().error(...)` / `useToast().success('历史已清空')`

**分页:**
- 保留现有分页逻辑，更新按钮样式为 BaseButton

**Step 2: 验证**

- 历史列表显示正常
- 清空历史弹出 ConfirmDialog 而非原生 confirm
- Dark mode 下样式正常

**Step 3: Commit**

```bash
git add frontend/src/views/HistoryView.vue
git commit -m "feat: redesign history page with accuracy rings and confirm dialog"
```

---

### Task 13: 单词本页面样式更新

**Files:**
- Modify: `frontend/src/views/VocabularyView.vue`

**Step 1: 更新 VocabularyView.vue 样式**

这个页面已经比较完善，只做样式对齐：
- 卡片样式统一为 `rounded-card-lg shadow-card`
- 添加 `dark:` 样式变体
- 字母导航条: 更新高亮色为 `bg-primary-600`
- "回到顶部" 浮动按钮: `bg-primary-600 dark:bg-primary-500`
- 替换页面中所有 `alert()` 为 `useToast().error()`
- 管理员操作按钮统一为 BaseButton

**Step 2: Commit**

```bash
git add frontend/src/views/VocabularyView.vue
git commit -m "feat: update vocabulary page with design system tokens and dark mode"
```

---

### Task 14: 管理页面重设计

**Files:**
- Rewrite: `frontend/src/views/AdminBanksView.vue`
- Rewrite: `frontend/src/views/AdminQuestionsView.vue`
- Modify: `frontend/src/views/AdminSettingsView.vue`

**Step 1: 重写 AdminBanksView.vue**

- 替换 3 个内联模态框为 BaseModal:
  - 创建题库 modal → `<BaseModal :open="showCreate" title="创建题库" @close="showCreate = false">`
  - 编辑题库 modal → `<BaseModal :open="showEdit" title="编辑题库" @close="showEdit = false">`
  - 导入题目 modal → `<BaseModal :open="showImport" title="导入题目" maxWidth="lg" @close="showImport = false">`
- 替换 `confirm('确定删除？')` 为 ConfirmDialog (danger 模式)
- 所有按钮替换为 BaseButton
- 卡片样式更新: `rounded-card-lg shadow-card`
- 添加 dark mode 样式

**Step 2: 重写 AdminQuestionsView.vue**

- 替换 2 个内联模态框为 BaseModal（添加题目、编辑题目）
- 替换 `confirm()` 为 ConfirmDialog
- 替换所有 `alert()` 为 `useToast()`
- 分页统一: 添加上一页/下一页按钮，使用与 HistoryView 相同的分页逻辑
- 按钮替换为 BaseButton
- 添加 dark mode 样式

**Step 3: 更新 AdminSettingsView.vue**

- 卡片样式: `rounded-card-lg shadow-card`
- 按钮替换为 BaseButton
- 保存成功/失败反馈改为 toast
- 添加 dark mode 样式

**Step 4: 验证**

- 管理页面所有模态框正常打开/关闭，带动画
- 删除操作弹出 ConfirmDialog
- 所有 alert 已替换为 toast

**Step 5: Commit**

```bash
git add frontend/src/views/AdminBanksView.vue frontend/src/views/AdminQuestionsView.vue frontend/src/views/AdminSettingsView.vue
git commit -m "feat: redesign admin pages with BaseModal, ConfirmDialog, and toast"
```

---

### Task 15: AI 按钮组件样式统一 + alert 替换

**Files:**
- Modify: `frontend/src/components/TranslateButton.vue`
- Modify: `frontend/src/components/ExplainButton.vue`
- Modify: `frontend/src/components/AddVocabButton.vue`
- Modify: `frontend/src/components/FileUpload.vue`

**Step 1: 更新按钮组件**

所有 4 个组件:
- 替换 `alert()` 为 `useToast().error()`
- 按钮样式统一为 secondary 风格，带 heroicons 图标:
  - TranslateButton: LanguageIcon + `翻译`/`隐藏翻译`
  - ExplainButton: LightBulbIcon + `AI 解析`
  - AddVocabButton: BookmarkIcon + `收藏单词`
  - FileUpload: ArrowUpTrayIcon
- 添加 dark mode 样式
- ExplainButton 的解析展示区: `bg-sky-50 dark:bg-sky-900/20 border border-sky-200 dark:border-sky-800`
- AddVocabButton 的弹出框: 添加 dark mode 样式 + `shadow-lg`

**Step 2: Commit**

```bash
git add frontend/src/components/TranslateButton.vue frontend/src/components/ExplainButton.vue frontend/src/components/AddVocabButton.vue frontend/src/components/FileUpload.vue
git commit -m "feat: unify AI button styles with heroicons and replace alerts with toast"
```

---

### Task 16: 页面过渡动画 + 最终收尾

**Files:**
- Modify: `frontend/src/App.vue` (添加路由过渡)
- Verify all pages

**Step 1: 添加路由过渡动画**

在 App.vue 中使用 `<router-view v-slot="{ Component }">` + `<Transition>` 包裹:
```vue
<router-view v-slot="{ Component }">
  <transition name="fade" mode="out-in">
    <component :is="Component" />
  </transition>
</router-view>
```

在 style.css 中添加:
```css
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
```

**Step 2: 全面验证**

逐页检查:
- [ ] 登录页: 渐变背景、dark mode、表单功能
- [ ] 注册页: 同上
- [ ] 首页: 统计卡片、题库列表、骨架屏、dark mode
- [ ] 答题页: 侧边栏、选项交互、答题反馈动效、移动端导航
- [ ] 结果页: 正确率圆环、详情列表、再来一次
- [ ] 错题本: 掌握率进度条、展开/折叠、标记掌握动效
- [ ] 答题历史: 正确率圆环、分页、清空确认
- [ ] 单词本: 字母导航、dark mode
- [ ] 管理页面: 模态框动画、确认对话框
- [ ] 移动端: 底部 Tab Bar、所有页面响应式
- [ ] Dark mode: 所有页面深色主题正常
- [ ] Toast: 所有错误/成功提示使用 toast

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: add page transition animations and final UI polish"
```

---

## 实施顺序总结

| Task | 内容 | 依赖 |
|------|------|------|
| 1 | Design Tokens + Dark Mode | 无 |
| 2 | Toast 通知系统 | 无 |
| 3 | BaseButton + BaseModal + ConfirmDialog | 无 |
| 4 | SkeletonLoader | 无 |
| 5 | NavBar + MobileNav | 1, 2 |
| 6 | 登录/注册页 | 1, 3 |
| 7 | 首页 | 1, 2, 3, 4 |
| 8 | QuestionCard | 1, 3 |
| 9 | QuizView | 1, 2, 8 |
| 10 | 答题结果页 | 1, 3, 4 |
| 11 | 错题本 | 1, 2, 3, 4 |
| 12 | 答题历史 | 1, 2, 3, 4 |
| 13 | 单词本 | 1, 2, 3 |
| 14 | 管理页面 | 1, 2, 3 |
| 15 | AI 按钮组件 | 1, 2 |
| 16 | 页面过渡 + 收尾 | 1-15 |
