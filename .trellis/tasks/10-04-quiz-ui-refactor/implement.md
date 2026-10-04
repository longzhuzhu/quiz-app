# 执行计划：Quiz UI 重构

## 顺序清单

### 阶段 A：全局基建
- [ ] A1 `frontend/src/router/index.js`：`ExamQuiz` 路由加 `meta.quizFocus: true`
- [ ] A2 `frontend/src/App.vue`：`route.meta.quizFocus` 时隐藏 MobileNav
- [ ] A3 `frontend/src/style.css`：删 shake keyframes/.animate-shake；新增 prefers-reduced-motion 降级

### 阶段 B：答题链路（核心，B1→B2 有依赖）
- [ ] B1 `frontend/src/views/QuizView.vue`：
  - drafts 草稿 map + 受控传参（selectedAnswers/result/editing/submitting/showTranslation）
  - 进度口径：已答数进度条 + 已答/未答常驻 + 位置独立
  - 底部固定操作条 + 题号面板（手机）+ 结束答题入口与未答确认
  - 自动下一题仅答对触发 + 取消 + 切题滚顶
  - 键盘快捷键（输入焦点跳过）
  - 加载错误态（可重试）
- [ ] B2 `frontend/src/components/QuestionCard.vue`：
  - 受控化 props/emits；选项 input change 单一入口；三列布局悬挂对齐
  - 结果态标签（你的选择/正确答案，正常对比度）；examMode 适配
  - 题干排版（pre-line/常规字重/列宽）；翻译行紧邻题干
  - 反馈区 aria-live + 答案对照 + 解析折叠 + 重新作答
  - 更正答案流程保留（correctionMode 与受控选项的交互边界）
- [ ] B3 回归检查点：多选一次 toggle、草稿往返、examMode、更正答案、复制

### 阶段 C：结果页与错题本
- [ ] C1 `frontend/src/views/QuizResultView.vue`：未答统计 + 筛选 chips + 可展开详情/选项对比 + 去嵌套滚动
- [ ] C2 `frontend/src/views/WrongAnswersView.vue`：手机布局独立操作行 + min-h-11 触摸目标 + 翻译状态统一 + 加载错误态 + resolveWrong try/catch

### 阶段 D：首页与历史
- [ ] D1 `frontend/src/views/HomeView.vue`：区块重排（继续→题库→概览→图表）+ 统计紧凑化 + 去 emoji/彩色顶条
- [ ] D2 `frontend/src/views/HistoryView.vue`：加载错误态 + 重试

### 阶段 E：验证
- [ ] E1 `cd frontend && npm run build`；lint（如存在脚本）
- [ ] E2 启动 Vite + Playwright 隔离模拟 API，按 PRD 验收清单逐条验证（1440/390/320 + 明暗模式 + console 检查）
- [ ] E3 发现问题修复后复验（回归门）

## 验证命令

```bash
cd frontend && npm run build
# 浏览器验证：node Playwright 脚本（隔离 route mock），或 browser-use 技能
```

## 回滚点

- 每阶段独立可编译；阶段 B 完成前不合并到提交。
- 全部改动在单一分支 `feat/quiz-ui-refactor`，出问题 revert 整个 PR。

## 审查门

- E1 通过后才进入 E2 浏览器验证；E2 全部验收项通过才进入提交。
