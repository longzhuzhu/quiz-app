# 组件模式

> 本项目组件的编写约定与实际模式。

---

## 组件结构

全量 `<script setup>` 语法，无 Options API 混用。模板、脚本、样式三段式，组件文件内不使用 `<style>` 块（样式统一用 Tailwind 内联类）。

```vue
<template>
  <!-- 模板 -->
</template>

<script setup>
// 导入 + 响应式声明 + 方法，全部在顶层
</script>
```

真实示例：`frontend/src/components/BaseButton.vue` 行22-64（script setup + defineProps）

---

## Props 约定

使用 `defineProps()` 对象语法（运行时声明），不用泛型语法 `defineProps<T>()`。

### 简单类型：直接写构造函数

```javascript
const props = defineProps({
  questionId: Number,
  hasTranslation: Boolean,
  show: Boolean,
})
```

真实示例：`frontend/src/components/TranslateButton.vue` 行20-24

### 带默认值 / 校验：对象形式含 type / default / validator

```javascript
const props = defineProps({
  question: Object,
  currentIndex: Number,
  total: Number,
  hideProgress: { type: Boolean, default: false },
  initialAnswer: { type: String, default: '' },
  initialResult: { type: Object, default: null },
  examMode: { type: Boolean, default: false },
  answerCount: { type: Number, default: 0 },
})
```

真实示例：`frontend/src/components/QuestionCard.vue` 行120-129

### 带 validator 的基础组件

```javascript
const props = defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'secondary', 'danger', 'ghost'].includes(v),
  },
  maxWidth: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})
```

真实示例：`frontend/src/components/BaseButton.vue` 行25-44、`frontend/src/components/BaseModal.vue` 行71-85

---

## Emits 约定

使用 `defineEmits()` 字符串数组声明：

```javascript
defineEmits(['close'])

const emit = defineEmits(['submit', 'next', 'prev', 'finish', 'translated'])
```

- 模板中用 `$emit`：`@close="$emit('close')"`（`frontend/src/components/BaseModal.vue` 行3）
- 脚本中用 `emit()` 函数：`emit('submit', answer, callback)`（`frontend/src/components/QuestionCard.vue` 行209）

真实示例：`frontend/src/components/BaseModal.vue` 行87、`frontend/src/components/QuestionCard.vue` 行131

---

## 智能组件模式

业务组件 `TranslateButton`、`ExplainButton`、`AddVocabButton` 采用"智能组件"模式：

- **内部直接调用 `client` 发 API**，不通过 Store 或 props 传入回调
- **自己管理 `loading` 状态**，内部 `ref(false)`
- **通过 `emit` 向上传递结果**，不修改外部数据

```javascript
// TranslateButton.vue — 典型智能组件
const loading = ref(false)
async function handleClick() {
  loading.value = true
  try {
    const res = await client.post('/ai/translate', { question_id: props.questionId })
    emit('translated', res.data)
  } catch (e) {
    toast.error(e.response?.data?.error || '翻译失败')
  } finally {
    loading.value = false
  }
}
```

真实示例：
- `frontend/src/components/TranslateButton.vue` 行12-43
- `frontend/src/components/ExplainButton.vue` 行14-79
- `frontend/src/components/AddVocabButton.vue` 行40-90

`ExplainButton` 额外约定：未显示时文案“AI 解析”、可短路由中文缓存；已显示时文案“更新解析”，请求必须带 `force: true`。禁用只看 `loading`。FastAPI 错误读 `e.response?.data?.detail`。更新失败固定提示“更新失败，已保留原解析”。

`QuestionCard` 答题面约定（2026-10 受控化重构后）：卡片是**受控展示组件**，答题状态归 `QuizView` 所有——草稿 `drafts[questionId]` 与已提交 `questionAnswerMap/questionResultMap` 都在视图层，卡片经 props 读取、经 emits 写回。props：`selectedAnswers`（当前草稿）、`submittedAnswer`（已提交答案字符串，已答展示锚点）、`result`（对错结果对象）、`editing`（重新作答中）、`submitting`、`showTranslation`（会话级翻译偏好，切题不重置）。emits：`update:selectedAnswers`、`update:showTranslation`、`start-editing`、`cancel-editing`、`translated`、`answer-corrected`。提交动作由 `QuizView` 的固定底栏触发，卡内不放操作按钮。要点：

- 选项激活以原生 input 的 `change` 为唯一状态入口；选项行用 `<component :is="interactive ? 'label' : 'div'">`，已答锁定态渲染为 div（带 `question-option` class），input 加 `pointer-events-none`。键盘 A–Z/数字、Enter 由 `QuizView` 的 window keydown 处理，焦点在输入控件上时不拦截。
- 已答展示：全部选项保持正常对比度（不降透明度），用边框 + 「你的选择 / 正确答案 / 你的答案 ✓」文本标签表达结果；examMode 只打「已选」标签。
- 反馈区 `role="status" aria-live="polite"`，先给「你的答案 → 正确答案」对照；AI 解析可折叠、默认收起（`explainOpen`，切题重置）。
- 更正答案流程保留在卡内：`correctionMode` 下点选项只改待写入的正确答案，不得清掉对错反馈；写入走 `PUT /questions/{id}/correct-answer`（body 带 `correct_answer`、`session_id`、`local_date`），用 `correctionGeneration` 丢弃切题后的过期响应；确认框复用 `ConfirmDialog`。复制是页眉图标按钮（`aria-label="复制题目"`），模拟考试也保留。

父组件写回时，`QuestionCard` 的 `result` 必须与 `QuizView.questionResultMap[questionId]` 是**同一对象**。若提交时把 API 响应另存一份拷贝，更新解析后切题再切回会显示旧文案。`answer-corrected` 也必须就地改这份映射，不能另存拷贝。

