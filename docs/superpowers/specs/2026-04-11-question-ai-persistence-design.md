# 题库题目 AI 翻译与解析持久化设计

## 概要

本设计针对题库题目的“翻译”和“AI 解析”能力补齐跨设备可复用的后端持久化语义，并修正题目被编辑后的失效问题。

目标是在**不新增独立结果表**、继续沿用现有 `Question` 字段存储结果的前提下，实现：

- 同一道题首次生成翻译后写入数据库，后续任意设备复用
- 同一道题首次生成 AI 解析后写入数据库，后续任意设备复用
- 题目内容、选项、答案、题型发生变化时，按影响范围自动清空旧结果
- 前端在题目对象已自带结果时优先复用，避免无意义地再次点击触发上游 AI 生成

本设计优先保证改动最小、兼容现有数据模型与接口语义、避免重复调用上游 AI 服务。

## 背景与现状

当前相关实现位于：

- [backend/routes/ai.py](/home/ubuntu/github/quiz-app/backend/routes/ai.py)
- [backend/services/ai_service.py](/home/ubuntu/github/quiz-app/backend/services/ai_service.py)
- [backend/routes/questions.py](/home/ubuntu/github/quiz-app/backend/routes/questions.py)
- [frontend/src/components/TranslateButton.vue](/home/ubuntu/github/quiz-app/frontend/src/components/TranslateButton.vue)
- [frontend/src/components/ExplainButton.vue](/home/ubuntu/github/quiz-app/frontend/src/components/ExplainButton.vue)
- [frontend/src/components/QuestionCard.vue](/home/ubuntu/github/quiz-app/frontend/src/components/QuestionCard.vue)

当前行为：

- 翻译结果已经写入 `Question.content_zh` 与 `Question.options` JSON 内的 `text_zh`
- AI 解析结果已经写入 `Question.explanation` 与 `Question.explanation_zh`
- `/api/ai/translate` 在 `content_zh` 已存在时会直接返回缓存结果
- `/api/ai/explain` 在 `explanation` 已存在时会直接返回缓存结果
- 多个题目接口会把 `content_zh`、`explanation`、`explanation_zh` 一并返回给前端

当前缺口：

1. 题目被编辑后，旧翻译和旧解析不会自动失效，存在返回过期内容的风险
2. 翻译缓存返回结构不完整，cached 命中时未显式返回 `options_zh`
3. 前端对“题目对象里已经自带解析结果”的场景没有优先复用，仍可能再次调用 `/api/ai/explain`
4. 用户需求关注的是“换设备后不重复生成”，因此验收口径应聚焦于**不重复调用上游 AI**，而不是完全不再请求业务后端

## 目标

### 功能目标

1. 同一道题翻译结果在后端持久化后，可跨设备复用
2. 同一道题 AI 解析结果在后端持久化后，可跨设备复用
3. 题目编辑后按字段影响范围自动清理过期翻译/解析
4. `/api/ai/translate` 与 `/api/ai/explain` 命中持久化结果时不再调用上游 AI
5. 前端在题目对象已带有持久化解析时，点击“AI 解析”直接展示现有结果

### 设计目标

1. 不新增独立结果表，继续沿用 `Question` 现有字段
2. 不引入新的复杂缓存层或迁移体系
3. 改动聚焦在 AI 路由、题目更新逻辑和相关前端组件
4. 保持现有接口主体语义稳定，仅补齐缺失字段与复用逻辑

## 非目标

本次不包含以下范围：

- 新建独立的 AI 结果表
- 为翻译/解析引入模型版本、提示词版本或多版本结果管理
- 按用户隔离翻译或解析结果
- 构建前端本地缓存体系
- 为 AI 接口加入分布式锁、任务队列或复杂并发协调
- 回填历史题目的翻译或解析数据

## 数据模型与职责边界

本次继续以 `Question` 作为 AI 结果的唯一持久化载体。

### 1. 翻译结果

持久化位置：

- `Question.content_zh`
- `Question.options` JSON 中每个选项对象的 `text_zh`

职责：

- `content_zh` 保存整题中文题干
- `text_zh` 保存对应选项的中文翻译
- 两者共同组成“单题翻译结果”

### 2. AI 解析结果

持久化位置：

- `Question.explanation`
- `Question.explanation_zh`

职责：

- `explanation` 保存英文解析
- `explanation_zh` 保存中文解析

### 3. 与独立结果表的取舍

本次明确不新增独立结果表，原因：

- 当前模型已经具备持久化能力
- 项目没有正式迁移体系，新增表会增加运行时 schema 维护与测试成本
- 当前需求只要求“首次生成后跨设备复用”，不要求版本管理或保留历史结果
- 现有接口与前端已经大量依赖 `Question` 上的这些字段，继续复用可把改动控制在最小范围

## 命中规则与接口语义

### 1. 翻译接口：`POST /api/ai/translate`

处理规则：

1. 根据 `question_id` 读取题目
2. 若题目已有有效翻译结果，则直接返回持久化内容
3. 若无有效翻译结果，则调用上游 AI，写回题目，再返回新结果

命中条件：

- `Question.content_zh` 已存在

