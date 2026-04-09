# AI 按场景拆分模型别名设计

## 概要

当前系统的 AI 配置仅支持单一 `ai_model`，题目翻译、词汇翻译与 AI 解析共用同一个模型。由于翻译场景对响应时延更敏感，而 AI 解析对模型能力要求更高，统一模型配置无法同时兼顾性能与效果。

本设计采用增量式拆分方案：在保留现有统一模型配置的基础上，新增翻译场景模型和解析场景模型两个可选配置项，实现“按场景优先命中、未配置时回退默认模型”的模型选择策略。

目标效果：

- 翻译场景优先使用低延迟模型，例如 `gpt-5-nano`
- AI 解析场景优先使用高能力模型，例如 `gpt-5.4`
- 未配置场景模型时，默认使用现有 `ai_model`
- 保持现有系统配置、调用链路与历史缓存的兼容性

## 背景与现状

当前实现涉及以下模块：

- `backend/routes/settings.py`：AI 设置读取、保存与连接测试
- `backend/services/settings_service.py`：AI 配置解析与 API Key 处理
- `backend/services/ai_service.py`：AI 调用、翻译与解析业务逻辑
- `frontend/src/views/AdminSettingsView.vue`：管理后台 AI 设置页面

现状特点：

- 管理后台仅支持配置一个模型字段 `ai_model`
- `call_ai_api()` 使用统一模型发起所有 AI 请求
- 题目翻译、词汇翻译、批量翻译、题目解析均共用同一模型
- 题目翻译结果与解析结果会写入数据库缓存，避免重复调用

现有问题：

- 翻译场景通常更关注吞吐与响应速度，不一定需要高能力模型
- 解析场景需要更强的语义理解与推理能力，适合保留高能力模型
- 单一模型配置难以平衡性能、质量与成本

## 目标

### 功能目标

1. 管理后台支持分别配置默认模型、翻译模型、解析模型
2. 翻译场景优先使用 `ai_translate_model`
3. AI 解析场景优先使用 `ai_explain_model`
4. 当对应场景模型未配置时，默认走 `ai_model`
5. 保持现有 API Base URL、API Key 与连接测试能力不变

### 设计目标

1. 改造范围聚焦在 AI 设置与调用链，不扩散到无关模块
2. 场景模型选择逻辑收口到服务层，避免业务代码重复判断
3. 保持对旧配置完全兼容，降低上线风险
4. 不引入数据库 schema 变更，继续复用 `SystemSetting`

## 非目标

本次设计不包含以下范围：

- 不同场景使用不同 `API Base URL`
- 不同场景使用不同 `API Key`
- 运行时失败后自动切换备用模型
- 已缓存翻译/解析数据的自动重算
- 模型下拉推荐、模型能力提示或智能选型

## 配置与兼容策略

### 配置项设计

保留现有配置项：

- `ai_api_base_url`
- `ai_api_key`
- `ai_model`

新增配置项：

- `ai_translate_model`
- `ai_explain_model`

字段含义：

- `ai_model`：系统默认模型，作为通用兜底配置
- `ai_translate_model`：翻译场景专用模型
- `ai_explain_model`：AI 解析场景专用模型

### 模型选择优先级

翻译场景：

- 优先使用 `ai_translate_model`
- 若未配置，则使用 `ai_model`

解析场景：

- 优先使用 `ai_explain_model`
- 若未配置，则使用 `ai_model`

默认场景：

- 直接使用 `ai_model`

### 存储策略

本方案不修改数据库表结构，继续复用 `SystemSetting` 的键值对存储，仅新增两个 setting key：

- `ai_translate_model`
- `ai_explain_model`

### 兼容性策略

- 老版本仅配置 `ai_model` 时，系统行为保持不变
- 新增场景模型后，仅对应场景切换到新模型
- 已缓存的翻译与解析结果不自动重算，新配置仅影响后续新请求

## 后端设计

