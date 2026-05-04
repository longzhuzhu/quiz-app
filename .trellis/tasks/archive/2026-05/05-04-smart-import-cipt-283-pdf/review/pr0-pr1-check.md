# Code Review — PR-0 + PR-1

> 复核范围：PR-0（删除 12 个 Flask 测试文件）+ PR-1（`call_ai_api` 加 `timeout` 参数 + smart_import 显式传 120s + 新增单元测试）。
> 工作目录：`/home/ubuntu/github/quiz-app`。
> 提交前 `git status` 计：12 D + 2 M（`ai_service.py`、`smart_import_service.py`）+ 1 ?? 测试新文件。

---

## A. 规范一致性

- **A1（FastAPI 类型注解风格）**：✅ `call_ai_api(messages, db, scene: str = "default", timeout: float = 60.0)`，新增的 `scene` 与 `timeout` 都带类型注解，与 `quality-guidelines.md` "FastAPI 端：完整类型注解" 一致。`messages` 与 `db` 沿用旧版无注解，**未越界改动**，符合"PR-1 最小变更面"约定。docstring 已显式覆盖参数（4 个）+ 返回值 + 3 类异常路径（ValueError / httpx.TimeoutException / httpx.HTTPError），描述与代码行为一致（行 76 ValueError、行 118 ValueError、行 211 不在 call_ai_api 内）。
- **A2（`smart_import_service.py:388` 单行修改风格）**：✅ 仅在原有 `call_ai_api(messages, db, scene="smart_import")` 末尾追加 `timeout=120.0`，缩进、换行、参数顺序保持原样，未引入额外空白或顺序调整。
- **A3（service 层异常风格）**：✅ `error-handling.md` "FastAPI 版统一 raise HTTPException" 是 route 层规则，service 层项目惯例是抛 ValueError + 让 route 层转换。本 PR 维持原 `ValueError` raise 链；超时按 PR-1 设计 H 节明确"原生 `httpx.TimeoutException` 直接冒泡"。**未把 service 层异常转成 HTTPException**，未越界。
- **A4（logging-guidelines）**：✅ PR-1 未新增 logger（设计 G.2 与 H 节明确"logger 留给 PR-2"）。`logging-guidelines.md` 现状描述项目几乎零日志，PR-1 未越界引入。

## B. 设计合规

- **B5（最小变更面）**：✅
  - 文件改动总数 = 2 modified + 1 new test，与 design G.2 表完全吻合。
  - `git diff backend/app/services/ai_service.py` 确认 **行 211**（`translate_term` 内独立 `httpx.post`）**未被改动**，仍为 `timeout=60.0` 字面量；与 design H 节 / PRD Out-of-Scope 一致。
  - `git diff backend/services/ai_service.py` 输出为空，Flask 旧版 `backend/services/` 目录无任何改动；与 PRD"仅改 FastAPI 一侧"一致。
- **B6（4 TC 与 design E.2 对齐）**：✅
  - TC-1 → `test_call_ai_api_default_timeout_is_60s`（断言 `captured["timeout"] == 60.0`）。
  - TC-2 → `test_call_ai_api_explicit_timeout_is_passed_to_httpx`（断言 `captured["timeout"] == 120.0`）。
  - TC-3 → `test_call_ai_api_propagates_timeout_exception`（同时做了 `pytest.raises` 与"反向防御不被 wrap 成 ValueError"两段断言，比 design E.2 更严格但合理）。
  - TC-4 → `test_smart_import_chunk_calls_ai_api_with_120s_timeout` 采用**静态正则断言** `re.findall(r"call_ai_api\([^)]*timeout=120(?:\.0)?[^)]*\)", src)`，是 design E.2 允许的两种方案之一（避免拉起完整 `_process_chunk` 的 DB / chunking 全栈），实施合理；正则容忍 `120` 或 `120.0`，鲁棒性 OK。
- **B7（PR-0 删除清单）**：✅ `git diff --name-only --diff-filter=D` 输出 12 个 `backend/tests/test_*.py`：account_password / admin_users / ai_service_scene_models / background_job_worker / background_jobs_api / bank_delete_api / bank_import_api / question_ai_persistence_api / quiz_reanswer_api / settings_ai_api_key / vocab_progress_api / vocab_translation_api。数量正确，全部为 Flask import；未误删 conftest 等文件。Grep 验证：所有外部引用都仅在 `docs/superpowers/plans/` 与 `docs/plans/` 中作为历史规划文档存在，无 conftest / Makefile / CI 引用其内部测试名。
- **B8（PR-1 禁止项）**：✅ Grep `max_retries|LlmTimeoutError|LlmCallError|AI_API_TIMEOUT` 在 `ai_service.py` / `smart_import_service.py` / `core/config.py` 全部 0 命中。未引入 `pytest-httpx` / `respx` / `pytesseract`（全仓 Grep 0 命中）。未新增依赖。

## C. 测试与运行

- **C9**：✅ `python3 -m py_compile backend/app/services/ai_service.py` 通过。
- **C10**：✅ `python3 -m py_compile backend/app/services/smart_import_service.py` 通过。
- **C11**：✅ `python3 -m py_compile backend/tests/test_ai_service_call_api_timeout.py` 通过。
- **C12**：✅ `python3 -m pytest backend/tests/ --collect-only -q` 输出仅 4 个 case，**0 collection error**：
  ```
  test_ai_service_call_api_timeout.py::test_call_ai_api_default_timeout_is_60s
  test_ai_service_call_api_timeout.py::test_call_ai_api_explicit_timeout_is_passed_to_httpx
  test_ai_service_call_api_timeout.py::test_call_ai_api_propagates_timeout_exception
  test_ai_service_call_api_timeout.py::test_smart_import_chunk_calls_ai_api_with_120s_timeout
  4 tests collected in 0.60s
  ```
