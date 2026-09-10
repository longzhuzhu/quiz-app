# 练习趋势图 — 执行计划

## 实施顺序

### 第 1 段：数据层

- [ ] `PracticeAccuracyDay` 模型 + `__init__` 导出
- [ ] Alembic `008_practice_accuracy_days.py`，`down_revision = "007"`，`downgrade()` 可逆

### 第 2 段：写入、查询、清空

- [ ] `recent_accuracy_for(...)` 抽出；`GET /recent-accuracy` 改走它
- [ ] `record_accuracy_snapshot(...)`：合法本地日 upsert；失败不打断答题
- [ ] `submit_answer` 在 `record_question_touch` 之后调用快照写入
- [ ] `trend_for(...)`：30 日密集序列 + 快照沿用 + 今日现势
- [ ] `GET /practice-trend?today=`，放在 `/session/{session_id}` 之前
- [ ] `clear_practice_days` 同时删快照

验证：`cd backend && python -m pytest tests/test_practice_trend.py tests/test_practice_day.py -q`

### 第 3 段：前端

- [ ] `PracticeTrendChart.vue`：SVG 双轴、图例、悬停
- [ ] `HomeView.vue`：并排布局 + 独立请求降级
- [ ] 热力图外边距改到容器

## 测试

- [ ] 合法日提交写快照；同日再提交只改当天
- [ ] 跨日改答不改写昨日快照
- [ ] 非法/缺失本地日不写快照
- [ ] `trend_for` 返回 30 日；空日 count=0；无快照 accuracy=null
- [ ] 有快照后空日沿用；今日现势覆盖
- [ ] 清历史后趋势为空

运行：`cd backend && python -m pytest tests/test_practice_trend.py tests/test_practice_day.py tests/test_practice_streak.py -q`

## 回滚

`alembic downgrade 007`。前端去掉并排容器即可。
