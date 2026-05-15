# Auto Handle Import Questions

## Goal

降低智能导入后的人工复核负担：程序自动处理常规导入结果，可入库题目直接入库，不可用题目自动跳过并保留可追溯记录。用户可以在导入任务详情页查看只读的自动处理记录，而不是被迫逐条接纳或跳过。

## What I already know

* 用户确认：不可用题目包括缺题干、选项不足、缺少正确答案、正确答案不在选项中。
* 用户确认：不可用题目自动跳过，但保留导入解析记录，不写入正式 `questions` 表。
* 用户确认：结构完整题目自动入库，包括低置信度、无题号、疑似噪声、疑似缺场景等质量提示场景。
* 用户确认：保留“复核待审核题目”作为兜底，但常规导入应尽量显示 0 待复核。
* 用户确认：在导入任务详情页，与“复核待审核题目”同层级增加“自动处理记录 (数量)”入口。
* 用户确认：自动处理记录页只读，不提供撤回、删除、重新复核。
* 用户确认：记录以单条列表展示，显示自动入库/自动跳过、中文原因、题号、题干摘要、时间。
* 用户确认：入口一直显示，并展示自动处理记录数量；没有记录时显示空状态。
* 用户确认：全部自动跳过时导入任务状态显示“未入库”。
* `CONTEXT.md` 已定义可入库题目、不可用题目、自动入库、自动跳过、自动处理记录。
* `docs/adr/0001-auto-handle-imported-questions.md` 已记录默认自动处理导入题目的决策。

## Assumptions

* 自动处理记录可以优先复用 `import_parsed_questions`，通过 `review_status` / `import_status` / `issues_json` 表示处理结果和原因，避免新增表。
* 现有 `ImportReviewItem` 继续只表示人工复核项，不用于自动处理记录。
* 自动处理记录的“时间”可使用解析记录的 `updated_at` 或 `created_at`；若自动入库/自动跳过在保存时立即发生，两者足以表达处理时间。

## Requirements

* 导入解析后，可入库题目自动写入正式题库。
* 导入解析后，不可用题目自动跳过，保留解析记录，不创建待复核项，不写入正式题库。
* 结构完整但存在低置信度、无题号、疑似噪声、疑似缺场景等质量提示的题目仍自动入库，并在记录中展示质量提示。
* 人工复核入口保留，仅用于无法安全自动归类的兜底场景。
* 导入任务详情页显示“自动处理记录 (数量)”入口，与“复核待审核题目”同层级。
* 自动处理记录页为只读列表，展示处理结果、中文原因、题号、题干摘要、处理时间。
* 全部题目自动跳过且无入库题时，导入任务状态显示“未入库”。
* 导入任务摘要应能体现自动入库数、自动跳过数、待复核数。

## Acceptance Criteria

* [ ] 缺题干的解析题保存为自动跳过记录，不进入 `questions`，不增加 `review_questions`。
* [ ] 选项不足的解析题保存为自动跳过记录，不进入 `questions`，不增加 `review_questions`。
* [ ] 缺少正确答案的解析题保存为自动跳过记录，不进入 `questions`，不增加 `review_questions`。
* [ ] 正确答案不在选项中的解析题保存为自动跳过记录，不进入 `questions`，不增加 `review_questions`。
* [ ] 低置信度但结构完整的解析题自动入库，并能在自动处理记录中看到质量提示。
* [ ] 导入任务详情页始终显示“自动处理记录 (N)”入口。
* [ ] 自动处理记录页为空时显示空状态。
* [ ] 自动处理记录页逐条显示自动入库/自动跳过、中文原因、题号、题干摘要、时间。
* [ ] 当导入任务全部解析题都自动跳过且无入库题时，任务状态显示“未入库”。
* [ ] 现有人工复核接受、跳过、重解析路径不回归。

## Definition of Done

* 后端自动处理规则有测试覆盖。
* 后端 API 能返回自动处理记录及数量。
* 前端入口和只读记录页面可用。
* 前端生产构建通过。
* 行为变更已在 `CONTEXT.md` 和 ADR 中记录。

## Out of Scope

* 自动处理记录页不提供撤回、删除、重新复核。
* 自动处理记录页首版不做筛选、搜索、排序配置。
* 不做批量编辑、批量恢复、导出自动处理记录。
* 不改变正式题库题目编辑页的能力。
* 不删除现有人工复核功能。

## Technical Approach

* 后端在 `smart_import_service._save_parsed_question` 中将自动处理决策从“置信度阈值”改为“可入库题目 vs 不可用题目”。
* 使用明确的 `review_status` / `import_status` 区分 `auto_imported` / `auto_skipped`，并在 `issues_json` 中保留机器码与详情。
* 在 `smart_import_service._finalize_import` 中增加“未入库”状态判断，并在序列化结果中返回自动处理计数。
* 在 `import_jobs` API 中增加自动处理记录查询端点，或扩展现有 parsed-questions 查询以支持自动处理过滤；优先选择清晰端点，减少前端推断。
* 前端新增自动处理记录路由与只读页面，并在 `ImportJobDetailView.vue` 操作区添加入口。

## Decision (ADR-lite)

**Context**: 现有导入流程把大量低置信度或缺字段题目推给人工复核，但用户实际只能接纳或跳过，造成额外操作负担。  
**Decision**: 默认自动处理：可入库题目自动入库，不可用题目自动跳过并保留记录，复核仅保留为兜底。  
**Consequences**: 导入更顺畅，人工队列显著减少；需要新增只读追溯入口，并清晰展示自动处理原因，避免用户感觉系统“悄悄丢题”。

## Technical Notes

* `backend/app/services/smart_import_service.py` 原先通过 `_quality_check` + 置信度阈值决定自动入库或创建 `ImportReviewItem`，本任务改为可用性优先的自动入库/自动跳过。
* 当前高风险问题包括 `ANSWER_MISSING`、`ANSWER_NOT_IN_OPTIONS`、`OPTION_COUNT_ABNORMAL`、`SCENARIO_MISSING`。
* `ImportJob` 当前有 `parsed_questions`、`imported_questions`、`review_questions`、`failed_chunks`，没有自动跳过计数字段。
* `serialize_import_job` 当前返回导入任务摘要与 reconciliation，可扩展返回自动处理计数。
* `frontend/src/views/ImportJobDetailView.vue` 当前仅在 `job.review_questions > 0` 时显示“复核待审核题目”。
* `frontend/src/router/index.js` 当前已有 `/import-jobs/:jobId/review`，可新增 `/import-jobs/:jobId/auto-handled`。

## Open Questions

* 无。MVP 已确认：自动处理记录页首版只做列表，不做筛选和搜索。
