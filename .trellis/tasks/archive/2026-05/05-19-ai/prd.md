# 修正题目 AI 解析与导入解析边界

## Goal

确保正式题目的 `explanation/explanation_zh` 只表示用户主动点击生成的 **AI 解析**，避免导入任务产生的解析内容占用正式题目的解析字段并阻止后续 AI 解析生成。同时提供显式一次性脚本清理历史正式题目解析字段，让旧数据符合新的领域边界。

## Requirements

* 正式题目的 `Question.explanation` 和 `Question.explanation_zh` 只表示用户主动请求生成的 **AI 解析**。
* 未来智能导入创建正式 `Question` 时，不再把 `ImportParsedQuestion.explanation` 写入 `Question.explanation`。
* 导入任务产生的解析内容继续保留在 `ImportParsedQuestion.explanation`，用于导入详情页追溯导入解析结果。
* 导入详情页继续展示导入解析记录，不受本次调整影响。
* 现有前端交互不调整：按钮继续叫“AI 解析”，已有正式题目 AI 解析时再次点击只展示已有结果，不重新生成。
* 提供显式一次性清理脚本，清空所有题库正式题目的 `Question.explanation` 和 `Question.explanation_zh`。
* 清理脚本不得自动挂到 Alembic migration 或应用启动流程中，必须由操作者显式运行。
* 清理脚本必须支持 dry-run 默认模式，输出将清理的题目数量；只有传入 `--apply` 时才真正清空字段。
* 清理脚本只清空正式题目的解析字段，不修改 `ImportParsedQuestion.explanation`。

## Acceptance Criteria

* [ ] 智能导入自动入库或人工接受入库后，新创建的 `Question.explanation` 为空。
* [ ] 导入解析记录中的 `ImportParsedQuestion.explanation` 仍被保存，并可在导入详情或复核相关视图中查看。
* [ ] 用户点击“AI 解析”后，后端仍会把生成结果写入 `Question.explanation/explanation_zh`。
* [ ] 题目已有 `Question.explanation` 或 `Question.explanation_zh` 时，现有 AI 解析接口继续返回缓存结果，不重新调用 AI。
* [ ] 一次性清理脚本默认 dry-run，不修改数据库，并输出待清理题目数量。
* [ ] 一次性清理脚本传入 `--apply` 后清空所有存在解析字段的正式题目。
* [ ] 一次性清理脚本不会修改任何 `ImportParsedQuestion.explanation` 数据。
* [ ] 不新增 Alembic 数据清理 migration，不在部署或启动时自动清理历史解析。

## Definition of Done

* 相关后端逻辑已更新。
* 一次性清理脚本已添加，并具备 dry-run / `--apply` 行为。
* 针对导入入库不再写入正式题目解析、清理脚本 dry-run/apply 行为补充或更新测试。
* 可运行的后端测试通过；如无完整测试环境，说明已执行的替代验证。
* 领域语言已在 `CONTEXT.md` 中同步：正式题目体验中的解析只表示 **AI 解析**。

## Technical Approach

* 调整 `backend/app/services/smart_import_service.py` 中创建正式 `Question` 的逻辑，不再从 `parsed_question.explanation` 赋值给 `Question.explanation`。
* 保留 `ImportParsedQuestion.explanation` 的写入逻辑，确保导入详情仍可追溯导入解析结果。
* 复用现有 `Question.explanation/explanation_zh` 字段作为正式题目的 AI 解析存储，不新增数据库字段。
* 新增后端一次性维护脚本，使用项目现有数据库会话配置，默认只统计，`--apply` 时执行清空并提交。
* 不调整前端组件；当前 `ExplainButton` 已在正式题目解析为空时调用 `/api/ai/explain`，在正式题目解析存在时展示缓存。

## Decision (ADR-lite)

**Context**: 导入任务会生成用于识别题目结构和答案的解析内容，但这类解析质量和目标不同于用户在练习中主动请求的 AI 辅导解析。历史实现把导入解析写入正式题目的解析字段，导致“AI 解析”按钮误以为已有结果而不再生成真正的 AI 解析。

**Decision**: 正式题目的 `explanation/explanation_zh` 只表示 AI 解析；导入解析只保留在导入解析记录中。历史正式题目解析字段通过显式一次性脚本清空，不放入 Alembic migration 自动执行。

**Consequences**: 用户需要重新点击生成 AI 解析；历史正式题目里已有的解析会被清空。好处是字段语义变得一致，后续前端和后端缓存判断不需要新增来源字段或复杂兼容逻辑。

## Out of Scope

* 不新增 AI 解析来源字段、版本字段或解析历史表。
* 不提供“重新生成 AI 解析”入口。
* 不调整前端 UI 文案、布局或空状态。
* 不删除或清空 `ImportParsedQuestion.explanation`。
* 不自动批量重新生成 AI 解析。
* 不把数据清理放进 Alembic migration、应用启动或部署钩子。

## Technical Notes

* `CONTEXT.md` 已收敛领域术语：正式题目体验中的解析只表示 **AI 解析**。
* 当前 AI 解析缓存判断位于 `backend/app/api/routes/ai.py`，当 `has_question_explanation(question)` 为真时返回缓存。
* 当前 AI 解析写入逻辑位于 `backend/app/services/ai_service.py` 的 `explain_question`。
* 当前导入创建正式题目的逻辑位于 `backend/app/services/smart_import_service.py`，其中 `Question(explanation=parsed_question.explanation)` 是需要调整的核心位置。
* 当前前端 `frontend/src/components/ExplainButton.vue` 会在 `initialExplanation` 为空时请求 `/api/ai/explain`，已有解析时直接展示。
