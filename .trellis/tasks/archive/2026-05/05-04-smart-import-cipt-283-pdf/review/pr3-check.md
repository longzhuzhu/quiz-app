# Code Review — PR-3（reparse 卫生 + imported_qnos 题号去重 + bg_job 透传）

> 审核范围：1 M `backend/app/services/smart_import_service.py`（+127/-25）；
> 1 M `backend/tests/test_smart_import_process_chunk_retry.py`（+1/-1，PR-2 兼容性补丁）；
> 1 ?? `backend/tests/test_smart_import_reparse_hygiene.py`（新文件，549 行 / 8 TC）。
> 对照依据：`research/pr3-design-reparse-hygiene.md` J 节、PRD Decision 5、AC1–AC6。

---

## A. 设计合规

| 项 | 结果 | 落点说明 |
|---|---|---|
| 1. `_normalize_qno(qno)` helper | ✅ | `smart_import_service.py:152-164`。`qno is None / 空白 / "#"` 一律返回 None；`" #222 "` / `"#222"` / `"222"` → `"222"`。保持 `str` 类型（兼容非纯数字题号），与设计 B.2 一致。 |
| 2. `_persist_duplicate_parsed_question(...)` helper | ✅ | `smart_import_service.py:796-859`。`if reason not in ("qno", "content"): raise ValueError(...)` 防御性校验存在；`review_status='duplicate'`、`import_status='skipped'`；`issues_json.issues=["DUPLICATE"]` 主 code 不变；`details[0].reason ∈ {"qno","content"}` + `severity="LOW"` + `detail` 文案；`parsed_questions += 1`；不调 `_quality_check` / `_write_question_to_bank`；不更新 `seen_signatures`；helper 内部 `db.commit()`。与设计 I.1 / J.2 完全一致。 |
| 3. `_save_parsed_question` 签名加 `imported_qnos: set[str] \| None = None` | ✅ | `smart_import_service.py:862-871`。位置紧跟 `seen_signatures` 之后（kw-only 风格保持）。 |
| 4. 入口 DUPLICATE_QNO 优先判断（仅 `imported_qnos is not None` 时） | ✅ | `smart_import_service.py:885-892`。归一化后题号命中即调 helper(`reason="qno"`) + `return`；不进入内容签名路径；不污染任何集合。 |
| 5. 内容签名 DUPLICATE 路径改用 helper | ✅ | `smart_import_service.py:902-906`。原内联 25 行 ImportParsedQuestion 构造代码块（PR-2 后约 814-840）已被替换为单行 `_persist_duplicate_parsed_question(..., reason="content")` 调用 + `return`。原行为字段保留 + 额外多了 `reason: "content"`。 |
| 6. `_process_chunk` / `_process_chunk_cached` 签名加参数并透传 | ✅ | `_process_chunk` 签名行 408-417 加 `imported_qnos`，行 476、619 透传给 `_save_parsed_question`；`_process_chunk_cached` 签名行 625-633 加 `imported_qnos`，行 668 透传。 |
| 7. `run_reparse` 改动（imported_qnos 构建 + bg_job 透传） | ✅ | 行 1163-1188。`seen_signatures` 构建段保留；新增 `imported_qnos` 集合从 `ImportParsedQuestion(import_job_id=this, import_status='imported')` 取数 → `_normalize_qno` → 仅添加非 None 项；调 `_process_chunk` 时同时传 `bg_job=background_job`（PR-2 留尾巴）+ `imported_qnos=imported_qnos`（PR-3 新增）。 |
| 8. `run_smart_import` 入口不传 `imported_qnos` | ✅ | 行 377-385 调 `_process_chunk` 仍只传 `bg_job=bg_job`；`imported_qnos` 走默认 None。初次导入路径行为字节级不变。 |
| 9. `_question_signature` 函数体未被修改 | ✅ | 行 118-140 内容与 PR-2 后一致；diff 中无该函数变更。 |
| 10. 不引入 ORM schema / Alembic / PROMPT_VERSION 改动 | ✅ | `git diff` 仅触及 `smart_import_service.py`；模型文件、`PROMPT_VERSION="v1"` 不变；无 Alembic migration 新增。 |

---

## B. 测试质量

