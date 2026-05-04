# PR-1 Design — call_ai_api timeout

> 研究子代理产出，仅做静态分析；未修改任何源代码、未发起 LLM 调用。
> 数据源：`backend/app/services/ai_service.py`、`backend/app/services/smart_import_service.py`、`backend/app/api/routes/settings.py`、`backend/app/core/config.py`、`backend/tests/`、`backend/services/ai_service.py`（旧 Flask 版）。

## A. 现状

### A.1 FastAPI 侧 `call_ai_api`（本任务唯一改动目标）

文件：`backend/app/services/ai_service.py`

| 项 | 值 / 位置 |
|---|---|
| 函数签名 | `def call_ai_api(messages, db, scene="default"):`（行 73）|
| HTTP 调用 | `httpx.post(api_url, json=payload, headers=headers, timeout=60.0, verify=False)`（行 97）|
| 同步 / 异步 | **同步** `httpx.post`（模块级函数，每次新建临时 client，不复用连接、无共享池）|
| 当前 timeout | `60.0` 秒，**硬编码**字面量 |
| 重试 | **无任何重试**（一次性调用，直接 raise）|
| db 用途 | 仅 `get_effective_ai_settings(db, scene=scene)`（行 74）读取 SystemSetting；**没有 db.add / db.commit / 事务边界**|
| 缓存 / 共享 client | 无；项目内**没有**共享 `httpx.Client` 实例池 |

raise 路径与异常类型（按代码顺序）：

| 序号 | 行号 | 触发条件 | 抛出 |
|---|---|---|---|
| 1 | 76 | API key 未配置 | `ValueError("AI API Key 未配置，请在管理后台设置")` |
| 2 | — | httpx 网络/超时层 | `httpx.TimeoutException`（含子类 `ConnectTimeout` / `ReadTimeout` / `WriteTimeout` / `PoolTimeout`）、`httpx.ConnectError`、`httpx.HTTPError` 等 — **不会被 wrap**，直接冒泡 |
| 3 | 100 | `resp.is_success == False`（4xx/5xx） | `ValueError(f"AI API 错误 ({resp.status_code}): {detail}")` |
| 4 | 102 | `data["choices"][0]...`访问失败 | 隐式 `KeyError` / `IndexError` |

> **关键事实**：超时不会被 wrap 成 `ValueError`，调用方若想精准 catch 必须直接 `except httpx.TimeoutException`。当前 `_process_chunk`（`smart_import_service.py:387-393`）采用 broad `except Exception`，所以表现一致；但若 PR-2 想区分 timeout 与 4xx/5xx，仍要靠 httpx 原生异常类型。

### A.2 第二处 `httpx.post`（不属于 call_ai_api）

文件 `backend/app/services/ai_service.py:190` 位于 `translate_term(term, db=None)`，行 143-196。

* 它**不是** `call_ai_api` 的另一个入口，也不是批量/流式版本，而是 `db=None` 兼容路径下**重复实现了一遍** httpx.post 调用（参数与行 97 几乎相同）。
* 当 `translate_term` 接收到 `db` 实参时，它走的还是行 190 这条独立分支（不会跳到 call_ai_api），但**没有任何 in-tree 调用方真正用 `translate_term(db=None)`**（仅 `batch_translate_translate_terms` 调用 call_ai_api，前端只通过 vocab API 触发 batch 路径）。
* 结论：**PR-1 暂不动行 190**。把它列入 "## H 不做事项" 但需在报告里点名，避免审查者误以为它是 call_ai_api 的另一面。

### A.3 第三处 `httpx.post`（管理后台连通性测试）

`backend/app/api/routes/settings.py:120`：`/api/settings/ai/test-connection` 端点用的 `timeout=15.0`（短探针）。**与 call_ai_api 无关**，PR-1 不动。

### A.4 Flask 旧版 `call_ai_api`（迁移期遗留）

