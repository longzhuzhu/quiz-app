# 当前 AI 解析链路与根因调研

## 结论摘要

当前“无法更新”和“新旧格式混杂”不是单一前端问题，而是以下机制叠加：

1. 前端在发现任一中英文解析后直接复用本地数据，不请求后端。
2. 后端只要任一中英文解析非空就返回数据库缓存，没有强制更新参数。
3. 结构化输出只靠自然语言 Prompt，后端兼容逻辑允许缺段、旧两键格式和过短内容通过。
4. Prompt 迁移不会重写题目缓存，历史导入和旧 Prompt 产生的解析会长期保留。
5. 自定义考试项目 AI Profile 当前完整替代平台 Prompt，可继续产生结构分叉。
6. 同步生成与预热任务之间缺少结果新旧保护，可能重复调用并发生后提交覆盖。

## 前端证据

### 使用范围

- 答题页通过 `QuestionCard` 使用 `ExplainButton`：`frontend/src/components/QuestionCard.vue:56-63`、`frontend/src/views/QuizView.vue:110-124`。
- 错题本直接使用 `ExplainButton`：`frontend/src/views/WrongAnswersView.vue:137-153`。
- 模拟考试隐藏解析按钮和内容：`frontend/src/components/QuestionCard.vue:56-58`、`frontend/src/components/QuestionCard.vue:91-96`。

### 当前按钮状态

- 禁用条件为 `loading || displayed`：`frontend/src/components/ExplainButton.vue:3-7`。
- 文案为“AI 解析 / 解析中... / 解析已显示”，没有“更新AI解析”：`frontend/src/components/ExplainButton.vue:9`。
- 组件只绑定普通 `click`，没有长按手势：`frontend/src/components/ExplainButton.vue:3`。
- 点击时只要本地或父组件传入的 `explanation` / `explanation_zh` 任一存在，就直接 emit，不发 API：`frontend/src/components/ExplainButton.vue:31-45`。

### 展示与竞态

- 答题页和错题本都只展示 `explanation_zh` 纯文本，不展示英文，也不解析 Markdown：`frontend/src/components/QuestionCard.vue:90-96`、`frontend/src/views/WrongAnswersView.vue:145-153`。
- 错题本会直接展示题目已有中文解析，因此按钮立即进入已显示状态：`frontend/src/views/WrongAnswersView.vue:137-153`、`frontend/src/views/WrongAnswersView.vue:206-208`。
- 答题结果恢复也可能自动提供并展示解析：`frontend/src/views/QuizView.vue:200-211`、`frontend/src/views/QuizView.vue:312-321`。
- 切题时父组件清空解析状态，但请求没有取消或 generation 校验，旧题慢响应存在污染当前展示的风险：`frontend/src/components/QuestionCard.vue:158-169`。
- 组件读取 `response.data.error`，FastAPI 实际返回 `detail`，具体错误会退化成通用提示：`frontend/src/components/ExplainButton.vue:47`、`backend/app/api/routes/ai.py:161-162`。

## 后端证据

### API 与缓存

- 同步接口为 `POST /api/ai/explain`：`backend/app/api/routes/ai.py:144-162`。
- 请求 schema 只有 `question_id`，没有 `force`、`refresh` 或 `regenerate`：`backend/app/schemas/ai.py:14-16`。
- `has_question_explanation()` 将任一中英文解析非空视为命中：`backend/app/services/ai_service.py:49-50`。
- 缓存命中后路由直接返回并标记 `cached=true`；没有缓存才调用模型：`backend/app/api/routes/ai.py:152-160`。
- `explain_question()` 本身会覆盖中英文解析并提交，因此真正阻断更新的是前后端两层早返回：`backend/app/services/ai_service.py:357-385`。

### 输出结构与质量

- 当前平台 Prompt 要求固定 JSON：`stem_breakdown`、`explanation`、`explanation_zh`、`distractors`，目标版式为题干拆解、知识点解析、干扰项分析：`backend/app/services/exam_service.py:39-87`。
- AI 请求只发送 `model/messages/temperature`，没有 `response_format`、JSON Schema 或 strict tool contract：`backend/app/services/ai_service.py:90-140`。
- `compose_explanation_zh()` 对缺少结构字段、错误类型和旧两键格式进行宽松降级：`backend/app/services/ai_service.py:292-354`。
- 最终仅检查英文或中文正文任一非空，未校验三段完整性、错误选项覆盖、干扰项类型合法性或内容充分程度：`backend/app/services/ai_service.py:373-383`。
- 现有测试明确把旧两键透传和缺段降级视为兼容行为：`backend/tests/test_explanation_prompt_structure.py:117-190`。

### 历史数据与 Profile

- Prompt 迁移只替换符合旧默认值的 `Exam.ai_profile`，不修改 `Question.explanation*`：`backend/alembic/versions/004_structured_explanation_prompt.py:58-84`。
- 历史解析清理脚本默认 dry-run，只有显式 `--apply` 才清理，且未挂入迁移或启动流程：`backend/scripts/clear_question_explanations.py:1-4`、`backend/scripts/clear_question_explanations.py:28-48`。
- 早期智能导入曾将导入解析写入正式 Question；后续虽停止，但历史记录依赖人工清理。
- 当前生成直接使用考试项目 `ai_profile.explanation_system_prompt` 作为 system Prompt：`backend/app/services/ai_service.py:357-369`，自定义旧 Prompt 可继续返回非三段结构。

### 失败与并发

- JSON 解析、空结果等失败发生在字段赋值和 commit 前，正常情况下不会写半成品：`backend/app/services/ai_service.py:373-383`。
- 路由使用 broad `except` 返回 500，数据库异常没有显式 rollback：`backend/app/api/routes/ai.py:158-162`；项目规范要求 DB 写入失败 rollback：`.trellis/spec/backend/error-handling.md:85-99`。
- 同步接口是无锁 check-then-generate；Question 没有解析版本字段。
- 预热 worker 执行前会重新检查缓存，但无法阻止其在 AI 调用期间与同步请求并发：`backend/app/services/job_handlers.py:60-100`。
- 同步生成与预热同时运行时可能调用两次模型，并由最后 commit 的结果覆盖先提交结果。

## 已确认产品边界

- 所有操作使用普通点击。
- 尚未显示解析时，“AI 解析”缓存优先；显示后改为“更新AI解析”并真实调用模型。
- 按钮按展示状态切换，不按点击次数切换。
- 历史缓存保留并按需更新，不批量清理或重生成。
- 只有英文没有中文的记录视为缓存缺失。
- 新生成与主动更新必须严格通过三段式质量校验。
- 平台固定输出契约，考试项目 AI Profile 只补充领域角色、术语和讲解偏好。
- 更新失败保留旧内容；不增加冷却时间或确认弹窗。
- 结构/质量首次不合格时携带具体错误自动纠正重试一次。

## 相关规范

- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/spec/guides/code-reuse-thinking-guide.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/hook-guidelines.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/quality-guidelines.md`
