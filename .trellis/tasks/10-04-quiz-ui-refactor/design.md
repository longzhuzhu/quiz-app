# 技术设计：Quiz UI 重构

## 1. 数据流重构：QuestionCard 受控化

现状：`QuestionCard` 本地持有 `selectedAnswers/answered/result`，切题即丢（N1 根因），提交按钮在卡内（M1 根因）。

目标契约（保持 spec「result 必须与 QuizView.questionResultMap 同一对象」约定）：

```
QuizView（状态所有者）
├─ drafts: reactive { [questionId]: string[] }   // 未提交草稿（N1）
├─ questionAnswerMap / questionResultMap          // 已提交答案与结果（沿用）
├─ autoNext / autoNextTimer / autoNextCancelable   // 仅答对自动跳（F1）
├─ loadError                                       // 加载失败态（U2）
└─ 底部操作条（唯一主操作区，M1）

QuestionCard（展示 + 交互，受控）
├─ props: question/currentIndex/total/examMode/answerCount/sessionId
│         selectedAnswers: string[]（草稿或已提交答案）
│         result: Object|null（= questionResultMap 引用）
│         editing: Boolean（重新作答中）
│         submitting: Boolean
│         showTranslation: Boolean（会话级偏好，R2）
├─ emits: update:selectedAnswers / submit / next / prev / finish
│         translated / answer-corrected
└─ 内部仅保留：correctionMode 流程、explainData、copyQuestion
```

状态判定：
- `isAnswered = !!result && !editing && !correctionMode`
- 选项选中态 = `selectedAnswers`（未答/editing 时来自 drafts；已答时来自已提交答案）
- 已答点击选项：不改变任何状态（E2 边界）；`update:selectedAnswers` 仅在未答/editing/correctionMode 时 emit。
- editing 进入：初始化 draft 为已提交答案（可微调）；取消 editing：draft 恢复为已提交答案。
- 提交成功：`delete drafts[qid]`；`questionResultMap[qid] = resultPayload`（新引用触发 QuestionCard watch 重置 editing）。

## 2. 底部操作条（M1，全断点统一）

- QuestionCard 移除卡内操作栏；QuizView 渲染唯一操作条 `fixed bottom-0 inset-x-0 z-30`，含 safe-area。
- 布局：`上一题(secondary) | 第x/y题 · 已答n·未答m(摘要，窄屏精简) | 题号按钮(手机) | 主按钮`。
- 主按钮状态机（E2）：
  - 未答无选择 → 「提交答案」disabled；有选择 → enabled
  - 已答 && 非最后一题 → 「下一题」primary
  - 已答 && 最后一题 → 「完成答题」primary
  - editing → 「提交答案」primary（重新提交）
- 「重新作答」ghost 按钮位于反馈区内（QuestionCard），editing 时提供「取消重做」。
- 「结束答题」入口：桌面在左侧导航底部；手机在题号面板底部（P2）。
- 正文预留：QuizView 根容器 `pb-40 md:pb-28`；答题路由加 `meta.quizFocus`，App.vue 据此隐藏 MobileNav（消除双底栏与 M3 叠加风险）。
- 题号面板：手机按需展开的浮层（grid 6 列、min 40px 触摸目标），含状态色与未答计数；桌面保留左侧 sticky 题目导航。
- 键盘 E3：QuizView 挂 window keydown；`e.target` 为 input/textarea/select/contenteditable 或带 modifier 时忽略；A–Z/数字映射选项索引；Enter = 提交→下一题（最后一题 → 结束确认）。
- 自动下一题 F1：`is_correct === true && autoNext` 才启动 1500ms timer；操作条上方显示「即将进入下一题 · 取消」；examMode 保持 300ms 无反馈跳转（无对错概念）；答错永不自动跳。
- 切题滚动：`jumpTo/next/prev` 后 `window.scrollTo({ top: 0 })`。

## 3. 进度口径（P1）

- QuizView 顶部条：`第 {currentIndex+1}/{N} 题`（位置）+ `已答 {answeredCount} · 未答 {unansweredCount}`（完成度）。
- 进度条宽度 = `answeredCount / N`，纯 `bg-primary-500`（去渐变，U1）。
- `answerResults` 仅由提交/恢复写入；drafts 不计入。

