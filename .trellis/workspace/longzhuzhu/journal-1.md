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
