# PR-3 Design — reparse 卫生 + imported_qnos 题号去重 + bg_job 透传补尾

> 研究子代理产出，仅做静态分析；未修改任何源代码、未发起 LLM 调用。
> 数据源：`backend/app/services/smart_import_service.py`（PR-2 commit `109c45b` 之后）、
> `backend/app/models/import_parsed_question.py`、`backend/app/models/import_chunk.py`、
> `backend/app/schemas/llm_parse.py`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/prd.md`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/diagnosis-step0.md`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/pr1-design-call-ai-api-timeout.md`、
> `.trellis/tasks/05-04-smart-import-cipt-283-pdf/research/pr2-design-process-chunk-retry.md`、
> `.trellis/spec/guides/code-reuse-thinking-guide.md`、
> `.trellis/spec/guides/cross-layer-thinking-guide.md`。

## 行号说明（PR-2 commit `109c45b` 之后）

* `_process_chunk` ← `smart_import_service.py:395-606`
* `_save_parsed_question` ← `smart_import_service.py:778-889`
* `run_reparse` ← `smart_import_service.py:1022-1093`

PR-3 主要改动均落在以上 3 个函数。

---

## A. 当前 `run_reparse` 控制流逐行摸清

### A.1 状态机概览（行 1022-1093）

```
入口：BackgroundJob (job_type=JOB_TYPE_QUESTION_IMPORT_LLM_REPARSE)
      payload = {import_job_id, chunk_id, bank_id}
  │
  │  1024-1027 反序列化 payload
  │  1029-1031 db.get(ImportJob, …)；不存在 → raise ValueError
  │  1033-1035 db.get(ImportChunk, …)；不存在 → raise ValueError
  │
  ├─[A] 删除"未 imported"的 ImportParsedQuestion + 关联 ReviewItem
  │       行 1037-1053
  │       条件：pq.import_status == "imported" AND pq.imported_question_id   → 跳过删除
  │       否则：① 删除 ImportReviewItem.parsed_question_id == pq.id
  │             ② 若 pq.review_status == "pending"  → import_job.review_questions -= 1
  │             ③ import_job.parsed_questions -= 1
  │             ④ db.delete(pq)
  │       行 1055 db.flush()        ← 不 commit；事务延展到下方 1062
  │
  ├─[B] 重置 chunk 状态（行 1057-1061）
  │       chunk.status            = "pending"
  │       chunk.llm_request_json  = None
  │       chunk.llm_response_json = None
  │       chunk.issues_json       = None      ← 关键：清空 PR-2 写入的
  │                                              retry_count / fallback_used /
  │                                              per_question_failures / fallback_meta
  │       行 1062 db.commit()       ← A+B 同一事务边界
  │
  ├─[C] 重新构建 seen_signatures（行 1069-1075）
  │       来源 = Question 表（按 bank_id），不是 ImportParsedQuestion 表
  │       per row：sig = (qtype, content, options, normalized_answer)
  │
  └─[D] 调 _process_chunk（行 1077-1084）
        参数：db, chunk, import_job, auto_import, use_llm_cache=False,
              seen_signatures
        ⚠️ 当前**未传** bg_job —— PR-2 决议 4 第 3 条要求补上

  └─[E] 收尾（行 1086-1090）
        若 import_job.review_questions > 0 → status="review_required"
        否则                                  → status="imported"
        最后 _update_bank_stats(db, bank_id)
```

### A.2 所有 db 写点（按行号）

| 行号 | 写点 | 事务边界 |
|------|------|----------|
| 1048 | `db.query(ImportReviewItem).filter_by(parsed_question_id=pq.id).delete()` | 与 [A]+[B] 合并到 1062 commit |
| 1051 | `import_job.review_questions -= 1` | 同上 |
| 1052 | `import_job.parsed_questions -= 1` | 同上 |
| 1053 | `db.delete(pq)` | 同上 |
| 1055 | `db.flush()` | — |
| 1058-1061 | chunk 状态重置（5 个字段） | 同上 |
| 1062 | `db.commit()` | A+B+C 同一 commit |
| 1077 | `_process_chunk(...)` | _process_chunk 内部多次 commit |
| 1088/1090 | `_update_import_job_status` 内部 `db.commit()` | 单独事务 |
| 1093 | `_update_bank_stats` 内部 `db.commit()` | 单独事务 |

> **关键事实 1**：[A]+[B] 共一个 commit；事务回滚边界由 commit 决定。reparse 中途如果 `_process_chunk` 抛异常，[A]+[B] 已经落盘——这是 PR-2 之前的既有行为，PR-3 不改变。
>
> **关键事实 2**：`run_reparse` **没有任何 try/except 包裹 `_process_chunk`**（行 1077-1084）。`_process_chunk` 内部对硬失败（4xx / API Key / parse_failed）会 `raise`，由上层 worker `run_smart_import_job` / job_worker 兜底——这与 `run_smart_import` 主路径有 try/except（行 373-379）的行为不同。PR-3 不在此修复，仅记录此差异。

### A.3 `seen_signatures` 在 reparse 路径的构建（行 1069-1075）

```python
seen_signatures = set()
existing_questions = db.query(Question).filter_by(bank_id=import_job.bank_id).all()
for eq in existing_questions:
    eq_options = eq.options if isinstance(eq.options, list) else json.loads(eq.options or "[]")
    eq_answer  = [a.strip() for a in (eq.correct_answer or "").split(",")] if eq.correct_answer else []
    seen_signatures.add(_question_signature(eq.question_type, eq.content, eq_options, eq_answer))
