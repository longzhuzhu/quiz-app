# 全面替换 Flask 为 FastAPI

## Goal

将当前生产 Web 服务、开发入口和后台 Worker 从旧 Flask/WSGI 链路切换到已有 FastAPI/ASGI 链路，最终让应用在端口 5003 上由 FastAPI 提供 `/api/*` 与前端 SPA 静态回退，并停止依赖旧 Flask app factory 作为运行入口。

## What I already know

* 用户要求“全面替换 Flask，替换现在的为 FastAPI”。
* Trellis 后端规范明确项目处于 Flask → FastAPI 迁移期：旧代码在 `backend/` 根目录，新代码在 `backend/app/` 下，新功能统一走 FastAPI。
* `backend/app/main.py` 已存在 FastAPI `create_app()`，并注册了 auth、account、admin_users、banks、questions、quiz、wrong、ai、jobs、settings、vocab、import_jobs、import_review、background_jobs 等路由。
* `backend/app/main.py` 已支持前端 SPA fallback，保持非 `/api/*` 路由返回 `frontend/dist/index.html`。
* 根目录 `run.py` 仍通过 `from app import create_app` 启动旧 Flask debug server。
* 根目录 `serve.py` 仍通过 `from app import create_app` + `werkzeug.serving.run_simple` 暴露旧 Flask app。
* `scripts/start-prod.sh` 当前检查 `flask/dotenv/sqlalchemy`，优先用 `waitress serve:app` 启动 WSGI。
* `scripts/start-worker.sh` 当前检查 `flask/sqlalchemy`，执行旧版 `backend/workers/job_worker.py`。
* 旧版 `backend/workers/job_worker.py` 依赖 Flask app context、`models.db`、`services.job_service`。
* 新版 `backend/app/workers/job_worker.py` 已存在，不依赖 Flask app context，直接使用 `SessionLocal` 与 `app.services.job_service`。
* `backend/run_api.py` 已存在，可用 `uvicorn` 运行 `app.main:create_app`，但它位于 `backend/` 下且开发模式默认 `reload=True`。
* `backend/requirements.txt` 仍是 Flask/Waitress 依赖清单；`backend/requirements-fastapi.txt` 已包含 FastAPI、uvicorn、SQLAlchemy 2.x、psycopg、Alembic、pydantic-settings、python-jose、python-multipart 等依赖，但仍保留 `waitress`。
* `deploy/systemd/quiz-app.service` 与安装脚本均指向 `scripts/start-prod.sh`，环境文件已正确使用 `backend/.env`。
* `deploy/systemd/quiz-app-worker.service` 与安装脚本均指向 `scripts/start-worker.sh`，环境文件已正确使用 `backend/.env`。
* 前端 Vite 开发代理仍指向 `http://127.0.0.1:5003`，因此替换后 FastAPI 需要继续监听 5003 并保持 `/api/*` API 兼容。
* 旧 Flask 入口兼容层在 `backend/app/__init__.py`，当前导出的是从 `backend/app.py` 加载的旧 Flask `create_app`。
* 历史 PRD 记录：用户曾决议“Flask 后续不维护，移除相关用例”，因此本任务不以保护 Flask 测试为目标。

## Assumptions (temporary)

* 本任务不重新设计业务 API；FastAPI 现有路由应作为新的生产真相。
* 端口、API 前缀、JWT header 形式、前端 SPA fallback 和 `backend/.env` 配置源必须保持兼容。
* `backend/requirements.txt` 仍作为部署安装入口时，应替换为 FastAPI 运行所需依赖。
* 旧 Flask 代码、WSGI 入口和 Flask-only 测试/文档引用纳入清理范围；共享的密码哈希、文件解析、AI 等仍被 FastAPI 使用的模块不得误删。

## Open Questions

* 无。

## Requirements (evolving)