`backend/services/ai_service.py:72`：`def call_ai_api(messages, scene='default')`，使用 `requests.post(..., timeout=60, ...)`（行 96）。
* 签名与 FastAPI 版**不一致**（无 `db` 参数）。
* 调用方（同文件内的 `translate_question` / `translate_term` / `batch_translate_terms` / `explain_question`）。
* PRD 已显式说明本任务**仅改 FastAPI 一侧**，旧版不动。
* 风险评估：旧版仍被 Flask 路由 `backend/routes/ai.py` 使用，但当前生产入口已迁到 FastAPI（`backend/app/api/routes/banks.py:226`），**没有 cross-call** 关系。

## B. 调用方清单

> 通过 `Grep "call_ai_api\("` 全仓扫描，已剔除 docs/、archived plans/、PRD 自身。

### B.1 FastAPI 版调用清单（PR-1 关心的范围）

| # | 文件 : 行 | 调用语句 | scene | 是否在 try/except | 上层异常去向 | 当前实际 timeout 需求 | 建议 PR-1 显式传值 |
|---|---|---|---|---|---|---|---|
| 1 | `backend/app/services/ai_service.py:127` | `_strip_code_fence(call_ai_api(messages, db, scene="translate"))` | `translate` | **否**（直接调用，`json.loads` 也无 catch）| 异常冒泡到 `routes/ai.py` 的 endpoint，FastAPI 默认转 500 | 60s 够（单题目+选项 2k tokens 输入）| **不传**（沿用默认 60s）|
| 2 | `backend/app/services/ai_service.py:245` | `call_ai_api(messages, db, scene="translate")` | `translate` | **否** | 同上（批量术语翻译，由 `/api/ai/translate-terms` 同步触发）| 60s 偶尔吃紧（≤20 术语一批），但当前未观测到 timeout 失血 | **不传**（沿用默认 60s）|
| 3 | `backend/app/services/ai_service.py:274` | `_strip_code_fence(call_ai_api(messages, db, scene="explain"))` | `explain` | **否** | 同上，前端 `ExplainButton` 触发 | 60s 够 | **不传**（沿用默认 60s）|
| 4 | `backend/app/services/smart_import_service.py:388` | `response_text = call_ai_api(messages, db, scene="smart_import")` | `smart_import` | **是**（行 387-393：`except Exception` → `chunk.status="llm_failed"` + `issues_json` + `raise`）；外层 `run_smart_import` 行 332-337 再 `except` 设 `status="failed"` | 不冒泡（chunk 失败不中断 import）| **120s**（CIPT 283 PDF 实测：chunk 27 在 60s 默认下整体 timeout，11.8k 字符 / 24 题）| **显式 timeout=120.0** |

### B.2 Flask 旧版调用清单（PR-1 不改，仅记录）

| # | 文件 : 行 | scene |
|---|---|---|
| 1 | `backend/services/ai_service.py:124` | `translate` |
| 2 | `backend/services/ai_service.py:158` | `translate` |
| 3 | `backend/services/ai_service.py:215` | `translate` |
| 4 | `backend/services/ai_service.py:244` | `explain` |

> 旧版函数签名 `(messages, scene)` 没有 `db`、没有 `timeout`，且使用 `requests` 而非 `httpx`。本 PR 不修改。

### B.3 调用方对超时的耐受度评估

| 场景 | 同步 / 异步 | 用户感知 | 60s 够吗？ | 120s 是否可接受？ |
|---|---|---|---|---|
| `/api/ai/translate-question` (单题翻译) | **同步** HTTP request | 前端长 spinner | 够（实测 < 30s）| 不必抬高 |
| `/api/ai/translate-terms` (批量) | **同步** HTTP request | 前端长 spinner | 够（≤20 项/批）| 抬高至 120s 会让用户多等；保留 60s |
| `/api/ai/explain` (题目解析) | **同步** HTTP request | 前端长 spinner | 够 | 不必抬高 |
| `smart_import._process_chunk` | **异步 worker**（`run_worker.py`，`WORKER_LEASE_SECONDS=600`）| 用户在前端 polling 进度，无直接等待感 | **不够**（chunk 27 11.8k 字符 24 题 → 60s timeout）| **可接受**，120s 远小于 worker lease 600s |

