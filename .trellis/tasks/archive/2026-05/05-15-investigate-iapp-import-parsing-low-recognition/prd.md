# Investigate iapp Import Parsing Low Recognition

## Goal

深入分析并解决近期以 `iapp-certified-information-privacy-technologist` 开头的导入文件题目解析识别率低的问题：文档中约 7、8 道题，目前只解析到 1 道，需要找出根因、修复并防止同类问题复发。

## What I already know

* 问题集中在近期几个导入任务。
* 文件名以 `iapp-certified-information-privacy-technologist` 开头。
* 单个文档中有约 7、8 道题，但智能导入只解析到 1 道。
* 需要按 break-loop 思路做根因分类、失败原因、预防机制、系统性扩展和知识沉淀。

## Assumptions

* 低识别率可能发生在文本抽取、题目切分、LLM chunk 输入、LLM 输出解析、或保存/过滤阶段之一。
* 最近新增自动处理导入题目逻辑后，部分解析题可能被自动跳过，但“只解析到一道”更可能指 parsed question 数量偏低，需要用导入任务记录验证。

## Open Questions

* 无阻塞问题；先从仓库数据、导入任务记录和解析流水线代码中定位。

## Requirements

* 定位相关 `iapp-certified-information-privacy-technologist*` 文件或导入任务记录。
* 判定低识别率发生在哪一层：文本抽取、chunk 切分、LLM 返回、JSON 解析、质量过滤/保存、或前端展示。
* 复现至少一个“7、8 道题只解析 1 道”的样本路径。
* 修复导致识别率低的根因，不牺牲既有场景题、噪声过滤、重解析和自动处理行为。
* 输出 break-loop 分析，并把可复用的防复发规则写入相关 `.trellis/spec/` 文档。

## Acceptance Criteria

* [ ] 能解释低识别率的具体根因与触发条件。
* [ ] 以 `iapp-certified-information-privacy-technologist` 开头的样本不再只解析 1 道。
* [ ] 新增或更新测试覆盖该样本形态。
* [ ] 现有智能导入、场景题保留、自动处理记录相关测试不回归。
* [ ] `.trellis/spec/` 记录本次防复发知识。

## Definition of Done

* 后端测试通过。
* 如涉及前端展示，前端构建通过。
* break-loop 分析完成并沉淀到 spec。
* 修复提交完成。

## Out of Scope

* 不重新设计整套智能导入架构。
* 不引入新的 OCR/LLM 供应商。
* 不做批量人工修复历史导入结果，除非根因要求。

## Technical Notes

* 重点检查 `backend/app/services/smart_import_service.py`、导入任务 API、历史 `storage/` 或数据库中相关文件/任务。
* 需要区分 parsed question 数量低与自动跳过数量高这两类问题。
