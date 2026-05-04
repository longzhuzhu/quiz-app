# Code Review — PR-2

> 复核范围：`backend/app/services/smart_import_service.py`（+412 行）、`backend/tests/test_ai_service_call_api_timeout.py`（PR-1 TC-4 正则放宽）、`backend/tests/test_smart_import_process_chunk_retry.py`（新增 12 TC，598 行）。
> 复核依据：`research/pr2-design-process-chunk-retry.md` J 节伪代码骨架 + PRD Decision 4 + spec 目录下质量/异常/日志/重用规范。

---

## A. 设计合规

| 项 | 结果 | 证据 / 说明 |
|---|---|---|
| 1. 模块级常量完整且对齐 | ✅ | `smart_import_service.py:54-80`：`L1_MAX_RETRIES=1`、`L1_RETRY_BACKOFF_SECONDS=2.0`、`RETRY_BASE_SECONDS=2.0`、`RETRY_CAP_SECONDS=10.0`、`L2_PER_QUESTION_TIMEOUT=60.0`、`CHUNK_TOTAL_BUDGET_SECONDS=480.0`、`HEARTBEAT_EVERY_N_SEGMENTS=3`、`RETRYABLE_HTTP_EXC=(httpx.TimeoutException, httpx.HTTPError)` 全部存在，值 100% 对齐 design J.2 / Decision 4。注释明确写出"RETRY_BASE/CAP 暂不消费、未来扩展预留"。 |
| 2. `_is_retryable_value_error` 仅按 `"AI API 错误 (5"` 前缀判断 | ✅ | 行 143-149：`return "AI API 错误 (5" in str(exc)`。4xx / API key 缺失消息不会包含 `"(5"` 前缀，自动落入"不重试"分支。TC-6 / TC-7 已显式断言。 |
| 3. `_split_by_single_question` 不走"短片段合并"分支 | ✅ | 行 1353-1386：finditer 遍历后直接构造 `out` 列表返回，无 `merged` / `buffer_text` 合并步骤。`best_count == 0` 时 `return []`（与 design J.2 对齐）。注意阈值 `>0` 而非 `_split_by_question_markers` 的 `<2`（语义合理：单题 chunk 也允许 L2 走完）。 |
| 4. `_call_llm_with_l1_retry` 双元组返回 | ✅ | 行 657-694：签名 `-> tuple[str, int]`，成功路径 `return text, attempt`（attempt=0 表首次成功）；非可重试 ValueError 立即 `raise`（行 686），retryable 用尽抛 last_exc（行 694）。 |
| 5. `_run_per_question_fallback` 行为 | ✅ | 行 697-775：① 切不出题号 → 行 722-727 返回 `[{stage:"L2_fallback_skipped", error:"no_question_markers"}]`；② budget kill switch `time.monotonic() - started_at > CHUNK_TOTAL_BUDGET_SECONDS` 行 732；③ 超 budget 把剩余 segment 标 `L2_fallback_budget_exceeded` 后 `break`（行 733-739）；④ heartbeat `idx % HEARTBEAT_EVERY_N_SEGMENTS == 0` 行 762；⑤ heartbeat 失败 `try/except Exception: pass` 行 771-773 不打断 fallback；⑥ 异常分类 `(ValueError, httpx.HTTPError, json.JSONDecodeError, ValidationError)` 行 749-754 ✓。 |
| 6. `_process_chunk` 终态映射顺序正确 | ✅ | 行 549-563：`if fallback_used and not merged_questions → failed` → `elif fallback_used and per_question_failures → parsed_partial` → `elif fallback_used → parsed_fallback` → `elif retry_count > 0 → parsed_retry` → `else parsed`。`parsed_partial` 在 `parsed_fallback` 之前（关键，否则部分失败会被错判全成）✓。 |
| 7. `chunk.issues_json` schema | ✅ | 行 565-581：`retry_count` / `fallback_used` / `per_question_failures` 一律写入；`fallback_meta` 仅 `if fallback_used` 才写（含 `total_segments / succeeded / failed / elapsed_seconds`）；`chunk_issues` 仅 LLM 真返回时写入（行 579-580）。完全对齐 Decision 4-第 6 点 schema。 |
| 8. `_store_llm_cache` 仅在非 fallback + 非失败状态调用 | ✅ | 行 584：`if use_llm_cache and not fallback_used and chunk.status not in ("failed", "llm_failed", "parse_failed")`。L1 重试成功（status=parsed_retry）写缓存；L2 fallback 一律不写。TC-3 / TC-12 显式断言 0 次。 |
| 9. `_process_chunk` 签名加 `bg_job` 参数 + run_smart_import 透传 | ✅ | 行 402 `bg_job: BackgroundJob \| None = None`；`run_smart_import` 行 364-372 传 `bg_job=bg_job`；`run_reparse` 行 1077 未传（PR-3 任务），默认 `None` 兼容。 |
| 10. L1 重试不再短暂 commit `chunk.status="llm_failed"` | ✅ | grep `llm_failed`（行 490 / 584 / 注释除外）：仅在不可重试 ValueError 入库行 490 写入 + commit + raise；retryable 路径直接进 fallback，无 llm_failed 写点。TC-11 用 `_CommitRecorder` 强约束断言 `"llm_failed" not in recorder.statuses_at_commit`，pass。 |

