# 优化 AI 解析更新与输出质量 — 技术设计

## 架构与边界

四块改动，全部落在现有 AI 解析链路上，不新增表、不新增页面：

1. **获取 vs 更新语义**：`POST /api/ai/explain` 增加 `force`；缓存是否可用改为“中文解析能否展示”。
2. **平台输出契约**：考试项目 AI Profile 只提供领域角色 / 术语 / 讲解偏好；三段式 JSON 形状、干扰项枚举与质量规则由平台在运行时注入并校验。
3. **生成后校验 + 一次纠正重试**：不合格结果不得 commit；主动更新失败时数据库与页面都保留旧解析。
4. **前端按钮按“是否已显示”切换**：未显示为“AI 解析”，已显示为“更新AI解析”；更新期间继续展示旧文案。

预热任务继续走 `explain_question()`，不另开生成实现。

## 数据流

```
用户点击 ExplainButton
  ├─ displayed=false 且本地已有 explanation_zh
  │     → 不发请求，直接 emit 缓存（获取语义）
  ├─ displayed=false 且本地没有中文解析
  │     → POST /api/ai/explain { question_id, force: false }
  │           → 库中有 explanation_zh：返回 cached=true，不调模型
  │           → 否则 explain_question(force=false)
  └─ displayed=true
        → POST /api/ai/explain { question_id, force: true }
              → 必须调用 explain_question(force=true)，禁止返回旧缓存

explain_question(force)
  → 组装 system = persona(profile) + 平台输出契约
  → call_ai_api(scene="explain")
  → JSON 解析 + validate_structured_explanation(result, question)
  → 失败则把具体错误作为纠正消息再调一次模型（合计最多 2 次）
  → 仍失败：不写字段、不 commit，抛 ValueError
  → 成功：compose_explanation_zh() 生成展示文本
        ├─ force=false：refresh 后若 explanation_zh 已存在则放弃写入，返回现有缓存
        └─ force=true：覆盖 explanation / explanation_zh 并 commit
```

### 缓存判定

`has_question_explanation()` 改为只认 `bool(question.explanation_zh)`。

英文-only 旧记录视为缓存缺失：首次获取会生成并覆盖；预热 `count_pending_items` / `handle_ai_prewarm` / `/ai/prewarm` 也会把这类题当成待生成。这与产品决策一致，不是行为分叉。

### 非强制写入的 compare-and-swap

同步首次生成与预热可能并发。`force=false` 在 commit 前 `db.refresh(question)`：若此时已有中文解析，丢弃本次结果并返回已有缓存。这样预热不会覆盖用户已经拿到或已经更新过的解析。

`force=true` 不走 CAS，始终覆盖。两次主动更新并发时后提交者胜出，可接受（产品无冷却）。

不新增解析版本列。

## 契约变更

| 端点 / 符号 | 变更 |
|---|---|
| `AIExplainRequest` | 增加 `force: bool = False` |
| `POST /api/ai/explain` | `force=false` 且有中文缓存 → `{..., cached: true}`；`force=true` 必须调模型 |
| `has_question_explanation()` | 只检查 `explanation_zh` |
| `explain_question(db, question, *, force=False)` | 增加 `force`；生成路径做严格校验与一次纠正重试 |
| 响应 `AIExplainResponse` | 字段不变：`explanation` / `explanation_zh` / `cached` |

错误：生成或校验最终失败时路由捕获异常、`db.rollback()`，返回 500 + `detail`。前端按当前是“获取”还是“更新”选择提示文案，不依赖 `response.data.error`。

不使用 `response_format` / JSON Schema 请求体约束。现有 `call_ai_api` 只发 `model/messages/temperature`，项目 AI 入口是可配置的 OpenAI 兼容代理；服务端校验 + 一次重试已满足“不得只靠 Prompt”的要求，不把供应商能力当作硬依赖。

## Prompt 与 Profile

当前 `Exam.ai_profile.explanation_system_prompt` 存的是 **persona + 输出契约** 的完整文本，生成时整段当作 system prompt，自定义 Profile 可以换掉三段式。

改为：

- `explanation_system_prompt` **只表示领域角色、术语和讲解偏好**（persona overlay）。
- 平台常量 `EXPLANATION_OUTPUT_CONTRACT`（JSON 形状、`stem_breakdown` 字段规则、`EXPLANATION_DISTRACTOR_TYPES`、只返回 JSON）在运行时拼到 persona 后面。
- `build_explanation_system_prompt(persona)` 是唯一组装入口；`explain_question` 与预热都走它。
- `DEFAULT_AI_PROFILE` / `CIPT_AI_PROFILE` 的该字段改为 persona-only。
- 新建考试项目因此不会把输出契约写进 JSONB。

存量行：按项目 JSONB 快照惯例，只改常量无效。新增 Alembic `006`（`down_revision = "005"`）：仅当 `ai_profile->>'explanation_system_prompt'` 与 **004 写入的新默认 / 新 CIPT 全文** 逐字节相等时，替换为对应 persona。用户自定义过的 prompt 不改；运行时仍会在其后追加平台契约，服务端校验以平台规则为准。

004 的 tripwire 测试保持不动（锁的是历史迁移）。006 增加：

- 006 的 old 全文 == 004 的 new 全文
- 006 的 new persona == 当前代码 persona 常量