* 生产 Web 服务通过 ASGI server（uvicorn）启动 FastAPI app，而不是通过 waitress/Werkzeug 启动 Flask app。
* 开发入口应能直接启动 FastAPI，并继续监听端口 5003。
* 后台 Worker 启动脚本应运行 `backend/app/workers/job_worker.py` 这条 FastAPI/SQLAlchemy 2.x 链路。
* FastAPI app 必须继续提供现有 `/api/*` 路由与前端 SPA fallback。
* systemd 模板与安装脚本继续使用 `backend/.env` 作为环境文件。
* 401/403 语义遵守现有规范：无效/缺失 token 返回 401，权限不足返回 403。
* 数据库连接继续通过 `backend/app/core/config.py` 的 pydantic-settings 绝对路径读取 `backend/.env`。
* 删除旧 Flask app factory、Flask 蓝图路由、Flask-SQLAlchemy 模型、Flask-only worker 和 Flask-only 依赖。
* 清理仍引用 Flask 启动链路的测试、脚本和当前开发指引文档，避免留下误导性入口。
* 同步更新当前文档（README、CLAUDE.md、脚本说明等）为 FastAPI 运行说明；历史归档任务和历史设计文档不作为清理对象。

## Acceptance Criteria (evolving)

* [ ] `python run.py` 或替代后的开发入口启动 FastAPI，而不是 Flask。
* [ ] `scripts/start-prod.sh` 使用 uvicorn 启动 `app.main:create_app`，不再使用 waitress/Werkzeug/Flask app。
* [ ] `scripts/start-worker.sh` 运行 FastAPI worker：`backend/app/workers/job_worker.py`。
* [ ] `systemd` Web/Worker 模板和安装脚本仍指向正确启动脚本与 `backend/.env`。
* [ ] `backend/requirements.txt` 不再包含 Flask、Flask-SQLAlchemy、Flask-JWT-Extended、Flask-CORS、waitress 等旧 Flask/WSGI 依赖。
* [ ] 仓库内生产代码不再包含 `from flask`、`flask_jwt_extended`、`flask_sqlalchemy`、`waitress`、`werkzeug.serving` 等 Flask 运行链路引用；仅允许共享密码兼容代码或历史归档文档中出现 Werkzeug 哈希兼容引用。
* [ ] README、CLAUDE.md 等当前开发指引不再把 Flask/Waitress 描述为运行方式；历史归档文档可保留原始记录。
* [ ] `curl http://127.0.0.1:5003/` 返回前端 HTML（构建产物存在时）。
* [ ] 至少验证一个公开 API（如 login）和一个受保护 API（如 banks/current-user 相关路径）在 FastAPI 下可达。
* [ ] `npm run build` 通过。
* [ ] 后端 FastAPI import smoke test 通过。

## Definition of Done

* Tests or smoke checks added/updated where appropriate.
* 前端构建通过。
* 后端启动、API 可达性、SPA fallback、Worker 启动链路均完成 smoke 验证。
* 部署/回滚风险已记录。
* 如删除 Flask 代码，所有文档、依赖和测试引用同步清理。

## Technical Approach (draft)

采用“彻底替换”路径：先把所有运行入口切到 FastAPI/uvicorn，再删除旧 Flask app factory、蓝图、Flask ORM 模型、旧 worker 和 Flask-only 依赖，最后通过代码搜索、构建、启动 smoke 和 API smoke 验证没有残留运行链路。

## Decision (ADR-lite)

**Context**: 用户要求全面替换 Flask；仓库已有 FastAPI app、FastAPI 路由和 FastAPI worker，但生产/开发入口、依赖和部分旧代码仍指向 Flask/WSGI。

**Decision**: 选择彻底移除 Flask 路径，而不是仅切换运行入口。旧 Flask 代码与依赖纳入本任务清理范围；共享且仍被 FastAPI 使用的模块保留。

**Consequences**: 代码状态更干净，后续不会继续误用旧 Flask 入口；代价是回滚成本更高，必须做更完整的启动、API、Worker 和前端 smoke 验证。

## Out of Scope (temporary)