返回语义：

- 命中持久化结果时返回 `cached: true`
- 首次生成时返回 `cached: false`

返回体要求：

- 无论是否命中缓存，都返回：
  - `content_zh`
  - `options_zh`
  - `cached`

说明：

- `options_zh` 需要从 `Question.options` 中提取，保证 cached 命中与首次生成返回结构一致
- 这样前端不需要区分“新生成结果”和“数据库已有结果”的结构差异

### 2. 解析接口：`POST /api/ai/explain`

处理规则：

1. 根据 `question_id` 读取题目
2. 若题目已有有效解析结果，则直接返回持久化内容
3. 若无有效解析结果，则调用上游 AI，写回题目，再返回新结果

命中条件：

- `Question.explanation` 存在，或
- `Question.explanation_zh` 存在

返回语义：

- 命中持久化结果时返回 `cached: true`
- 首次生成时返回 `cached: false`

返回体要求：

- 无论是否命中缓存，都返回：
  - `explanation`
  - `explanation_zh`
  - `cached`

### 3. “避免重复请求”的边界

本次只做后端持久化，因此最终保证的是：

- 不重复调用上游 AI / 翻译服务
- 题目结果在不同设备间复用

本次**不保证**浏览器永远不再访问 `/api/ai/translate` 或 `/api/ai/explain`。如果前端主动点了按钮，仍可能请求业务后端，但后端应直接返回数据库已有结果，而不是再次触发 AI 生成。

## 失效规则

题目编辑后需要根据变更字段清理过期结果，避免“题目已变，但旧翻译/旧解析仍被复用”。

### 1. 修改 `content`

影响：

- 翻译失效
- 解析失效

处理：

- 清空 `content_zh`
- 清空 `options[*].text_zh`
- 清空 `explanation`
- 清空 `explanation_zh`

### 2. 修改 `options`

影响：

- 翻译失效
- 解析失效

处理：

- 清空 `content_zh`
- 清空 `options[*].text_zh`
- 清空 `explanation`
- 清空 `explanation_zh`

说明：

- 这里连题干翻译一并清空，是为了保证整题翻译结果的一致性，避免一题中出现“题干是旧翻译、选项是新内容”的混杂状态

### 3. 修改 `correct_answer`

影响：

- 仅解析失效
- 翻译保留

处理：

- 保留 `content_zh`
- 保留 `options[*].text_zh`
- 清空 `explanation`
- 清空 `explanation_zh`

### 4. 修改 `question_type`

影响：

- 解析失效
- 翻译保留

处理：

- 保留 `content_zh`
- 保留 `options[*].text_zh`
- 清空 `explanation`
- 清空 `explanation_zh`

### 5. 不触发失效的字段

以下字段变化不应清空翻译/解析：

- `order_index`
- `bank_id`（如果未来允许移动题目）
- 其他纯排序、归档、关联类字段

## 后端设计

### 1. 统一的 AI 结果辅助函数

在 `backend/services/ai_service.py` 增加小型辅助函数，统一封装以下逻辑：

- 从 `question.options` 提取 `options_zh`
- 清空翻译字段
- 清空解析字段
- 按题目当前内容组装 cached 返回体

设计目的：

- 避免 route 层重复解析和拼装 `options`
- 避免未来新增题目编辑入口时失效逻辑散落各处
- 保持 AI route 与题目更新 route 的职责简单明确

建议职责拆分：

- `build_question_translation_payload(question)`
- `build_question_explanation_payload(question)`
- `clear_question_translation(question)`
- `clear_question_explanation(question)`

### 2. `backend/routes/ai.py`

调整点：

- `translate()` 在 cached 命中时，返回完整翻译结构而不只返回 `content_zh`
- `explain()` 保持优先读已持久化结果，但命中条件改为“英文或中文解析任一存在即可返回”
- 两个接口都保留 `cached` 字段，方便前端与测试统一判断

### 3. `backend/routes/questions.py`

在 `update_question()` 中增加变更检测和失效逻辑。

核心流程：

1. 读取原题目
2. 判断本次请求是否修改了：
   - `content`
   - `options`
   - `correct_answer`
   - `question_type`
3. 先按失效规则清空相应字段
4. 再写入新的题目内容
5. 提交事务

说明：

- 变更判断应基于“请求中是否传入字段且值不同”，避免无意义地清空已生成结果
- `options` 比较以反序列化后的结构比较为准，避免因为 JSON 编码格式不同造成误判

## 前端设计

### 1. `TranslateButton.vue`

当前逻辑已基本满足需求：

- 当 `hasTranslation` 为真时，只切换显示状态，不再请求 `/api/ai/translate`

本次仅需要保证：

- 前端接到 cached 返回时也能正确回填 `options_zh`
- 按钮继续以 `question.content_zh` 是否存在作为是否已有翻译的判断依据

### 2. `ExplainButton.vue`

当前问题：

- 组件只缓存“本组件实例里已经请求过的解析”
- 如果题目对象本身已经带有 `explanation` / `explanation_zh`，组件仍然会发起 `/api/ai/explain`

调整目标：

