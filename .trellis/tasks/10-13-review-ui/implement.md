# 执行计划：统一只读复盘页面

需求见本任务 `prd.md`；技术设计见父任务 `design.md` 第 5.1、5.2 节。

## 0. 开始前检查（依赖门禁）

```bash
python3 ./.trellis/scripts/task.py current     # 应为 10-13-review-ui
grep -n 'status_unknown\|has_snapshot\|"index"' backend/app/api/routes/quiz.py
```

**前置：`10-13-review-api` 必须已定契约。** 若响应中尚无 `index` / `status` / `status_unknown` / `has_snapshot`，停止并先完成该子任务。

同时与 `10-13-result-page` 确认文件归属，避免并行改同一文件：

| 文件 | 归属 |
| --- | --- |
| `frontend/src/views/QuizReviewView.vue`（新建） | 本任务 |
| `frontend/src/components/ReviewQuestionCard.vue`（新建） | 本任务 |
| `frontend/src/router/index.js` 新增路由 | 本任务 |
| `frontend/src/views/QuizResultView.vue` | `result-page` |
| `frontend/src/stores/quiz.js` | `result-page` |

若 `result-page` 需要从复盘页反向跳转，接口由本任务提供、对方消费。

## 1. 只读题目组件

新建 `frontend/src/components/ReviewQuestionCard.vue`。

参考两个来源，但**不要**直接复用 `QuestionCard.vue`：

- 只读选项渲染与正确项高亮的既有写法：`frontend/src/views/WrongAnswersView.vue:103-145`（`isCorrectOption` 在 `:193-195`）。
- 答题页的翻译／解析／收藏区块：`QuestionCard.vue:61-64`（`TranslateButton` + `AddVocabButton`）、`:94-95`（`QuestionExplanation`）。

Props 建议（保持最小集）：

```
question（含 id/index/content/options/user_answer/is_correct/correct_answer/status/status_unknown）,
total, currentIndex
```

要点：

- **无 emits 到作答链路**；不 import `/quiz/answer` 或 correct-answer 调用。
- 选项渲染为纯展示，**不绑定点击处理器**——不要写「看起来可点但无效果」的按钮。
- 未答：显示「未答」标签，不渲染用户选择，判定样式用中性色而非错误红。
- `status_unknown`：显示「未知／不可用」中性标签。
- **先看 `status_unknown` 再看 `status`。** 后端在无法核实状态时返回
  `status="unanswered"` + `status_unknown=true`，此处的 `status` **只是占位**，不代表「确实未答」。
  渲染顺序反了会把「不可核实」显示成「未答」。筛选时同样据此归类。
- **不得用布尔兜底**把缺失的 `is_correct` 当作 `false`（Issue #63 的根因就是这个模式）。
  `is_correct` 为 `null` 时按 `status_unknown` 分支处理。
- 最终选择与当场正确答案分别标注（如「你的答案」「当场正确答案」），视觉可区分。

## 2. 复盘页面

新建 `frontend/src/views/QuizReviewView.vue`。

### 2.1 数据加载

```js
const res = await client.get(`/quiz/session/${route.params.sessionId}`)
```

直接调 `client`（与 `QuizView.vue:269`、`QuizResultView.vue:120` 的既有风格一致）；**不要**为一次性读取新增 store action（若 `result-page` 已抽出共享 action，则复用它）。

加载中显示骨架屏（参考 `QuizResultView.vue:4-5` 的 `SkeletonLoader`），失败显示可返回的提示（参考 `:9-13`）。

### 2.2 页面结构

按 `QuizView.vue:36-140` 的结构复刻题号导航：

- 桌面侧栏 `hidden md:block w-48`，逐题按钮 + 状态徽标。
- 移动端 `md:hidden fixed bottom-14` 横向滚动。
- 内容区渲染当前题的 `ReviewQuestionCard`。

题号按钮的状态色建议复用 `QuizView.vue:350-363` 的配色思路，但**未答用中性灰**、`status_unknown` 用中性色，不用错误红。

### 2.3 筛选

- 状态：`filter` ∈ `all | correct | wrong | unanswered`。
- 初始值从 `route.query.filter` 读取，非法值回落 `all`。
- 可见集合 = 按 filter 过滤后的题目数组；**显示的题号用元素自带的 `index`**，不是过滤后下标。
- 切换筛选时把当前题重置为可见集合的第一题（若当前题仍在可见集合中则保持）。
- 空集合时显示空状态文案，不跳转。

### 2.4 长内容与固定导航

- 题干、选项不设 `truncate`、不设 `max-h-*` 截断。
- 移动端底部固定导航需给内容区预留底部内边距，避免遮挡最后一屏内容。

## 3. 路由

`frontend/src/router/index.js` 新增：

```js
{ path: '/exams/:examSlug/quiz/:sessionId/review', name: 'ExamQuizReview',
  component: () => import('../views/QuizReviewView.vue'),
  meta: { auth: true, examScoped: true } },
```

若 `utils/examRoutes.js` 的 `routeKind` 需要识别该路由（例如返回 dashboard 来源），按 `result-page` 的约定处理，避免双方同时改该文件。

## 4. 测试

### 4.1 组件／契约测试（`node --test`）

参考 `frontend/tests/questionTimerPresentation.test.js` 的写法，新增专注测试覆盖：

- 四种筛选下可见集合与**题号不重编号**。
- `status_unknown` 与 `unanswered` 的展示分支。
- `has_snapshot=false` 的兼容提示渲染。

### 4.2 端到端（真实浏览器 + 隔离 PostgreSQL）

参考 `frontend/tests/vocabularyStudyE2E.test.js` 与 `helpers/studyBrowser.js`、`helpers/studyBackend.js`，新增 `frontend/tests/quizReviewE2E.test.js`，覆盖：

1. 模拟 10 题 7 对 3 错完成后进入复盘：显示 7 对 3 错，正确答案非空（回归 Issue #63 原始症状）。
2. 页面上**不存在**「提交答案」「完成答题」「更正答案」按钮（用 `find` 断言元素不存在）。
3. 点击选项后断言无网络请求发出、选择状态不变。
4. 未答题显示「未答」，不进错误筛选。
5. 桌面与移动视口下长题干完整可读（可断言元素文本完整与无 `truncate` 类）。
6. `?filter=wrong` 直达错误筛选。
7. 未完成会话访问该路由 → 不能看到答案与对错（后端隔离生效）。

### 验证命令

```bash
cd frontend && npm test
cd frontend && npm run build
```

## 5. 回归门禁

- **不改** `QuizView.vue` 的答题与恢复逻辑；若确实需要共享样式，抽到独立文件而不是改答题页。
- **不改** `QuestionCard.vue`。
- 确认结果页仍可正常打开（`result-page` 完成前，现有 `QuizResultView` 不应被本任务破坏）。

## 6. 回滚点

- 新增路由与页面之前 → 单一回滚点；本任务只新增文件 + 一处路由注册，回滚只需还原这些改动。

## 7. 风险文件与禁止顺手改动

**本任务改动：** 新增 `QuizReviewView.vue`、`ReviewQuestionCard.vue`、`quizReviewE2E.test.js`；`router/index.js` 新增一条路由。

**禁止顺手改动：** 不改 `QuizResultView.vue`（属 `result-page`）；不改 `stores/quiz.js`（属 `result-page`）；不改 `QuizView.vue` 与 `QuestionCard.vue`；不改 `WrongAnswersView.vue`；不改后端；不重构 `examRoutes.js` 的既有行为。
