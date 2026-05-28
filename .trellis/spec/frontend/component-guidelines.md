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
- `frontend/src/components/ExplainButton.vue` 行14-51
- `frontend/src/components/AddVocabButton.vue` 行40-90

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