| 项 | 结果 | 说明 |
|---|---|---|
| 11. 8 个 TC 命名 | ✅ | TC-1..TC-8 命名直接对齐设计 H.2 表前 8 项；TC-9..TC-11 在本 PR 不实施（属可选加强测试），不阻塞。 |
| 12. 8 个 TC 全部 PASS | ✅ | `pytest backend/tests/test_smart_import_reparse_hygiene.py -v` 8 passed，无 SKIP / XFAIL。 |
| 13. mock 策略评估 | ✅ | 全部用 `monkeypatch.setattr(svc, ...)` 替换模块级符号（`_write_question_to_bank` / `_process_chunk` / `_persist_duplicate_parsed_question`）；自定义轻量 `_FakeDB` 替代 SQLAlchemy Session（捕获 add/delete/flush/commit + query 路由）。不进 httpx；不引入 pytest-httpx / respx 新依赖。TC-4/5 用 `_FakeDB.set_query_result` 路由表精确控制 `ImportParsedQuestion` 不同 filter 切片返回值，避开真 ORM 复杂度，符合 PR-1/PR-2 既定测试风格。 |
| 14. TC-1 关键断言 | ✅ | 行 202-218：`db.added` 长度 = 1；`isinstance(... ImportParsedQuestion)`；`review_status="duplicate"`；`import_status="skipped"`；`issues_json.details[0].reason == "qno"` + `code == "DUPLICATE"` + `severity == "LOW"`；`parsed_questions == 1`；`imported_questions == 0`；`write_calls == []`（哨兵确认 `_write_question_to_bank` 未被调）。 |
| 15. TC-3 兼容性断言 | ✅ | 行 290-312：用 spy 包装 `_persist_duplicate_parsed_question`，断言 `imported_qnos=None` 时 helper 完全未被调用，正常入库路径完整跑完（`_write_question_to_bank` 调一次）。即"内容签名 DUPLICATE 路径仍生效"由 TC-3 兼容路径间接覆盖；TC-3 偏向断言"DUPLICATE_QNO 完全跳过"。设计 H.2 中 TC-3 的本意如此。一项可选加强：补一个独立 case 验证 `seen_signatures` 命中时调用 helper(reason="content")，但当前 PR-3 未触发也不破坏现有内容签名 DUPLICATE 行为，作为非阻塞建议。 |
| 16. TC-6 题号格式覆盖 | ✅ | 行 437-444 直接对 `_normalize_qno` 单测：`" #222 "` / `"#223"` / `"224"` 三种主形式齐全；外加 `"##5a##"`（lstrip 仅去首字符）/ `""` / `"   "` / `"#"` / `None` 边界。行 457-468 通过 `_save_parsed_question` 端到端验证 `parsed_q.source_question_no=" #222 "` 命中 `imported_qnos={"222"}` → DUPLICATE_QNO。 |
| 17. TC-7 双 reparse 断言 | ⚠️ 实质满足，形式略弱 | 行 474-519：测试连续两次 `_save_parsed_question(... imported_qnos={"222"})` 而非两次 `run_reparse`。从单测目的看等价（`run_reparse` 入口每次重建 `imported_qnos`，且 `import_status='imported'` 行从不被删；连续两次解析同题号即等同于双 reparse 在 `_save_parsed_question` 视角的等价场景）。断言完整：`write_calls == []`、`db.added` 中 ImportParsedQuestion 行 = 2、各行均 review_status='duplicate' + import_status='skipped' + reason='qno'、`parsed_questions == 2`、`imported_questions == 0`。**非阻塞**。如需更接近端到端，可后续补一个用 `_FakeDB` 路由两次 `run_reparse` 的集成 case；当前已能保护核心不变量。 |
| 18. TC-8 不污染 seen_signatures | ✅ | 行 525-549：`seen = set()`；调用后 `assert seen == set()`，明确断言 DUPLICATE_QNO 早返回路径不更新签名集合。 |

> 综合：8 个 TC 落地，断言密度高、监控点齐全。最弱项是 TC-7 偏单测性，但与 design H.2 留有 9..11 号备选 TC（PR-3 设计已声明 PR-3 单测就够，端到端留 PR-4），符合 MVP 约束。

---

## C. PR-2 测试 fixture 兼容性补丁

| 项 | 结果 | 说明 |
|---|---|---|
| 19a. 仅 1 行变动 | ✅ | `git diff backend/tests/test_smart_import_process_chunk_retry.py` 只有 `_fake_save_parsed` 签名加 `imported_qnos=None` 一行。 |
| 19b. 是否破坏 PR-2 12 TC 语义 | ✅ | 12 TC 全部 PASS；新 kwarg 仅是函数签名兼容性吸收，未触及任何断言或调用栈。 |
| 19c. 是否符合"最小手术"原则 | ✅ | 替代方案是在 `_process_chunk` 内 conditional kwargs（仅当 `imported_qnos is not None` 才传），但那会污染生产代码以兼容老测试 fixture。**当前选择正确**：生产代码无条件透传新 kwarg，老 fixture 吸收 `imported_qnos=None` 默认值，单点最小变更。 |

