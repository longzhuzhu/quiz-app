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


## Session 9: 移除硬编码数据库凭据

**Date**: 2026-05-04
**Task**: 移除硬编码数据库凭据
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

将 config.py 和 db_diag.py 中的明文 PostgreSQL 密码替换为占位符/环境变量，.env 提供真实值

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `683c180` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 10: Replace Flask runtime with FastAPI

**Date**: 2026-05-08
**Task**: Replace Flask runtime with FastAPI
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

Replaced the deployed Flask runtime with FastAPI/uvicorn, updated docs, fixed add-vocabulary default input behavior, and fixed unfinished quiz resume progress with deployment verification.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `9211785` | (see git log) |
| `8aa2632` | (see git log) |
| `284d53e` | (see git log) |
| `6687e95` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 11: Fix smart import scenario stems

**Date**: 2026-05-12
**Task**: Fix smart import scenario stems
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

Preserved scenario/reading material in smart import question content, added conservative leading-text attribution, scenario quality checks, and a dry-run backfill script.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `fa2620c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 12: Auto Handle Import Questions

**Date**: 2026-05-15
**Task**: Auto Handle Import Questions
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

Implemented automatic smart-import handling: structurally usable parsed questions are imported, unusable parsed questions are auto-skipped with traceable records, the import job API exposes auto-handled counts and records, and the frontend adds the auto-handled records entry/page.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f2ecec5` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 13: Fix IAPP Import Recognition

**Date**: 2026-05-15
**Task**: Fix IAPP Import Recognition
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

Investigated low recognition for iapp-certified-information-privacy-technologist imports, identified valid-but-incomplete L1 LLM responses and bad cache hits as the root cause, added completeness-triggered L2 fallback with cache bypass, covered the regression with backend tests, updated the smart import pipeline spec, rebuilt production frontend, restarted quiz-app services, and verified the deployed frontend loads.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `322b3a1` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 14: Allow duplicate smart imports with question dedupe

**Date**: 2026-05-15
**Task**: Allow duplicate smart imports with question dedupe
**Branch**: `codex/vocab-progress-settings-deploy`

### Summary

Allowed repeated uploads of the same smart-import file without file-hash blocking, preserved per-question duplicate skipped records, fixed answer-key parsing so inline Answer blocks no longer truncate later questions, updated import status summary for all-duplicate reruns, and redeployed/verified web and worker services.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `571ab5a` | (see git log) |
| `96ec6e7` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