### 设置接口改造

扩展现有 AI 设置接口，新增场景模型字段支持。

#### `GET /api/settings/ai`

返回字段新增：

- `ai_translate_model`
- `ai_explain_model`

返回示例：

```json
{
  "ai_api_base_url": "https://api.openai.com",
  "ai_api_key": "sk-****abcd",
  "ai_api_key_configured": true,
  "ai_model": "gpt-5.4",
  "ai_translate_model": "gpt-5-nano",
  "ai_explain_model": "gpt-5.4"
}
```

#### `PUT /api/settings/ai`

支持保存新增字段：

- `ai_translate_model`
- `ai_explain_model`

请求示例：

```json
{
  "ai_api_base_url": "https://api.openai.com",
  "ai_api_key": "sk-xxx",
  "ai_model": "gpt-5.4",
  "ai_translate_model": "gpt-5-nano",
  "ai_explain_model": "gpt-5.4"
}
```

### 设置服务改造

当前 `backend/services/settings_service.py` 中的 `get_effective_ai_settings()` 只返回单一模型配置。建议扩展为支持按场景解析模型，例如：

- `scene='default'`
- `scene='translate'`
- `scene='explain'`

解析规则：

- `translate` 优先读取 `ai_translate_model`，未配置则回退 `ai_model`
- `explain` 优先读取 `ai_explain_model`，未配置则回退 `ai_model`
- `default` 直接读取 `ai_model`

这样可以将模型选择策略集中在设置服务层，降低后续维护成本。

### AI 调用层改造

当前 `backend/services/ai_service.py` 中的 `call_ai_api(messages)` 使用统一模型调用 AI。建议改造为：

- `call_ai_api(messages, scene='default')`

各业务方法与场景映射如下：

- `translate_question()` → `scene='translate'`
- `translate_term()` → `scene='translate'`
- `batch_translate_terms()` → `scene='translate'`
- `explain_question()` → `scene='explain'`

### 调用链路

翻译链路：

前端发起翻译请求 → 后端翻译接口 → 翻译服务方法 → `call_ai_api(scene='translate')` → 优先使用 `ai_translate_model`，未配置则回退 `ai_model`

解析链路：

前端发起解析请求 → 后端解析接口 → 解析服务方法 → `call_ai_api(scene='explain')` → 优先使用 `ai_explain_model`，未配置则回退 `ai_model`

### 错误处理策略

本次只调整模型选择逻辑，不改变现有异常处理语义：

- API Key 未配置：继续返回现有错误提示
- Base URL 未配置：继续返回现有错误提示
- 第三方 AI 接口报错：继续透传现有错误信息
- 场景模型未配置：不报错，自动回退到 `ai_model`

## 前端设计

### 设置页改造目标

在 `frontend/src/views/AdminSettingsView.vue` 现有“AI API 配置”区域基础上，新增按场景配置模型别名的能力，同时保留现有 Base URL、API Key 与默认模型配置。

### 表单字段设计

页面保留现有字段：

- `AI API Base URL`
- `API Key`
- `默认模型（ai_model）`

新增字段：

- `翻译模型（ai_translate_model）`
- `AI 解析模型（ai_explain_model）`

推荐展示顺序：

1. API Base URL
2. API Key
3. 默认模型
4. 翻译模型
5. AI 解析模型

### 交互说明

建议在输入框下增加帮助文案，明确各字段作用：

- 默认模型：系统统一默认模型；当未配置翻译模型或解析模型时，默认使用该模型
- 翻译模型：用于题目翻译、词汇翻译等场景；留空时默认使用“默认模型”
- AI 解析模型：用于题目 AI 解析场景；留空时默认使用“默认模型”

### 数据加载与保存

页面加载时，调用 `GET /api/settings/ai`，读取并展示以下字段：

- `ai_api_base_url`
- `ai_api_key`（掩码展示）
- `ai_model`
- `ai_translate_model`
- `ai_explain_model`

