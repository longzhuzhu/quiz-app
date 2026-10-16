# Cross-Layer Thinking Guide

> **Purpose**: Think through data flow across layers before implementing.

---

## The Problem

**Most bugs happen at layer boundaries**, not within layers.

Common cross-layer bugs:
- API returns format A, frontend expects format B
- Database stores X, service transforms to Y, but loses data
- Multiple layers implement the same logic differently

---

## Before Implementing Cross-Layer Features

### Step 1: Map the Data Flow

Draw out how data moves:

```
Source → Transform → Store → Retrieve → Transform → Display
```

For each arrow, ask:
- What format is the data in?
- What could go wrong?
- Who is responsible for validation?

### Step 2: Identify Boundaries

| Boundary | Common Issues |
|----------|---------------|
| API ↔ Service | Type mismatches, missing fields |
| Service ↔ Database | Format conversions, null handling |
| Backend ↔ Frontend | Serialization, date formats |
| Component ↔ Component | Props shape changes |

### Step 3: Define Contracts

For each boundary:
- What is the exact input format?
- What is the exact output format?
- What errors can occur?

---

## Common Cross-Layer Mistakes

### Mistake 1: Implicit Format Assumptions

**Bad**: Assuming date format without checking

**Good**: Explicit format conversion at boundaries

### Mistake 2: Scattered Validation

**Bad**: Validating the same thing in multiple layers

**Good**: Validate once at the entry point

### Mistake 3: Leaky Abstractions

**Bad**: Component knows about database schema

**Good**: Each layer only knows its neighbors

### Mistake 4: 单侧收紧既有响应契约

**Bad**: 后端给响应新增字段时顺手把旧字段删掉/置空，认为「前端反正在改」。

**Good**: 只增不删，旧字段标注为过渡并保留，等消费方切换后再由前端子任务删除。

多子任务并行时最容易踩：新增契约的子任务先落地，而删旧字段的消费方子任务还没开始。
此时旧字段的删除会立刻让**线上所有用户**降级，不是「反正要删」。

实际案例（#63 复盘 API）：完成态把 `answers` 置空，理由是新的 `questions` 结构已取代它、
且 `design.md` §5.3 要求结果页删除该列表。但结果页重做属另一个尚未开始的子任务，
而 `frontend/src/views/QuizResultView.vue` 仍读 `res.data.answers` 渲染详情列表
——影响面是**所有普通练习用户**，不只是原问题涉及的模拟考试。

判断方法：**改动前后各跑一次「谁读这个字段」的全仓搜索**，确认每个消费方都已在本次改动内完成切换。
若有一个没有，就保留字段并在注释里写明「过渡字段 + 由谁删除」。

收口（#63 最后一个子任务 `10-13-result-page`）：消费方切换完成后，完成态才真正不再输出 `answers`，
判断条件是「结果页已改读 `questions`」。关键是不能一刀切删——**进行中会话必须保留 `answers`**，
答题页刷新恢复依赖它。所以收口的是「完成态」这一个分支，不是整个字段。

---

### Mistake 5: 把「配置值」下发给拿不到配置接口的消费者

平台参数通常只在管理员接口暴露（如 `GET /api/settings/quiz` 带 `Depends(require_admin)`），但需要显示
它的界面往往**不是**管理员页面。这时不能顺手让前端去调那个 admin 接口——普通用户会拿到 403。

正确做法是**沿已有的用户可见路径下发**：找一个该页面**已经在调用**的认证接口，把配置值作为只读字段
带出去。本次是让 `/api/wrong/stats` 附带 `mastery_correct_streak`（错题页本就在调它），而不是
让 `WrongAnswersView` 去请求 `/api/settings/quiz`。

```javascript
// Wrong：普通用户会 403，且给错题页新增一条与渲染无关的请求依赖
const res = await client.get('/settings/quiz')
const threshold = res.data.wrong_mastery_correct_streak

// Correct：搭该页面已有的请求（backend/app/api/routes/wrong.py 的 /stats 响应里带该字段）
const res = await client.get('/wrong/stats')
threshold.value = res.data.mastery_correct_streak
```

命名也要跟着换：admin 接口用配置键名，用户只读路径用领域语义名（`mastery_correct_streak`）。

### Mistake 6: 前端为「后端字段缺失」猜一个默认值

后端返回值取不到时，前端若用 `?? 2` 之类的兜底填一个默认值，就制造了**第二个真值来源**——
而且会把它写回去。实测案例：管理页加载失败后表单仍可保存，`?? 2` 让一次「只想改 AI 模型」的保存
把管理员先前设定的阈值悄悄改回 2。后端 `is not None` 语义本来是「不改动」，但前端发的是
一个具体的 2，后端无从区分。

正确做法是让「未知」保持未知，并在 UI 上体现出来：

```javascript
// Wrong：猜默认值，且会写回后端
form.value = { threshold: res.data.threshold ?? 2 }

// Correct：null 表示未加载，不提交该字段（后端 is not None → 不改动）
form.value = { threshold: res.data.threshold ?? null }
// 保存时
let threshold = null
if (form.value.threshold !== null) {
  threshold = Math.trunc(Number(form.value.threshold))
  if (!Number.isInteger(threshold) || threshold < 1 || threshold > 9) {
    toast.error('...'); return
  }
}
```

配套：输入框 `v-if="form.threshold !== null"`，未知时显示「当前值未加载成功，保存时不会改动此项」
而不是渲染一个空输入框。参见 `frontend/src/views/AdminSettingsView.vue` 与
`WrongAnswersView.vue`（后者同样保持 `null` 而非猜默认值）。

---

## Checklist for Cross-Layer Features