---

## D. Cross-layer / Code Reuse

| 项 | 结果 | 说明 |
|---|---|---|
| 20. helper 抽取符合"先搜索再创建" | ✅ | `_persist_duplicate_parsed_question` 不是新工具被多处调用，而是从既有内联代码抽出；2 处调用（DUPLICATE_QNO 入口 + DUPLICATE_CONTENT 入口）；按 `code-reuse-thinking-guide.md`"Same code appears 2x 边界值 + 主动复用时机"规则，抽取得当，杜绝双写漂移。 |
| 21. 跨层最小传染 | ✅ | `imported_qnos` 仅在 `smart_import_service.py` 内 `run_reparse` → `_process_chunk` → `_process_chunk_cached` → `_save_parsed_question` → `_persist_duplicate_parsed_question` 流通。`routes/banks.py`、`schemas/llm_parse.py`、`models/*`、前端任何文件不被触及。`serialize_parsed_question` 不需修改（issues_json 主 code 仍 `"DUPLICATE"`，前端零兼容代价）。完全符合 `cross-layer-thinking-guide.md`"Each layer only knows its neighbors"。 |
| 22. `_normalize_qno` 双向使用同一函数 | ✅ | `run_reparse:1175` 构建集合用 `_normalize_qno(pq.source_question_no)`；`_save_parsed_question:887` 入口比对用 `_normalize_qno(parsed_q.source_question_no)`。两处函数一致，单一事实源，避免未来归一化漂移。 |

---

## E. 异常处理 & 日志

| 项 | 结果 | 说明 |
|---|---|---|
| 23a. 防御性 ValueError 是否破坏现有调用 | ✅ | 两处调用都是字面量 `reason="qno"` / `reason="content"`，永不触发 ValueError；属未来误用保护。 |
| 23b. 是否符合 FastAPI 服务层错误约定 | ✅ | 与 `error-handling.md` 4 模式中"Service 抛 ValueError → Route 转 400"一致；helper 抛 ValueError 在 service 边界即可。 |
| 24. 关键路径日志 | ⚠️ 建议项（非阻塞） | `_persist_duplicate_parsed_question` / DUPLICATE_QNO 命中均无 `logger.info` / `logger.warning`。当前文件仅 `logger.error("Chunk %d 解析失败")` 与 `logger.info("题库 %d 已存在相同题目")` 两处使用。建议在未来 PR（或本 PR 视主代理裁决）补 `logger.info("DUPLICATE_QNO hit qno=%s import_job_id=%d", qno_norm, import_job.id)`，便于诊断 reparse 命中规模。**不阻塞 commit**。 |

---

## F. 运行验证

| 项 | 结果 | 命令 / 输出 |
|---|---|---|
| 25. 语法编译 | ✅ | `python3 -m py_compile backend/app/services/smart_import_service.py` 无报错。 |
| 26. 全量测试 | ✅ | `python3 -m pytest backend/tests/ -v` → 24 passed in 0.76s（4 PR-1 + 12 PR-2 + 8 PR-3）。 |
| 27. PR-3 测试单跑 | ✅ | `pytest test_smart_import_reparse_hygiene.py -v` 8 passed。 |
| 28. PR-2 测试单跑（回归） | ✅ | `pytest test_smart_import_process_chunk_retry.py -v` 12 passed。 |
| 29. 核心 diff 对齐设计 J 节 | ✅ | `git diff` 与 J.2 伪代码骨架字面对齐：`_normalize_qno`（行 152-164）、`_persist_duplicate_parsed_question`（行 796-859）、`_save_parsed_question` 入口（行 885-906）、`_process_chunk` 签名 + 透传（行 416、476、619）、`_process_chunk_cached` 签名 + 透传（行 631、668）、`run_reparse` 集合构建 + bg_job 补尾（行 1163-1188）。 |

---

## G. AC 对账（前置）

| AC | 结果 | 说明 |
|---|---|---|
| AC1（CIPT 283 PDF 全 283 题入库） | ⏳ 待 PR-4 | PR-3 不直接保证 AC1，但提供 reparse 路径下"零虚胖"基础——配合 PR-2 重试链路，对 chunk 27 reparse 时已 imported 题号不会被二次入库。AC1 集成验证留 PR-4。 |
| AC2（reconciliation 写入 config_json） | ⏳ 待 PR-4 | PR-3 已确认 `issues_json.details[0].reason ∈ {"qno","content"}` 是 PR-4 reconciliation 稳定 lookup 接口（设计 G 节）。PR-3 自身不写 reconciliation 字段。 |
| AC3（reparse 不重复入库） | ✅ | TC-7 直接覆盖；TC-1 / TC-4 / TC-6 间接保护。 |
| AC4（单元测试覆盖） | ✅ | 累计 24 个 FastAPI 风格测试（4 + 12 + 8）；CI 假设全绿。 |
| AC5（pytest 0 collected, 0 errors → 24 passed） | ✅ | PR-0 已删 12 Flask 测试，PR-1 起累计 24 测试全绿。 |
| AC6（无新依赖 / 无 OCR / PROMPT_VERSION 不动） | ✅ | 未引入 `pytest-httpx` / `respx` / `pytesseract`；未加 ORM 字段；`PROMPT_VERSION="v1"` 维持。 |