- 支持从父组件传入题目已持久化的解析结果
- 当题目已有解析时，点击按钮直接 `emit('explained', existingExplanation)`
- 仅当题目没有任何解析时，才请求 `/api/ai/explain`

### 3. `QuestionCard.vue`

需要承担的职责：

- 将当前题目对象里已有的 `explanation` / `explanation_zh` 传给 `ExplainButton`
- 切题时根据当前题目自带的解析结果初始化展示状态
- 保持“AI 解析面板”和“答题反馈里的官方解析”职责分离

说明：

- 答题反馈区展示的是答题接口返回的解析
- AI 解析按钮区展示的是按需点击查看的 AI 解析
- 二者都基于 `Question` 的持久化字段，但交互入口不同

## 数据流设计

### 1. 首次翻译

1. 前端点击“翻译”
2. `POST /api/ai/translate`
3. 后端发现 `content_zh` 不存在
4. 调用上游 AI 生成翻译
5. 写入 `Question.content_zh` 与 `options[*].text_zh`
6. 返回完整翻译结果，`cached: false`

### 2. 重复翻译（同设备或跨设备）

1. 前端点击“翻译”
2. `POST /api/ai/translate`
3. 后端发现 `content_zh` 已存在
4. 直接从数据库组装返回完整翻译结果，`cached: true`
5. 不调用上游 AI

### 3. 首次 AI 解析

1. 前端点击“AI 解析”
2. 若题目对象本身未携带解析，则调用 `POST /api/ai/explain`
3. 后端发现 `explanation` / `explanation_zh` 不存在
4. 调用上游 AI 生成解析
5. 写入 `Question.explanation` 与 `Question.explanation_zh`
6. 返回解析结果，`cached: false`

### 4. 重复 AI 解析

有两种可能路径：

#### 路径 A：题目对象已自带解析

1. 前端点击“AI 解析”
2. 前端直接展示题目对象现有解析
3. 不访问 `/api/ai/explain`
4. 更不会调用上游 AI

#### 路径 B：前端仍访问 `/api/ai/explain`

1. 前端点击“AI 解析”
2. `POST /api/ai/explain`
3. 后端发现解析已存在
4. 直接返回数据库结果，`cached: true`
5. 不调用上游 AI

### 5. 编辑题目后的重新生成

1. 管理员更新题目
2. 后端按字段影响范围清空旧翻译/旧解析
3. 用户再次点击“翻译”或“AI 解析”
4. 因相关字段已清空，后端重新调用上游 AI 生成新结果

## 错误处理

### 1. AI 服务不可用或配置缺失

保持当前错误语义：

- 翻译失败返回 `500` 与错误信息
- 解析失败返回 `500` 与错误信息

本次不改变错误码策略，只保证：

- 失败时不写入半成品翻译/解析
- cached 命中路径不受上游 AI 服务可用性影响

### 2. 部分解析字段缺失

对于解析缓存命中，采用保守策略：

- 只要 `explanation` 或 `explanation_zh` 任一存在，即允许作为已有结果返回
- 这样可兼容历史上只写入部分字段的边界情况

### 3. 题目更新时无意义失效

变更检测必须以“字段值实际改变”为前提：

- 请求未传某字段：不触发相应失效
- 请求传了但值未变：不触发相应失效

## 测试与验收

### 后端自动化测试

建议新增或补充以下用例：

1. `POST /api/ai/translate` 命中 `content_zh` 时不调用 AI，并返回 `content_zh + options_zh + cached: true`
2. `POST /api/ai/explain` 命中已有解析时不调用 AI，并返回 `cached: true`
3. 修改 `content` 时，同时清空翻译与解析字段
4. 修改 `options` 时，同时清空翻译与解析字段
5. 修改 `correct_answer` 时，仅清空解析字段
6. 修改 `question_type` 时，仅清空解析字段

### 前端手工验证

至少验证以下场景：

1. 首次点击“翻译”，结果生成并展示
2. 刷新页面后再次点击“翻译”，直接复用结果
3. 换设备登录再次点击“翻译”，直接复用结果
4. 首次点击“AI 解析”，结果生成并展示
5. 刷新页面后再次点击“AI 解析”，直接复用结果
6. 题目对象已自带解析时，点击“AI 解析”不再请求接口而直接展示
7. 管理员编辑题干后，再次点击“翻译/AI 解析”会重新生成
8. 管理员只改正确答案后，翻译仍存在，但 AI 解析需重新生成

### 验收标准

满足以下条件即视为完成：

- 翻译结果首次生成后持久化到 `Question`
- 解析结果首次生成后持久化到 `Question`
- 同一道题在任意设备重复查看时，不再重复调用上游 AI
- 题目编辑后旧结果不会继续被复用
- 接口 cached 命中与首次生成的返回结构保持一致
- 前端在已有解析时优先复用，不再无意义请求 `/api/ai/explain`

## 实施范围

本次实施范围限定为：

- `backend/services/ai_service.py`
- `backend/routes/ai.py`
- `backend/routes/questions.py`
- `frontend/src/components/ExplainButton.vue`
- `frontend/src/components/QuestionCard.vue`
- 相关后端测试文件

不扩展到无关页面或新的数据表。
