# 目录结构

> 前端代码的文件组织与命名规则。

---

## 目录布局

```
frontend/src/
  api/         — Axios 客户端配置（单文件 client.js）
  assets/      — 静态资源
  components/  — 可复用 UI 组件（12 个 .vue 文件）
  composables/ — 自定义 Composition API hooks（3 个 .js 文件）
  router/      — 路由配置（单文件 index.js）
  stores/      — Pinia 状态管理（3 个 .js 文件）
  utils/       — 工具函数（2 个 .js 文件）
  views/       — 页面级视图组件（16 个 .vue 文件）
```

---

## 文件命名规则

| 目录 | 规则 | 示例 |
|------|------|------|
| `views/` | PascalCase + `View` 后缀 | `HomeView.vue`、`QuizResultView.vue`、`AdminBanksView.vue` |
| `components/` | PascalCase，基础组件带 `Base` 前缀 | `BaseButton.vue`、`BaseModal.vue`、`QuestionCard.vue` |
| `stores/` | camelCase + `.js` | `auth.js`、`quiz.js`、`bank.js` |
| `composables/` | `use` 前缀 + camelCase + `.js` | `useDarkMode.js`、`useToast.js`、`useBackgroundJob.js` |
| `utils/` | camelCase + `.js` | `jobStatus.js`、`passwordValidation.js` |

---

## 组件分类

| 分类 | 组件 | 特征 |
|------|------|------|
| 原子组件 | `BaseButton`、`SkeletonLoader` | 无业务逻辑，纯 UI 展示 |
| 分子组件 | `BaseModal`、`ConfirmDialog`、`ToastNotification`、`FileUpload` | 组合原子组件，带交互逻辑 |
| 业务组件 | `QuestionCard`、`TranslateButton`、`ExplainButton`、`AddVocabButton` | 内部直接调 API，自己管 loading（智能组件） |
| 布局组件 | `NavBar`、`MobileNav` | 页面级布局框架 |

---

## 模块组织

- `api/` 只有一个 `client.js`，无独立 API 函数层，Store 和 View 直接用 `client`
- `composables/` 每个文件导出一个 `use*` 函数
- `stores/` 每个文件导出一个 `use*Store`，Store 之间无直接 import
- `views/` 与路由一一对应，路由在 `router/index.js` 中用懒加载注册
- `utils/` 纯函数，无 Vue / DOM 依赖

---

## 完整文件列表

### components/（12 个）

- `AddVocabButton.vue` — 收藏单词按钮（智能组件）
- `BaseButton.vue` — 基础按钮
- `BaseModal.vue` — 基础弹窗
- `ConfirmDialog.vue` — 确认对话框
- `ExplainButton.vue` — AI 解析按钮（智能组件）
- `FileUpload.vue` — 文件上传
- `MobileNav.vue` — 移动端导航
- `NavBar.vue` — 顶部导航栏
- `QuestionCard.vue` — 答题卡片
- `SkeletonLoader.vue` — 骨架屏
- `ToastNotification.vue` — Toast 通知
- `TranslateButton.vue` — AI 翻译按钮（智能组件）

### composables/（3 个）

- `useBackgroundJob.js` — 后台任务轮询（实例级）
- `useDarkMode.js` — 深色模式（模块级单例）
- `useToast.js` — Toast 通知（模块级单例）

### stores/（3 个）

- `auth.js` — 认证 + localStorage 持久化
- `bank.js` — 题库列表
- `quiz.js` — 答题会话

### views/（16 个）

- `AccountView.vue`、`AdminBanksView.vue`、`AdminQuestionsView.vue`、`AdminSettingsView.vue`、`AdminUsersView.vue`
- `HistoryView.vue`、`HomeView.vue`、`ImportJobDetailView.vue`、`ImportJobsView.vue`、`ImportReviewView.vue`
- `LoginView.vue`、`QuizResultView.vue`、`QuizView.vue`、`RegisterView.vue`、`VocabularyView.vue`、`WrongAnswersView.vue`

### utils/（2 个）

- `jobStatus.js` — 任务状态格式化
- `passwordValidation.js` — 密码验证规则
