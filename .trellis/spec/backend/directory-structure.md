# 目录结构

> 后端 Flask/FastAPI 双套共存，新代码在 `backend/app/` 下按职责分层。

---

## Flask 旧版结构

```
backend/
├── app.py               # 应用工厂 create_app()，行98-120注册蓝图
├── config.py             # class Config + os.environ
├── models.py             # 单文件 291 行，全部模型
├── routes/               # Flask 蓝图
│   ├── auth.py           # auth_bp  -> /api/auth
│   ├── banks.py          # banks_bp -> /api/banks
│   ├── questions.py      # questions_bp -> /api/questions
│   ├── quiz.py           # quiz_bp  -> /api/quiz
│   ├── wrong.py          # wrong_bp -> /api/wrong
│   ├── ai.py             # ai_bp    -> /api/ai
│   ├── jobs.py           # jobs_bp  -> /api/jobs
│   ├── settings.py       # settings_bp -> /api/settings
│   ├── vocab.py          # vocab_bp -> /api/vocab
│   ├── account.py        # account_bp -> /api/account
│   └── admin_users.py    # admin_users_bp -> /api/admin/users
├── services/             # Flask 业务逻辑
│   ├── auth_service.py
│   ├── ai_service.py
│   ├── import_service.py
│   ├── job_service.py
│   └── settings_service.py
└── scripts/              # 独立脚本
    └── import_iapp_glossary.py
```

- `backend/app.py` 行98-120：`from routes.xxx import xxx_bp` + `app.register_blueprint(xxx_bp, url_prefix='/api/xxx')`
- `backend/models.py`：291 行单文件，包含 User、QuestionBank、Question 等 12 个模型
- 蓝图变量命名：`*_bp` 后缀（如 `auth_bp`、`banks_bp`）

---

## FastAPI 新版结构

```
backend/app/
├── main.py               # 应用工厂 create_app()，行37-65注册路由
├── core/
│   ├── config.py         # pydantic-settings BaseSettings + .env
│   ├── database.py       # SQLAlchemy 2.x engine/session/Base
│   ├── security.py       # JWT + 密码哈希（兼容 Werkzeug）
│   └── storage.py        # 本地文件存储
├── api/
│   ├── deps.py           # FastAPI 依赖：get_db, get_current_user, require_admin
│   └── routes/           # 路由按业务实体命名
│       ├── auth.py        # /api/auth
│       ├── account.py     # /api/account
│       ├── admin_users.py # /api/admin/users
│       ├── banks.py       # /api/banks
│       ├── questions.py   # /api/questions
│       ├── quiz.py        # /api/quiz
│       ├── wrong.py       # /api/wrong
│       ├── ai.py          # /api/ai
│       ├── jobs.py         # /api/jobs
│       ├── settings.py    # /api/settings
│       ├── vocab.py       # /api/vocab
│       ├── import_jobs.py     # /api/import-jobs
│       ├── import_review.py   # /api/import-jobs (复核)
│       └── background_jobs.py # /api/background-jobs
├── models/               # 模型按实体拆分，一个文件一个（或几个紧密关联的）实体
│   ├── user.py
│   ├── question_bank.py
│   ├── question.py
│   ├── quiz.py           # QuizSession + QuizAnswer
│   ├── wrong.py
│   ├── vocabulary.py
│   ├── bank_word.py      # BankWordFrequency + BankWordExclusion
│   ├── background_job.py
│   ├── import_job.py
│   ├── import_chunk.py
│   ├── import_parsed_question.py
│   ├── import_review_item.py
│   ├── llm_parse_cache.py
│   ├── vector_index.py
│   └── system_setting.py
├── schemas/              # Pydantic schema 按领域拆分
│   ├── auth.py
│   ├── bank.py
│   ├── question.py
│   ├── quiz.py
│   ├── wrong.py
│   ├── ai.py
│   ├── settings.py
│   ├── vocab.py
│   ├── job.py
│   ├── import_job.py
│   ├── import_review.py
│   └── llm_parse.py
├── services/             # 服务按能力命名
│   ├── ai_service.py
│   ├── import_service.py
│   ├── smart_import_service.py
│   ├── settings_service.py
│   ├── job_service.py
│   └── job_handlers.py
└── workers/
    └── job_worker.py
```

- `backend/app/main.py` 行37-65：`from app.api.routes.xxx import router as xxx_router` + `app.include_router(xxx_router, prefix="/api/xxx")`
- 路由变量命名：统一 `router`（无后缀），导入时用 `as xxx_router` 区分
- 模型按实体拆分：`backend/app/models/user.py` 行11-22 定义 User 类

---

## 文件命名规则

- 路由：按业务实体命名 -- auth, banks, quiz, ai, jobs, vocab, wrong, settings
- 模型：按实体拆分，关系紧密的合并（如 `quiz.py` = QuizSession + QuizAnswer）
- 服务：按能力命名 -- ai_service, import_service, job_service, settings_service
- Schema：按领域命名，与路由一一对应

---

## 蓝图变量命名对比

| 框架 | 变量名 | 导入方式 |
|------|--------|----------|
| Flask | `auth_bp`、`banks_bp` 等 `*_bp` 后缀 | `from routes.auth import auth_bp` |
| FastAPI | 统一 `router`，导入时 `as xxx_router` | `from app.api.routes.auth import router as auth_router` |
