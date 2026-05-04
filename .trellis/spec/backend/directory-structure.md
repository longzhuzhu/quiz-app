# Directory Structure

> How backend code is organized in this project.

---

## Overview

后端从 Flask + SQLite 迁移到 FastAPI + PostgreSQL。新代码在 `backend/app/` 下按职责分层，旧 Flask 代码保留在 `backend/` 根目录待完全切换后移除。

---

## Directory Layout

```
backend/
├── app/                          # FastAPI 应用（新）
│   ├── main.py                   # 应用工厂 create_app()，路由注册，CORS，SPA fallback
│   ├── core/
│   │   ├── config.py             # pydantic-settings 配置，读取 .env
│   │   ├── database.py           # SQLAlchemy 2.x engine/session/Base
│   │   ├── security.py           # JWT + 密码哈希（兼容 Werkzeug pbkdf2 格式）
│   │   └── storage.py            # 本地文件存储
│   ├── api/
│   │   ├── deps.py               # FastAPI 依赖：get_db, get_current_user, require_admin
│   │   └── routes/
│   │       ├── auth.py           # /api/auth
│   │       ├── account.py        # /api/account
│   │       ├── admin_users.py    # /api/admin/users
│   │       ├── banks.py          # /api/banks
│   │       ├── questions.py      # /api/questions
│   │       ├── quiz.py           # /api/quiz
│   │       ├── wrong.py          # /api/wrong
│   │       ├── ai.py             # /api/ai
│   │       ├── jobs.py           # /api/jobs
│   │       ├── settings.py       # /api/settings
│   │       ├── vocab.py          # /api/vocab
│   │       ├── import_jobs.py    # /api/import-jobs — 导入任务列表/详情/chunks/解析结果
│   │       ├── import_review.py  # /api/import-jobs — 复核 accept/skip/reparse
│   │       └── background_jobs.py # /api/background-jobs
│   ├── models/
│   │   ├── user.py
│   │   ├── question_bank.py
│   │   ├── question.py
│   │   ├── quiz.py               # QuizSession + QuizAnswer
│   │   ├── wrong.py
│   │   ├── vocabulary.py
│   │   ├── bank_word.py
│   │   ├── background_job.py
│   │   ├── import_job.py          # 智能导入任务
│   │   ├── import_chunk.py       # 导入文本切片
│   │   ├── import_parsed_question.py  # LLM 解析结果
│   │   ├── import_review_item.py # 人工复核项
│   │   ├── llm_parse_cache.py    # LLM 响应缓存
│   │   ├── vector_index.py       # 向量索引预留（本阶段不启用 pgvector）
│   │   └── system_setting.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── bank.py
│   │   ├── question.py
│   │   ├── quiz.py
│   │   ├── wrong.py
│   │   ├── ai.py
│   │   ├── settings.py
│   │   ├── vocab.py
│   │   ├── job.py
│   │   ├── import_job.py         # 智能导入任务 Pydantic response schema
│   │   ├── import_review.py      # 复核 Pydantic response schema
│   │   └── llm_parse.py          # LLM 解析 Pydantic schema (ParsedOption, ParsedQuestion, LlmParseResult)
│   ├── services/
│   │   ├── ai_service.py
│   │   ├── import_service.py     # 旧规则解析 + 高频词统计（保留，词频逻辑仍复用）
│   │   ├── smart_import_service.py  # 智能导入核心服务：抽取/切片/LLM解析/质量评分/入库/复核
│   │   ├── settings_service.py
│   │   ├── job_service.py
│   │   ├── job_handlers.py
│   └── workers/
│       └── job_worker.py         # Worker 进程，支持 question_import_llm / reparse
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial.py
│       └── 002_smart_import_tables.py
├── alembic.ini
├── requirements-fastapi.txt       # FastAPI 依赖
├── requirements.txt              # Flask 依赖（旧）
├── run_api.py                    # FastAPI 启动入口
├── run.py                        # Flask 启动入口（旧）
├── app.py                        # Flask 应用工厂（旧）
├── config.py                     # Flask 配置（旧）
├── models.py                     # Flask SQLAlchemy 模型（旧）
├── routes/                       # Flask 蓝图（旧）
└── services/                     # Flask services（旧）
```

---

## Module Organization

- **One model per file**: `models/user.py` 而非 `models.py` 单文件，关系紧密的可合并（如 `quiz.py` 包含 QuizSession + QuizAnswer）
- **One schema module per domain**: `schemas/auth.py` 对应 `routes/auth.py`
- **Routes are thin**: 路由只做参数校验和依赖注入，业务逻辑放在 `services/`
- **Services are database-agnostic**: 通过 `db: Session` 参数接收数据库会话，不自己创建

---

## Naming Conventions

- 文件名：`snake_case`（如 `question_bank.py`）
- 路由前缀：`/api/<domain>`，与 Flask 保持一致
- Pydantic schema 命名：`<Domain><Action>Request` / `<Domain>Response`（如 `BankCreateRequest`）
- SQLAlchemy model：类名 `PascalCase`，表名 `snake_case`

---

## Key Files

- `backend/app/main.py` — 应用入口，注册所有路由
- `backend/app/core/config.py` — 所有配置项（环境变量 + 默认值）
- `backend/app/api/deps.py` — 共享依赖（认证、数据库）