---

## H. 风险 & 回归

| 项 | 结果 | 说明 |
|---|---|---|
| 34. 初次导入路径回归 | ✅ | `run_smart_import` 行 377-385 不传 `imported_qnos`（默认 None）；`_save_parsed_question:886` 的 `if imported_qnos is not None` 守卫确保 happy path 与 PR-3 之前字节级一致；现有 12 PR-2 TC + happy path 行为均已验证。 |
| 35. 内容签名 DUPLICATE 路径回归 | ✅（含 schema 增量） | `_persist_duplicate_parsed_question(..., reason="content")` 完整保留原 6 字段（`review_status='duplicate'` / `import_status='skipped'` / `issues_json.code='DUPLICATE'` / `parsed_questions += 1` / 无 `_write_question_to_bank` / 无 `seen_signatures.add`）；唯一新增 `details[0].reason="content"` 子字段。前端读 `issues[0]` 主码不受影响（`serialize_parsed_question` 直接返回 issues_json）；DB 数据与 PR-3 之前的内容签名 DUPLICATE 行多一个键，向前兼容。 |
| 36. `imported_questions` 计数稳定性 | ✅ | helper 内行 858 仅 `parsed_questions += 1`，`imported_questions` 不动；TC-1 / TC-7 显式断言 `job.imported_questions == 0`。两条 DUPLICATE 路径计数行为一致。 |

---

## 结论

- **通过（可 commit）**。
- **必修项：0**。
- **建议项（非阻塞，可后续 PR）**：
  1. 在 `_persist_duplicate_parsed_question` 命中分支补 `logger.info("DUPLICATE_%s hit qno=%s import_job_id=%d", reason.upper(), _normalize_qno(parsed_q.source_question_no), import_job.id)`，便于线上反查 reparse 命中规模。与 `smart_import_service.py:1021` 已有 `logger.info("题库 %d 已存在相同题目...")` 风格对齐，符合 `logging-guidelines.md`"smart_import_service 是项目唯一正确使用 logging 的文件"。
  2. 未来如某 PR 补一个端到端集成 case（用 `_FakeDB` 路由两次 `run_reparse` 调用对同 chunk），让 TC-7 的语义从单点路径升级到入口级。

---

## Commit message 关键信息

- **范围**：PR-3 of smart-import-cipt-283-pdf 任务（决策 5）。
- **核心改动**：
  - 新增 `_normalize_qno` helper（`#` 前缀 / 空白归一化）；
  - 新增 `_persist_duplicate_parsed_question` helper（统一两条 DUPLICATE 路径落库逻辑，杜绝双写漂移）；
  - `_save_parsed_question` 入口加 DUPLICATE_QNO 优先判断（仅 reparse 路径生效，初次导入零影响）；
  - `_process_chunk` / `_process_chunk_cached` 签名透传 `imported_qnos`；
  - `run_reparse` 构建 `imported_qnos` 集合（来源 `ImportParsedQuestion.import_status='imported'`）+ 同时透传 `bg_job=background_job`（PR-2 留尾巴）；
  - `issues_json.details[0].reason ∈ {"qno","content"}` 子字段——PR-4 reconciliation 的稳定 lookup 接口；
  - PR-2 测试 fixture `_fake_save_parsed` 签名兼容性补丁（仅加 `imported_qnos=None` 默认值）；
  - 新增 `test_smart_import_reparse_hygiene.py`（8 TC，549 行）。
- **不改**：`PROMPT_VERSION`（仍 v1）；ORM schema；Alembic；前端；`call_ai_api`；`_quality_check`；`_write_question_to_bank`。
- **测试**：24 passed（4 PR-1 + 12 PR-2 + 8 PR-3）。
- **AC 进度**：AC3 / AC4 / AC5 / AC6 ✅；AC1 / AC2 留 PR-4。
- **无 breaking change**：初次导入路径默认 None 等价 noop；DUPLICATE_CONTENT 行向前兼容（仅多一个可选字段）；前端零修改。