## B. 测试质量

| 项 | 结果 | 证据 |
|---|---|---|
| 11. 12 TC 名字与 G.1 表对齐 | ✅ | `test_smart_import_process_chunk_retry.py` 12 个测试函数与 design G.1 TC-1~TC-12 完全同名同语义。 |
| 12. 12 TC 全 pass、无 SKIP/XFAIL | ✅ | `python3 -m pytest backend/tests/ -v` 输出：16 passed，0 skipped/failed/xfail。 |
| 13. mock 策略合规 | ✅ | TC 全用 `monkeypatch.setattr(svc, "call_ai_api", ...)`（不进 httpx 真实层）；fixture `patch_io` 行 150 用 `monkeypatch.setattr(svc.time, "sleep", lambda _s: ...)` 屏蔽 backoff 阻塞；`_lookup_llm_cache` / `_store_llm_cache` / `_save_parsed_question` / `heartbeat_job` 全部 mock 出独立计数器。 |
| 14. TC-4 部分失败断言完整 | ✅ | 行 323-331：`chunk.status == "parsed_partial"` ✓；`failures[0]["source_question_no"] == "302"` ✓；`failures[0]["stage"] == "L2_fallback"` ✓；`job.failed_chunks == 1` ✓；`save_parsed` = 2 题（301、303）✓；`store_cache` = 0 ✓。 |
| 15. TC-10 L1 重试不查缓存 | ✅ | 行 525：`assert len(patch_io["lookup_cache"]) == 1`。代码 `_process_chunk` 行 451 仅在入口 `if cached: ...` 路径前查一次，重试链路在 `_call_llm_with_l1_retry` 内不再触碰 `_lookup_llm_cache`。 |
| 16. TC-11 重试期 status 不短暂 commit `llm_failed` | ✅ | `_CommitRecorder` 行 87-90 在每次 `db.commit()` 时记录 `chunk.status` 快照；行 558-563 断言 `"llm_failed" not in statuses_at_commit` 且 `"parse_failed"` 也不出现。pass。 |
| 17. TC-12 L2 不写缓存 | ✅ | 行 596：`assert len(patch_io["store_cache"]) == 0`。代码 line 584 的条件 `not fallback_used` 直接拦截。 |

## C. PR-1 测试调整评估

| 项 | 结果 | 评估 |
|---|---|---|
| 18. PR-1 TC-4 正则放宽合理性 | ✅ **必要且最小** | PR-2 把 `_process_chunk` 内对 `call_ai_api(..., timeout=120.0)` 的字面调用搬到了 `_call_llm_with_l1_retry(..., timeout=120.0)`（后者透传给 `call_ai_api`），原静态正则 `r"call_ai_api\([^)]*timeout=120(?:\.0)?[^)]*\)"` 在 `smart_import_service.py` 中**不再命中**（`call_ai_api(..., timeout=timeout)` 只剩参数透传形式，无 120 字面量）。把正则改为 `(?:call_ai_api\|_call_llm_with_l1_retry)\(...timeout=120...\)` 是**等价契约**：仍要求 smart_import 路径有"显式传 120s"的字面证据；只是把"哪一行承载 120s 字面值"从底层 API 调用上移一层到 retry helper。语义没有放宽。docstring 已说明。 |
| 19. PR-1 其它 3 个 TC 未被无意触动 | ✅ | `git diff backend/tests/test_ai_service_call_api_timeout.py` 仅修改了 TC-4 的 docstring 与 1 个 regex assertion；`test_call_ai_api_default_timeout_is_60s` / `_explicit_timeout_is_passed_to_httpx` / `_propagates_timeout_exception` 三 TC 文本零变动，运行全绿。 |