**结论**：异步 worker 内的调用是唯一需要把 timeout 抬到 120s 的场景；其他三个同步 endpoint 维持默认 60s，避免前端 spinner 时间翻倍。

## C. 默认值与向后兼容

### C.1 是否新增 `settings.AI_API_TIMEOUT` 配置项？

`backend/app/core/config.py` **没有** `AI_API_TIMEOUT`、`AI_REQUEST_TIMEOUT` 等配置项。

* 选项 A：新增 `AI_API_TIMEOUT_DEFAULT=60` / `AI_API_TIMEOUT_SMART_IMPORT=120` 两条 settings。
  * `+` 可在 `.env` 调整、不需改代码
  * `−` 把"不同 scene 不同 timeout"耦合到 settings 层，未来加 scene 都要建新字段
  * `−` PRD 明确建议 `timeout=60.0` 作函数默认值，新增 settings 反而让默认值有两层（settings + 函数签名），**违背 KISS**
* 选项 B：**不引入 settings**，函数签名默认 60s，调用方显式传 120s。
  * `+` 改动面最小，调用方意图最显式
  * `+` 与 PRD 推荐一致（`Requirements 行 124`）
  * `−` 调高生产环境 timeout 需要改代码

**推荐：选项 B**。本 PR 不引入新 settings；如未来需要环境化，再开 PR-X 加 `settings.AI_API_TIMEOUT_SMART_IMPORT`（已记入 H 节）。

### C.2 函数签名：统一默认 60s vs scene 查表

| 方案 | 描述 | 评估 |
|---|---|---|
| 方案 1（PRD 当前提议）| `call_ai_api(messages, db, scene="default", timeout: float = 60.0)` | 4 个调用方中只有 1 个改（smart_import 显式传 120）；其余无变化；**通过 keyword arg 兼容向后调用** |
| 方案 2（scene 查表）| `call_ai_api(messages, db, scene="default", timeout=None)` 函数内查 `_SCENE_TIMEOUT = {"smart_import": 120, "default": 60, ...}` | 调用方 0 改动，但 ai_service 行为对 caller 不透明；scene 字符串变更（拼写错）会静默回退 60s |

**推荐：方案 1**。理由：
1. 显式 > 隐式（与 Python 之禅一致），caller 看代码即知 timeout；
2. PR-2 即将在 `_process_chunk` 内为重试链路再次调用 `call_ai_api`，重试时若想用更短/更长 timeout（如单题降级 60s），方案 1 直接 `call_ai_api(..., timeout=60.0)` 即可，方案 2 还得查表逻辑能不能 override；
3. 4 个调用方中只 1 个改，单元测试覆盖面小，回归风险低。

### C.3 Flask 旧版同名函数

`backend/services/ai_service.py:72` 的 `call_ai_api` **不在本 PR 范围**。研究确认两者**没有运行时 cross-call**（FastAPI 服务进程不会进 Flask 那份代码；run.py / run_api.py 入口分离）。

## D. 异常与重试

### D.1 是否在 PR-1 引入 `max_retries` 参数？

**不引入**。理由：

| 维度 | 在 call_ai_api 引入 max_retries | 留给 _process_chunk 自行重试（PR-2）|
|---|---|---|
| 复用度 | 所有 4 个调用方都能享受 | 仅 smart_import 享受 |
| PR-2 重试策略 | "整 chunk 重试 1 次 → 单题降级"两级，需要 caller 完全控制 retry 流（包括 chunk_text 重新切分），call_ai_api 内的 retry 与 PR-2 的 L1 重试**会重叠**导致 2×2=4 次实际调用 | 单层、清晰、好测 |
| 副作用 | call_ai_api 已被同步 endpoint 调用（translate/explain），加 retry 会让 4xx/5xx 错误也吃 N 次配额 | 仅 chunk 级别按需 retry |
| 异常透明度 | 所有 caller 必须知道"我可能被自动重试 N 次"，破坏单一职责 | 重试逻辑显式在 _process_chunk 内 |

