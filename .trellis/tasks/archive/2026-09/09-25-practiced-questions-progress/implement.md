# Implement — 已刷题目进度

按序执行；每步后跑对应验证命令。

## 1. CONTEXT.md 术语（先落语言，再落代码）

- [ ] `CONTEXT.md` Language 区「当日作答量」条目之后插入「已刷题目」术语（文案见 design.md）。
- [ ] `CONTEXT.md` Relationships 区按 design.md 追加 3 条关系。
- 验证：人工读一遍上下相邻术语无口径冲突。

## 2. 后端

- [ ] `backend/app/services/practice_service.py`：新增 `practiced_questions_for(db, user_id, exam_id) -> int`，联表形态对齐 `recent_accuracy_for`（import 区补 `distinct`）。
- [ ] `backend/app/api/routes/quiz.py`：`/recent-accuracy` 后新增 `GET /practiced-summary` 路由，返回 `{"practiced_questions": <int>}`。
- [ ] 新增 `backend/tests/test_practiced_summary.py`，覆盖：
  1. 无作答 → `{"practiced_questions": 0}`；
  2. 两个会话答同一题 + 同会话改答 → 仍为 1；
  3. 跨考试项目作答互不计数（只算 X-Exam-Slug 项目）；
  4. `DELETE /quiz/history` 后归零。
  - 参照既有测试的 client/建数据方式（见 `backend/tests/test_answer_submit_lock_latency.py` 等）。
- 验证：`cd backend && python -m pytest tests/test_practiced_summary.py -q`，再跑全量 `python -m pytest -q`。

## 3. 前端

- [ ] `frontend/src/views/HomeView.vue`：
  - 新增 `practicedQuestions` ref 与 `practicedPercent` computed；
  - `fetchDashboardData()` 的 `Promise.allSettled` 增加 `GET /quiz/practiced-summary`；
  - 总题目卡副行改「已刷 N · P%」，底部加细进度条（结构见 design.md）。
- 验证：`cd frontend && npm run build`。

## 4. 收尾检查门

- [ ] 后端全量 pytest 通过。
- [ ] 前端 build 通过。
- [ ] 对照 prd.md Acceptance Criteria 逐条自检。
- [ ] git diff 复查：无越界改动（不改 clear_history、不动 user_question_stats）。

## 回滚点

- 任一步失败：`git checkout -- <file>` 回退该文件；整体回滚 = revert 提交。
