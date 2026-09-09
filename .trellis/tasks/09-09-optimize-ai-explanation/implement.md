# 优化 AI 解析更新与输出质量 — 执行计划

## 实施顺序

分四段，每段结束后相关单测可先跑通；前端段完成后再做页面验收。

### 第 1 段：缓存口径、force 契约、CAS

- [ ] `backend/app/schemas/ai.py` — `AIExplainRequest` 增加 `force: bool = False`
- [ ] `backend/app/services/ai_service.py` — `has_question_explanation()` 只认 `explanation_zh`
- [ ] `backend/app/services/ai_service.py` — `explain_question(..., *, force=False)`：`force=false` 在 commit 前 refresh，已有中文解析则不覆盖
- [ ] `backend/app/api/routes/ai.py` — `force=true` 跳过缓存早返回；失败路径 `db.rollback()`；读 `detail` 而不是改响应形状
- [ ] 确认 `job_handlers.handle_ai_prewarm` / `job_service.count_pending_items` / `/ai/prewarm` 继续调用同一个 `has_question_explanation()`，英文-only 会进入生成

验证：`cd backend && python -m pytest tests/test_explanation_prompt_structure.py tests/test_ai_explanation_refresh.py -q`（本段可先补缓存 / force / CAS 用例，校验用例在第 2 段补齐）。

### 第 2 段：平台契约、校验、一次纠正重试

- [ ] `backend/app/services/exam_service.py` — 拆出 `DEFAULT_EXPLANATION_PERSONA` / `CIPT_EXPLANATION_PERSONA` 与 `EXPLANATION_OUTPUT_CONTRACT`；`build_explanation_system_prompt(persona)` 公开为组装入口
- [ ] `DEFAULT_AI_PROFILE` / `CIPT_AI_PROFILE` 的 `explanation_system_prompt` 改为 persona-only
- [ ] `explain_question` 始终 `persona(profile) + 平台契约`，不再把 Profile 全文当作可替换的输出协议
- [ ] `validate_structured_explanation(result, question)`：题干拆解必填字段、限定词出现时必填、知识点至少两句实质说明、干扰项恰好覆盖全部错误选项、type 枚举、拒绝空泛 reason
- [ ] 首次结构 / JSON 不合格时带错误列表重试一次；第二次仍失败不赋值、不 commit
- [ ] `compose_explanation_zh` 只渲染已通过校验的结构；删除“旧两键透传即可落库”语义
- [ ] `backend/alembic/versions/006_explanation_prompt_persona_split.py` — `down_revision = "005"`，只替换与 004 新默认 / 新 CIPT 全文逐字节相等的行

验证：`cd backend && python -m pytest tests/test_explanation_prompt_structure.py tests/test_ai_explanation_refresh.py -q`

### 第 3 段：前端获取 / 更新

- [ ] `frontend/src/components/ExplainButton.vue` — 文案与 disabled 按 `displayed` / `loading` 切换；本地短路由只认中文；更新走 `force: true`；generation 忽略过期响应；错误读 `detail`；更新失败固定提示“更新失败，已保留原解析”
- [ ] `frontend/src/components/QuestionCard.vue` — `initialExplanation` 以中文为准；成功后写回 `explainData`、`result.explanation_zh`、`question.explanation_zh`
- [ ] `frontend/src/views/WrongAnswersView.vue` — 成功后写回 `explainResults` 与 `w.question.explanation_zh`；已显示时按钮应为可点的“更新AI解析”

验证：答题页未显示时点“AI 解析”走缓存优先；已显示（含答完恢复、错题本自动展示）点“更新AI解析”发出 `force: true`；更新中旧文案仍在；失败 toast 为指定文案。

### 第 4 段：领域文档

- [ ] `CONTEXT.md` — 确认词汇与关系规则已与 PRD 一致（当前工作区已改过，实现时核对无回退即可）

## 测试

沿用 `backend/tests/` 纯单元测试（无 conftest、无 DB、`sys.path` 插入）：

- [ ] 扩展 `tests/test_explanation_prompt_structure.py`
  - 组装后的 prompt 含三段式契约与枚举；Profile persona 不含可独立生效的另一套 JSON 形状
  - 004 tripwire 保持：004 old == 003 写入值，004 new == 004 当时全文
  - 006 tripwire：006 old == 004 new；006 new == 当前 persona 常量；upgrade/downgrade 映射互逆
- [ ] 新增 `tests/test_ai_explanation_refresh.py`
  - `has_question_explanation`：仅中文为命中；英文-only 为未命中
  - `validate_structured_explanation`：缺段、漏错误选项、含正确答案、非法 type、空泛 reason、不足两句、题干有 MOST 但 qualifier 为空 → 失败；合格样本 → 通过
  - `explain_question` 首次不合格会带错误再调一次，第二次失败不 commit；合格则最多一次或两次调用后 commit
  - `force=false` + refresh 后已有中文 → 不覆盖
  - `force=true` → 覆盖
  - 现有“旧两键透传落库”断言改为拒绝落库

运行：`cd backend && python -m pytest tests/test_explanation_prompt_structure.py tests/test_ai_explanation_refresh.py -q`

前端无单测框架：用浏览器走答题页与错题本主路径，并确认模拟考试仍不显示解析按钮。

## 风险点与回滚

| 风险 | 处理 |
|---|---|
| 006 字面量与 004 新 prompt 差一个字符，存量 Profile 升级静默失败 | tripwire 锁 006 old == 004 new；升级后抽查 CIPT 项目 persona 是否已缩短 |
| 严格校验导致成功率下降 | 自动纠正一次；仍失败保留旧解析，用户可重试 |
| 预热与强制更新并发 | 非强制 CAS；强制更新后预热 refresh 看到中文即放弃写入 |
| 前端仍读 `error` 字段 | ExplainButton 改为 `detail`，更新失败用固定文案 |
| 切题后过期响应写到新题 | generation + `ExplainButton` 的 `:key="question.id"` |

回滚：还原代码；`alembic downgrade 005` 仅还原已知默认 Profile 字符串，题目缓存不受迁移影响。

## 起工前确认

- [ ] 规划摘要已获用户确认，且 `task.py start` 已把本任务翻成 `in_progress`
- [ ] `cd backend && alembic current` 确认本地链能升到 005，006 才能接上
- [ ] 本地 `AI_API_BASE_URL` / `AI_API_KEY` / `AI_MODEL` 可用，否则页面上的真实更新路径无法手工验收
