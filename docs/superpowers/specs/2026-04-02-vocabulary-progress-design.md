# 单词本掌握状态与删除能力设计

## 概要

本设计覆盖单词本页面的三个列表区域：

- 我的单词本
- 专业词汇
- 高频词汇

目标是在保留现有顶部三张统计卡片和 tab 切换结构的前提下，为三个列表统一提供以下能力：

- 按当前用户记录“已掌握 / 未掌握”状态
- 按掌握状态筛选列表
- 由管理员执行删除操作

本设计优先保证资源边界清晰、接口语义规范、数据模型可扩展，并达到个人项目但按开源项目标准维护的实现质量。

## 背景与现状

当前实现位于 [VocabularyView.vue](/home/ubuntu/github/quiz-app/frontend/src/views/VocabularyView.vue) 和 [vocab.py](/home/ubuntu/github/quiz-app/backend/routes/vocab.py)：

- 顶部已有三张卡片，分别切换专业词汇、我的单词本和高频词汇
- 我的单词本和专业词汇已有基础列表与删除能力
- 高频词汇来自 `bank_word_frequencies`，是题库导入后生成的派生数据
- 三类列表均未支持按用户记录的掌握状态
- 三类列表均未支持掌握状态筛选

额外约束：

- 删除按钮仅对 `is_admin = true` 的用户开放
- “已掌握”必须按用户记录，不能是全局状态
- 当前项目没有正式数据库迁移体系，数据库结构通过 `db.create_all()` 和运行时 schema ensure 维护

## 目标

### 功能目标

1. 三类列表都支持查看当前用户的掌握状态
2. 三类列表都支持筛选全部、未掌握、已掌握
3. 三类列表都支持标记已掌握与取消已掌握
4. 三类列表都支持管理员删除

### 设计目标

1. 查询、状态变更、删除三类职责分离
2. 公共词条数据与用户学习状态分离建模
3. 高频词汇按自然键 `bank_id + term` 作为资源身份
4. 改动范围聚焦在单词本域，不扩散到无关模块

## 非目标

本次不包含以下范围：

- 顶部三张统计卡片新增掌握率或掌握数展示
- 批量标记已掌握
- 删除恢复、回收站
- 普通用户删除权限
- 大规模前端组件重构

## 数据模型设计

### 1. `user_vocab_progress`

用途：记录当前用户对 `Vocabulary` 词条的学习状态。

适用范围：

- 我的单词本
- 专业词汇

字段：

- `id`
- `user_id`
- `vocabulary_id`
- `is_mastered`，默认 `False`
- `created_at`
- `updated_at`

约束与索引：

- 唯一约束：`user_id + vocabulary_id`
- 为 `user_id`、`vocabulary_id` 增加查询友好的索引

说明：

- 该表不存储词条内容，仅存储用户状态
- 同一词条可被不同用户记录不同掌握状态

### 2. `user_bank_word_progress`

用途：记录当前用户对某题库高频词的学习状态。

适用范围：

- 高频词汇

字段：

- `id`
- `user_id`
- `bank_id`
- `term`
- `is_mastered`，默认 `False`
- `created_at`
- `updated_at`

约束与索引：

- 唯一约束：`user_id + bank_id + term`
- 为 `user_id + bank_id`、`bank_id + term` 增加索引

说明：

- 高频词不复用 `Vocabulary` 的整数主键体系
- `bank_id + term` 是该域内天然稳定的自然键

### 3. `bank_word_exclusions`

用途：记录管理员删除的高频词，防止题库重新导入、重建词频后再次出现在列表中。

字段：

- `id`
- `bank_id`
- `term`
- `created_by`
- `created_at`

约束与索引：

- 唯一约束：`bank_id + term`
- 为 `bank_id` 增加索引

说明：

- 该表用于表示“此高频词资源在该题库下已被管理员移除”
- 删除高频词不是删除用户进度，而是移除公共可见资源

## 删除语义

### 我的单词本

