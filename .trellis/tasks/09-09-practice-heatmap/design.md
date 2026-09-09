# 练习热力图 — 技术设计

## 架构与边界

三块改动：

1. **练习日事实表**：新表记录「谁、哪个考试项目、哪天本地日、动过哪题」，提交答案时 upsert。不读、不改 `QuizAnswer.answered_at`。
2. **查询 API**：按当前用户 + 当前考试项目聚合近 53 周稀疏天数与当前连续。
3. **首页组件**：`HomeView` 在四格统计和继续答题之间挂练习热力图。

考试上下文已是所有者隔离（`backend/app/api/deps.py:85-91`），查询按 `current_user.id + exam.id` 即可，不必另做管理员过滤。

## 数据模型

### `practice_day_questions`（新表）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer FK → `users.id` NOT NULL | 所有者 |
| `exam_id` | Integer FK → `exams.id` ON DELETE CASCADE NOT NULL | 考试项目边界 |
| `local_date` | Date NOT NULL | 作答当时客户端给出的本地自然日，冻结 |
| `question_id` | Integer FK → `questions.id` ON DELETE CASCADE NOT NULL | 当天动过的题 |
| `created_at` | DateTime UTC | 首次记入该日该题的时间 |

约束：`UNIQUE (user_id, exam_id, local_date, question_id)`。  
索引：`(user_id, exam_id, local_date)` 供热力图按日计数。

**当日作答量** = 该 `(user_id, exam_id, local_date)` 下的行数。  
**练习日** = 该日行数 ≥ 1。

不存「提交次数」。同题同日再提交走唯一约束，静默忽略（幂等 upsert）。

删题、删考试项目靠 FK CASCADE。清空答题历史**不会**碰到此表，必须在 `clear_history` 里按 `user_id + exam_id` 显式删除（D15）。

## 数据流

### 写入

```
POST /api/quiz/answer  { session_id, question_id, user_answer, local_date? }
  → 现有判题 / QuizAnswer 写入（不变）
  → 若 local_date 合法：INSERT practice_day_questions
       ON CONFLICT (user_id, exam_id, local_date, question_id) DO NOTHING
```

`local_date` 由前端在提交瞬间取设备本地 `YYYY-MM-DD`。后端校验：必须是 ISO 日期，且落在 `[utc_today - 1 day, utc_today + 1 day]`（时区与时钟偏差）。非法或缺失：不写练习日，答题主流程照常（AC10）。

不在后端用 UTC `now` 切日——那会违反 D8。

### 读取

```
GET /api/quiz/practice-heatmap?today=YYYY-MM-DD
```

`today` 必填，取浏览器本地今天。窗口：`[today - 52 weeks - weekday_offset, today]`，足够覆盖周一为起点的 53 列。只返回窗口内 `count > 0` 的天。

```json
{
  "today": "2026-09-09",
  "current_streak": 3,
  "days": [{"date": "2026-09-08", "count": 12}]
}
```

`current_streak` 在服务端算，避免前后端对「今天还没练算不算断」理解分裂：

1. 若 `today` 有记录，从 `today` 往过去连续计。
2. 否则若 `today - 1` 有记录，从昨天往过去连续计（D11 宽限）。
3. 否则为 0。

深浅分档只在前端做：0 / 1–3 / 4–9 / 10–19 / 20+。API 只给原始 `count`。

### 清空

`DELETE /api/quiz/history` 在删除会话之后：

```
DELETE FROM practice_day_questions
 WHERE user_id = :user AND exam_id = :exam
```

与会话删除同一事务。

## 前端

新组件 `frontend/src/components/PracticeHeatmap.vue`（不要把方格网格直接堆进 `HomeView.vue`）。

`HomeView.vue`：`fetchDashboardData` 增加 `GET /quiz/practice-heatmap?today=`（`today` 用本地日）。插在四格统计网格之后、继续答题卡片之前。

`frontend/src/stores/quiz.js` 的 `submitAnswer` 带上 `local_date`。所有走该 store 的模式（顺序/随机/专项/模拟/错题）都会记练习日。若答题页有不经 store 的直连 `POST /quiz/answer`，同样补字段。

布局：

- 7 行（周一 → 周日），列从左到右为周。
- `md+`：近 53 周；默认小于 `md`：近 16 周。不足的前导空列补齐，使今天落在最后一列的对应星期行。未来的格子不画（或画成不可点亮的占位，与 GitHub 一致：当前周未到的天留空）。
- 颜色（GitHub 贡献绿，深色模式同步加深底）：无记录 `#ebedf0` / 档1 `#9be9a8` / 档2 `#40c463` / 档3 `#30a14e` / 档4 `#216e39`。
- 今天：额外描边。
- 右下 Less/More 五色图例。
- 标题行：`连续 n 天`（n 为 0 也显示）。

交互：`title` 或轻量 tooltip：`YYYY-MM-DD · n 题`。格子不是链接。

## 兼容与迁移

- Alembic `007_practice_day_questions.py`，`down_revision = "006"`。只加表，不改 `quiz_answers`。
- 旧客户端不传 `local_date`：答题成功，格子不亮。
- 不迁移历史 `answered_at`（D16 / ADR 0005）。
- Flask 旧层不接此功能。

## 取舍

| 方案 | 为何不用 |
|---|---|
| `GROUP BY QuizAnswer.answered_at` | 改答覆写时间戳，会偷走已成立的练习日（ADR 0005） |
| 作答事件流水（每次提交一行） | 当日作答量按不重复题目计，唯一约束已够；流水是多余写入 |
| 服务端用 UTC 切日 / 打开首页重切 | 违反冻结的本地日 |
| 预聚合日汇总表 | 多一张表要在改答跨日时维护；按日 COUNT 唯一行即可 |

## 回滚

`alembic downgrade 006` 掉新表。答题主路径在写入练习日失败时应记录日志并吞掉，不阻断提交（实现时写入放在同一事务更简单；若独立 try/except，以不丢答案为准）。产品回滚：前端不渲染组件即对用户消失，孤立表行可随后删。