```

* **来源表**：`Question`（按 bank_id 全集），不是 `ImportParsedQuestion`。
* 重建策略：`isinstance(options, list)` 兼容 SQLite/PG 历史下 options 可能是 list 也可能是 JSON 字符串；`correct_answer` 用逗号 split + strip。
* 与 `run_smart_import` 主路径行 338-343 完全一致 → 该构造逻辑应抽 helper（见 I.1）。
* **诊断 C.5 已实证**：该签名拦不住 reparse 的"虚胖"——LLM 二次返回的 content/options 与原入库内容空白/换行/引号略有差异，签名 miss → 重新走 `_save_parsed_question` 入库路径。这是 PR-3 的核心动机。

---

## B. `imported_qnos` 集合的构建与传递

### B.1 来源表选择

**推荐：选项 a — `ImportParsedQuestion` 表**。

```sql
SELECT source_question_no
FROM import_parsed_questions
WHERE import_job_id = :this_job_id
  AND import_status = 'imported'
  AND source_question_no IS NOT NULL;
```

| 维度 | 选项 a：ImportParsedQuestion | 选项 b：Question + 反向 join |
|---|---|---|
| 字段直接性 | ✅ `source_question_no` 即题号 | ❌ Question 无 `source_question_no` 字段，须经 `imported_question_id` 反查 |
| 跨多次 reparse 稳健性 | ✅ 第 1 次 reparse 后新入库的题也保留 import_status='imported'，第 2 次 reparse 启动时重新查表即可 | ⚠ 同样稳健，但 SQL 更复杂（join + filter NULL imported_question_id） |
| 与 PR-4 reconciliation 对齐 | ✅ 同一张表的另一种切片（`'skipped'`/`'imported'`）；schema 一致 | — |
| `import_job_id` 范围 | ✅ 显式只查本 job，跨 job 题号不污染 | ⚠ Question 表无 import_job_id，若 bank 内有其他来源题（手工导入），bank 范围会过宽 |
| 与现有 `seen_signatures` 来源对称 | ❌ `seen_signatures` 来自 Question；两个来源不对称 | ✅ 同源 Question 表 |

> 选项 b 的"对称"优点价值不大——`seen_signatures` 与 `imported_qnos` 本质语义不同（一个是内容签名、一个是题号），来源表不必对称。
>
> **决策**：用选项 a。本 job 内"已经被本 job 自己入库的题号"才是重复入库的源头，与其他来源题无关。

实施：

```python
# 在 run_reparse 行 1075 之后、行 1077 之前
imported_qnos = {
    pq.source_question_no.strip().lstrip("#").strip()
    for pq in db.query(ImportParsedQuestion)
                .filter_by(import_job_id=import_job.id, import_status="imported")
                .all()
    if pq.source_question_no  # 过滤 None / 空串
}
```

### B.2 归一化方案

`ImportParsedQuestion.source_question_no` 是 `String(64)`（行 24），nullable。来源是 LLM 返回的 `parsed_q.source_question_no`，类型 `str | None`。

* LLM 输出会带前缀：`"222"` / `"#222"` / `"Question #222"` / `" 222 "` 都可能出现。
* `_quality_check` 行 1561 仅判断 `not parsed_q.source_question_no or parsed_q.source_question_no.strip().lower() in ("unknown", "")`，未做剥离。
* 入库存储路径行 803 `source_question_no=parsed_q.source_question_no` —— **原样存**。

**推荐归一化**（构造集合 + 比对题号都同样处理）：

```python
def _normalize_qno(qno: str | None) -> str | None:
    """归一化题号：strip + 去掉前导 '#'。返回 None 表示无题号。"""
    if not qno:
        return None
    cleaned = qno.strip().lstrip("#").strip()
    return cleaned or None
```

* **保留字符串**而不是 `int`：CIPT PDF 全部数字，但通用性考虑（不排除题号有 `"5a"`、`"5-1"` 等）；与 `parsed_q.source_question_no` 的 `str | None` 类型一致。
* `lstrip("#")` 只剥前导 `#`；尾部 `#` 不太可能出现，且不剥更安全。
* 若 `_normalize_qno(parsed_q.source_question_no) is None` → 视为"无题号"，**不进 DUPLICATE_QNO 路径**（让现有内容签名/质量检查兜底，行 1561 NO_QUESTION_NO 处理）。

### B.3 贯穿到 `_save_parsed_question`

**当前签名（行 778-786）**：

```python
def _save_parsed_question(
    db: Session,
    parsed_q: ParsedQuestion,
    import_job: ImportJob,
    chunk: ImportChunk,
    chunk_text: str,
    auto_import: bool,
    seen_signatures: set | None = None,
) -> None:
```

**PR-3 推荐签名**：新增 `imported_qnos: set[str] | None = None` 关键字参数，与 `seen_signatures` 并列。

```python
def _save_parsed_question(
    db: Session,
    parsed_q: ParsedQuestion,
    import_job: ImportJob,
    chunk: ImportChunk,
    chunk_text: str,
    auto_import: bool,
    seen_signatures: set | None = None,
    imported_qnos: set[str] | None = None,
) -> None:
```

理由：

| 备选 | 评估 |
|---|---|
| (α) 新增独立参数 `imported_qnos` | ✅ **推荐**。语义清晰、与 `seen_signatures` 分桶；初次导入路径默认 `None`；测试时易于独立断言 |
| (β) 把题号 set "塞进" `seen_signatures` | ❌ 类型污染（既有元组又有字符串）；且 seen_signatures 在 _save_parsed_question 中 `seen_signatures.add(sig)` 的元组 add 会让题号 set 变质 |
| (γ) 合并为 `dedupe_context: dict` | ❌ 过度抽象（YAGNI），目前只 2 个键，代价不值；如未来扩到 3+ 维度再重构 |

### B.4 `_process_chunk` 是否也加参数？

**必须加**。`_process_chunk` 内部行 597-606 循环调 `_save_parsed_question`，要让 `imported_qnos` 流到下游必须在 `_process_chunk` 签名里加。

