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

## Flask/FastAPI 同名入口兼容

### 1. Scope / Trigger
- Trigger: 后端处于 Flask -> FastAPI 迁移期，同时存在 `backend/app.py` 和 `backend/app/` 包目录。
- 风险：当 `backend/` 被加入 `sys.path` 后，`from app import create_app` 会优先解析到 `backend/app/__init__.py` 包，而不是 `backend/app.py` 文件。

### 2. Signatures
- 旧 Flask 入口必须保持可导入：`from app import create_app`
- 生产 Web 启动链路：`scripts/start-prod.sh` -> `python -m waitress --host "$APP_HOST" --port "$APP_PORT" serve:app` -> `serve.py` -> `from app import create_app`
- Worker 启动链路：`scripts/start-worker.sh` -> `backend/workers/job_worker.py` -> `from app import create_app`

### 3. Contracts
- `backend/app/__init__.py` 必须兼容导出旧 Flask `create_app`。
- 兼容层只负责从父级 `backend/app.py` 加载并导出 `create_app`，不得复制应用工厂代码。
- 兼容层不得写 `from app import create_app`，否则会递归导入当前包。

### 4. Validation & Error Matrix
- `backend/app/__init__.py` 未导出 `create_app` -> systemd Web/Worker 日志出现 `ImportError: cannot import name 'create_app' from 'app' (/.../backend/app/__init__.py)`。
- 兼容层路径错误或 loader 为空 -> 主动抛出 `ImportError('无法加载旧 Flask 应用入口: .../backend/app.py')`。
- 5003 被手动进程占用 -> Web 日志出现 `OSError: [Errno 98] Address already in use`，需先确认并停止陈旧手动进程，再重启 systemd。

### 5. Good/Base/Bad Cases
- Good: `sys.path.insert(0, 'backend'); from app import create_app; app = create_app()` 成功返回 Flask app。
- Base: `systemctl restart quiz-app quiz-app-worker` 后两个服务均为 `active`，`curl http://127.0.0.1:5003/` 返回 200 HTML。
- Bad: 只验证 `python run.py` 或只检查 import 路径，不验证 systemd Web/Worker 重启。

### 6. Tests Required
- Import smoke test:
  ```bash
  python3 - <<'PY'
  import sys
  sys.path.insert(0, 'backend')
  from app import create_app
  app = create_app()
  print(app.name)
  PY
  ```
- Deployment smoke test:
  ```bash
  sudo systemctl restart quiz-app quiz-app-worker
  systemctl is-active quiz-app quiz-app-worker
  curl -sS -o /tmp/quiz-app-root.html -w '%{http_code} %{content_type}\n' http://127.0.0.1:5003/
  ```

### 7. Wrong vs Correct
#### Wrong
```python
# backend/app/__init__.py
from app import create_app
```

#### Correct
```python
# backend/app/__init__.py
from importlib import util
from pathlib import Path

legacy_app_path = Path(__file__).resolve().parent.parent / 'app.py'
spec = util.spec_from_file_location('_legacy_flask_app', legacy_app_path)
legacy_app = util.module_from_spec(spec)
spec.loader.exec_module(legacy_app)
create_app = legacy_app.create_app
```

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
