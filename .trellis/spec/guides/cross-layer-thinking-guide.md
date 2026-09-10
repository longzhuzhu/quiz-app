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

---

## Checklist for Cross-Layer Features

Before implementation:
- [ ] Mapped the complete data flow
- [ ] Identified all layer boundaries
- [ ] Defined format at each boundary
- [ ] Decided where validation happens

After implementation:
- [ ] Tested with edge cases (null, empty, invalid)
- [ ] Verified error handling at each boundary
- [ ] Checked data survives round-trip
- [ ] **New API route**: curl 验证端点可达（不只是 import 成功）
- [ ] **New API route**: 确认后端进程已重启加载新路由

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
FileUpload.vue → POST /api/banks/{bank_id}/import
  → create_smart_import_job() → ImportJob + BackgroundJob created
  → Response: { import_job_id, background_job_id }

Worker: handle_question_import_llm()
  → run_smart_import()
    → file extraction → text normalization → chunk splitting
    → for each chunk:
      → LLM parse (or cache hit) → quality scoring
      → high confidence → auto-insert Question
      → low confidence → create ImportReviewItem
    → _finalize_import() → update bank stats + word frequencies

Frontend: ImportJobDetailView.vue polls GET /api/import-jobs/{id}
  → displays progress, stats, chunk status

Frontend: ImportReviewView.vue
  → GET /api/import-jobs/{id}/review-items → display pending items
  → POST accept → write Question as-is
  → POST skip → mark review_item as skipped
  → POST reparse → creates new BackgroundJob (async)
```

### Critical Consistency Points

| Checkpoint | Risk | Mitigation |
|-----------|------|-----------|
| `config_json.answer_key_text` | Worker 中计算但未持久化 → `_process_chunk` 读空 | 提交前存储到 config_json |
| `progress_total` 初始为 0 | 前端显示 0/0 进度条 | chunk 创建后立即设置 |
| `heartbeat_job` 缺少 `success_increment` | progress_done 永远不增长 | 每次心跳传递 increment |
| 单 chunk 异常中断整个 Worker | 所有后续 chunk 丢失 | 每个chunk独立 try-except |
| review accept 重复执行 | 同一题目重复入库 | 检查 review_status 幂等拒绝 |
| reparse 同步执行 | API 超时 | 必须创建 BackgroundJob 异步执行 |