```python
def _process_chunk(
    db: Session,
    chunk: ImportChunk,
    import_job: ImportJob,
    auto_import: bool,
    use_llm_cache: bool,
    seen_signatures: set | None = None,
    bg_job: BackgroundJob | None = None,
    imported_qnos: set[str] | None = None,   # 新增
) -> None:
```

`_process_chunk_cached`（行 609-654）也要同步透传。

* `run_smart_import` 行 364-372 调 `_process_chunk` 时**不传** `imported_qnos`（默认 `None` → 维持初次导入行为不变）。
* `run_reparse` 行 1077-1084 调 `_process_chunk` 时**显式传** `imported_qnos=imported_qnos` + 同时补 `bg_job=bg_job`。

---

## C. 命中题号去重的语义路径

### C.1 `_save_parsed_question` 入口判断流程

PR-3 后的 `_save_parsed_question` 入口顺序（伪代码）：

```python
def _save_parsed_question(..., seen_signatures=None, imported_qnos=None):
    # 1) 题号归一化
    qno_norm = _normalize_qno(parsed_q.source_question_no)

    # 2) DUPLICATE_QNO 优先：题号已 imported？
    if imported_qnos is not None and qno_norm and qno_norm in imported_qnos:
        return _persist_duplicate_parsed_question(
            db, parsed_q, import_job, chunk,
            reason="qno",
            detail=f"题号 {qno_norm} 已入库（reparse 跳过）",
        )

    # 3) 现有内容签名 DUPLICATE 路径（保持不变）
    sig = _question_signature(...)
    if seen_signatures is not None and sig in seen_signatures:
        return _persist_duplicate_parsed_question(
            db, parsed_q, import_job, chunk,
            reason="content",
            detail="与已有题目重复",
        )
    if seen_signatures is not None:
        seen_signatures.add(sig)

    # 4) ... 其它原有逻辑（_quality_check / _write_question_to_bank / ImportReviewItem）
```

### C.2 DUPLICATE_QNO 命中时的副作用清单

按 PRD Decision 2 / Technical Approach L6 / 任务必查项 C.8：

| 副作用 | 行为 | 与现有 DUPLICATE_CONTENT 路径对比 |
|---|---|---|
| 写 ImportParsedQuestion 一行 | ✅（`review_status='duplicate', import_status='skipped', issues_json={"issues":["DUPLICATE"], "details":[{"code":"DUPLICATE","severity":"LOW","reason":"qno",...}]}`） | 同（仅 `reason` 不同）|
| 调 `_write_question_to_bank` | ❌ 不调 | 不调 |
| 调 `_quality_check` | ❌ 不调 | 不调 |
| `import_job.parsed_questions += 1` | ✅ | ✅（行 818）|
| `import_job.imported_questions` | 不变 | 不变 |
| `import_job.review_questions` | 不变 | 不变 |
| `seen_signatures.add(sig)` | ❌ **不更新** | ❌ 不更新（行 822-823 也仅在非命中分支才 add）|
| `imported_qnos.add(qno_norm)` | ❌ **不更新** | — |
| `db.commit()` | ✅（落盘 ImportParsedQuestion + 计数）| ✅（行 819）|

> **C.2 关键**：`seen_signatures` / `imported_qnos` 都**不**因 DUPLICATE_QNO 路径更新——避免"早返回的伪签名"污染后续题去重判断。这与 TC-8 一致。

### C.3 与现有 DUPLICATE 路径的代码组织

`_save_parsed_question` 行 796-820 的内容签名 DUPLICATE 路径与 PR-3 的 DUPLICATE_QNO 路径**80%+ 相同**（构造 ImportParsedQuestion + 写计数 + commit）。按 `code-reuse-thinking-guide.md` 的"Same code appears 3+ times" 原则，目前 2 次重复处于"边界值"——但 PR-3 是**主动复用**的好时机，**强烈推荐**抽出私有 helper。

**推荐：抽出 `_persist_duplicate_parsed_question` 私有函数**（见 J.2 伪代码）。

| 维度 | 抽 helper（推荐）| 不抽 helper |
|---|---|---|
| 行数 | -10 行（去重 ImportParsedQuestion 构造）| 0 |
| 测试便利性 | 可独立单测 helper | 需通过 `_save_parsed_question` 间接测 |
| reason 区分 | 集中处理 issues_json schema，未来 PR-4 reconciliation 取数稳定 | 两处都得记得改 |
| 改动面 | 一处 helper + 两处调用 | 两处入口各自 inline |
| 风险 | helper 私有、单文件、单测覆盖 | 无 |

> 工程师评估：抽 helper 收益 > 成本。helper 是 service 内私有函数，不增加跨模块表面。

### C.4 `issues_json` schema：DUPLICATE_QNO vs DUPLICATE_CONTENT

**当前 DUPLICATE_CONTENT**（行 813）：

```python
issues_json={
    "issues": ["DUPLICATE"],
    "details": [
        {"code": "DUPLICATE", "severity": "LOW", "detail": "与已有题目重复"}
    ],
}
```

**PR-3 推荐**：保留 `code: "DUPLICATE"` 主键不变，在 `details[0]` 增加 `reason` 子字段；`detail` 文案区分。

```python
# DUPLICATE_QNO
issues_json={
    "issues": ["DUPLICATE"],
    "details": [
        {"code": "DUPLICATE", "severity": "LOW",
         "reason": "qno",
         "detail": f"题号 {qno_norm} 已入库（reparse 跳过）"}
    ],
}

# DUPLICATE_CONTENT（PR-3 后改写）
issues_json={
    "issues": ["DUPLICATE"],
    "details": [
        {"code": "DUPLICATE", "severity": "LOW",
         "reason": "content",
         "detail": "与已有题目重复"}
    ],
}
```

**为什么不用 `code: "DUPLICATE_QNO"` / `"DUPLICATE_CONTENT"`?**

