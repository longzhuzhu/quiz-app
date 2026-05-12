# 修复智能导入场景题题干不完整

## Goal

修复智能导入中场景题、长题干题目只导入最后一问而丢失背景材料的问题，确保正式题库中的 `Question.content` 是完整可答题文本，并为已导入但可安全关联的历史题目提供回填修复路径。

## What I already know

* 用户反馈 CIPT 283 题库中存在多处题干不完整，例如 `CIPT 283.pdf` 第 162 页 `question#247` 最终只剩 `Which is the best next step the organization should take?`。
* 很多以 `SCENARIO` 开头的大段阅读材料题，也出现只提取最后一段/最后一问的问题。
* 已确认产品决策：正式 `Question.content` 应包含完整题干，即 `scenario/背景材料 + 最后一问`；`scenario_text` 只保留为导入复核和审计字段，不新增正式 `Question.scenario` 字段。
* 已确认修复范围包含两步：先修未来导入/重新解析链路，再修已导入的不完整题目。
* `backend/app/services/smart_import_service.py` 的 LLM prompt 当前要求场景背景放入 `scenario` 字段。
* `_save_parsed_question()` 会把 `ParsedQuestion.scenario` 保存到 `ImportParsedQuestion.scenario_text`。
* `_write_question_to_bank()` 当前只把 `parsed_question.content` 写入正式 `Question.content`，没有合并 `scenario_text`。
* `backend/app/models/question.py` 的 `Question` 模型没有 `scenario` 字段。

## Requirements

* 新导入的场景题进入正式题库时，`Question.content` 必须包含完整可答题文本：场景/背景材料在前，最后一问在后。
* 完整题干使用自然拼接格式：`scenario_text\n\ncontent`；如果原文 scenario 已包含 `SCENARIO` 标记则保留，不额外添加中文/英文标题。
* 重新解析并接受/自动入库的场景题也必须使用相同的完整题干合成规则。
* `ImportParsedQuestion.scenario_text` 继续保留，作为导入复核、审计和历史回填依据。
* 已导入题目的修复必须只处理可明确关联且风险较低的记录：优先基于 `ImportParsedQuestion.imported_question_id` 找到正式 `Question`，且 `scenario_text` 非空。
* 历史回填通过一次性管理脚本触发，支持先 dry-run 输出将修改的题目，再显式 apply 执行，保证可审计。
* 回填脚本不需要自动生成备份文件；回滚依赖 dry-run 输出、数据库备份或运行日志。
* 历史回填必须避免误改人工编辑过的题目，至少应限制在“正式题目的当前 content 与 parsed question 的 content 等价/匹配”的记录上。
* 修复需要覆盖 `SCENARIO` 大段背景 + 最后一问的题型。
* 本任务包含 PDF 跨页/版面提取改进，重点解决页首第一题、跨页场景材料、题号前导阅读材料被丢弃等导致题干不完整的问题。
* PDF 题号前导材料采用保守自动归属策略：只把看起来像场景/阅读材料的前导文本归到后面的第一题，例如包含 `SCENARIO`、长段落、没有选项/答案标记；优先降低误拼页眉、上一题解析或广告的风险。
* 轻量强化 LLM prompt/质量检查：明确 `scenario` 与 `content` 最终会合并为正式题干，并防止场景题背景遗漏后仍高置信入库。
* 修复不应新增正式题目表的 `scenario` 字段。

## Open Questions

* 无。

## Acceptance Criteria

* [ ] 当 LLM 输出 `scenario` 和 `content` 时，自动入库后的 `Question.content` 按 `scenario_text\n\ncontent` 格式同时包含两者。
* [ ] 当人工复核接受含 `scenario_text` 的解析题时，写入的正式题目也包含完整题干。
* [ ] 重新解析路径不会再次生成只含最后一问的正式题目。
* [ ] LLM prompt/质量检查经过轻量强化，能降低场景题背景遗漏后仍高置信入库的风险。
* [ ] PDF 跨页/页首第一题场景下，符合保守归属条件的题号前导阅读材料不会被切片逻辑丢弃。
* [ ] 前导材料归属不会明显吞入页眉、广告、上一题解析或答案段落。
* [ ] 已导入历史题目可通过一次性管理脚本在安全条件下回填为完整题干。
* [ ] 历史回填脚本支持 dry-run 预览和显式 apply 执行。
* [ ] 历史回填脚本不要求自动生成备份文件。
* [ ] 历史回填不会修改无法明确关联、`scenario_text` 为空、或疑似已被人工编辑的题目。
* [ ] 增加或更新后端测试覆盖场景题合并与历史回填保护条件。

## Definition of Done

* Tests added/updated for import write path, review accept/reparse path where appropriate, and historical backfill safety.
* Existing relevant backend tests pass.
* No database schema migration for `Question.scenario` is introduced.
* Rollback path considered for historical backfill.

## Technical Approach

* Introduce a single canonical helper to build full question content from `scenario_text` and `content`, avoiding auto-import、review accept、reparse、history backfill 多处规则漂移。
* Improve PDF chunking/extraction around page boundaries and leading text before the first question marker, so scenario/read-passage material is not discarded before LLM parsing.
* Use the canonical full content for duplicate signatures and `Question.content` writes where the final stored formal question is produced.
* Preserve raw parsed `content` and `scenario_text` in `ImportParsedQuestion` for review/audit, unless implementation proves canonicalization is safer earlier in the pipeline.
* For history repair, add a one-time management script with dry-run as the default mode and explicit apply for writes.
* For history repair, operate only on records with `ImportParsedQuestion.imported_question_id` pointing to an existing `Question` and `scenario_text` present; update only when existing `Question.content` still matches the parsed short `content`.

## Decision (ADR-lite)

**Context**: LLM 解析 schema 支持 `scenario`，但正式题目表只有 `content`。当前流程把背景材料保存在导入审计表，正式入库时丢掉，导致答题页只显示最后一问。

**Decision**: 不新增正式 `Question.scenario` 字段；正式题库使用合成后的完整 `Question.content`，`scenario_text` 仅作为导入复核和审计字段。

**Consequences**: 现有答题页、错题本、翻译、复制题目等读取 `Question.content` 的功能可直接获得完整题干；代价是 `content` 中会包含场景材料和最后一问的组合文本，未来如果要结构化展示场景，需要再设计正式字段或展示模型。

## Out of Scope

* 不新增 `questions.scenario` 或类似正式表字段。
* 不新增 OCR 能力，不处理扫描版 PDF 图片识别。
* 不保证修复所有无法关联到导入记录的历史题目。
* 不对疑似人工编辑过的题目做自动覆盖。

## Technical Notes

* 主要代码位置：`backend/app/services/smart_import_service.py`。
* 正式题目模型：`backend/app/models/question.py`。
* 相关 schema：`backend/app/schemas/llm_parse.py`。
* 相关流程：`run_smart_import()` → `_split_into_chunks()` → `_process_chunk()` → `_save_parsed_question()` → `_write_question_to_bank()`。
* 复核接受流程：`accept_review_item()` 最终调用 `_write_question_to_bank()`。
* 当前质量评分 `_quality_check()` 只看 `parsed_q.content` 与 options，后续实现时需要评估是否应使用合成后的完整题干参与质量/去重判断。