**结论**：PR-1 仅做 timeout 参数化，**完全不引入重试**。重试由 PR-2 在 `_process_chunk` 中实现两级策略。

### D.2 是否新建 `LlmTimeoutError` / `LlmCallError` 异常子类？

**不引入**。理由：
* PR-2 的 `_process_chunk` 可以直接 `except httpx.TimeoutException` + `except (httpx.HTTPError, ValueError)` 区分 timeout 与其他失败；
* 新增异常类需要在 ai_service 内 wrap → 改写 raise 链 → 所有 caller 都受影响（包括同步 endpoint），改动面**反而扩大**；
* 现有 `_process_chunk` 已用 broad `except Exception` 捕获，并把消息写入 `chunk.issues_json["error"]`；保留 httpx 原生类型即可。
* 若 PR-2 在调试中发现需要更精细分类，再开补丁 PR-2.x，本 PR 不预先创建 API 表面。

> 补充建议（写到 PR-2 研究里，不在本 PR）：在 `_process_chunk` 的 except 里区分 `httpx.TimeoutException` → 走两级重试；其他 `httpx.HTTPError` / 4xx / `ValueError("AI API Key 未配置")` → 直接失败不重试（重试无意义）。

## E. 测试策略

### E.1 现状

| 项 | 值 |
|---|---|
| 测试根目录 | `backend/tests/`（共 12 个 `test_*.py`）|
| 框架 | `pytest`（pytest-9.0.3，见 `__pycache__/*-pytest-9.0.3.pyc`）|
| 是否有 `conftest.py` | **无**（每个 test 文件自带 `app` fixture 与 `monkeypatch.setenv`）|
| 是否有 `pyproject.toml` | **无**（仅 `requirements*.txt`）|
| HTTP mock 模式 | **monkeypatch.setattr** 模块级 `requests.post` / `httpx.post`（旧版用 `monkeypatch.setattr(ai_service.requests, "post", fake_post)`，见 `test_ai_service_scene_models.py:89`）|
| pytest-httpx / respx | **未引入**，requirements 里无；MVP **无需新增依赖**，monkeypatch 已够用 |
| FakeResponse 模式 | 已有惯例（`test_ai_service_scene_models.py:38-47`，提供 `.json()` / `.is_success` 属性） |

> ⚠️ 现有测试目标都是 Flask 旧版（`from services import ai_service` + `requests.post`）；**FastAPI 版 `app.services.ai_service` 还没有任何单测**。PR-1 是引入 FastAPI 版 ai_service 第一个单测的好时机，需要建立 `FakeHttpxResponse` 的统一 fixture 风格（`is_success` / `text` / `reason_phrase` / `.json()` 四个属性，对应 httpx.Response 接口）。

### E.2 PR-1 必备单元测试 Case 清单

> 文件建议放 `backend/tests/test_ai_service_call_api_timeout.py`（新文件，避免与旧版 Flask test_ai_service_scene_models.py 混淆 import path）。

| TC | 名字 | 断言 |
|---|---|---|
| TC-1 | `test_call_ai_api_default_timeout_is_60s` | monkeypatch `app.services.ai_service.httpx.post` 捕获 kwargs；不传 `timeout` 调用 `call_ai_api(messages, db)` → 断言 `captured["timeout"] == 60.0`（保持向后兼容）|
| TC-2 | `test_call_ai_api_explicit_timeout_is_passed_to_httpx` | 调用 `call_ai_api(messages, db, scene="smart_import", timeout=120.0)` → 断言 `captured["timeout"] == 120.0` |
| TC-3 | `test_call_ai_api_propagates_timeout_exception` | fake httpx.post 抛 `httpx.TimeoutException("timed out")` → 断言 `pytest.raises(httpx.TimeoutException)`；**不被 wrap 成 ValueError**（保护 PR-2 的 caller 仍能精准 catch timeout）|
| TC-4 | `test_smart_import_chunk_calls_ai_api_with_120s_timeout` | monkeypatch `call_ai_api` 本身（不进 httpx）、断言 _process_chunk 调用时 `kwargs["timeout"] == 120.0` |

