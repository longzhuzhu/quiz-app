# 首页总题目卡片增加已刷题目进度

## Goal

考试项目首页的「总题目」卡片目前只显示当前题库题目总数，不体现用户刷了多少题。在不动现有 4 卡网格的前提下，让该卡片同时展示「已刷题目」进度（已刷 / 总数 + 百分比 + 细进度条）。

## Background（已冻结的设计决策）

- 口径：新术语「**已刷题目**」= 当前考试项目内存在至少一条作答记录的**不重复题目数**（去重，改答不重复计）。
- 范围：当前考试项目、历史累计（与「总题目」同口径，可相除出覆盖率）。
- 展示：改造现有「总题目」卡——主数值保持题目总数，副行加「已刷 N · P%」，卡片底部一条细进度条；不新增第 5 张卡。
- 接口：新增 `GET /quiz/practiced-summary`，返回 `{ practiced_questions }`（不含累计作答次数，UI 不展示就不查）。
- 数据源：`quiz_answers JOIN quiz_sessions JOIN question_banks`（按 user_id + exam_id 过滤），`COUNT(DISTINCT quiz_answers.question_id)`。
  - 否决 `practice_day_questions`：2026-09-09 才建表且按 CONTEXT.md 规定不回填历史，累计数会漏约 4 个月数据。
  - 否决 `user_question_stats`：`clear_history` 不清它，清空答题历史后不归零（且现状已存在清空后残留的存量问题，本任务不修）。
  - `quiz_answers` 自 001 迁移全量存在；`QuizSession.answers` 级联 `all, delete-orphan`（`backend/app/models/quiz.py:42`），清空历史自动归零；联表过滤 exam 的写法与 `recent_accuracy_for` 同款。

## Requirements

1. 后端新增 `GET /quiz/practiced-summary`：认证 + 考试项目上下文（同现有统计端点），返回 `{"practiced_questions": <int>}`。
2. 前端首页 `HomeView.vue` 并发请求该端点，「总题目」卡片显示：
   - 主数值不变（题目总数）；
   - 副行「已刷 N · P%」（N=已刷题目数，P=去重覆盖率百分比，四舍五入取整）；
   - 卡片底部细进度条，宽度 = P%（0–100 封顶）。
3. CONTEXT.md 新增术语「已刷题目」及其关系条目（见 implement.md 检查项）。
4. 后端测试覆盖：无作答返回 0；多会话同题去重只计 1；清空答题历史后归零。

## Acceptance Criteria

- [ ] 未作答时卡片显示「已刷 0 · 0%」，进度条为空，主数值不受影响。
- [ ] 同一道题跨会话/改答多次，只计 1 道。
- [ ] 只统计当前考试项目（X-Exam-Slug 对应项目）内的作答，切换项目数字随之切换。
- [ ] 清空答题历史后「已刷」归零。
- [ ] 现有 4 卡布局不破坏（2 列移动端 / 4 列桌面端）。
- [ ] 后端测试通过；前端构建通过。

## Out of Scope

- 不新增累计作答次数统计与展示。
- 不修复 `user_question_stats` 在清空历史后残留的存量问题（可另立任务）。
- 不改动热力图 / 趋势图 / 正确率卡片。
