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

---

## 常见问题

### Flask 服务层返回 `{"error": "..."}` dict 让路由猜测状态码

部分 Flask service 返回包含 error 键的 dict，路由层需要自行判断返回什么状态码。FastAPI 版推荐 service 抛异常或返回明确结果，由路由层决定 HTTP 状态码。

### 序列化函数分散在路由和 service 中

Flask 版的 `*_to_dict()` 定义在各路由文件中（如 `bank_to_dict` 在 `banks.py`，`_word_to_dict` 在 `vocab.py`）。FastAPI 版的 `serialize_*()` 定义在对应 service 文件中。