- 删除操作仅 admin 可执行
- 删除为物理删除 `Vocabulary` 中该个人词条
- 删除后该词条对应的 `user_vocab_progress` 记录一并失效

### 专业词汇

- 删除操作仅 admin 可执行
- 删除为物理删除系统词条
- 删除后所有用户都不再看到该词条

### 高频词汇

- 删除操作仅 admin 可执行
- 删除动作写入 `bank_word_exclusions`
- 高频词列表查询时过滤 exclusion
- 题库重新导入、重建词频时继续过滤 exclusion 中的词

## API 设计

### 查询接口

保留现有三个列表入口作为查询接口：

- `GET /api/vocab/personal`
- `GET /api/vocab/professional`
- `GET /api/vocab/frequent?bank_id=1`

统一支持查询参数：

- `mastered=true`
- `mastered=false`
- 不传时返回全部

统一返回字段：

- `is_mastered`
- `can_delete`
- `can_mark_mastered`

说明：

- `can_delete` 由后端根据当前用户权限计算
- 高频词接口在返回前过滤 `bank_word_exclusions`

### `Vocabulary` 词条进度接口

用于更新我的单词本和专业词汇的掌握状态：

- `PUT /api/vocab/items/<int:vocabulary_id>/progress`

请求体：

```json
{
  "is_mastered": true
}
```

行为：

- 若进度记录存在则更新
- 不存在则创建
- `false` 表示取消已掌握

### 高频词进度接口

用于更新高频词掌握状态：

- `PUT /api/vocab/frequent-items/progress`

请求体：

```json
{
  "bank_id": 1,
  "term": "privacy",
  "is_mastered": true
}
```

说明：

- 不将 `term` 放入 path，避免空格、大小写和 URL 编码带来的自然键处理复杂度
- `bank_id + term` 作为高频词资源身份

### 删除接口

#### `Vocabulary` 词条删除

- `DELETE /api/vocab/items/<int:vocabulary_id>`

规则：

- 仅 admin 可执行
- 若词条是个人词条，则删除该个人词条
- 若词条是系统词条，则删除该系统词条

#### 高频词删除

- `DELETE /api/vocab/frequent-items?bank_id=1&term=privacy`

规则：

- 仅 admin 可执行
- 将 `bank_id + term` 写入 `bank_word_exclusions`
- 当前查询结果中移除该项

### 响应约定

列表项返回示例：

```json
{
  "id": 12,
  "term": "privacy",
  "term_zh": "隐私",
  "is_mastered": false,
  "can_delete": true,
  "can_mark_mastered": true
}
```

写操作返回示例：

```json
{
  "message": "已标记为掌握"
}
```

错误响应继续使用：

```json
{
  "error": "无权限"
}
```

状态码约定：

- `400`：参数非法或缺失
- `403`：权限不足
- `404`：目标资源不存在

## 前端交互设计

### 顶部卡片

保留现有三张统计卡片：

- 专业词汇
- 我的单词本
- 高频词汇

不在本次范围内修改统计口径。

### 列表工具栏

三个列表区域统一提供工具栏，包含：

- 搜索框
- 三段筛选：全部 / 未掌握 / 已掌握
- 各区域原有操作按钮

细化如下：

- 专业词汇：保留添加、批量翻译、导入按钮
- 我的单词本：保留添加按钮
- 高频词汇：保留题库选择器，并补充搜索与掌握状态筛选

### 列表项操作

每个词条项统一提供：

- `标记已掌握` / `取消掌握`
- `删除`，仅 admin 可见

交互规则：

- 当前筛选为“未掌握”时，标记已掌握成功后即时从当前列表移除
- 当前筛选为“已掌握”时，取消已掌握成功后即时从当前列表移除
- 当前筛选为“全部”时，仅更新状态样式与按钮文案

### 视觉状态

已掌握项增加明确视觉提示：

- 显示“已掌握”状态 badge
- 卡片边框或强调色使用轻量绿色状态

要求：

- 保留可读性，不做大幅灰化处理
- 状态提示不能只依赖按钮文案