| 备选 | 评估 |
|---|---|
| (α) 主 code 仍 `"DUPLICATE"` + `details[].reason: "qno" / "content"` | ✅ **推荐**。前端 `issues` 数组的展示逻辑不变（仍显示"重复"标签）；PR-4 reconciliation 通过 `details[0].reason == "qno"` 区分 |
| (β) 主 code 升级为 `"DUPLICATE_QNO"` / `"DUPLICATE_CONTENT"` | ❌ 前端 `serialize_parsed_question` 直接返回 `issues_json`，主 `issues: ["DUPLICATE_QNO"]` 会让前端复核页可能漏读未升级的过滤逻辑 |
| (γ) 新增 `details[].source: "reparse"` | ❌ 模糊（首次导入也可能内容签名 DUPLICATE）；不如 `reason: qno/content` 直接 |

> 这与必查项 C.10 的"建议保留 `"DUPLICATE"` 主键 + 增加 `reason: "qno"` 子字段"一致。

---

## D. `seen_signatures` 与 `imported_qnos` 的并行 / 互斥语义

### D.1 初次导入路径（`run_smart_import`）

* `seen_signatures = set()` 初始 + Question 表内容签名（行 338-343）。
* PR-3 **不**在此路径启用 `imported_qnos`：调 `_process_chunk(..., imported_qnos=None)` 即可（默认值，无需改动）。
* 理由：初次导入时 `ImportParsedQuestion` 表还没有该 job 的任何 `'imported'` 行（chunks 顺序处理，但同 chunk 内题号不会同时 imported——而 reparse 是事后再来一次），即便强行启用 `imported_qnos`，集合在每个 chunk 入口都是空（要么是 0 要么是已处理 chunks 的结果）。
* 严格说初次导入也"可以"启用，但带来 N×SQL 查询且不解决任何已知问题——**YAGNI 原则**：不启用。

### D.2 Reparse 路径

并行运作流程：

```
_save_parsed_question 入口
  ├── (1) qno 归一化
  ├── (2) imported_qnos 命中？  ──[是]──► DUPLICATE_QNO（_persist_duplicate）
  │                                       不更新任何集合
  ├── (3) seen_signatures 内容签名命中？──[是]──► DUPLICATE_CONTENT（_persist_duplicate）
  │                                              不更新任何集合
  ├── (4) seen_signatures.add(sig)
  └── (5) _quality_check → _auto_accept → _write_question_to_bank / ReviewItem
```

> **顺序"题号先于内容签名"**：因为题号是更强的"已被本 job 入库"信号；签名只是"内容相似"，可能误伤多版本同题（虽然诊断 C.5 已显示当前未发生此误伤）。

### D.3 多次 reparse 同一 chunk 的稳健性

第 1 次 reparse：
1. `imported_qnos` = {本 job 已 imported 题号}（不含本次还未跑的）
2. `_process_chunk` 把成功题写为 `import_status='imported'`、命中题号写为 `'skipped'`

第 2 次 reparse（紧跟第 1 次）：
1. `run_reparse` 入口删除"未 imported"的 ImportParsedQuestion（行 1037-1053）——**包含上一次 DUPLICATE_QNO 写的 `'skipped'` 行**（条件 `import_status == "imported"` 才跳过）；
2. 重新查 `imported_qnos`，把第 1 次新入库的题号也包含进来；
3. `_process_chunk` 命中所有 `imported_qnos` → 全部 DUPLICATE_QNO 跳过。

→ **稳健**。每次 reparse 入口都重建集合，不需特殊状态保留。

### D.4 corner case：DUPLICATE_QNO 行被下次 reparse 删掉的影响

必查项 C.14 提出：第 1 次 reparse 写的 `'skipped'` 行，会在第 2 次 reparse 入口被删除（不在 imported_qnos 集合里）。这会把它误重新入库吗？

**分析**：不会。第 2 次 reparse 入口：

1. 行 1037-1053 删除上次的 `'skipped'` 行（包括 review_status='duplicate' 的 DUPLICATE_QNO 行）；
2. **重新查 `imported_qnos`**——查的是 `import_status='imported'` 的行，与上次的 `'skipped'` 行无关；
3. 上次 DUPLICATE_QNO 命中的题号此时仍然在 `imported_qnos` 中（因为该题号对应的"原始 imported 行"从未被删过——`run_reparse` 行 1043-1046 显式跳过 `import_status == "imported"` 的删除）；
4. 第 2 次 LLM 解析返回同一题号 → 仍然命中 DUPLICATE_QNO → 再写一行 `'skipped'`。

→ **正确**：DUPLICATE_QNO 不需要"自我持久化"，imported_qnos 由 `import_status='imported'` 的稳定行支撑。

### D.5 与 `seen_signatures.add` 的交互

当前 _save_parsed_question 行 822-823：

```python
if seen_signatures is not None:
    seen_signatures.add(sig)
```

PR-3 在 DUPLICATE_QNO 路径**不进入此行**（早返回）。这意味着：

* 一个 chunk 内若题号 222 命中 DUPLICATE_QNO 跳过，再来一题（也是 222）——还会再次命中 DUPLICATE_QNO → 又写一行 skip 。
* 这与现状一致（DUPLICATE_CONTENT 路径也没有 `seen_signatures.add`）；前端复核页会看到"多个 DUPLICATE_QNO 行"，但都是 `'skipped'`，不污染入库。

---

## E. PR-2 留的尾巴：`bg_job` 透传

### E.1 PR-2 决议 4 第 3 条要求

> "`run_smart_import` 与 `run_reparse` 调用 `_process_chunk` 时必须传 `bg_job=background_job`"

`run_smart_import` 行 371 已传 `bg_job=bg_job`（PR-2 commit `109c45b` 完成）；
`run_reparse` 行 1077-1084 **未传**——PR-3 必须补上。

### E.2 实施

`run_reparse` 入参签名 `(db: Session, background_job: BackgroundJob)` 已经持有 `BackgroundJob`，无需重新查表：

