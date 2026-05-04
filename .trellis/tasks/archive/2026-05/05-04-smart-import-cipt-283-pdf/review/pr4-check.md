# Code Review — PR-4

> 复核范围：`backend/app/services/smart_import_service.py`（+135/-5）
> + 新增 `backend/tests/test_smart_import_e2e_reconciliation.py`（568 行 / 7 TC）。
> 对照 PRD Decision 6 / `research/pr4-design-reconciliation.md` J 节伪代码 / AC1-AC6。

---

## A. 设计合规

| 必查项 | 结论 | 证据 |
|---|---|---|
| `_qno_sort_key` 签名 | ✅ 三元组 `(int, int, str)` 兜底类型一致（避免 `(0,int)` vs `(1,str)` 比较 TypeError）| 行 165-172 |
| `_compute_reconciliation` 签名 | ✅ `(db, import_job) -> dict`，输出 6 字段全 | 行 1836-1898 |
| `_write_reconciliation` 签名 | ✅ `(db, import_job) -> None`，dict spread + 显式重赋值触发 dirty | 行 1901-1912 |
| `run_smart_import` 写 `expected_qnos` | ✅ 在 `_split_into_chunks` 之后、`_process_chunk` 循环之前；用 `_split_by_single_question` 取题号；与 `answer_key_text` 同事务一次性 commit；用 `import_job.config_json = config` 重赋值 | 行 349-366 |
| `_finalize_import` 末尾调 `_write_reconciliation` | ✅ 在 status / summary_json / `_update_bank_stats` / `bank.source_filename` 之后；语义为"对账元数据" | 行 1960-1963 |
| `run_reparse` 末尾调 `_write_reconciliation` | ✅ 在 `_update_import_job_status` + `_update_bank_stats` 之后；满足 PRD AC3 | 行 1239-1242 |
| `serialize_import_job` 暴露 `reconciliation` | ✅ `(import_job.config_json or {}).get("reconciliation")` None-safe | 行 2053 |
| `_compute_reconciliation` expected 来源 | ✅ `config.get("expected_qnos") or []` 双重 None-safe | 行 1854-1855 |
| imported_set 来源 | ✅ `ImportParsedQuestion` 按 `import_job_id + import_status='imported'`；归一化后入集 | 行 1857-1865 |
| duplicates_set 接 PR-3 接口 | ✅ `import_status='skipped'` + `details[0].reason=='qno'` 过滤；遍历用 `any(...)` 兼容多 detail | 行 1867-1877 |
| per_q_failures_set | ✅ 遍历 `ImportChunk.issues_json["per_question_failures"]`，归一化后入集 | 行 1879-1887 |
| `missing_set = (expected - imported) \| per_q_failures` | ✅ 合集语义；防御 expected_qnos 漏题号的极端情况 | 行 1889 |
| `computed_at` | ✅ `datetime.now(timezone.utc).isoformat()` | 行 1897 |
| 5 处 logger 补齐 | ✅ 全部到位 | 详见 E.E |

**A 节结论**：完全对齐 PR-4 design J 节伪代码骨架。

---

## B. 测试质量

| 必查项 | 结论 | 证据 |
|---|---|---|
| 7 个 TC 覆盖 PR-4 design E.5 | ✅ 全部 | 7 PASSED / 0 SKIP / 0 XFAIL |
| TC-1 全成功断言 | ✅ `len(expected)==283 / len(imported_unique)==283 / missing_qnos==[] / duplicates_in_db==[] / per_question_failures_count==0`，`computed_at` 由 `datetime.fromisoformat()` 反查 | 测试 306-324 |
| TC-2 `chunk_27.status=="parsed_retry"` + `retry_count==1` + `fallback_used is False` | ✅ | 测试 330-351 |
| TC-3 `chunk_27.status=="parsed_fallback"` + caplog 含 "entering L2"/"L1 retry" | ✅ | 测试 357-389 |
| TC-4 `missing_qnos=={"222","223","224","225"}` + `chunk_27.status=="parsed_partial"` + `failed_chunks==1` + `status=="partial_imported"` | ✅ | 测试 395-421 |
| TC-5 reparse 后 `missing_qnos==[]` + `expected_qnos` 不变（AC3） | ✅ 阶段 1/2 顺序，`expected_before` 与 reparse 后比对 | 测试 427-473 |
| TC-6 `_finalize_import` 不 clobber `answer_key_text/expected_qnos/auto_import/custom_marker` | ✅ | 测试 479-512 |
| TC-7 `serialize_import_job` 暴露 `reconciliation`（None-case + dict-case） | ✅ 两个 ImportJob 实例 | 测试 518-568 |
| 31 chunk 题号分布完全对齐 diagnosis B.2 | ✅ `assert sum(end-start+1)==283` | 测试 73-84 |
| mock 风格沿用 PR-2/PR-3 | ✅ `monkeypatch.setattr(svc, "call_ai_api", ...)` + `time.sleep`/`heartbeat_job` 归零 | 测试 213-217 / 308 等 |