> TC-4 保护"smart_import 端显式传 120s"这一 PRD 必须项；TC-1/2 保护 ai_service 端的签名契约。

### E.3 是否需要新增 mock 工具？

**不需要**。`pytest-httpx` / `respx` 都没必要——4 个 case 都用 `monkeypatch.setattr` 解决。
* 不新增 `backend/requirements-fastapi.txt` 依赖；
* 不新增 `pytest-httpx` / `respx`；
* 与既有 test_ai_service_scene_models.py 保持同一风格（仅把 `requests` 改成 `httpx`）。

## F. Cross-layer 副作用

### F.1 call_ai_api 是否对 db 做写入？

**否**。call_ai_api 只读：
* 行 74 `get_effective_ai_settings(db, scene=scene)` 内部仅 `db.query(SystemSetting).filter_by(...).first()`（已确认无 `db.add` / `db.commit`）；
* 行 97 之后没有任何 db 操作。

→ **timeout 抛出时不会留下半提交状态**，PR-1 无需在 ai_service 内插 try/finally 做 rollback。

### F.2 _process_chunk 上层事务

`_process_chunk` 在 call_ai_api 之前已经 `db.commit()` 了 `chunk.llm_request_json`（行 384-385）；call_ai_api 抛 timeout 后：
* 行 389-393 catch → 写 `chunk.status = "llm_failed"` + `chunk.issues_json` → `db.commit()` → `raise`；
* 外层 `run_smart_import` 行 332-337 catch → 写 `chunk.status = "failed"` + `chunk.issues_json` + `import_job.failed_chunks += 1` → `db.commit()`。

→ DB 一致性已由 `_process_chunk` / `run_smart_import` 现有 except 逻辑保证；**PR-1 不需要在 call_ai_api 内引入事务管理**。这是 PR-2 的关注点（PR-2 加重试时要小心：重试前要把 `chunk.status` 重置为 `parsing`，不能让 L1 重试在 `llm_failed` 状态下二次写）。

## G. 推荐落地方案 + 最终签名

### G.1 最终函数签名

```python
# backend/app/services/ai_service.py

def call_ai_api(
    messages,
    db,
    scene: str = "default",
    timeout: float = 60.0,
):
    """调用 AI Chat Completion API。

    参数：
        messages: OpenAI 兼容的 messages 列表
        db: SQLAlchemy Session（用于读取 SystemSetting）
        scene: AI 场景，用于选择不同 model（"default" / "translate" / "explain" / "smart_import"）
        timeout: HTTP 请求超时秒数。默认 60.0；smart_import 等异步重 chunk 场景应显式传 120.0。
                 该值直接透传给 httpx.post 的 timeout 参数（即对单次连接 + 读 + 写都生效）。

    抛出：
        ValueError: API Key 未配置 / API 返回非 2xx
        httpx.TimeoutException: 请求超时（caller 应感知此异常并按需重试）
        httpx.HTTPError: 其他 httpx 层错误
    """
```

httpx 调用从字面量改为参数：
```python
resp = httpx.post(api_url, json=payload, headers=headers, timeout=timeout, verify=False)
```

### G.2 最小变更面（PR-1 完整 diff 范围）

| 文件 | 变更 | 行数估算 |
|---|---|---|
| `backend/app/services/ai_service.py` | 函数签名加 `timeout: float = 60.0`；`httpx.post` 的 `timeout=60.0` → `timeout=timeout`；docstring 升级 | 函数签名 1 行 + httpx 调用 1 行 + docstring 7-10 行 |
| `backend/app/services/smart_import_service.py:388` | `call_ai_api(messages, db, scene="smart_import")` → `call_ai_api(messages, db, scene="smart_import", timeout=120.0)` | 1 行 |
| `backend/tests/test_ai_service_call_api_timeout.py` | **新文件**，4 个 TC（参见 E.2）| 80-120 行 |

