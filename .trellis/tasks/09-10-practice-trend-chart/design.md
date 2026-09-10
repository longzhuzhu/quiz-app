# 练习趋势图 — 技术设计

## 架构与边界

四块改动：

1. **按日正确率快照表**：提交时把当时的滚动正确率写入作答本地日，只更新该日。
2. **查询 API**：近 30 个本地日的密集序列（当日作答量 + 展开后的滚动正确率）。
3. **首页组件**：`PracticeTrendChart` 与热力图并排。
4. **复用正确率计算**：四格卡片与快照、今日现势共用同一查询。

不读、不改 `QuizAnswer.answered_at` 来回放历史日（ADR-0006）。

考试上下文已是所有者隔离，查询按 `current_user.id + exam.id`。

## 数据模型

### `practice_accuracy_days`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer FK → `users.id` ON DELETE CASCADE | |
| `exam_id` | Integer FK → `exams.id` ON DELETE CASCADE | |
| `local_date` | Date NOT NULL | 作答当时客户端本地日，冻结 |
| `accuracy` | Float NOT NULL | 当时近 100 记正确率 |
| `sample_size` | Integer NOT NULL | 实际记数（≤100） |
| `updated_at` | DateTime UTC | 该日最后一次写入 |

约束：`UNIQUE (user_id, exam_id, local_date)`。  
索引：`(user_id, exam_id, local_date)`。

删考试项目靠 FK CASCADE。清空历史必须在 `clear_practice_days` 里一并按 `user_id + exam_id` 删除。

## 数据流

### 写入

```
POST /api/quiz/answer
  → 现有判题 / QuizAnswer / record_question_touch
  → 若 local_date 合法：upsert practice_accuracy_days
       SET accuracy, sample_size = recent_accuracy_for(..., limit=100)
```

`recent_accuracy_for` 从 `quiz.py` 的现有查询抽出，卡片接口改为调用它。

非法/缺失本地日：不写快照，答题照常。快照写入失败只打日志，不阻断提交（与练习日同一套 nested savepoint）。

### 读取

```
GET /api/quiz/practice-trend?today=YYYY-MM-DD
```

静态路由，必须写在 `/session/{session_id}` 之前。

窗口：`[today - 29 days, today]`，共 30 天，**密集**返回（含 count=0）。

```json
{
  "today": "2026-09-10",
  "days": [
    {"date": "2026-08-12", "count": 0, "accuracy": null, "sample_size": 0},
    {"date": "2026-08-20", "count": 3, "accuracy": 72.0, "sample_size": 100}
  ]
}
```

展开规则：

1. `count` 来自 `practice_day_questions` 按日去重计数，无行则为 0。
2. 历史日：若该日有快照则用快照，否则沿用上一快照（含窗口开始日之前最近的一条，用来填窗口前段空日）；窗口开始前也没有任何快照则为 `null`。不从 `answered_at` 补这条种子。
3. `today`：`recent_accuracy_for` 现势；`total > 0` 时覆盖当天点，保证与四格卡片一致；`total == 0` 则当天也为 `null`。
4. 不用 `answered_at` 回填 `null` 段。

### 清空

`clear_practice_days` 同时删除两表中该用户该考试项目的行。

## 前端

新组件 `frontend/src/components/PracticeTrendChart.vue`。不引入图表库：SVG 双纵轴折线。

`HomeView.vue`：热力图外再包一层 `grid grid-cols-1 md:grid-cols-2`；`fetchDashboardData` 增加 `GET /quiz/practice-trend?today=`，独立 catch，失败则 30 日空轴。

布局：

- 卡片与热力图同高；桌面绘图区跟随热力图内容高度（`md:min-h-0`），不再用 `min-h-[180px]` 把热力图撑出底空；窄屏保留 `min-h-[148px]`。
- 左轴：0 到窗口内最大 `count`（至少 1）。右轴：固定 0–100%。
- 题数线与正确率线颜色区分；正确率只连接 `accuracy != null` 的点。
- 标题「近 30 日」。图例：当日作答量、近 100 记正确率（`sample_size` 不足则用实际记数）。
- 悬停/点到具体点：只展示该点短文案（`答题数：n题` 或 `正确率：n%`）。点击不是链接。

热力图根节点去掉单独的 `mb-4`，外边距改到并排容器上。

## 兼容与迁移

- Alembic `008_practice_accuracy_days.py`，`down_revision = "007"`。只加表。
- 旧客户端不传 `local_date`：答题成功，无新快照；今日现势仍可画一点。
- 不回填历史快照。
- Flask 旧层不接。

## 取舍

| 方案 | 为何不用 |
|---|---|
| `GROUP BY answered_at` | 改答搬家，ADR-0006 |
| 作答事实日志 | 图只要 y 值，N 已锁 |
| `practice_day_questions` 加对错 | 按题×日去重，撑不起近 100 记 |
| 新增 npm 图表库 | 双轴 30 点用 SVG 足够 |

## 回滚

`alembic downgrade 007` 掉新表。前端不挂组件即消失。