```python
# 行 1077 改写
_process_chunk(
    db=db,
    chunk=chunk,
    import_job=import_job,
    auto_import=auto_import,
    use_llm_cache=use_llm_cache,
    seen_signatures=seen_signatures,
    bg_job=background_job,                    # ← 新增
    imported_qnos=imported_qnos,              # ← 新增
)
```

> 注意：`run_smart_import` 在 chunk 循环内 `db.get(BackgroundJob, background_job.id)` 重新拿了一遍（行 361，原因是 db session 跨多个 chunk 可能 expire）。`run_reparse` 单次性，不需要重新 get；直接用入参 `background_job`。

### E.3 回归风险评估

* `_process_chunk` 的 `bg_job` 参数在 PR-2 已定为 `BackgroundJob | None = None` 默认值（`smart_import_service.py:402`）；
* `bg_job is None` 的兼容路径已经被 PR-2 测试覆盖（heartbeat 仅在 `bg_job is not None` 时调用，行 762）；
* `bg_job` 仅用于 L2 fallback 内的 heartbeat 续约——在正常 reparse 不进 L2 的情况下零副作用。

→ **回归风险评估：0**。这是纯加法改动。

---

## F. ImportJob 计数

### F.1 DUPLICATE_QNO 路径的计数变化

| 字段 | 变化 | 与 DUPLICATE_CONTENT 路径一致？ |
|---|---|---|
| `parsed_questions` | **+= 1**（语义：解析了一题，但跳过入库） | ✅ 一致（行 818） |
| `imported_questions` | 不变 | ✅ 一致 |
| `review_questions` | 不变 | ✅ 一致 |
| `failed_chunks` | 不变 | ✅ 一致 |

### F.2 与 `run_reparse` 入口"减计数"行为的交互

行 1051-1052 `run_reparse` 入口删除"未 imported"行时：

```python
if pq.review_status == "pending":
    import_job.review_questions -= 1
import_job.parsed_questions -= 1
```

* 上次 DUPLICATE_QNO 行 `review_status='duplicate'`（不是 `'pending'`）→ `review_questions` 不减；
* `parsed_questions -= 1` 仍然减。

* 第 2 次 reparse 跑完后：DUPLICATE_QNO 命中题再 `parsed_questions += 1` —— 净变化 = 0。
* 第 1 次 reparse："imported" 题不变（被跳过删除），DUPLICATE_QNO 行新增 `parsed_questions += 1`。

→ **守恒不变量**："reparse 后 `parsed_questions` ≥ 该 chunk 实际 LLM 解出的题数"，与诊断 C.1 中观察到的"虚胖现象消失但计数仍合理"目标一致。

### F.3 `failed_chunks` 与 chunk.status

DUPLICATE_QNO 路径在 `_save_parsed_question` 内执行——`_process_chunk` 已经走完 status 决策（行 549-563）。`failed_chunks` 计数不被 PR-3 影响。

---

## G. PR-4 reconciliation 的接口

### G.1 PR-4 schema 锚点（PRD Technical Approach L4-c）

```jsonc
import_job.config_json["reconciliation"] = {
    "expected": 283,
    "imported_unique": <int>,
    "missing_qnos": [...],
    "duplicates_in_db": [...]   // ← PR-3 的 DUPLICATE_QNO 行进入此字段
}
```

### G.2 PR-3 暴露给 PR-4 的接口

```python
# PR-4 伪代码（PR-3 不实现，仅记录契约）

duplicates_in_db = [
    pq.source_question_no
    for pq in db.query(ImportParsedQuestion)
                .filter_by(import_job_id=job.id, import_status="skipped",
                           review_status="duplicate")
                .all()
    if pq.issues_json
       and any(d.get("reason") == "qno" for d in (pq.issues_json.get("details") or []))
]

# missing_qnos：DUPLICATE_QNO 行已 imported，**不**计入 missing_qnos
# 仅 chunk.issues_json["per_question_failures"] 与"题号集 - imported_unique"贡献 missing_qnos
```

### G.3 PR-3 ↔ PR-4 区分约定

* 主代理只需保证 PR-3 的 `issues_json` schema 在 `details[0].reason ∈ {"qno", "content"}` 二选一即可；
* PR-4 通过 `details[0].reason` 区分，**不依赖** `code` 字段；
* PR-3 不实现 reconciliation 字段写入（那是 PR-4 的核心职责）。

### G.4 一致性检查

为避免 PR-4 写完后"DUPLICATE_QNO 行数 ≠ duplicates_in_db.length"，PR-3 必须保证：

| 不变量 | 来源 |
|---|---|
| 凡是 DUPLICATE_QNO 命中 → ImportParsedQuestion 写一行 | C.2 表 |
| 该行 `review_status='duplicate' AND import_status='skipped' AND issues_json.details[0].reason='qno'` | C.4 schema |
| 不调 `_write_question_to_bank` | C.2 表 |

PR-3 测试 TC-1 / TC-7 / TC-8 应显式断言上述三项。

---

## H. 测试策略

### H.1 文件命名 / 风格

新建 `backend/tests/test_smart_import_reparse_hygiene.py`，沿用 PR-1/PR-2 的 fixture 风格（无 conftest.py，每文件自带 DB session fixture + `monkeypatch` mock）。

### H.2 必备单元测试 case 清单

