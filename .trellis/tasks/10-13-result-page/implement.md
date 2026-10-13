# 执行计划：完成页统计与本次错题入口

需求见本任务 `prd.md`；技术设计见父任务 `design.md` 第 5.3、5.4 节。

## 0. 开始前检查（依赖门禁）

```bash
python3 ./.trellis/scripts/task.py current     # 应为 10-13-result-page
grep -n 'wrong_count\|unanswered_count\|accuracy_basis' backend/app/api/routes/quiz.py
grep -n 'def retry_quiz' backend/app/api/routes/quiz.py
grep -n 'ExamQuizReview' frontend/src/router/index.js
```

**前置：** `10-13-review-api`（统计字段）、`10-13-retry-api`（`/quiz/retry`）、`10-13-review-ui`（复盘路由）均需可用。缺任一项则停止，不要在前端临时凑数据。

`retry-api` 的失败响应会列出不可用题目，先确认其 `detail` 形态再写错误提示。

## 1. 统计与详情

`frontend/src/views/QuizResultView.vue`：

- 三列改为正确／错误／未答（`:41-54`），数值取 `session.correct_count`、`session.wrong_count`、`session.unanswered_count`。
- `accuracy` 直接用 `session.accuracy`，不在前端重算。
- 删除 `:56-73` 的内嵌详情列表（`answers` 的相关状态与赋值一并清理，避免留下未使用变量——那是本次改动产生的孤儿）。
- 圆环与配色（`:104-116`）保持不变。

## 2. 四个入口

替换 `:76-80` 的按钮区：

```js
查看详情   → router.push(currentExamPath(route, 'quizReview', { sessionId }))
本次错题   → router.push(currentExamPath(route, 'quizReview', { sessionId, filter: 'wrong' }))
再来一次   → retryQuiz()
返回首页   → router.push(currentExamPath(route, 'dashboard'))   // 不变
```

`frontend/src/utils/examRoutes.js` 新增 `quizReview` kind：

```js
if (kind === 'quizReview' && params.sessionId) {
  const query = params.filter ? `?filter=${encodeURIComponent(params.filter)}` : ''
  return `/exams/${encoded}/quiz/${params.sessionId}/review${query}`
}
```

并在 `routeKind()` 中按需识别 `ExamQuizReview`（参考 `ExamQuiz` / `ExamQuizResult` 归到 `dashboard` 的既有写法）。

## 3. 再来一次

`frontend/src/stores/quiz.js` 新增：

```js
async function retryQuiz(sessionId) {
  const res = await client.post('/quiz/retry', { session_id: sessionId })
  session.value = res.data.session
  questions.value = res.data.questions
  currentIndex.value = 0
  return res.data
}
```

**保持 `startQuiz` 签名不变**（仍有题库页等调用方）。

`QuizResultView.vue` 中：

- 用 `retrying` 标志在请求期间禁用按钮（`:disabled`）。
- catch 中留在原页并 toast 错误原因，**不**跳转、不清空 `session`。
- 成功后 `router.push(currentExamPath(route, 'quiz', { sessionId: quizStore.session.id }))`。

注意现有实现的错误提示读的是 `e.response?.data?.error`（`:137`），而 FastAPI 的 `HTTPException` 返回 `detail`。确认实际字段，两处都兼容或统一取 `detail`，避免提示为空。

## 4. 历史入口

`frontend/src/views/HistoryView.vue:27`：已完成会话的 `currentExamPath(route, 'quizResult', ...)` 改为 `'quizReview'`。

## 5. 测试

### 5.1 端到端（真实浏览器 + 隔离 PostgreSQL）

新增 `frontend/tests/quizResultE2E.test.js`，参考 `helpers/studyBrowser.js`、`helpers/studyBackend.js`。**这是原始症状的回归防线，必须包含：**

1. **模拟 10 题 7 对 3 错完成后**：完成页显示 70%、正确 7、错误 3、未答 0；**断言不再出现「全部显示错误」**。
2. 10 题只答 2 题全对：普通练习 100% / 模拟 20%，均显示 2 对 0 错 8 未答。
3. 零答案结束：0%，未答等于总题数，页面无 `NaN`、不崩溃。
4. 「查看详情」进入复盘页，默认全部筛选。
5. 「本次错题」进入复盘页并选中错误筛选。
6. 「再来一次」：新会话题数与原场一致、模式相同；请求期间按钮禁用。
7. 原题被删除后「再来一次」：留在原页并提示不可用题目。
8. 历史页已完成会话进入复盘页。

### 验证命令

```bash
cd frontend && npm test
cd frontend && npm run build
```

## 6. 回归门禁

- 结果页是完成答题后的必经页面，改动后必须同时确认：
  - 未完成会话刷新仍走答题页恢复（`QuizView.vue` 不受本任务影响）。
  - 已完成会话从答题页跳转到结果页正常（`QuizView.vue:271-274` 的 `router.replace` 目标路径未变）。
- 确认「答题历史」页其他字段（模式、题库名、时间）未受影响。

## 7. 回滚点

- 结果页改统计之前 → 单一回滚点（本任务只改前端，回滚无数据影响）。

## 8. 风险文件与禁止顺手改动

**本任务改动：** `frontend/src/views/QuizResultView.vue`、`frontend/src/views/HistoryView.vue`、`frontend/src/stores/quiz.js`、`frontend/src/utils/examRoutes.js`、新增测试文件。

**禁止顺手改动：** 不改 `QuizReviewView.vue` 与 `ReviewQuestionCard.vue`（属 `10-13-review-ui`）；不改 `QuizView.vue`、`QuestionCard.vue`、`WrongAnswersView.vue`；不改后端；不改首页统计；不重构 `examRoutes.js` 既有分支行为。
