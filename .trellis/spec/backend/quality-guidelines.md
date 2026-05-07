# 代码质量

> Flask 版无类型注解、依赖 Flask 上下文；FastAPI 版完整类型注解、通过 Depends 注入。两套风格共存。

---

## 类型注解对比

### Flask 版：无类型注解，依赖 Flask 上下文

```python
# backend/routes/auth.py 行10-17
@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()          # request 是 Flask 全局上下文
    try:
        user = register_user(data['username'], data['email'], data['password'])
        return jsonify({'message': '注册成功', 'user': user_to_dict(user)}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
```

- 函数签名无类型注解
- `request`、`get_jwt_identity()` 来自 Flask 全局上下文，非参数传入
- import 用相对路径：`from models import db, User`

### FastAPI 版：完整类型注解，通过 Depends 注入

```python
# backend/app/api/deps.py 行14-57
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    ...
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="...")
    ...
    user = db.get(User, user_id)
    return user
```

- 函数签名带 type hints + Depends
- `db`、`credentials` 通过参数传入，不依赖全局状态
- import 用绝对路径：`from app.models.user import User`

---

## 返回格式

项目无统一 envelope，直接返回 dict/列表：

- 成功：返回业务数据 dict 或列表
- 错误：`{'error': '...'}`（Flask）或 `HTTPException(detail='...')`（FastAPI）
- 操作确认：`{'message': '...'}`

```python
# 成功 - 业务数据
return jsonify([bank_to_dict(b) for b in banks])

# 成功 - 操作确认
return jsonify({'message': '题库已删除'})

# 错误 - Flask
return jsonify({'error': '需要管理员权限'}), 403

# 错误 - FastAPI
raise HTTPException(status_code=403, detail="需要管理员权限")
```

---

## 服务层风格对比

### Flask 版：用全局 `db.session`

```python
# backend/routes/banks.py 行102-111
user = db.session.get(User, int(get_jwt_identity()))
db.session.add(bank)
db.session.commit()
```

Service 函数也直接用全局 `db.session`，不需要传参。

### FastAPI 版：显式接收 `db: Session`

```python
# backend/app/services/job_service.py 行66
def list_bank_frequent_terms(db: Session, bank_id: int) -> list:
    excluded_terms = {row.term for row in db.query(BankWordExclusion).filter_by(bank_id=bank_id).all()}
    ...
```

所有 service 函数的第一个参数是 `db: Session`，不自己创建数据库会话。

---

## 序列化：手工 `*_to_dict()`

项目不使用 Pydantic `from_attributes` 自动转换。主流做法是手工编写序列化函数：

```python
# Flask 版 - backend/routes/banks.py 行81-89
def bank_to_dict(bank):
    return {
        'id': bank.id,
        'name': bank.name,
        'created_at': bank.created_at.isoformat(),
    }

# FastAPI 版 - backend/app/services/smart_import_service.py 行1418-1451
def serialize_import_job(import_job: ImportJob) -> dict:
    return {
        "id": import_job.id,
        "created_at": import_job.created_at.isoformat() if import_job.created_at else None,
        ...
    }
```

日期统一用 `.isoformat()`。部分 FastAPI endpoint 使用 `response_model`，但不是主流。

---

## 配置方式对比

### Flask 版：class Config + os.environ

```python
# backend/config.py
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(basedir, "quiz.db")}')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    AI_API_KEY = os.environ.get('AI_API_KEY', '')
```

运行时通过 `_apply_runtime_env_overrides()` 再次覆盖（`backend/app.py` 行19-43）。

### FastAPI 版：pydantic-settings BaseSettings + .env

```python
# backend/app/core/config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    DATABASE_URL: str = "postgresql+psycopg://quiz:..."
    JWT_SECRET_KEY: str = "jwt-secret-key-change-in-production"
    AI_API_KEY: str = ""
```

- 自动读取 `.env` 文件（注意 env_file 必须用绝对路径）
- 类型自动校验（如 `MAX_UPLOAD_SIZE_MB: int`）
- 计算属性：`upload_max_size_bytes` 属性方法

### 部署环境文件必须对齐 backend/.env

#### 1. Scope / Trigger
- Trigger: Flask 旧服务、FastAPI 新服务与 systemd Web/Worker 共存，生产数据源和密钥由 `backend/.env` 提供。
- 风险：systemd 或 Flask 只读取仓库根 `.env` 时，如果该文件不存在，会回退到 Flask 默认 SQLite `backend/quiz.db`，导致题库数量缺失、JWT/AI 配置错配或页面提示接口失败。

#### 2. Signatures
- Flask 配置入口：`backend/config.py` 必须在定义 `Config` 前执行 `load_dotenv(os.path.join(basedir, '.env'))`。
- systemd Web：`deploy/systemd/quiz-app.service` 使用 `EnvironmentFile=-/home/ubuntu/github/quiz-app/backend/.env`。
- systemd Worker：`deploy/systemd/quiz-app-worker.service` 使用 `EnvironmentFile=-/home/ubuntu/github/quiz-app/backend/.env`。
- 安装脚本：`scripts/install-systemd-service.sh` 生成的两个 unit 必须使用 `EnvironmentFile=-${ROOT_DIR}/backend/.env`。

#### 3. Contracts
- `backend/.env` 是生产共享配置源，至少提供 `DATABASE_URL`、`JWT_SECRET_KEY`、`SECRET_KEY` 和 AI 相关键。
- Flask 和 FastAPI 必须解析到同一 `DATABASE_URL`，不得一个连接 PostgreSQL、另一个回退 SQLite。
- 不要求仓库根 `.env` 存在；不能把根 `.env` 当作生产必需文件。