**JSONB→JSON SQLite 兼容钩子评估**（必查项 11）：
- 钩子 `@compiles(JSONB, "sqlite")` 仅在测试文件 `test_smart_import_e2e_reconciliation.py` 顶部定义（行 47-50）；
- production 代码（`smart_import_service.py`）未引用任何 `compiles`/`JSONB` 装饰器；
- 钩子是 SQLAlchemy 公开 API、行业惯用 fixture 技巧；register 是进程内全局，但只在 SQLite dialect 下生效，PG 生产路径不受影响；
- 与生产环境 `psycopg` 路径正交。**评估：合理、范围可控。**

---

## C. PR-2/PR-3 测试不回归

* `git diff backend/tests/test_smart_import_process_chunk_retry.py backend/tests/test_smart_import_reparse_hygiene.py backend/tests/test_ai_service_call_api_timeout.py` 输出为空 — PR-4 完全没动既有测试 fixture。
* `pytest backend/tests/ -v` 共 **31 PASSED**：
  - PR-1: 4 / 4 (test_ai_service_call_api_timeout)
  - PR-2: 12 / 12 (test_smart_import_process_chunk_retry)
  - PR-3: 8 / 8 (test_smart_import_reparse_hygiene)
  - PR-4: 7 / 7 (test_smart_import_e2e_reconciliation)
* 0 SKIP / 0 XFAIL / 0 collection error。

---

## D. Cross-layer / Reuse

* `_normalize_qno` 在 PR-4 共复用 4 处：`run_smart_import` 写 expected（行 354）、`_compute_reconciliation` 三个集合（行 1863 / 1875 / 1885）、`_persist_duplicate_parsed_question` 内日志（行 894）。**统一归一化路径**，符合 code-reuse-thinking-guide.md。
* `_split_by_single_question` 由 PR-2 引入，A.3 计算 `expected_qnos` 复用，避免新建并行函数。
* `_qno_sort_key` 用作 `expected_qnos` 排序与 `_compute_reconciliation` 内 4 处 `sorted(...)` 的 key —— 单点定义，处处复用。
* dict 重赋值触发 dirty 的写法与 `run_smart_import:359-364` / `run_reparse:1191`（既有）/ `_write_reconciliation` 完全一致。
* Cross-layer：`_compute_reconciliation` 读 ORM → 计算 set diff → 写 ORM JSONB；`serialize_import_job` 透传到 API；前端不依赖。各层职责清晰。

**性能评估**：`_compute_reconciliation` 内 4 次 `db.query(...).filter_by(...).all()`，对 CIPT 283 题量级（~283 ImportParsedQuestion + 31 ImportChunk）单测 5s 跑完 7 TC，N+1 风险可忽略；finalize 一次性调用而非热路径。

---

## E. 异常 & 日志

5 处 logger 全到位，日志 grep 实测：

```
408:    logger.error("Chunk %d 解析失败: %s", ...)         # 既有
730:    logger.warning("[smart_import] L1 retry attempt=%d/%d sleep=%ss reason=%s", ...)
773:    logger.warning("[smart_import] chunk_no=%s entering L2 per-question fallback (segments=%d)", ...)
780:    logger.warning("[smart_import] chunk_no=%s L2 budget %ss exceeded, dropped=%d", ...)
824:    logger.warning("[smart_import] chunk_no=%s heartbeat failed at segment %d/%d: %s", ...)
893:    logger.info("[smart_import] duplicate parsed question reason=%s source_qno=%s", ...)
1061:   logger.info("题库 %d 已存在相同题目 (id=%d)，跳过写入", ...)  # 既有
```