## 质量校验

`validate_structured_explanation(result, question) -> list[str]`，空列表表示通过。校验在 `compose_explanation_zh` 之前。`compose_explanation_zh` 不再承担“旧两键透传 / 缺段降级即可落库”的职责；它只渲染已通过校验的结构。旧两键兼容测试改为断言 **校验拒绝**，不再断言透传成功。

题目错误选项 = 全部 option key − `correct_answer` 拆出的 key（逗号分隔、strip）。判断题、多选题用同一规则。

| 项 | 通过条件 |
|---|---|
| `stem_breakdown` | 必须是 dict；`role` / `scenario` / `asked` 均非空 |
| `qualifier` | 题干出现 `EXPLANATION_STEM_QUALIFIERS` 中的词（按词边界、大小写不敏感）时必须非空；未出现时允许空 |
| `constraint` | 允许空；有值则必须是非空文本 |
| `explanation_zh` | 至少两句有实质信息的完整说明（按 `。！？；.!?` 分句）；不得只是“正确答案是 X”这类结论句 |
| `distractors` | 恰好覆盖全部错误选项，不含正确答案；每项 `type` ∈ `EXPLANATION_DISTRACTOR_TYPES`；`reason` 必须是与本题相关的具体原因，拒绝“该选项不正确 / 该选项错误 / 不正确 / 不对”等空泛句 |
| `explanation`（英文） | 不作为缓存与展示门槛；缺省不导致失败 |

“实质信息”不以单一字符数作为唯一标准：分句后丢弃空句，再排除明显结论套话；剩余有效句少于两句则失败。干扰项 `reason` 同样先看是否空泛，再看是否缺少具体说明。

纠正重试：把 `validate_*` 返回的错误列表格式化进第二条 user 消息（“只返回修正后的完整 JSON”），保留原 system + 原题 user。JSON 解析失败视为结构不合格，占用同一次重试名额。HTTP / 超时 / Key 未配置不走纠正重试。一次用户操作最多 2 次 `call_ai_api`。

## 前端

`ExplainButton` 仍是智能组件：自己调 `client`、自己管 loading、`emit('explained')`。

| 状态 | 文案 | disabled |
|---|---|---|
| 未显示、未请求 | AI 解析 | 否 |
| 未显示、请求中 | 解析中... | 是 |
| 已显示、未请求 | 更新AI解析 | 否 |
| 已显示、请求中 | 更新中... | 是 |

- 禁用条件改为只有 `loading`，去掉 `displayed`。
- 本地短路由只认 `explanation_zh`，与后端缓存口径一致。
- 更新请求必须带 `force: true`，不得因本地已有解析而跳过 API。
- 更新期间父组件继续渲染旧 `displayedExplanation`；成功后再用新 payload 替换。
- 更新失败 toast：`更新失败，已保留原解析`。首次获取失败：`e.response?.data?.detail || '解析失败'`。
- 组件内 generation 计数：切题或重入后忽略过期响应。`QuestionCard` 已有 `:key="question.id"`，generation 是双保险。

写回，避免“更新成功 → 切走再切回”显示旧文案：

- `QuestionCard`：成功后写入 `explainData`，并同步 `result.explanation_zh` / `question.explanation_zh`（`result` 与 `QuizView.questionResultMap` 是同一对象引用）。
- `WrongAnswersView`：成功后写入 `explainResults[w.id]`，并同步 `w.question.explanation_zh`。

模拟考试保持 `v-if="!examMode"`，本任务不改。

## 错误与事务

- `explain_question` 只在校验通过后才给 ORM 对象赋值并 `commit`。
- 路由 `except` 中 `db.rollback()`，避免脏 session。
- 失败路径不得留下半成品 `explanation*`。

## 兼容与迁移

- API 增加可选 `force`，旧客户端不传则行为接近“仅获取”；差别是英文-only 不再当缓存命中。
- 存量中文旧格式缓存继续可被首次获取返回；只有主动更新或英文-only 首次生成才走新校验。
- 006 只改匹配到的默认 Profile 字符串，不碰 `Question.explanation*`。
- 回滚：`alembic downgrade 005` 把已知 persona 还原成 004 全文；代码回退后旧客户端仍能调无 `force` 的接口。

## 权衡记录

- **CAS 而非版本列**：能挡住预热覆盖用户更新，不必改表。两名用户同时 `force` 更新仍是 last-write-wins。
- **运行时强制追加契约，而不是禁止自定义 prompt**：自定义 Profile 仍可写角色和术语；即使里面残留旧 JSON 说明，校验仍按平台规则拒绝不合格输出。
- **不启用 response_format**：避免绑死代理实现；质量由校验和重试保证。
- **compose 降级退出落库路径**：否则“兼容旧两键”会继续把不合格内容写进缓存，与本任务目标冲突。

## 未决 / 已知风险

- 纠正重试仍可能被模型忽略；第二次失败时用户看到失败提示，缓存不变，可再点更新。
- 自定义 Profile 若与平台契约互相矛盾，prompt 变长，偶发校验失败率可能升高；不在本期做 prompt 清洗 UI。
- `backend/tests/` 仍是无 DB 的纯单元测试形态；本任务沿用，覆盖校验、重试次数、CAS、`force` 与英文-only 缓存判定。
