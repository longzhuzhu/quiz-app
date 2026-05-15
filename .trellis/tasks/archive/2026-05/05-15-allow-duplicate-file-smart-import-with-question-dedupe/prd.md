# Allow Duplicate File Smart Import With Question Dedupe

## Goal

支持同一个题库中重复导入相同文件：不再因为文件 hash 已存在而直接报错阻断导入；重复导入时相同题目不能重复写入正式题库，仍需保留可追踪的导入任务、解析记录和跳过原因。

## What I already know

* 当前同一文件再次导入会返回：`{"error":"该文件已导入过","duplicate_of":31,"existing_status":"review_required","hint":"使用 force=true 强制重新导入"}`。
* 用户期望：支持相同文件导入，但相同题目导入时题目不会重复。
* 最近智能导入已经有题目级去重、自动入库、自动跳过和自动处理记录能力。

## Assumptions

* 文件级重复拦截应从“默认阻断”调整为“默认允许新建导入任务”。
* 题目级重复应依赖现有题号/内容签名去重，不写重复 `Question`。
* `force=true` 如已存在，可保留但不再是同文件重导入的必要条件。

## Requirements

* 同一题库重复上传相同文件时，不返回 400 `该文件已导入过` 阻断错误。
* 重复导入流程仍创建新的 `ImportJob` / background job，便于用户查看本次导入结果。
* 重复导入中的相同题目不得重复写入 `questions` 表。
* 被判定为重复的解析题应保留解析记录，并以 skipped/duplicate 状态体现。
* 不破坏不同题库导入、强制导入、人工复核、自动处理、reparse、reconciliation 行为。

## Acceptance Criteria

* [ ] 同一题库再次导入相同文件不会返回“该文件已导入过”。
* [ ] 相同文件重复导入后，正式题目数量不重复增长。
* [ ] 重复题目有可追溯的解析/跳过记录。
* [ ] 现有智能导入自动处理和去重相关测试不回归。
* [ ] break-loop 分析沉淀到 `.trellis/spec/backend/import-pipeline.md` 或相关 spec。

## Definition of Done

* 后端测试覆盖同文件重复导入与题目去重。
* 相关后端测试通过。
* spec 已更新并提交。
* 修复提交完成。

## Out of Scope

* 不做导入任务 UI 的大改版。
* 不删除历史 duplicate import job。
* 不实现“覆盖已有题目”或“批量替换题库”。

## Technical Notes

* 重点定位上传入口中基于 `file_hash` 的重复检查。
* 重点确认 `_save_parsed_question()` 中题号去重、内容签名去重是否覆盖重复文件场景。
