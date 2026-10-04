# Quiz UI 只读体验审计

## Goal

仅审计现有考试备考应用的 UI 与答题体验，降低认知负荷、加快答题、改善英文题干与选项阅读、方便错题复习，保持界面安静聚焦。用户明确要求不实施代码变更。

## Requirements

- 使用 redesign-existing-projects 技能，仅执行 Scan 与 Diagnose。
- 覆盖答题效率、题干阅读、选项阅读、答题反馈、错题复习、切题导航、进度可见性、移动适配、视觉层级、冗余 UI 十个维度。
- 每项问题列出严重程度、建议与实际受影响组件/文件，并区分源码确认、浏览器验证与待验证风险。
- 浏览器检查采用本地前端和隔离 API 模拟，不连接真实账户或写入真实学习记录。

## Acceptance Criteria

- [x] 十个维度均有证据化结论，不将推测描述为实测事实。
- [x] 高优先级问题提供现状、用户影响、建议和文件定位。
- [x] 只创建审计任务文档及证据，不改动产品源码、依赖、配置或测试。
- [x] 任务保持 planning，不执行 task.py start、不提交或部署。

## 已确认背景

- 前端使用 Vue 3、Pinia、Vue Router、Tailwind CSS 4、Headless UI 与 Heroicons。
- 核心路径：HomeView → QuizView / QuestionCard → QuizResultView → WrongAnswersView；HistoryView 可回看会话结果。
- 用户已授权登记只读审计任务，未授权实现。

## 范围外

不输出或实施营销站改版；不引入背景图片、视差、装饰性噪点或大幅动效；不迁移技术栈；不替换字体/图标库以追求差异化；不制定已经获批的实现方案。
