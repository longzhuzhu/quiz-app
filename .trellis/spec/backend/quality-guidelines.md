# Quality Guidelines

> Code quality standards for backend development.

---

## Testing Framework

### Design Decision: pytest + FastAPI TestClient

**Context**: 项目从 Flask 迁移到 FastAPI，测试框架需同步迁移。

**Options Considered**:
1. pytest + Flask test client（现状） — 依赖 Flask app.py / flask-jwt-extended / werkzeug，无法测试 FastAPI 路由
2. pytest + httpx.AsyncClient — 异步测试，需要 pytest-asyncio，配置较复杂
3. pytest + FastAPI TestClient（`from fastapi.testclient import TestClient`） — 同步调用异步路由，零额外配置

**Decision**: 选择 **pytest + FastAPI TestClient**。理由：
- `TestClient` 基于 httpx，可同步调用 FastAPI 的 async 路由，无需 pytest-asyncio
- 直接复用 FastAPI 依赖注入体系（`get_db`、`get_current_user`、`require_admin`）
- 与 FastAPI `create_app()` 工厂无缝集成

### 当前状态与迁移路径

| 状态 | 说明 |
|------|------|
| **现状** | 12 个测试文件仍使用 Flask `app.test_client()` + `flask_jwt_extended` + `werkzeug` |
| **目标** | 全部迁移到 FastAPI `TestClient(app)` + `python-jose` JWT + `passlib` |

现有 Flask 测试文件通过 `from app import create_app` 导入的是旧 Flask `backend/app.py`，而非 `app.main.create_app`（FastAPI 版本）。迁移需逐个改写 import 和 fixture。

### 依赖（需添加到 requirements-fastapi.txt）

```
pytest>=7.4.0
httpx>=0.27.0        # TestClient 隐式依赖
```

### 运行方式

```bash
cd backend
python -m pytest tests/ -v
```

### conftest.py（共享 Fixture）

迁移后应创建 `backend/tests/conftest.py` 统一 fixture，消除当前每个文件重复定义的问题：

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import create_app
from app.core.database import Base, get_db
from app.core.security import create_access_token

TEST_DB_URL = "sqlite:///file::memory:?cache=shared"
TEST_JWT_SECRET = "test-jwt-secret-0123456789012345"