#### 4. Validation & Error Matrix
- `systemctl show quiz-app -p EnvironmentFiles` 显示根 `.env` -> unit 模板或安装脚本未更新，重装后会回归。
- Flask smoke test 的 `SQLALCHEMY_DATABASE_URI` 为 `sqlite:///.../backend/quiz.db` -> 未加载 `backend/.env`，生产数据源错误。
- 首页提示“获取题库失败”或题库数量少于 PostgreSQL -> 优先检查 Flask/systemd 是否读取了错误 env 文件。
- Web/Worker JWT 不一致 -> 页面可能保留 token 但接口返回 401。

#### 5. Good/Base/Bad Cases
- Good: `from app import create_app; app.config['SQLALCHEMY_DATABASE_URI']` 脱敏后与 `app.core.config.settings.DATABASE_URL` 指向同一 PostgreSQL。
- Base: `systemctl restart quiz-app quiz-app-worker` 后两个服务均 `active`，`EnvironmentFiles` 均为 `backend/.env`。
- Bad: 只修改 `serve.py` 或只修改已安装的 `/etc/systemd/system/*.service`，但没有更新仓库内 `deploy/systemd/*.service` 和 `scripts/install-systemd-service.sh`。

#### 6. Tests Required
- Flask config smoke test：插入 `backend/` 到 `sys.path` 后导入 `create_app()`，断言脱敏后的 DB scheme 不是 `sqlite`。
- Data smoke test：在 app context 中查询 `QuestionBank.query.count()`，与预期生产库数量一致。
- Deployment smoke test：`sudo systemctl restart quiz-app quiz-app-worker`，再断言 `systemctl show ... -p EnvironmentFiles` 指向 `backend/.env`。
- API smoke test：使用有效 JWT 请求 `/api/banks/`，断言 HTTP 200 且返回题库数量正确。

#### 7. Wrong vs Correct

##### Wrong
```ini
EnvironmentFile=-/home/ubuntu/github/quiz-app/.env
```

```python
# serve.py 只加载根 .env，backend/.env 不参与 Flask 配置
load_dotenv(os.path.join(ROOT_DIR, '.env'))
```

##### Correct
```ini
EnvironmentFile=-/home/ubuntu/github/quiz-app/backend/.env
```

```python
# backend/config.py
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))
```

---

## FastAPI 路由注册顺序

> **Warning**: 静态路径必须定义在动态参数路径之前，否则 FastAPI 会把静态字符串匹配为参数值。

```python
# 正确：静态路由在前
@router.get("/recent-accuracy")
def recent_accuracy(): ...

@router.get("/session/{session_id}")
def session_detail(session_id: int): ...

# 错误：动态路由在前会吞掉 /recent-accuracy（当作 session_id="recent-accuracy"）
@router.get("/session/{session_id}")
def session_detail(session_id: int): ...

@router.get("/recent-accuracy")  # 永远匹配不到
def recent_accuracy(): ...
```

**Why**: FastAPI 按定义顺序匹配路由，`{session_id}` 能匹配任何字符串包括 `recent-accuracy`。

---

## 聚合查询模式：条件计数

使用 `func.count().filter()` 在一次查询中同时计算 total 和 correct，避免两次 DB 往返：

```python
total, correct = db.query(
    func.count(),
    func.count().filter(sub.c.is_correct.is_(True)),
).select_from(sub).one()
```

**Why**: 两次独立 `db.query(func.count())` 意味着两次子查询执行；条件聚合只需一次。

---

## 子查询排序稳定性

当业务排序字段可能存在重复值时，必须加 tie-breaker 保证结果确定性：

```python
# 正确：id 作为 tie-breaker
.order_by(QuizAnswer.answered_at.desc(), QuizAnswer.id.desc())

# 错误：时间相同的记录顺序不稳定，可能导致不同请求返回不同子集
.order_by(QuizAnswer.answered_at.desc())
```

---

## 部署验证必检项

新增 API 路由后，部署前必须执行以下验证：

1. **后端重启确认**：uvicorn 不开 `--reload` 时，代码修改后必须手动重启进程，否则新路由不存在
2. **API 可达性验证**：用 curl 或 httpie 实际调用新端点，不能只检查 `import` 成功
3. **前端构建**：`npm run build` 通过仅验证语法/打包，不验证运行时 API 调用

```bash
# 部署后验证脚本模板
TOKEN=$(curl -s -X POST http://localhost:5003/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"testuser","password":"testpass"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

curl -s http://localhost:5003/api/quiz/recent-accuracy \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Why**: 本次首页正确率修复在开发时未发现 404，因为旧 uvicorn 进程仍在运行旧代码。没有集成测试覆盖新端点，构建通过不等于功能可用。

---

## 常见问题

### Flask 服务层返回 `{"error": "..."}` dict 让路由猜测状态码

部分 Flask service 返回包含 error 键的 dict，路由层需要自行判断返回什么状态码。FastAPI 版推荐 service 抛异常或返回明确结果，由路由层决定 HTTP 状态码。

### 序列化函数分散在路由和 service 中

Flask 版的 `*_to_dict()` 定义在各路由文件中（如 `bank_to_dict` 在 `banks.py`，`_word_to_dict` 在 `vocab.py`）。FastAPI 版的 `serialize_*()` 定义在对应 service 文件中。
