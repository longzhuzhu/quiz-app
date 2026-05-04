# 类型安全

> 本项目的类型约定与防护模式。

---

## 纯 JavaScript 项目

整个项目使用纯 JavaScript，无 `.ts` / `.tsx` 文件。不使用 TypeScript 编译器或类型注解。

---

## defineProps 运行时声明

使用 `defineProps()` 对象语法（运行时声明），不用 `defineProps<T>()` 泛型语法：

```javascript
// 正确 — 运行时声明
const props = defineProps({
  questionId: Number,
  hideProgress: { type: Boolean, default: false },
})

// 不使用 — 泛型语法
// const props = defineProps<{ questionId: number, hideProgress?: boolean }>()
```

真实示例：`frontend/src/components/TranslateButton.vue` 行20-24、`frontend/src/components/QuestionCard.vue` 行120-129

---

## Ref 初始值暗示类型

通过 `ref()` 的初始值隐式确定响应式变量的类型：

| 声明 | 暗示类型 | 常见场景 |
|------|---------|---------|
| `ref(null)` | 可空对象 | API 响应数据、详情对象 |
| `ref('')` | 字符串 | 表单输入、搜索关键词 |
| `ref(false)` | 布尔 | loading、开关、弹窗显隐 |
| `ref(0)` | 数值 | 计数器、分页页码 |
| `ref([])` | 数组 | 列表数据 |
| `reactive({})` | 对象 | 映射、状态聚合 |

---

## API 响应无类型定义

没有独立的 API 响应类型或接口定义文件。靠约定 + 可选链防护访问嵌套属性：

```javascript
e.response?.data?.error
job.file_type?.toUpperCase() ?? ''
```

---

## reactive 用作映射

`reactive({})` 常用作键值映射（键为 ID / index），有两种典型用法：

### 索引映射：index -> boolean

```javascript
// QuizView.vue — 记录每题的答题结果
const answerResults = reactive({})          // { [index]: true/false }

// 会话恢复映射：questionId -> user_answer
const questionAnswerMap = reactive({})
const questionResultMap = reactive({})
```

真实示例：`frontend/src/views/QuizView.vue` 行146-151

### 进度状态聚合

```javascript
// VocabularyView.vue — 轮询进度
const professionalJobState = reactive({ progressDone: 0, progressTotal: 0 })
const professionalJobError = ref('')

const frequentJobState = reactive({ progressDone: 0, progressTotal: 0 })
const frequentJobError = ref('')
```

真实示例：`frontend/src/views/VocabularyView.vue` 行501-506

### 表单对象

```javascript
const newWord = reactive({ term: '', term_zh: '', definition: '', definition_zh: '' })
```

真实示例：`frontend/src/views/VocabularyView.vue` 行510

---

## 防护模式

### 可选链访问 API 错误信息

```javascript
toast.error(e.response?.data?.error || '操作失败')
```

全项目统一使用此模式提取后端错误消息，不使用类型守卫或解构。

### Set 作为集合

```javascript
const expandedIds = reactive(new Set())
```

真实示例：`frontend/src/views/VocabularyView.vue` 行509