## 4. QuestionCard 视觉结构（R1/O1/O2/F2/F3/H2/U1）

- 题干：`whitespace-pre-line font-normal leading-relaxed max-w-[72ch]`；删除卡内进度条与 hideProgress prop。
- 翻译行：题干下方紧跟 TranslateButton（ghost 小号）+ `content_zh` 文本；选项翻译随同一状态显隐（R2）。
- 选项：`grid grid-cols-[auto_2rem_1fr] items-start`（控件 / 标号 / 正文）；label 无 click handler，input `@change` 驱动；input 用 `accent-*` 样式；正文 `min-w-0 break-words`（O1）。
- 结果态（O2，正常对比度）：
  - 正确答案：emerald 边框 + 轻背景 + 右侧「正确答案」标签
  - 你的错选：rose 边框 + 轻背景 + 「你的选择」标签
  - 答对且已选：emerald + 「你的答案 ✓」
  - 其余选项：默认中性样式（不降透明度）
  - examMode：已选 sky「已选」标签，其余中性
- 反馈区（F2/H2）：`aria-live="polite"`；第一行图标 + 对/错 + 「你的答案 A → 正确答案 B」；「重新作答」「更正答案」为次级文本按钮；AI 解析移入折叠区（`<details>` 或 ref 控制），默认收起，`ExplainButton` 在解析区头部。
- 移除 `animate-shake`；style.css 删除 shake keyframes 并新增 `prefers-reduced-motion` 全局降级（F3）。
- 工具行：ExplainButton/ AddVocabButton 保留但 ghost 化；「已答 n 次」保留小字但弱化（U1）。

## 5. 页面级改动

### HomeView（H1/U1）
顺序：标题 → 继续上次答题（若有）→ 题库列表 → 学习概览（单卡 2×2/4 列紧凑数字，待攻克保留链接）→ 热力图 + 趋势。统计卡去彩色顶条与大图标底色；按钮组去 emoji（同组一致性，符合 spec）。

### WrongAnswersView（M2/W3/U2）
- 摘要行：`flex-col`，题干全宽 → 元信息行 → 操作行（标记掌握 min-h-11 + 展开箭头）。
- 翻译：`translationVisible[w.id]` 同时控制题干翻译、选项翻译、按钮 `:show`（W3）。
- `fetchWrongs` 增加 catch → `loadError`，错误态内联可重试；`resolveWrong` 增加 try/catch 防未处理 rejection（U2）。

### QuizResultView（W2/P2）
- 统计四列：总题数/正确/错误/未答（`total - answered`）。
- 详情：筛选 chips「全部/答错 n」；每项可展开（完整题干 + 选项对比列表，user_answer/correct_answer 标签）；移除 `max-h-64` 嵌套滚动与 truncate。

### HistoryView / QuizView（U2）
- HistoryView：`fetchHistory` catch → `loadError` 内联错误态 + 重试。
- QuizView：`onMounted` catch 不再跳 dashboard，改渲染错误卡 + 重试；无 questions 跳转保留。

### 全局
- router：`ExamQuiz` 加 `meta.quizFocus: true`；App.vue：`showMobileNav = showAuthenticatedShell && !route.meta.quizFocus`。
- style.css：删 shake；加 reduced-motion；保留 safe-area 工具。

## 6. 兼容与回滚

- 对外契约不变：API、路由、store 对外行为（startQuiz/submitAnswer/finishQuiz）不变；QuestionCard 仅 QuizView 使用，props 变更无外部消费者。
- 保留既有功能：examMode 语义、更正答案（correctionGeneration 防竞态）、翻译/解析智能组件、复制题目、会话恢复映射、AI prewarm。
- 回滚：单分支单 PR，revert 即可；无数据迁移。

## 7. 验证方案

1. `npm run build`（vite build + eslint 如配置）。
2. Vite dev + Playwright 隔离会话（模拟 /api），复用审计任务的做法：桌面 1440×900 + 手机 390×844 + 320。
3. 交互回归清单 = PRD 验收标准逐条；console 0 error/warning。
4. 明暗模式切换检查。