页面保存时，调用 `PUT /api/settings/ai`，提交完整表单数据，包括新增两个模型字段。

### 输入规则

首版保持自由文本输入，不引入模型下拉选项或复杂校验，仅进行基础 trim 处理。

原因：

- 模型别名由不同 OpenAI 兼容服务商定义，格式不统一
- 当前系统已采用自由输入方式，保持一致性更利于维护
- 降低首版实现复杂度

### 测试连接策略

“测试连接”按钮继续沿用现有逻辑，仅验证默认模型 `ai_model` 对应的连接是否可用，不单独增加“测试翻译模型”或“测试解析模型”按钮。

这样可以保持页面操作简单，并将测试目标聚焦在 API 服务可用性验证，而不是场景路由逻辑验证。

## 测试方案

### 后端接口测试

验证设置接口已支持新增字段：

- `GET /api/settings/ai` 可正确返回 `ai_translate_model`、`ai_explain_model`
- `PUT /api/settings/ai` 可正确保存 `ai_translate_model`、`ai_explain_model`
- 新字段留空时不影响原有 `ai_model`

### 模型选择逻辑测试

#### 用例一：仅配置默认模型

- `ai_model = gpt-5.4`
- `ai_translate_model = ''`
- `ai_explain_model = ''`

预期：

- 翻译使用 `gpt-5.4`
- 解析使用 `gpt-5.4`

#### 用例二：配置翻译模型

- `ai_model = gpt-5.4`
- `ai_translate_model = gpt-5-nano`
- `ai_explain_model = ''`

预期：

- 翻译使用 `gpt-5-nano`
- 解析使用 `gpt-5.4`

#### 用例三：配置解析模型

- `ai_model = gpt-5.4`
- `ai_translate_model = ''`
- `ai_explain_model = gpt-5.4`

预期：

- 翻译使用 `gpt-5.4`
- 解析使用 `gpt-5.4`

#### 用例四：同时配置翻译与解析模型

- `ai_model = gpt-5.4`
- `ai_translate_model = gpt-5-nano`
- `ai_explain_model = gpt-5.4`

预期：

- 翻译使用 `gpt-5-nano`
- 解析使用 `gpt-5.4`

### 业务链路测试

验证以下能力是否命中正确场景模型：

- 题目单题翻译
- 题目批量翻译
- 词汇翻译
- AI 题目解析

同时确认：

- 缓存命中逻辑不受影响
- 现有错误提示不受影响

### 前端页面测试

验证设置页的新增字段是否：

- 正确展示
- 正确保存
- 正确回显
- 留空时保存正常
- 不影响现有 API Key 掩码与测试连接行为

## 上线影响说明

### 数据库影响

本方案继续复用 `SystemSetting` 键值存储，不修改表结构，因此：

- 无需数据库迁移
- 无需新增表或字段
- 上线成本低

### 存量配置影响

如果现有系统只配置了：

- `ai_api_base_url`
- `ai_api_key`
- `ai_model`

则上线后系统行为保持不变。只有在管理员主动填写 `ai_translate_model` 或 `ai_explain_model` 后，对应场景才会切换到新的模型别名。

### 存量业务数据影响

当前翻译结果和解析结果会缓存到数据库中，因此新配置仅影响后续新请求，已生成的翻译与解析数据不自动更新。

### 回滚影响

若后续需要回滚：

- 前端可移除新增字段展示
- 后端可忽略新增设置项
- 即使 `SystemSetting` 中保留 `ai_translate_model`、`ai_explain_model` 两个 key，也不会影响旧逻辑运行

因此本方案回滚风险较低。

## 预期收益

- 在不改变整体架构的前提下，实现翻译与解析的模型解耦
- 翻译场景可优先使用低延迟模型，提升性能
- AI 解析场景保留高能力模型，保障结果质量
- 保持旧配置兼容，降低上线与维护成本