**总计：2 个文件改动 + 1 个新文件**，无 ORM / 迁移影响。

### G.3 端到端验证清单（PR-1 内自测）

* [ ] `python -m py_compile backend/app/services/ai_service.py`
* [ ] `python -m py_compile backend/app/services/smart_import_service.py`
* [ ] `cd backend && python -m pytest tests/test_ai_service_call_api_timeout.py -v`（4 case 全绿）
* [ ] `cd backend && python -m pytest tests/ -v`（既有 12 个 test 全绿不回归——尤其 `test_ai_service_scene_models.py` 是 Flask 旧版，import path 不应被影响）
* [ ] 手动验证：跑一次 `/api/ai/explain` 或 `/api/ai/translate-question`（如 dev 环境有 AI key），确认行为不变（仍 60s）

## H. 不做事项 / 留作后续 PR

| 项 | 原因 / 留给哪个 PR |
|---|---|
| 引入 `LlmTimeoutError` / `LlmCallError` 自定义异常 | PR-2 / PR-3 视调试需要再起；当前 httpx 原生异常足够 |
| 在 call_ai_api 内做 retry / `max_retries` 参数 | 重试策略 = PR-2 在 `_process_chunk` 内实现两级重试 |
| 新增 `settings.AI_API_TIMEOUT_DEFAULT / _SMART_IMPORT` env 配置 | 当前两个 timeout 值（60 / 120）已硬编码够用；如未来要按部署环境调整再加 |
| 改 `backend/app/services/ai_service.py:190` `translate_term` 内重复的 httpx.post | 它是另一段独立代码，与 call_ai_api 无关；属于代码债务，单独 PR 清理 |
| 改 Flask 旧版 `backend/services/ai_service.py:72` `call_ai_api` | PRD 明确 "仅改 FastAPI 一侧" |
| 引入 `httpx.Client` 共享池 / 连接复用 | 性能优化，超出 PR-1 范围；本 PR 仍用 `httpx.post`（每次新建临时 client）|
| 引入 `pytest-httpx` / `respx` 依赖 | monkeypatch 已足够，不增加供应链 |
| 把 timeout 参数传到 batch_translate_terms 等同步 endpoint | 当前 60s 在 `/api/ai` 路径未观察到 timeout；不在 PR-1 范围 |
| `/api/settings/ai/test-connection`（settings.py:120）调整 timeout | 短探针 15s 是有意为之，不动 |

---

## 给主代理的总结（< 200 字）

1. **最终签名**：`call_ai_api(messages, db, scene: str = "default", timeout: float = 60.0)`，httpx.post 把硬编码 `timeout=60.0` 替换为参数 `timeout=timeout`；smart_import 调用点显式传 `timeout=120.0`。
2. **调用方改动文件总数 = 2**（`ai_service.py` 加签名/docstring；`smart_import_service.py:388` 加 `timeout=120.0`），加 1 个新测试文件 `tests/test_ai_service_call_api_timeout.py`（4 个 TC）。
3. **不引入新异常类**：保留 `httpx.TimeoutException` 原生类型直接冒泡，PR-2 在 `_process_chunk` 内 `except httpx.TimeoutException` 即可精准 catch；新建子类会扩大改动面且违背 YAGNI。
4. **回填 PRD 的新约束**：(a) PR-1 明确**不引入 `max_retries` 参数**，重试 100% 留给 PR-2；(b) `translate_term`（ai_service.py:190）内部还有一处独立 httpx.post（不是 call_ai_api 的调用点），属代码债务但本任务**不动**——建议 PRD 在 Out-of-Scope 段加一行声明，避免 codex review 误判遗漏。