| TC | 名字 | 关键断言 |
|----|------|---------|
| TC-1 | `test_save_parsed_question_qno_in_imported_qnos_goes_duplicate` | imported_qnos={"222"}; parsed_q.source_question_no="222" → 写 ImportParsedQuestion 一行（review_status='duplicate', import_status='skipped', issues_json.details[0].reason="qno"）；不调 `_write_question_to_bank`；`import_job.parsed_questions` += 1；`import_job.imported_questions` 不变 |
| TC-2 | `test_save_parsed_question_qno_not_in_imported_qnos_goes_normal` | imported_qnos={"100"}; parsed_q.source_question_no="222" → 走原路径（_quality_check + _auto_accept + _write_question_to_bank）；`import_job.imported_questions` += 1 |
| TC-3 | `test_save_parsed_question_imported_qnos_none_keeps_legacy_behavior` | imported_qnos=None（默认）→ 完全跳过 DUPLICATE_QNO 检查；与初次导入路径行为字节级一致 |
| TC-4 | `test_run_reparse_builds_imported_qnos_from_parsed_questions_table` | fixture：ImportParsedQuestion 多行（imported×3 / skipped×1 / pending×1）；mock `_process_chunk` 捕获实参；断言 imported_qnos == {3 个 imported 题号}（不含 skipped/pending）|
| TC-5 | `test_run_reparse_passes_bg_job_to_process_chunk` | mock `_process_chunk`，断言 kwargs["bg_job"] is background_job（identity 比较）|
| TC-6 | `test_imported_qnos_normalization_strips_hash_and_whitespace` | imported_qnos 原始题号包含 `" #222 "` `"222"` `"#223"` → 归一化后 == {"222", "223"}；parsed_q.source_question_no=" 222 " 命中；parsed_q.source_question_no="#223" 命中 |
| TC-7 | `test_reparse_double_run_does_not_reimport_qno` | 集成式：fixture 准备 1 个 imported 题（qno=222）；mock LLM 让 _process_chunk 返回 qno=222 的题；调 run_reparse 两次；断言 Question 表中 qno=222 题目个数 == 1（首次入库的那一道），ImportParsedQuestion 中 import_status='skipped' 的 DUPLICATE_QNO 行 ≥ 2（每次 reparse 各一行）|
| TC-8 | `test_save_parsed_question_qno_collision_does_not_pollute_seen_signatures` | imported_qnos={"222"}; seen_signatures=set()；调一次（命中 DUPLICATE_QNO）→ 断言 seen_signatures 仍为空（未被 add） |
| TC-9 | `test_save_parsed_question_qno_dup_writes_correct_issues_json` | DUPLICATE_QNO 行的 issues_json["details"][0]["reason"] == "qno"，issues == ["DUPLICATE"]（与 PR-4 reconciliation 接口对齐） |
| TC-10 | `test_persist_duplicate_helper_unifies_qno_and_content_paths` | 直接调 `_persist_duplicate_parsed_question`，分别传 reason="qno" / "content"；断言两次写入的 ImportParsedQuestion 仅 `details[0].reason` / `details[0].detail` 不同，其他字段（review_status / import_status / parsed_questions += 1）完全一致 |
| TC-11 | `test_save_parsed_question_qno_none_falls_back_to_content_signature` | parsed_q.source_question_no=None；imported_qnos={"222"}；正常 → 跳过 DUPLICATE_QNO，走内容签名路径（避免 None 误命中）|

> TC-1, TC-2, TC-3 覆盖 `_save_parsed_question` 的 3 条路径分支；TC-4 ~ TC-7 覆盖 `run_reparse` 的集合构建与透传；TC-8 ~ TC-11 覆盖 issues schema 与 corner cases。

### H.3 mock 策略

* **直接 mock `app.services.smart_import_service.call_ai_api`**（PR-2 测试已验证可行）；
* **TC-4/5 mock `_process_chunk`** 而非 call_ai_api，断言入参（运行时无需进入实际 chunk 处理逻辑）；
* `monkeypatch.setattr` 不引入 pytest-httpx / respx 新依赖。

### H.4 集成测试

PR-3 不写"全 PDF E2E"，留给 PR-4。PR-3 单元测试已覆盖核心路径。

---

## I. 改动面与代码重用思考

### I.1 抽 `_persist_duplicate_parsed_question` helper（推荐）

按 `code-reuse-thinking-guide.md`：

* 当前 DUPLICATE_CONTENT 路径（行 796-820）= 25 行；
* PR-3 DUPLICATE_QNO 路径若不抽 helper，需要复制 ≈22 行；
* 抽 helper 后两条路径调用 → 一处实现，一处单测（TC-10）。

```python
def _persist_duplicate_parsed_question(
    db: Session,
    parsed_q: ParsedQuestion,
    import_job: ImportJob,
    chunk: ImportChunk,
    *,
    reason: str,        # "qno" 或 "content"
    detail: str,
) -> None:
    """落库 DUPLICATE 行（review_status='duplicate', import_status='skipped'）。

    与 _save_parsed_question 内容签名 DUPLICATE 路径共享，避免 6 个字段双写漂移。
    """
    correct_answer_list = parsed_q.correct_answer or []
    question_type = "single" if parsed_q.question_type == "unknown" else parsed_q.question_type
    options_for_storage = [{"key": opt.label, "text": opt.text} for opt in parsed_q.options]
    correct_answer_str = ",".join(correct_answer_list) if correct_answer_list else ""

    parsed_question = ImportParsedQuestion(
        import_job_id=import_job.id,
        chunk_id=chunk.id,
        source_question_no=parsed_q.source_question_no,
        question_type=question_type,
        scenario_text=parsed_q.scenario,
        content=parsed_q.content,
        options_json=options_for_storage,
        correct_answer=correct_answer_str.split(",") if correct_answer_str else [],
        explanation=parsed_q.explanation or None,
        references_json=parsed_q.references if parsed_q.references else None,
        llm_confidence=Decimal(str(round(parsed_q.confidence, 4))),
        final_confidence=Decimal("0"),
        issues_json={
            "issues": ["DUPLICATE"],
            "details": [{
                "code": "DUPLICATE", "severity": "LOW",
                "reason": reason, "detail": detail,
            }],
        },
        review_status="duplicate",
        import_status="skipped",
    )
    db.add(parsed_question)
    import_job.parsed_questions = (import_job.parsed_questions or 0) + 1
    db.commit()
```