### 高频词分页行为

高频词删除后：

- 当前页即时移除该项
- 若当前页清空且仍存在上一页，则自动回退到上一页重新拉取

### 空状态

区分三类空状态：

- 原始空列表
- 搜索无结果
- 当前掌握筛选无结果

避免将筛选为空误导为系统异常。

## 后端实现边界

主要改动文件：

- [models.py](/home/ubuntu/github/quiz-app/backend/models.py)
- [app.py](/home/ubuntu/github/quiz-app/backend/app.py)
- [vocab.py](/home/ubuntu/github/quiz-app/backend/routes/vocab.py)

按需最小补充：

- 与高频词重建相关的导入或服务代码

明确不改：

- 认证体系
- 首页统计展示
- Pinia 全局状态结构

## Schema Ensure 策略

由于当前项目没有 Alembic 等迁移体系，本次采用与现有仓库一致、但更集中化的 schema ensure 方案：

- 在 `app.py` 中新增清晰命名的 ensure 函数
- 负责新表存在性检查
- 负责必要索引与少量补结构逻辑
- 不在路由层执行 schema 修补

目标是将数据库结构兼容逻辑集中在应用启动阶段，避免运行时分散补丁。

## 测试策略

优先补后端接口测试，确保核心行为可回归验证。

至少覆盖以下场景：

1. `GET /api/vocab/personal` 支持 `mastered=true/false`
2. `GET /api/vocab/professional` 返回当前用户的 `is_mastered`
3. `GET /api/vocab/frequent` 返回当前用户的 `is_mastered`
4. `GET /api/vocab/frequent` 过滤 `bank_word_exclusions`
5. `PUT /api/vocab/items/<id>/progress` 可创建和更新状态
6. `PUT /api/vocab/frequent-items/progress` 可创建和更新状态
7. 非 admin 删除 `Vocabulary` 词条返回 `403`
8. admin 删除专业词汇成功
9. admin 删除个人词汇成功
10. admin 删除高频词后当前列表不再返回该词
11. 高频词重建后 exclusion 中的词仍不返回

前端验证方式：

- 运行前端构建，确认页面代码可编译
- 手动验证三个 tab 的筛选、掌握、删除交互闭环

## 实现顺序建议

1. 新增数据模型与 schema ensure
2. 补后端查询、进度、删除接口
3. 先补后端测试覆盖核心行为
4. 改造 `VocabularyView.vue` 的统一工具栏和词条操作区
5. 验证高频词分页与筛选联动
6. 跑后端测试与前端构建

## 风险与取舍

### 风险 1：高频词自然键规范化

若 `term` 在大小写、首尾空格上处理不一致，可能导致进度记录或 exclusion 匹配偏差。

处理策略：

- 后端统一对 `term` 做 `strip()`
- 与词频表保持一致的大小写策略
- 测试覆盖大小写和精确匹配场景

### 风险 2：无正式迁移体系

运行时 ensure 适合当前项目阶段，但长期会增加启动阶段结构维护复杂度。

当前取舍：

- 本次延续仓库既有方式
- 将 ensure 逻辑集中，避免继续分散

### 风险 3：单文件前端复杂度继续增加

`VocabularyView.vue` 已包含较多逻辑。本次可以先通过局部抽象压住复杂度，但不强制做大重构。

当前取舍：

- 统一三类列表的查询状态与操作函数
- 若实现过程中视图代码明显失控，再考虑抽出词条卡片组件

## 结论

本方案采用“公共词条与用户进度分离建模”的路线：

- `Vocabulary` 与 `BankWordFrequency` 继续承担词条资源
- `user_vocab_progress` 与 `user_bank_word_progress` 承担用户学习状态
- `bank_word_exclusions` 承担管理员删除后的高频词屏蔽语义

这样可以在不破坏现有页面结构的前提下，为三个列表统一补齐按用户记录的掌握状态、筛选和管理员删除能力，并保持接口边界和代码结构处于可维护状态。