`QuizView` 答题页约定：路由 meta 带 `quizFocus: true`（`App.vue` 据此隐藏 `MobileNav`，避免双底栏）；底部固定操作条是唯一主操作区（上一题 / 位置与完成度摘要 / 主按钮），主按钮状态机为 未答→提交答案、已答→下一题、最后一题→完成答题、重新作答中→提交答案；进度条按已提交数计算，「第 n/N 题」只表达位置；未提交草稿按 questionId 存 `drafts`，不计入已答统计；自动下一题仅在答对且开启偏好时触发（1.5s，可取消），答错停留；手机题号网格收敛为按需展开面板（触摸目标 ≥44px），「结束答题」入口在桌面侧栏与手机面板底部，有未答题时弹确认。

### 状态边界约定：空态 / 失败态

列表页（QuizView、WrongAnswersView、HistoryView）加载失败必须显示可重试的内联错误态（`loadError` + 重新加载按钮），不允许把网络失败渲染成「暂无数据」空态；空态只在请求成功后展示。

---

## 日期序列化

后端统一 `.isoformat()` 输出，前端 `new Date()` 解析。不使用第三方日期库。

---

## 样式

- 全量 Tailwind CSS 内联类，无 `<style>` 块
- 深色模式通过 `dark:` 变体，由 `useDarkMode` composable 控制 `document.documentElement.classList.toggle('dark')`
- 自定义圆角 token：`rounded-button`、`rounded-card`、`rounded-card-lg`

### 同组操作按钮视觉语言

同一个按钮组里的操作按钮要保持图标/文案风格一致：如果相邻按钮使用 emoji 或符号前缀，新加入的同级操作按钮也要使用同类前缀，不能只满足功能而忽略视觉节奏。

```vue
<!-- Correct: 同组按钮都使用符号前缀 -->
<BaseButton>▶ 继续答题</BaseButton>
<BaseButton>▶ 顺序练习</BaseButton>
<BaseButton>🔀 随机练习</BaseButton>

<!-- Wrong: 同组按钮中只有新增按钮没有前缀 -->
<BaseButton>继续答题</BaseButton>
<BaseButton>▶ 顺序练习</BaseButton>
<BaseButton>🔀 随机练习</BaseButton>
```

视觉一致性同样覆盖按钮高度：当按钮组里某个按钮被 wrapper（例如附带进度文案 `<span>` 的 `flex flex-col`）包裹，而其他按钮直接渲染时，外层 flex 容器默认 `items-stretch` 会把直接按钮拉伸到 wrapper 总高度，造成按钮自身和带 wrapper 的按钮视觉高度不一致。这种情况下外层容器要显式声明 `items-start`，让所有按钮按 `size` 决定自身高度并顶部对齐。

```vue
<!-- Correct: 外层 items-start，按钮按自身 sm size 等高 -->
<div class="flex gap-2 flex-wrap flex-shrink-0 items-start">
  <div class="flex flex-col gap-1">
    <BaseButton size="sm">▶ 继续答题</BaseButton>
    <span class="text-xs">已答 5/30｜顺序练习</span>
  </div>
  <BaseButton size="sm">▶ 顺序练习</BaseButton>
  <BaseButton size="sm">🔀 随机练习</BaseButton>
</div>

<!-- Wrong: 没有 items-start，直接按钮被 stretch 到 wrapper 高度，按钮间高低不一 -->
<div class="flex gap-2 flex-wrap flex-shrink-0">
  <div class="flex flex-col gap-1">
    <BaseButton size="sm">▶ 继续答题</BaseButton>
    <span class="text-xs">已答 5/30｜顺序练习</span>
  </div>
  <BaseButton size="sm">▶ 顺序练习</BaseButton>
  <BaseButton size="sm">🔀 随机练习</BaseButton>
</div>
```

真实示例：`frontend/src/views/HomeView.vue` 行105。

视觉一致性的更高优先建议：**避免给单个按钮附加 wrapper subtitle**。当某个按钮需要附带状态/进度类信息时，首选把状态信息放进所在卡片的 micro-info 信息流（例如题库卡片左侧 `XX 道题目` 那一行末尾，用 `｜` 分隔追加），而不是在按钮下方挂 `<span>` 副标题。后者会让小字成为视觉孤儿，跟同组其他按钮无关联，并且强迫使用 wrapper 容器，引入按钮组高度对齐的次生问题。

```vue
<!-- Correct: 状态信息进卡片 micro-info 行，按钮组平级 -->
<div class="min-w-0">
  <h3>{{ bank.name }}</h3>
  <p class="text-xs">
    {{ bank.question_count }} 道题目<template v-if="incompleteSession"> ｜ 已答 {{ incompleteSession.answered_count }}/{{ incompleteSession.total_questions }} ｜ {{ modeLabel(incompleteSession.mode) }}</template>
  </p>
</div>
<div class="flex gap-2 flex-wrap flex-shrink-0">
  <BaseButton v-if="incompleteSession" size="sm">▶ 继续答题</BaseButton>
  <BaseButton size="sm">▶ 顺序练习</BaseButton>
  <BaseButton size="sm">🔀 随机练习</BaseButton>
</div>

<!-- Wrong: 按钮下方 wrapper subtitle，小字孤立 + 按钮组高度问题 -->
<div class="flex gap-2 flex-wrap flex-shrink-0">
  <div class="flex flex-col gap-1">
    <BaseButton size="sm">▶ 继续答题</BaseButton>
    <span class="text-xs">已答 5/30｜顺序练习</span>
  </div>
  <BaseButton size="sm">▶ 顺序练习</BaseButton>
</div>
```