> 同时建议把 `run_smart_import` 行 338-343 与 `run_reparse` 行 1069-1075 的 `seen_signatures` 构建逻辑抽出 `_build_existing_question_signatures(db, bank_id) -> set` helper（**纯加法重构**，已重复 2 次但属"边界值"，主代理可视情况裁决；本 PR-3 设计**不强制**纳入）。

### I.2 跨层影响（cross-layer-thinking-guide.md）

* `imported_qnos` 仅在 service 层（`smart_import_service.py`）流动；
* 不污染 `routes/banks.py`、`schemas/llm_parse.py`、前端任何文件；
* `serialize_parsed_question` / `serialize_chunk` 等序列化函数**不修改**（issues_json 主 `code` 仍是 `"DUPLICATE"`）；
* 前端 `ChunkList.vue` / 复核页对 issues 数组只看 `issues[0]`，PR-3 不改变此行为。

→ **传染最小化** ✅。`imported_qnos` 是 service 内私有抽象，不渗透。

### I.3 改动文件清单

| 文件 | 变更 | 估算行数 |
|------|------|----------|
| `backend/app/services/smart_import_service.py` | (1) 新增 `_normalize_qno`；(2) 新增 `_persist_duplicate_parsed_question`；(3) `_save_parsed_question` 入口加 `imported_qnos` 参数 + DUPLICATE_QNO 分支 + 改写原 DUPLICATE_CONTENT 路径调 helper；(4) `_process_chunk` / `_process_chunk_cached` 签名加 `imported_qnos`；(5) `run_reparse` 构建 `imported_qnos` 并传给 `_process_chunk` + 补 `bg_job=background_job` | +60 / -20 |
| `backend/tests/test_smart_import_reparse_hygiene.py` | 新文件，TC-1 ~ TC-11 | +260 |

> **不改**：`call_ai_api`、`_quality_check`、`_write_question_to_bank`、`run_smart_import`（除签名风波外不变）、ORM 模型、前端、Alembic。

---

## J. 推荐落地方案 + 关键代码骨架

### J.1 总览

* `_save_parsed_question(... seen_signatures=None, imported_qnos=None)`
* `_process_chunk(... seen_signatures=None, bg_job=None, imported_qnos=None)`
* `_process_chunk_cached(... seen_signatures, imported_qnos)`（同步加参数）
* 新增 `_normalize_qno(qno: str | None) -> str | None`
* 新增 `_persist_duplicate_parsed_question(db, parsed_q, import_job, chunk, *, reason: str, detail: str) -> None`
* `run_reparse` 构建 `imported_qnos` + 同时透传 `bg_job=background_job`、`imported_qnos=imported_qnos`

### J.2 关键伪代码（≤80 行）

```python
# ─── 新增辅助函数 ─────────────────────────────────

def _normalize_qno(qno: str | None) -> str | None:
    """归一化题号：strip + 去前导 '#'。无效返回 None。"""
    if not qno:
        return None
    cleaned = qno.strip().lstrip("#").strip()
    return cleaned or None


def _persist_duplicate_parsed_question(
    db: Session,
    parsed_q: ParsedQuestion,
    import_job: ImportJob,
    chunk: ImportChunk,
    *,
    reason: str,        # "qno" | "content"
    detail: str,
) -> None:
    """统一 DUPLICATE 落库（review_status='duplicate', import_status='skipped'）。"""
    # ... 详见 I.1 全量代码

# ─── _save_parsed_question 改写（仅入口） ──────────

def _save_parsed_question(
    db, parsed_q, import_job, chunk, chunk_text, auto_import,
    seen_signatures: set | None = None,
    imported_qnos: set[str] | None = None,
) -> None:
    # PR-3：题号去重优先（reparse 路径生效；初次导入 imported_qnos=None 跳过）
    qno_norm = _normalize_qno(parsed_q.source_question_no)
    if imported_qnos is not None and qno_norm and qno_norm in imported_qnos:
        _persist_duplicate_parsed_question(
            db, parsed_q, import_job, chunk,
            reason="qno",
            detail=f"题号 {qno_norm} 已入库（reparse 跳过）",
        )
        return

    # 内容签名 DUPLICATE（保持现有语义；改为调用 helper）
    correct_answer_list = parsed_q.correct_answer or []
    question_type = "single" if parsed_q.question_type == "unknown" else parsed_q.question_type
    options_for_sig = [{"label": opt.label, "text": opt.text} for opt in parsed_q.options]
    sig = _question_signature(question_type, parsed_q.content, options_for_sig, correct_answer_list)
    if seen_signatures is not None and sig in seen_signatures:
        _persist_duplicate_parsed_question(
            db, parsed_q, import_job, chunk,
            reason="content",
            detail="与已有题目重复",
        )
        return
    if seen_signatures is not None:
        seen_signatures.add(sig)

    # ... 原行 825-889 不变

# ─── _process_chunk 签名 ─────────────────────────

def _process_chunk(
    db, chunk, import_job, auto_import, use_llm_cache,
    seen_signatures: set | None = None,
    bg_job: BackgroundJob | None = None,
    imported_qnos: set[str] | None = None,    # 新增
) -> None:
    ...
    for parsed_q in llm_result.questions:
        _save_parsed_question(
            db=db, parsed_q=parsed_q, import_job=import_job,
            chunk=chunk, chunk_text=chunk_text, auto_import=auto_import,
            seen_signatures=seen_signatures,
            imported_qnos=imported_qnos,         # 透传
        )

# ─── run_reparse 改写 ────────────────────────────

def run_reparse(db, background_job):
    # ... 行 1024-1075 不变

    # PR-3：构建 imported_qnos（来源 = 本 job 的 ImportParsedQuestion 中
    #        import_status='imported' 的 source_question_no，归一化后入集合）
    imported_qnos: set[str] = set()
    for pq in (
        db.query(ImportParsedQuestion)
          .filter_by(import_job_id=import_job.id, import_status="imported")
          .all()
    ):
        normalized = _normalize_qno(pq.source_question_no)
        if normalized:
            imported_qnos.add(normalized)

    _process_chunk(
        db=db,
        chunk=chunk,
        import_job=import_job,
        auto_import=auto_import,
        use_llm_cache=False,
        seen_signatures=seen_signatures,
        bg_job=background_job,                   # PR-2 决议补尾
        imported_qnos=imported_qnos,             # PR-3 核心
    )

    # ... 行 1086-1093 不变
```

