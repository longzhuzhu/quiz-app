# 练习热力图 — 执行计划

## 实施顺序

分三段，每段结束后系统可运行。

### 第 1 段：数据层

- [ ] `backend/app/models/practice.py` — `PracticeDayQuestion`（`UNIQUE(user_id, exam_id, local_date, question_id)`，索引 `(user_id, exam_id, local_date)`）
- [ ] `backend/app/models/__init__.py` — 导出
- [ ] `backend/alembic/versions/007_practice_day_questions.py` — `down_revision = "006"`，建表，`downgrade()` 可逆

验证：`cd backend && alembic upgrade head`，再 `alembic downgrade 006` 后重新 `upgrade head`。

### 第 2 段：写入、查询、清空

- [ ] `backend/app/schemas/quiz.py QuizAnswerRequest` — 加 `local_date: date | None = None`
- [ ] `backend/app/services/practice_service.py`（新）— `record_question_touch(...)` 幂等 upsert；`local_date` 校验（ISO，且相对 UTC 今天 ±1 天）；`heatmap_for(...)` 返回稀疏 days + `current_streak`（D11）
- [ ] `backend/app/api/routes/quiz.py submit_answer` — 判题成功后调用 `record_question_touch`；校验失败或缺失日期不打断主流程
- [ ] `backend/app/api/routes/quiz.py` — `GET /practice-heatmap?today=`
- [ ] `backend/app/api/routes/quiz.py clear_history` — 删会话同一事务内按 `user_id + exam_id` 删除练习日行

验证：单测覆盖 upsert 幂等、跨日改答不偷走、streak 宽限、非法日期丢弃。

### 第 3 段：前端

- [ ] `frontend/src/stores/quiz.js submitAnswer` — 传 `local_date`（`new Date` 的本地 `YYYY-MM-DD`）。全库搜 `quiz/answer`，遗漏的直连调用一并补
- [ ] `frontend/src/components/PracticeHeatmap.vue` — 网格、档位色、今天描边、图例、连续天数、tooltip；`md` 53 周 / 默认 16 周；周一起排
- [ ] `frontend/src/views/HomeView.vue` — 四格统计与继续答题之间挂组件；`fetchDashboardData` 拉 `GET /quiz/practice-heatmap?today=`

验证：本地提交一题后刷新首页，今天格子点亮且连续至少为 1；改答旧题后天数不丢；清空历史后全灰。

## 测试

沿用 `backend/tests/` 纯单元测试（无 conftest、不连库）：

- [ ] `backend/tests/test_practice_day.py` — 日期校验（缺省 / 非法 / ±1 天外拒绝、±1 天内接受）；同一日同一题第二次 touch 不增计数；跨日同一题两天各计 1
- [ ] `backend/tests/test_practice_streak.py` — 今天有练从今天计；今天空昨天有则从昨天计；昨天也空为 0；中间缺一天断开

运行：`cd backend && python -m pytest tests/test_practice_day.py tests/test_practice_streak.py -q`

## 风险点与回滚

| 风险 | 处理 |
|---|---|
| 写入练习日失败导致答案丢失 | 主路径先写 `QuizAnswer`；练习日 upsert 失败只打日志，或同事务但约束简单（唯一冲突视为成功） |
| 客户端乱传 `local_date` | ±1 天窗口拒绝写入格子，答题仍成功 |
| 首页多一次请求 | 与现有 dashboard 请求 `Promise.allSettled`，失败则空图，不挡题库列表 |
| 迁移 007 | `alembic downgrade 006` 只掉新表 |

## 起工前确认

- [ ] `alembic current` 确认本地库已在 `006`（或更高且 head 将含 007）
- [ ] 规划摘要已获用户明确批准后再 `task.py start`