@pytest.fixture()
def db_engine(tmp_path, monkeypatch):
    """每个测试独立的 SQLite 引擎"""
    db_file = tmp_path / "quiz_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(db_engine):
    """SQLAlchemy Session，覆盖 FastAPI 的 get_db 依赖"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient，自动注入测试数据库"""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(db_session):
    """已认证用户的 Authorization headers"""
    token = create_access_token({"sub": "1"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(db_session):
    """管理员的 Authorization headers"""
    token = create_access_token({"sub": "1"})  # 需确保 user_id=1 为 admin
    return {"Authorization": f"Bearer {token}"}
```

### 测试文件组织

```
backend/tests/
├── conftest.py                 # 共享 fixture
├── api/                        # API 接口测试
│   ├── test_banks.py
│   ├── test_import_jobs.py
│   ├── test_import_review.py
│   ├── test_vocab.py
│   └── test_quiz.py
├── services/                   # Service 层单元测试
│   ├── test_smart_import_service.py
│   └── test_job_service.py
└── workers/                    # Worker 进程测试
    └── test_job_worker.py
```

### 测试模式

#### API 接口测试

```python
# tests/api/test_banks.py
from app.models import User

def test_create_bank(client, admin_headers, db_session):
    admin = User(username="admin", email="a@t.com", password_hash="x", is_admin=True)
    db_session.add(admin)
    db_session.commit()

    resp = client.post("/api/banks", json={"name": "New Bank"}, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["name"] == "New Bank"


def test_create_bank_unauthorized(client):
    resp = client.post("/api/banks", json={"name": "New Bank"})
    assert resp.status_code == 401
```

#### Service 层单元测试

```python
# tests/services/test_job_service.py
from app.services.job_service import create_or_reuse_job

def test_create_or_reuse_job_returns_existing(db_session):
    job1, result1, _ = create_or_reuse_job(db_session, "professional_vocab_translate", {}, 1)
    job2, result2, _ = create_or_reuse_job(db_session, "professional_vocab_translate", {}, 1)
    assert result1 == "created"
    assert result2 == "existing"
```

#### 依赖注入覆盖

```python
# 覆盖 get_current_user 依赖，注入固定用户
from app.api.deps import get_current_user

def fake_user():
    return User(id=1, username="test", is_admin=False)

app.dependency_overrides[get_current_user] = fake_user
```

### 关键特征

- **依赖注入覆盖**：通过 `app.dependency_overrides[get_db]` 替换数据库，`app.dependency_overrides[get_current_user]` 替换认证
- **同步调用异步路由**：`TestClient` 自动处理 async，无需 `pytest-asyncio`
- **每个测试独立 SQLite**：使用 `tmp_path` + `monkeypatch`，测试间完全隔离
- **JWT 测试**：直接调用 `create_access_token()` 生成 token，不依赖 flask-jwt-extended

### 现有 Flask 测试清单（待迁移）

| 测试文件 | 覆盖范围 | 迁移要点 |
|---------|---------|---------|
| `test_vocab_progress_api.py` | 词汇进度 API | `app.test_client()` → `TestClient(app)` |
| `test_vocab_translation_api.py` | 词汇翻译 API | 同上 |
| `test_bank_delete_api.py` | 题库删除 API | 同上 |
| `test_bank_import_api.py` | 题库导入 API | 同上 |
| `test_background_job_worker.py` | 后台任务 Worker | `app.app_context()` → 直接用 db_session |
| `test_background_jobs_api.py` | 后台任务 API | 同上 |
| `test_question_ai_persistence_api.py` | AI 结果持久化 | `flask_jwt_extended` → `create_access_token` |
| `test_quiz_reanswer_api.py` | 重答 API | 同上 |
| `test_account_password_api.py` | 账号密码 API | `werkzeug` → `passlib` |
| `test_admin_users_api.py` | 管理员用户 API | 同上 |
| `test_settings_ai_api_key.py` | AI API Key 设置 | 同上 |
| `test_ai_service_scene_models.py` | AI 场景模型 | 最简单，无 JWT 依赖 |

### Lint 工具

项目**未配置** lint 工具（无 flake8、pylint、ruff、eslint、prettier 等）。代码格式和风格主要通过代码审查保障。

---

## Required Patterns

### 1. 使用 Pydantic schema 校验请求体

所有 API 路由的请求体必须使用对应的 Pydantic schema，不允许用 `dict`。

```python
# Correct
@router.post("/banks")
def create_bank(data: BankCreateRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ...

# Wrong - 绕过 FastAPI 自动校验
@router.post("/banks")
def create_bank(data: dict, ...):
```

### 2. 文件上传必须校验大小

```python
content = await file.read()
if len(content) > settings.upload_max_size_bytes:
    raise HTTPException(status_code=413, detail="File too large")
```

### 3. 权限检查使用依赖注入

```python
# 普通用户接口
def endpoint(user: User = Depends(get_current_user)):

# 管理员接口
def endpoint(admin: User = Depends(require_admin)):
```

### 4. 数据库会话通过依赖注入

```python
def endpoint(db: Session = Depends(get_db)):
```

不要在路由或 service 中创建自己的数据库会话。

---

## Forbidden Patterns

### 1. 死代码条件

```python
# Wrong - 条件永远为 False
if mastered_value is not None and mastered_value is None:
```

检查条件逻辑时必须确认条件可以达到期望的分支。

### 2. 参数顺序与函数签名不匹配

```python
# Wrong - 位置参数传错
create_or_reuse_job(job_type, payload, admin_id, db)
# 当函数签名是 create_or_reuse_job(db, job_type, payload, created_by)

# Correct
create_or_reuse_job(db, job_type, payload, admin_id)
```

### 3. 返回类型注解与实际返回值不一致

```python
# Wrong - 声明返回 dict | None 但下游要求非 None
def _build_payload(...) -> dict | None:
    if error:
        return None, error_msg
    return payload, None

# Correct - 使用元组明确错误路径
def _build_payload(...) -> tuple[dict, str | None]:
    if error:
        return {}, error_msg
    return payload, None
```

---

## BackgroundJob Async Pattern

长时间运行的操作（如批量翻译、智能导入）必须使用 BackgroundJob 异步模式，不允许同步阻塞。

### 架构

```
Frontend: POST /jobs → 200 OK → poll GET /jobs/active
Backend:  JobService.create_or_reuse_job() → Worker claims → heartbeat → complete/fail
Worker:   job_worker.py (独立进程, cd backend && python3 -m app.workers.job_worker)
```

### 关键约定

1. **防重复提交**: `create_or_reuse_job()` 返回 `result="existing"` 当同 scope 有活跃任务
2. **进度更新**: Worker 通过 `heartbeat_job()` 上报 progress_done / progress_total
3. **Worker 必须从 backend/ 目录启动** (模块路径依赖 `app.*`)
4. **Job scope**: `professional_vocab_translate` (全局) vs `bank_frequent_translate` (需 bank_id) vs `question_import_llm` (需 import_job_id)

```python
# 创建任务
job, result, message = create_or_reuse_job(db, job_type, payload, created_by)

# Worker 心跳更新进度
heartbeat_job(db, job, success_increment=10, status_message="已处理 40/662")

# 前端查询活跃任务
GET /api/jobs/active?job_type=professional_vocab_translate
GET /api/jobs/active?job_type=bank_frequent_translate&bank_id=1
```

### Job Types

| job_type | scope_key | 用途 |
|---------|-----------|------|
| `professional_vocab_translate` | `professional_vocab` | 专业词汇批量翻译 |
| `bank_frequent_translate` | `bank_frequent:{bank_id}` | 题库高频词翻译 |
| `question_import_llm` | `import_llm:{import_job_id}` | 智能导入（LLM 解析 + 自动入库/复核） |
| `question_import_llm_reparse` | `import_llm_reparse:{chunk_id}` | 单 chunk 重新解析 |

### Don't: 同步循环批量操作

```python
# Wrong - 阻塞请求直到完成
while True:
    result = translate_batch()
    if result.remaining <= 0:
        break
```

### Do: 异步后台任务

```python
# Correct - 立即返回，Worker 后台处理
job, result, message = create_or_reuse_job(db, job_type, payload, user_id)
return {"result": result, "job": _job_to_dict(job), "message": message}
```

---

## API Compatibility Checklist

迁移 Flask → FastAPI 时，对每个 API 必须验证：

- [ ] URL 路径完全一致（`/api/auth/login` 而非 `/auth/login`）
- [ ] HTTP 方法一致（GET/POST/PUT/DELETE）
- [ ] 请求参数位置一致（query/body/form/path）
- [ ] 响应 JSON 字段名和结构一致
- [ ] 认证方式一致（Bearer token）
- [ ] 错误状态码一致（特别是 401 vs 403）
- [ ] 文件上传接口使用 `multipart/form-data`

---

## JWT Compatibility

FastAPI JWT 实现必须与 Flask-JWT-Extended 保持兼容：

- 相同 `JWT_SECRET_KEY` 和 `JWT_ALGORITHM`（HS256）
- Token payload 中 `sub` 字段存储字符串形式的用户 ID
- 默认过期时间 7 天（1440 分钟）
- 新旧系统使用同一密钥时，Flask 生成的 token 可在 FastAPI 端验证

### 密码兼容

新系统使用 passlib `pbkdf2_sha256` 格式。旧 Flask 系统使用 Werkzeug 格式 `pbkdf2:sha256:iterations$salt$hex_checksum`。`verify_password()` 必须兼容两种格式：

```python
def verify_password(plain_password: str, hashed_password: str) -> bool:
    # 1. 先尝试 passlib 格式
    # 2. 再尝试 Werkzeug 格式
    # 3. 都不匹配返回 False
```

---

## Common Mistakes

### 条件分支逻辑错误

在质量检查中发现 `vocab.py` 的 `is_mastered` 过滤条件写成 `if mastered_value is not None and mastered_value is None`，导致过滤永远不生效。编写条件时需仔细检查逻辑含义。

### FastAPI redirect_slashes 与 catch-all 路由冲突

FastAPI 默认 `redirect_slashes=True`，会将 `/api/banks/` 重定向到 `/api/banks`。但 `/{full_path:path}` catch-all SPA fallback 会吞掉未匹配的 API 请求并返回 200 + HTML 而非 404。

```python
# Wrong - API 404 请求返回 HTML
@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    # /api/nonexistent 走到这里，返回 index.html (200)

# Correct - 排除 /api 前缀
app = FastAPI(redirect_slashes=False)

@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404)
```

### 路由尾部斜杠

FastAPI 路由装饰器用 `""` 而非 `"/"` 注册根路径，避免 redirect_slashes 导致双重重定向：

```python
# Preferred
@router.get("")
def list_banks(...):

# Avoid (causes 307 redirect when redirect_slashes is on)
@router.get("/")
def list_banks(...):
```

### Don't: Service 层返回 `{"error": "..."}` dict 让路由猜测状态码

```python
# Wrong - 路由需要做字符串匹配来决定 HTTP 状态码
def accept_review_item(...):
    return {"error": "复核项不存在"}

# Route layer:
if "不存在" in result.get("error", ""):
    raise HTTPException(status_code=404, ...)
```

### Do: Service 层抛出业务异常或返回明确的状态标识

```python
# Correct - service 返回结果或抛异常
def accept_review_item(...):
    item = db.get(ImportReviewItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="复核项不存在")
    ...
```

### Worker 进程中单 chunk 失败不得导致整个 Worker 崩溃

```python
# Wrong - 未捕获异常会中断所有后续 chunk
for chunk in chunks:
    _process_chunk(db, chunk, ...)

# Correct - 每个chunk独立try-except，失败记录但继续
for chunk in chunks:
    try:
        _process_chunk(db, chunk, ...)
    except Exception as exc:
        logger.error("Chunk %d 解析失败: %s", chunk.chunk_no, exc)
        chunk.status = "failed"
        chunk.issues_json = {"error": str(exc)}
        import_job.failed_chunks = (import_job.failed_chunks or 0) + 1
        db.commit()
```

### BackgroundJob progress_total 必须在已知总量时立即设置

```python
# Wrong - progress_total 初始化为 0，前端显示 0/0 进度条
bg_job.progress_total = 0

# Correct - 创建 chunk 后立即更新
bg_job.progress_total = len(chunks)
db.commit()
```

### heartbeat_job 必须传递 success_increment

```python
# Wrong - 缺少 success_increment 导致 progress_done 永远不增长
heartbeat_job(db, job)

# Correct
heartbeat_job(db, job, success_increment=1)
```

### 新增迁移后必须验证 `alembic upgrade head` 实际执行成功

```python
# Wrong - 只验证 app 能 import，不验证迁移已执行
# implement/check agent 报告 "Verification: Passed" 但数据库表不存在

# Correct - 验证清单必须包含：
# 1. cd backend && alembic upgrade head   ← 迁移实际执行
# 2. cd backend && alembic downgrade -1   ← 回滚验证
# 3. 对新表做一次实际查询确认表存在
# 4. 关键 API 端点端到端调用（至少 curl）
```

> **教训**: 子代理验证 `from app.main import create_app` 成功只说明代码能加载，不代表数据库 schema 与代码一致。新增 Alembic 迁移时，**迁移执行是验收的必要步骤**，不是可选步骤。