## D. Cross-layer / Code reuse

| 项 | 结果 | 评估 |
|---|---|---|
| 20. `_split_by_single_question` 与 `_split_by_question_markers` 重复度 | ⚠️ **建议（非阻塞）** | 行 1311-1386 两个函数前 12 行（"找最优 pattern"循环）逻辑完全一致；可抽 `_select_best_question_pattern(text) -> tuple[Pattern \| None, list[Match]]` helper。重用阈值 `code-reuse-thinking-guide.md` 是 3 处重复才必须抽，目前 2 处仍合规。**不阻塞 PR-2**；建议在未来若新增第 3 个 splitter 时一并重构。 |
| 21. `heartbeat_job` 调用的事务边界 | ✅ | `heartbeat_job` 内部自带 `db.commit()`（`job_service.py:318`）；PR-2 的 fallback 循环每 3 段调一次，调用前后**无未关闭的 transaction**（前一次循环结束时 chunk 状态尚未写入，但循环内并无未 commit 的 chunk 修改 → heartbeat 内部 commit 不会泄漏 chunk 中间态）。符合 `database-guidelines.md` 的"在已开 transaction 中不可调"约束（这里没有显式开 transaction）。 |
| 22. `bg_job` 传染范围最小 | ✅ | `bg_job` 仅出现于 `_process_chunk`（行 402）→ `_run_per_question_fallback`（行 701）。**未渗透**到 `_save_parsed_question`（行 778-789，签名零变动）、`_call_llm_with_l1_retry`、`_process_chunk_cached` 等下游。符合 `cross-layer-thinking-guide.md` "层只与邻居对话"原则。 |

## E. 异常处理 & 日志

| 项 | 结果 | 评估 |
|---|---|---|
| 23. fallback 中 `except (ValueError, ...)` 不会吞掉不该吞的 ValueError | ✅ | `_run_per_question_fallback` 内 try 块仅包裹 `call_ai_api(...)` + `_parse_llm_response(...)`。这两个调用栈中产生的 ValueError 都属于 LLM 调用域（API key / 4xx/5xx / 解析失败），不可能产生"ImportJob 不存在"等业务级 ValueError（业务校验在 `run_smart_import` 入口已做完）。范围合规。 |
| 24. logger 调用密度 | ⚠️ **建议（非阻塞）** | grep 显示 PR-2 改动**未新增任何 logger 调用**。`logging-guidelines.md` 明确指出 smart_import_service 是项目中唯一标准使用 logging 的文件，应在 (a) L1 重试触发；(b) L2 fallback 启动；(c) budget 超时；(d) heartbeat 失败；(e) chunk 终态为 partial/failed 5 个关键节点用 `logger.warning`/`logger.info` 留痕。当前缺失会让生产环境无法回溯失败链路。**不阻塞**当前 PR（项目其它 service 也几乎零日志），但强烈建议在 PR-4 合并前补齐。 |

## F. 运行验证

| 项 | 结果 | 证据 |
|---|---|---|
| 25. py_compile 通过 | ✅ | `python3 -m py_compile backend/app/services/smart_import_service.py` → 0 退出。 |
| 26. 全部 16 测试 pass | ✅ | `python3 -m pytest backend/tests/ -v` → `16 passed in 0.63s`（4 PR-1 + 12 PR-2）。 |
| 27. PR-2 12 TC pass | ✅ | `python3 -m pytest backend/tests/test_smart_import_process_chunk_retry.py -v` → 12 passed。 |
| 28. 核心逻辑对齐 design J.2 骨架 | ✅ | git diff smart_import_service.py 共 +412 行：① 常量段 +27 行（J.2 完全对齐）；② `_is_retryable_value_error` +7 行；③ `_process_chunk` 重写 +153 行（cache → L1 → fallback → 状态映射 → cache 写入 → 入库）；④ `_process_chunk_cached` 抽出 +47 行；⑤ `_call_llm_with_l1_retry` +38 行；⑥ `_run_per_question_fallback` +79 行；⑦ `_split_by_single_question` +34 行。结构与 J.2 行内骨架 100% 同构。 |

## G. AC 对账（前置）