* 不重新设计已有 API URL 或前端调用协议。
* 不引入 Redis/Celery/MQ。
* 不改变数据库 schema，除非迁移过程中发现 FastAPI 链路缺少必要表或列。
* 不把前端代理端口改到 5003 之外。
* 不删除历史归档任务或历史设计文档中的 Flask 记录，除非它们会影响当前运行或开发指引。

## Implementation Plan (small PRs)

* PR1: 切换运行入口与依赖：`run.py`、`serve.py`、生产/worker 启动脚本、requirements、systemd 模板保持 FastAPI/uvicorn 路径一致。
* PR2: 删除旧 Flask 运行代码：旧 app factory、蓝图、Flask ORM 模型、旧 worker、Flask-only 测试/引用，并保留 FastAPI 仍依赖的共享模块。
* PR3: 更新当前文档与验证：README/CLAUDE.md 改为 FastAPI 说明，执行构建、import smoke、API smoke、worker smoke 和残留引用搜索。

## Validation Results

* `python3 -m pytest backend/tests` → 41 passed, 1 passlib deprecation warning.
* `npm --prefix frontend run build` → passed.
* `python3 -m compileall -q backend/app backend/services run.py serve.py` → passed.
* FastAPI import smoke: `from app import create_app`, `from app.main import create_app` → both return FastAPI app.
* Worker smoke: `bash scripts/start-worker.sh --help` → passed.
* HTTP smoke with uvicorn `serve:app`: `/` returns 200 HTML, `/api/auth/me` without token returns 401, invalid login returns 401.
* `python run.py` smoke: `/` returns 200 HTML.
* `bash scripts/start-prod.sh` smoke: `/` returns 200 HTML.
* Deployment restart: `sudo systemctl restart quiz-app quiz-app-worker` completed; both services active.
* Deployment status: Web runs `/home/ubuntu/github/quiz-app/.venv/bin/python -m uvicorn serve:app --host 0.0.0.0 --port 5003`; Worker runs `/home/ubuntu/github/quiz-app/.venv/bin/python -m app.workers.job_worker`.
* Deployment HTTP smoke: `/` returns `200 text/html`, `/api/auth/me` without token returns `401 application/json`, invalid login returns `401 application/json`.
* Browser smoke: Playwright opened `http://127.0.0.1:5003/`, app redirected to `/login`, page title is `CIPT 备考`, login form and register link rendered; console only reported a browser autocomplete suggestion.
* Regression fix: `GET /api/banks/` initially returned 404 because `redirect_slashes=False`; `backend/app/api/routes/banks.py` now supports both `/api/banks` and `/api/banks/` for list/create.
* Authenticated browser smoke: injected a temporary local JWT, loaded `/`, homepage rendered `题库列表`; network showed `/api/banks`, `/api/wrong/stats`, `/api/quiz/recent-accuracy`, `/api/quiz/history?page=1&per_page=1` all `200 OK`, with zero console errors.
* Deployment logs after restart show uvicorn startup and static assets served; no new Flask/Waitress runtime logs after restart.
* Residual reference grep over current production code/docs/scripts found no Flask/WSGI runtime imports.
* `git diff --check` → passed.

## Technical Notes

* Relevant specs read: `.trellis/spec/backend/index.md`, `directory-structure.md`, `database-guidelines.md`, `error-handling.md`, `quality-guidelines.md`, `logging-guidelines.md`, shared thinking guides.
* Key files inspected: `run.py`, `serve.py`, `backend/app/main.py`, `backend/app/__init__.py`, `backend/run_api.py`, `backend/requirements.txt`, `backend/requirements-fastapi.txt`, `scripts/start-prod.sh`, `scripts/start-worker.sh`, `backend/workers/job_worker.py`, `backend/app/workers/job_worker.py`, `deploy/systemd/*.service`, `scripts/install-systemd-service.sh`, `frontend/vite.config.js`.
* Cross-layer risk: backend route compatibility affects frontend Axios calls and auth logout behavior.
* Deployment risk: uvicorn without reload must be restarted before curl verification; build success alone is insufficient.
* Spec update: `.trellis/spec/backend/error-handling.md` now documents the `HTTPBearer(auto_error=False)` 401 contract.