Before implementation:
- [ ] Mapped the complete data flow
- [ ] Identified all layer boundaries
- [ ] Defined format at each boundary
- [ ] Decided where validation happens
- [ ] **Config values**: 确认每个消费者都有权限读到它（别让用户页面调 admin 接口）
- [ ] **Optional fields**: 前端取不到时是「不提交」还是「猜默认值」？后者会覆盖后端已有的值
- [ ] **Config change semantics**: 改了配置，存量数据要不要重算？不重算的话 UI 有没有说明

After implementation:
- [ ] Tested with edge cases (null, empty, invalid)
- [ ] Verified error handling at each boundary
- [ ] Checked data survives round-trip
- [ ] **New API route**: curl 验证端点可达（不只是 import 成功）
- [ ] **New API route**: 确认后端进程已重启加载新路由
- [ ] **New contract field**: 只增不删，老前端忽略新字段仍能工作
- [ ] **Mutation check**: 把实现改成错误版本，新写的断言会失败吗？（恒真断言是假保障）

---

## When to Create Flow Documentation

Create detailed flow docs when:
- Feature spans 3+ layers
- Multiple teams are involved
- Data format is complex
- Feature has caused bugs before

---

## Homepage Accuracy — Cross-Layer Flow

### Data Flow

```
HomeView.vue onMounted()
  → GET /api/quiz/recent-accuracy?limit=100
  → quiz.py: recent_accuracy()
    → QuizAnswer JOIN QuizSession (filter user_id + non-null)
    → ORDER BY answered_at DESC, id DESC (tie-breaker)
    → LIMIT 100 → subquery
    → conditional aggregate: func.count() + func.count().filter(is_correct)
    → { total, correct, accuracy, limit }

  → GET /api/wrong/stats
  → wrong.py: wrong_stats()
    → { unresolved, resolved, total }

HomeView.vue display:
  → accuracy card: recentTotal > 0 ? recentAccuracy : 0 + "(近N题)"
  → wrong card: unresolved count
```

### Critical Consistency Points

| Checkpoint | Risk | Mitigation |
|-----------|------|-----------|
| 语义对齐 | "正确率"标签实际计算错题掌握率 | 统一用 QuizAnswer 正确率，不混用 wrong/stats |
| API 失败隔离 | Promise.all 单点失败拖垮全页 | 各自独立 catch + Promise.allSettled |
| FastAPI 路由顺序 | `/session/{id}` 吞掉 `/recent-accuracy` | 静态路由必须在动态参数路由之前定义 |
| 排序确定性 | `answered_at` 相同记录顺序不稳定 | 加 `id DESC` 作为 tie-breaker |
| 部署验证 | uvicorn 未重启导致新路由 404 | 部署后必须 curl 验证新端点可达 |

---

## Practice Trend — Cross-Layer Flow

### Data Flow

```
POST /api/quiz/answer (local_date)
  → record_question_touch → practice_day_questions
  → record_accuracy_snapshot → recent_accuracy_for(limit=100) → practice_accuracy_days
  → 非法/缺失 local_date：两表都不写，答题照常

HomeView.vue fetchDashboardData()
  → GET /api/quiz/recent-accuracy          （四格卡片，现势）
  → GET /api/quiz/practice-trend?today=    （30 日密集序列）
  → 各自独立 catch + Promise.allSettled；趋势失败则 30 日空轴

trend_for():
  → count 来自 practice_day_questions 按日去重
  → 历史正确率来自 practice_accuracy_days，空日沿用上一快照
  → 窗口开始日前最近一条快照要当作种子，否则窗口前段会假断档
  → today 用 recent_accuracy_for 现势覆盖，与四格卡片同一查询
  → 不用 QuizAnswer.answered_at 回放
```

### Critical Consistency Points

| Checkpoint | Risk | Mitigation |
|-----------|------|-----------|
| 今日点 vs 卡片 | 两套查询口径分叉 | 卡片与 `trend_for` 的 today 都走 `recent_accuracy_for`，N=100 |
| 窗口前快照 | 只查窗口内快照会让窗口第一天从 null 起画 | `local_date < window_start` 取最近一条作种子 |
| 0 记快照 | 查询没看见刚提交的作答会写入 0% 假悬崖 | `total <= 0` 不写快照 |
| 空日展开 | 稀疏返回让折线错位 | API 固定 30 个本地日；前端只接受 `days.length === 30` |
| 路由顺序 | `/session/{id}` 吞掉 `/practice-trend` | 静态路由写在动态参数路由之前 |
| 清历史 | 只删练习日会留下正确率形状 | `clear_practice_days` 同时删两表 |

---

## Smart Import Cross-Layer Flow

### Data Flow

```
Upload → ImportJob + BackgroundJob
  → claim + immutable attempt + shared ImportJob lock
  → initialize/reuse manifest
  → persist response (cache/LLM) → atomic per-chunk persistence + checkpoint
  → recount progress/stats/reconciliation → guarded terminal

Manual review / new reparse → same ImportJob writer coordination
```

修改这条链路时读取[导入执行恢复合同](../backend/import-recovery.md)，并区分三个层次：单次模型L1/L2、同后台请求自动retry、新用户reparse请求。

### 检查问题

- 响应已解析与入库完成是否有独立证据，故障后既不重复也不漏题？
- 领取、所有提交、心跳及终态是否验证同一个不可变attempt？失租控制流是否穿透泛化捕获？
- HTTP期间是否结束业务事务，独立续约与finally是否释放线程/连接？
- 人工accept/skip与reparse是否协调并刷新行，避免旧判断删除已接受来源？
- 重跑是否保留manifest/expected基线并重算进度，而非再切片或累加次数？
- 新请求审计与同请求幂等是否分离，同文件新job重导仍可用？
- 词频等派生更新是否保留原ID/释义/学习事实，而非只重建计数？