### J.3 端到端验证清单

* [ ] `python -m py_compile backend/app/services/smart_import_service.py`
* [ ] `cd backend && python -m pytest tests/test_smart_import_reparse_hygiene.py -v`（TC-1 ~ TC-11 全绿）
* [ ] `cd backend && python -m pytest tests/test_ai_service_call_api_timeout.py -v`（PR-1 不回归）
* [ ] `cd backend && python -m pytest tests/test_smart_import_process_chunk_retry.py -v`（PR-2 不回归）
* [ ] `cd backend && python -m pytest tests/ -v`（既有测试不回归）
* [ ] 手工验证：取诊断 ImportJob#7 的某 chunk（如 chunk_no=23，含 174-188），构造 reparse → 断言无新增 Question 行 + ImportParsedQuestion 多出对应 DUPLICATE_QNO 行（仅在 dev 环境，需 LLM key；可作 ad-hoc 验证）

---

## K. 不做事项 / 留作后续 PR

| 项 | 原因 / 留给哪个 PR |
|----|-------------------|
| 给 `Question` 表加 `source_question_no` 字段（schema 迁移）| PRD Decision 2 / Technical Approach L6-c 显式拒绝；不改 schema 是本任务硬约束 |
| 把 `_question_signature` 内容做更激进 normalize（去多余空白 / 标点统一）| 超出 MVP；可能破坏现有"内容相似但不同题"的去重保护；如未来其他题库 DUPLICATE 仍虚胖再启动 |
| 前端复核页给 DUPLICATE_QNO 加专属图标 / 文案 | 不在 PRD Goal；issues 主 code 仍 `"DUPLICATE"`，前端零兼容 |
| `seen_signatures` 重命名为 `existing_content_signatures` 等更准确名字 | 超出 MVP；纯命名重构 PR 单独提 |
| `_build_existing_question_signatures` 抽 helper（`run_smart_import` 与 `run_reparse` 重复 2 次） | "边界值"重复；本 PR 不强求；可在 PR-4 / PR-5 顺手做 |
| reconciliation 写 `import_job.config_json["reconciliation"]` | **PR-4** 核心职责 |
| PR-4 之前的"积分清算"：用历史诊断脚本（C.5）把 ImportJob#7 既有的 16 个虚胖行清理掉 | 数据回填属一次性脚本任务，不在本 PR；可单独写 `research/scripts/cleanup_imp_job_7.py` 若用户需要 |
| 把 `imported_qnos` 渗透到初次导入路径（`run_smart_import`）| YAGNI；初次导入时 ImportParsedQuestion 集合在每 chunk 起点都为空（同 chunk 内 LLM 不会返回相同题号）；启用反而增加 N×SQL 查询 |
| 给 `chunk.issues_json` 增加 `dup_qno_count` / `dup_content_count` 字段 | PR-4 reconciliation 已能从 ImportParsedQuestion 表 group by 算出；不必预先冗余存 |
| 新增 `LlmParseCache` 字段 / 模型变更 | 不需要 |
| 引入 `pytest-postgresql` / 真 DB 集成测试 | PR-3 单测用 in-memory SQLite + monkeypatch 即可（与 PR-1/PR-2 风格一致）|

---

## 给主代理的总结（< 250 字）

1. **最终签名**：
   * `_save_parsed_question(... seen_signatures=None, imported_qnos: set[str] | None = None)`
   * `_process_chunk(... seen_signatures=None, bg_job=None, imported_qnos: set[str] | None = None)`（`_process_chunk_cached` 同步加参数）
2. **`imported_qnos` 来源 + 归一化**：来源表 = `ImportParsedQuestion`（按 `import_job_id == this_job AND import_status == 'imported'`）；归一化函数 `_normalize_qno(qno) = qno.strip().lstrip('#').strip() or None`，集合内只放归一化后非空字符串；比对 `parsed_q.source_question_no` 时也用 `_normalize_qno` 归一化。
3. **DUPLICATE_QNO vs DUPLICATE_CONTENT 区分**：主 `code` 都保持 `"DUPLICATE"`（前端 / serialize 零兼容），在 `details[0]` 增加 `"reason": "qno" | "content"` 子字段供 PR-4 reconciliation 区分；PR-3 同步把现有内容签名路径也带上 `reason: "content"`（一次性对齐）。
4. **抽 `_persist_duplicate_parsed_question` helper：是**。理由：DUPLICATE_QNO 与 DUPLICATE_CONTENT 路径 80%+ 字段相同（review_status / import_status / 6 个 ImportParsedQuestion 字段 / parsed_questions += 1 / commit），抽 helper 杜绝双写漂移、单测点收敛（TC-10），改动面 +1 函数 -10 行 inline 代码，纯净。
5. **回填 PRD 的新约束（建议）**：
   (a) PR-3 的 `issues_json.details[0].reason` ∈ {"qno", "content"} 是 PR-4 reconciliation 的稳定接口，应写入 PRD Technical Approach L6-d；
   (b) `_normalize_qno` 处理 `#` 前缀 / 空白的策略，应在 PRD Technical Notes 中加一行（避免后续 PR 误改 LLM prompt 让题号格式漂移破坏归一化）；
   (c) "PR-3 同时补 `bg_job=background_job` 透传"已在 PR-2 决议 4 第 3 条留位，无需新增 PRD 条款。