* 格式统一前缀 `[smart_import]`（除两条既有日志外），与 logging-guidelines.md 推荐模式一致。
* level 选择：异常路径（L1 retry / L2 entering / budget / heartbeat）= warning；正常业务事件（DUPLICATE 命中）= info；分级合理。
* 用 `%s` 懒格式化，未输出敏感信息（仅 chunk_no/题号/段号/异常类名）。
* `--log-cli-level=WARNING` 实测捕获到 4 条 PR-4 logger（TC-2/3/4/5），TC-3 的 caplog 断言 `entering L2` + `L1 retry` 都命中。

**异常处理**：`_compute_reconciliation` 内全部用 `.get(...)` / `or []` / `or {}` 防御 None，未抛异常的逻辑链 → 确保 `_finalize_import` 不会因对账数据缺失整体崩溃。

---

## F. 运行验证

| 命令 | 结果 |
|---|---|
| `python3 -m py_compile backend/app/services/smart_import_service.py` | ✅ |
| `python3 -m py_compile backend/tests/test_smart_import_e2e_reconciliation.py` | ✅ |
| `python3 -m pytest backend/tests/ -v` | ✅ **31 passed in 4.98s** |
| `python3 -m pytest backend/tests/test_smart_import_e2e_reconciliation.py -v --log-cli-level=WARNING` | ✅ 7 passed，stdout 显示 logger 输出 |

---

## G. AC 对账（终结）

| AC | 必修要求 | 结论 | 证据 |
|---|---|---|---|
| **AC1** | CIPT 31 chunk fixture 全 283 题入库（含 timeout 一次重试恢复）| ✅ | TC-1（happy path）/ TC-2（L1 retry）/ TC-3（L2 fallback）/ TC-5（reparse 恢复）四路径覆盖；fixture 严格 31 chunk 真实题号分布；断言 `len(imported_unique)==283` |
| **AC2** | reconciliation 6 字段完整 | ✅ | TC-1 行 316-322 完整断言；字段类型 = (array, array, array, array, int, ISO8601 string) |
| **AC3** | reparse 不重复入库 + 重新计算 reconciliation | ✅ | TC-5 阶段 2 `recon_after.missing_qnos == []` + `expected_qnos == expected_before`（不污染） |
| **AC4** | 单元 + 集成测试覆盖 3 条路径 | ✅ | 31 个测试全绿（含 PR-2 12 chunk 重试 TC + PR-3 8 reparse TC + PR-4 7 reconciliation TC） |
| **AC5** | `pytest backend/tests/` 0 collection error | ✅ | "31 passed in 4.98s, 0 skipped, 0 errors" |
| **AC6** | 不引入 OCR / 新 ORM 字段 / pytest-httpx / respx；PROMPT_VERSION=v1 | ✅ | grep 实测 `requirements*.txt` 无 respx/pytest-httpx/pytesseract；`PROMPT_VERSION = "v1"` 行 49 不变；无 Alembic 迁移新增 |

**AC1-AC6 全部勾选。**

---

## H. 风险 & 回归

* **reparse 路径**：PR-3 已加 `imported_qnos` + `bg_job`；PR-4 在末尾追加 `_write_reconciliation`。TC-5 端到端验证 reparse 流程不破。✅
* **初次导入路径**：TC-1 happy path 全成功 + reconciliation `missing_qnos==[]` 验证。✅
* **JSONB→JSON 兼容 hook 副作用**：仅在测试文件 import 时全局生效；`smart_import_service.py` 无任何 JSONB import；生产 PG 路径未触动。✅
* **`serialize_import_job` 暴露 reconciliation 字段**：前端 `serialize` 消费方不强制校验 schema（项目惯例宽松解析）；TC-7 验证 None-case 与 dict-case；前端代码未改（PRD Out of Scope 一致）。✅
* **`_compute_reconciliation` 性能**：4 次 query 仅在 finalize / reparse 完结时触发，非热路径。✅
* **expected_qnos 计算**：在 `_split_into_chunks` 后（行 349-366）一次性写入；reparse 路径完全不重写该字段（行 1184-1188 仅 `chunk.issues_json=None`），保证可重复对账。✅

---

## I. logger spec 对齐