- **C13**：✅ `python3 -m pytest backend/tests/test_ai_service_call_api_timeout.py -v` → **4 passed in 0.61s**。
- **C14**：✅ `cd backend && python3 -c "from app.services import ai_service; print(ai_service.call_ai_api.__doc__[:80])"` 输出"调用 AI Chat Completion API（OpenAI 兼容协议）。\n\n    参数:\n        messages: OpenAI 兼容的 me"，docstring 已更新到位，无残留旧版本。

## D. Cross-layer / Reuse

- **D15（code-reuse-thinking-guide）**：✅ PR-1 未引入新工具函数；timeout 处理直接落在 `httpx.post` 参数上，没有把通用代码错放到非通用位置。`translate_term` 内独立 httpx.post（行 211）属代码债务、design H 节明确不动 —— 复核确认未被顺手"重构合并"，避免引发不必要的回归面。
- **D16（cross-layer-thinking-guide / 向后兼容性）**：✅ Grep 全仓 `call_ai_api(`，FastAPI 端 4 个调用方：
  - `app/services/ai_service.py:148` (translate) — 不传 timeout，走默认 60s。✓
  - `app/services/ai_service.py:266` (translate) — 不传 timeout，走默认 60s。✓
  - `app/services/ai_service.py:295` (explain) — 不传 timeout，走默认 60s。✓
  - `app/services/smart_import_service.py:388` (smart_import) — 显式 `timeout=120.0`。✓
  Flask 旧版 4 处签名是 `(messages, scene)`，与本 PR 无 cross-call 关系；向后兼容性确实达到 design B.1 表预期（4 个调用方中 3 个零改动）。
- 数据流对照 `cross-layer-thinking-guide.md` 边界：PR-1 仅在"service 层 httpx 边界"做参数化，未跨到 route 层 / 前端 / DB 序列化 —— 无前端改动需求，符合 PRD Out-of-Scope。

## E. AC 对账

- **AC5**：✅ `pytest backend/tests/ --collect-only` 输出 0 collection error；新增 4 case 全绿。基线达成。
- **AC6**：✅
  - 未引入 OCR：全仓 Grep `pytesseract` 0 命中。
  - 未新增 ORM 字段：`git status` 未显示 `backend/app/models/` 任何文件改动；`alembic/versions/` 无新增。
  - 未引入新测试依赖：`pytest-httpx` / `respx` 全仓 0 命中；新测试文件依赖 `httpx`（已在 requirements）+ `pytest`（已在 requirements）+ `unittest.mock` + `re`，零新依赖。
  - `PROMPT_VERSION` 仍为 `"v1"`：`grep -n PROMPT_VERSION backend/app/services/smart_import_service.py` 第 46 行仍为 `PROMPT_VERSION = "v1"`，1247/1280 行使用点未改。

## F. 风险与回归

- **F19（docstring 一致性）**：docstring 中描述 `messages: OpenAI 兼容的 messages 列表（list[{"role": ..., "content": ...}])` 末尾 `])` 括号配对略不规整（`(... ])`，但这是合法 reST 文本，不影响 import / 不影响 sphinx 渲染（项目目前无 sphinx）。属可忽略小瑕疵，**非必修**。其余描述（默认 60.0、smart_import 应显式 120.0、超时不被 wrap）与代码行为完全一致；ValueError 列出"API Key 未配置 / 非 2xx"两条触发点准确（行 76 / 行 118）。
- **F20（删除测试是否被外部引用）**：✅ Grep 验证 12 个被删测试名仅在 `docs/superpowers/plans/` / `docs/plans/` 历史规划文档中以文件名出现，**无 conftest.py / Makefile / CI 脚本引用**，无 import 链断裂。仓库根无 `.github/`、无 `Makefile`，无 CI yaml，无回归风险。
- **F21（PR-0 影响半径）**：✅ 12 个删除文件全部位于 `backend/tests/`；`git diff --name-only --diff-filter=D` 未显示 `backend/` 之外任何路径。
- **回归风险评估（low）**：本 PR 改动面 = service 层签名追加 1 个 keyword arg + httpx 字面量替换 + 1 行调用点 + 80 行测试。未触碰事务边界、未触碰 ORM、未改 prompt（缓存继续生效）；其他 3 个同步 endpoint（translate × 2 / explain）调用签名未变 → 行为不变。
- **安全风险评估（none）**：未引入新外部依赖、未改密钥读取路径、未改 verify=False（沿用现状）、未泄露 API key 到日志。

## 结论

- **通过（可 commit）** ✅
- **必修项数量：0**
- **建议项数量：1**（非阻塞）
  - 建议（F19）：将 `call_ai_api` docstring 中 `messages` 行末 `])` 修为 `])` → `]`)（多余方括号，不影响功能）；可在 PR-2 顺手清理，无需为此再开 PR。

---

## 给主代理的总结（< 200 字）

1. **可 commit：是**。PR-0 删除 12 个 Flask 测试 + PR-1 改 2 个源文件 + 1 个新测试文件，与 design G.2 表 100% 对齐；4 个 TC 全绿；`pytest --collect-only` 0 error，AC5 / AC6 全部满足。
2. **必修项：0**。
3. **建议项：1**（非阻塞）—— `call_ai_api` docstring 一行末括号配对小瑕疵，不影响行为。
4. **风险：低**。未改事务边界 / ORM / `PROMPT_VERSION` / Flask 旧版 / `translate_term` 内独立 httpx.post；其他 3 个同步 endpoint 走默认 60s 不变；无 CI / Makefile / conftest 引用 12 个被删测试，无外部依赖新增，无安全面变化。
