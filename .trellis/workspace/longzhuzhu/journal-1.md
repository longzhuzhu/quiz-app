# Journal - longzhuzhu (Part 1)

> AI development session journal
> Started: 2026-05-03

---



## Session 1: FastAPI + PostgreSQL MVP Phase 1 基础迁移

**Date**: 2026-05-03
**Task**: FastAPI + PostgreSQL MVP Phase 1 基础迁移
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

实现 FastAPI + PostgreSQL + SQLAlchemy 2.x + Alembic 后端迁移（MVP Phase 1），包括所有核心 API 路由、数据模型、JWT 认证兼容、Pydantic schema 校验。质量检查发现并修复 2 个 Critical bug（vocab 死代码、jobs 参数顺序）、3 个 Major（上传校验、schema 替代 dict、返回类型）和 3 个 Minor。更新后端 spec 文档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `08bd8a7` | (see git log) |
| `97011ba` | (see git log) |
| `03d42fd` | (see git log) |
| `bccca29` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Async batch translate: sync→async job pattern

**Date**: 2026-05-04
**Task**: Async batch translate: sync→async job pattern
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

Convert vocabulary batch translation from synchronous while-loop to async BackgroundJob pattern. POST /jobs creates task, Worker processes in background, frontend polls GET /jobs/active for progress. Progress survives page refresh. Fix SPA catch-all swallowing API 404s. Update code-specs with async job conventions.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `07e4d11` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: Fix quiz translate options + vocab auto-translate

**Date**: 2026-05-04
**Task**: Fix quiz translate options + vocab auto-translate
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

修复答题页面两个问题：1) 翻译按钮不翻译选项（has_question_translation 只检查 content_zh + JSONB flag_modified 缺失）；2) 收藏单词无自动翻译（translate_term 不传 db 导致使用空 .env 配置 + AddVocabButton 无题目上下文）

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `45d0e5b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: 智能导入核心闭环实现

**Date**: 2026-05-04
**Task**: 智能导入核心闭环实现
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

实现 FastAPI + PostgreSQL + LLM 异步智能导入闭环：6 个新模型 + 002 迁移、smart_import_service (抽取/切片/LLM解析/质量评分/自动入库/复核)、Worker job_handlers 扩展、import_jobs + import_review API 路由、前端 3 个新页面 + 异步上传流程。质量检查修复 8 个问题（answer_key_text 持久化、progress_total/heartbeat、JSONB 类型注解、null safety）。Spec 更新覆盖目录结构、JSONB 类型、Worker 模式、轮询、跨层一致性。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `deba9e4` | (see git log) |
| `8c0a96d` | (see git log) |
| `64a88b6` | (see git log) |
| `59b3696` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: 智能导入去重与准确率提升

**Date**: 2026-05-04
**Task**: 智能导入去重与准确率提升
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

实现智能导入题内/跨导入去重签名(_question_signature)、同文件重复导入检测(file_hash+409)、LLM幻视抑制(Prompt规则11/12+无题号降分)、答案参考表优化(移除chunk拼接)、删除题库FK级联修复、LlmParseResult issues字段兼容dict。实测257→275题入库，唯一率94.7%，同文件重导入409拦截，删除题库正常。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `057b9ac` | (see git log) |
| `13b0cc3` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: Bootstrap Guidelines: 填充项目开发规范 spec

**Date**: 2026-05-04
**Task**: Bootstrap Guidelines: 填充项目开发规范 spec
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

扫描项目前后端真实代码模式，填充 13 个 spec 文件（后端 6 个 + 前端 7 个），内容均基于实际代码而非理想状态，包含真实文件路径和行号引用。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `882f1dc` | (see git log) |
| `ed5460f` | (see git log) |
| `9670f82` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 7: smart-import 准确率优化(CIPT 283 PDF) — PR-0~PR-4 全部闭环 + spec 收尾

**Date**: 2026-05-04
**Task**: smart-import 准确率优化(CIPT 283 PDF) — PR-0~PR-4 全部闭环 + spec 收尾
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

完成 smart-import CIPT 283 PDF 准确率优化任务：PR-0 移除 Flask 测试、PR-1 call_ai_api timeout 参数化、PR-2 chunk 失败两级重试+单题降级、PR-3 reparse 卫生(imported_qnos 去重)、PR-4 reconciliation 报告+logger+集成测试；收尾修复 flag_modified→整字段重赋值、补充 import-pipeline/database-guidelines/logging-guidelines spec；31 测试全绿，AC1-AC6 勾选。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `5ab8125` | (see git log) |
| `109c45b` | (see git log) |
| `4c5ca3e` | (see git log) |
| `41af6cf` | (see git log) |
| `5d7014e` | (see git log) |
| `4fba0b7` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 8: Deploy verify smart-import accuracy

**Date**: 2026-05-04
**Task**: Deploy verify smart-import accuracy
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

部署环境验证 PR-0~PR-4 smart-import 改造效果：后端重启+前端重启+新导入 Job 10 验证 282/283 唯一题号入库(99.6%)，chunk 27 重试成功，零重复，reconciliation 六字段齐全，所有验收标准通过

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e358076` | (see git log) |
| `8063656` | (see git log) |
| `4fba0b7` | (see git log) |
| `5d7014e` | (see git log) |
| `41af6cf` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