* `logging-guidelines.md` 现状："Flask 版零 logging / FastAPI 仅 smart_import_service 唯一使用 logging"。PR-4 在该文件已有 logger 基础上扩展 5 处（warning × 4 + info × 1），完全契合"推荐模式"段。
* `logger = logging.getLogger(__name__)` 已在文件行 45 存在，PR-4 未重复创建。
* 5 条 message format 全部使用懒格式化 `%s`，未在 message 中输出 chunk_text / 题干等可能含敏感数据的字段；仅暴露元数据（chunk_no、题号、异常类名、段号）。
* 与 spec "推荐：异常用 logger.error；关键业务事件用 logger.info" 略有偏差：PR-4 把 L1 retry / L2 entering / budget / heartbeat 用 warning 而非 error —— 这些是"中间态告警"，不应视为终结性 error；warning 选择与"还有恢复可能"语义一致，更精确。可接受。

---

## 结论

**通过（可 commit）。**

* PR-4 完整实现 `research/pr4-design-reconciliation.md` 全部决策，对齐 PRD Decision 6；
* 31 个回归测试 + 7 个新测试全绿；
* AC1-AC6 全部勾选；
* 无 schema / 依赖 / 前端连带改动；
* 既有 PR-1/PR-2/PR-3 测试零回归。

**必修项**：无。

**建议（非必修）**：

1. PRD AC2 措辞回填：把"`expected:283` / `imported_unique:283` 整数 count"改为"长度=283 的题号字符串数组"，与实际 schema 一致；当前测试已断言 `len(...)==283`，PRD 文字表述可一并对齐。
2. `quality-guidelines.md` 或新增 `import-pipeline.md` 可补充一节"chunk 失败两级重试 + reconciliation 报告"约定（DoD 项），承接 PR-2/PR-3/PR-4 的累计设计。属文档收尾，本 PR 不做也不阻塞。
3. 未来若新增"题号字典序兜底排序"非纯数字题号场景，`_qno_sort_key` 可加一个 `re.match(r"\d+([a-z]+)")` 的混合解析维度（如 `"5a"` < `"5b"` < `"6"`），对当前 CIPT 283 PDF 不需要。

---

## Commit message 关键信息

* 类型：feat（核心功能闭环）+ test（7 TC）
* 范围：smart_import service / tests
* 关键改动：
    1. `run_smart_import` 切完 chunk 后写 `expected_qnos` 到 `config_json`
    2. 新增 `_qno_sort_key` / `_compute_reconciliation` / `_write_reconciliation`
    3. `_finalize_import` & `run_reparse` 末尾追加 `_write_reconciliation`
    4. `serialize_import_job` 暴露 `reconciliation` 顶层字段
    5. 5 处 logger 补齐（L1 retry / L2 entering / L2 budget / heartbeat 失败 / DUPLICATE 命中）
    6. 新增 `test_smart_import_e2e_reconciliation.py`（7 TC，568 行；in-memory SQLite + JSONB→JSON @compiles 钩子）
* 关联 PRD AC1/AC2/AC3/AC4/AC5/AC6
* 任务整体闭环：smart_import CIPT 283 PDF 准确率 ≥98% 路径全部就位（PR-0 到 PR-4 共 31 个测试覆盖）

Suggested commit message:

```
feat(smart_import): PR-4 reconciliation report + logger 补齐 + E2E 集成测试

- 新增 _compute_reconciliation / _write_reconciliation：在 _finalize_import
  与 run_reparse 末尾产出 expected/imported_unique/missing_qnos/
  duplicates_in_db/per_question_failures_count/computed_at 六字段对账数据
- run_smart_import 切完 chunk 后将 expected_qnos 写入 config_json，作为
  reconciliation 不变基线（reparse 不污染）
- serialize_import_job 暴露 reconciliation 顶层字段（前端可选消费）
- 补齐 5 处 logger：L1 retry / L2 entering / L2 budget exceeded /
  heartbeat 失败 / DUPLICATE 命中
- 新增 backend/tests/test_smart_import_e2e_reconciliation.py（7 TC，
  纯 chunk fixture + monkeypatch + caplog；闭合 PRD AC1/AC2/AC3）
- 31 个测试全绿（PR-1 4 + PR-2 12 + PR-3 8 + PR-4 7）

Closes: smart-import 准确率优化（CIPT 283 PDF）任务 PR-4
AC1-AC6 全部勾选；无 schema / 新依赖 / 前端连带改动。
```