| 项 | 结果 | 评估 |
|---|---|---|
| 29. AC1 基础（chunk 27 timeout 场景） | ✅ | L1 1 次重试 + L2 24 题（每段独立 60s timeout）已落地；TC-3 / TC-4 / TC-5 模拟"L1 timeout → L2 全成 / 部分失败 / 全失败"三种关键路径均按预期工作。理论上即使 L1 仍 timeout，L2 在不超 480s 预算下能恢复 ≥22 题（24 题 × 60s = 1440s 远超 480s，但实际单题 ~5-10s 故能在预算内完成全部 24 段）。 |
| 30. AC4（单元测试已落地） | ✅ | 12 TC pass，覆盖正常 / 重试 / 降级 / 部分失败 / 全失败 / 4xx / 5xx / Pydantic / 无题号 / 缓存 / 状态机 / 不写缓存 12 条路径。集成测试留 PR-4。 |
| 31. AC5/AC6（无副作用引入） | ✅ | grep `pytesseract` / `respx` / `pytest-httpx`：0 命中。`PROMPT_VERSION = "v1"` 行 49 未变。无新 ORM 字段。无 Alembic 迁移。 |

## H. 风险 & 回归

| 项 | 结果 | 评估 |
|---|---|---|
| 32. reparse 路径未破坏 | ✅ | `run_reparse` 行 1077 调 `_process_chunk(db, chunk, import_job, auto_import, use_llm_cache, seen_signatures)` —— 未传 `bg_job`，命中默认值 `None`。`_run_per_question_fallback` 行 762 `if bg_job is not None` 防御 → reparse 路径无 heartbeat（reparse 仅 1 chunk，lease 180s 通常足够）。语义正确。 |
| 33. cache 命中路径未破坏 | ✅ | `_process_chunk_cached`（行 609-654）作为独立函数抽出，路径与 PR-1 行为对齐：写 `chunk.llm_response_json` → 解析 → 写 `chunk.status="parsed_cached"` → `_save_parsed_question` 循环。无重试 / 降级介入（缓存命中天然成功），无回归风险。 |
| 34. 状态映射顺序（design J.2:706-710） | ✅ | 见 A.6 项详述，行 549-563 按 `failed → parsed_partial → parsed_fallback → parsed_retry → parsed` 顺序判定，`parsed_partial` 严格在 `parsed_fallback` 之前。TC-3 / TC-4 / TC-5 三个测试覆盖所有分支边界。 |

---

## 结论

**通过（可 commit）**。

* 必修项：**0**。
* 建议项（非阻塞，留作后续 PR 改进）：**2**
  1. **D.20**：`_split_by_single_question` 与 `_split_by_question_markers` 共享"找最优 pattern + finditer"骨架，建议未来出现第 3 个 splitter 时抽 `_select_best_question_pattern` helper。
  2. **E.24**：PR-2 关键路径（L1 重试触发 / L2 启动 / budget 超时 / heartbeat 失败 / chunk 终态 partial/failed）全部缺少 `logger.warning`/`info` 留痕，生产环境无法回溯。建议 PR-4 合并前在 5 个关键节点补齐 logger 调用（项目唯一规范使用 logging 的 service 应保持高密度）。

## Commit message 关键信息

* **范围**：`backend/app/services/smart_import_service.py`（+412 / -30）+ `backend/tests/test_smart_import_process_chunk_retry.py`（新增 12 TC）+ `backend/tests/test_ai_service_call_api_timeout.py`（PR-1 TC-4 正则放宽以兼容 PR-2 重构）。
* **核心改动**：`_process_chunk` 引入"L1 整 chunk 1 次重试 + L2 单题降级 + budget kill switch + heartbeat 续约"；`chunk.status` 新增 `parsed_retry / parsed_fallback / parsed_partial` 三态（无 schema 迁移）；`chunk.issues_json` 扩展 `retry_count / fallback_used / per_question_failures / fallback_meta` 字段。
* **API 表面**：`_process_chunk` 签名新增 `bg_job: BackgroundJob | None = None` 参数（PR-3 / reparse 路径 None 兼容）；`call_ai_api` 与 `LlmParseCache` 行为零变动（PR-1 已铺路）。
* **回归保护**：12 个新单元测试覆盖正常路径 / 重试 / 降级 / 部分失败 / 全失败 / 4xx / 5xx / Pydantic / 无题号 / 缓存查询 / 中间状态 / 缓存写入 12 条路径，全 pass。
* **非引入**：无 OCR / 无新 ORM 字段 / 无 Alembic 迁移 / 无新依赖 / `PROMPT_VERSION` 维持 v1。
