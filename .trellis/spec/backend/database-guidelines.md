# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

使用 SQLAlchemy 2.x 声明式映射 + PostgreSQL + Alembic 迁移。数据库同时承担业务数据和任务调度。

---

## ORM Configuration

```python
# app/core/database.py
engine = create_engine(
    settings.DATABASE_URL,    # postgresql+psycopg://...
    pool_pre_ping=True,       # 自动检测断连
    pool_size=5,
    max_overflow=10,
)

class Base(DeclarativeBase):
    pass
```

- 连接字符串使用 `postgresql+psycopg`（psycopg3 同步驱动）
- 所有模型继承 `Base`，通过 `app/models/__init__.py` 统一导入确保 `Base.metadata` 包含所有表

---

## Model Patterns

### 基本模型结构

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Text, JSON
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(default=False)
```

- 使用 `Mapped[T]` + `mapped_column()` 类型注解风格（SQLAlchemy 2.x 推荐）
- 每个模型一个文件，放在 `app/models/` 下

### JSONB 字段

```python
from sqlalchemy.dialects.postgresql import JSONB

class Question(Base):
    options: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    correct_answer: Mapped[list] = mapped_column(JSONB, default=[])
```

- PostgreSQL 使用 `JSONB` 替代 SQLite 的 `Text` + JSON 序列化
- `options` 可以是 `list` 或 `dict`，前端兼容两种格式
- 读取时无需 `json.loads()`，写入时无需 `json.dumps()`

### 关系定义

```python
from sqlalchemy.orm import relationship

class QuestionBank(Base):
    questions: Mapped[list["Question"]] = relationship(back_populates="bank", cascade="all, delete-orphan")

class Question(Base):
    bank_id: Mapped[int] = mapped_column(Integer, ForeignKey("question_banks.id"))
    bank: Mapped["QuestionBank"] = relationship(back_populates="questions")
```

---

## Query Patterns

### 获取数据库会话

```python
# FastAPI 依赖注入
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### 常用查询

```python
# 按 ID 查询
user = db.get(User, user_id)

# 条件查询
db.query(Question).filter(Question.bank_id == bank_id).offset(skip).limit(limit).all()

# 计数
db.query(func.count(Question.id)).filter(Question.bank_id == bank_id).scalar()
```

---

## Migrations

### 初始化

```bash
cd backend
alembic init alembic               # 已完成
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### 配置要点

- `alembic/env.py` 中 `target_metadata = Base.metadata`
- 迁移文件放在 `backend/alembic/versions/`
- 命名规则：`NNN_<description>.py`（如 `001_initial.py`）

### 注意事项

> **Gotcha**: 修改模型后必须手动运行 `alembic revision --autogenerate`，Alembic 不会自动检测变更。不要使用 `db.create_all()`。

---

## Naming Conventions

- 表名：`snake_case` 复数（`users`, `question_banks`, `questions`）
- 列名：`snake_case`（`bank_id`, `created_at`）
- 索引名：`idx_<table>_<column>`（如 `idx_background_jobs_status`）
- 外键列：`<referenced_table_singular>_id`（如 `bank_id` 引用 `question_banks.id`）
- 时间戳列：`created_at`, `updated_at`（TIMESTAMP, DEFAULT NOW()）

---

## Common Mistakes

### Don't: 在路由中直接操作数据库

```python
# Wrong
@router.post("/banks")
def create_bank(data: dict, db: Session = Depends(get_db)):
    bank = QuestionBank(name=data["name"])
    db.add(bank)
    db.commit()  # 路由不应管理事务细节
```

### Do: 通过 service 层操作

```python
# Correct
@router.post("/banks")
def create_bank(data: BankCreateRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return bank_service.create_bank(db, data, user)
```

### Don't: 使用 dict 作为请求体

```python
# Wrong - 绕过 FastAPI 自动校验
def create_bank(data: dict, ...):
```

### Do: 使用 Pydantic schema

```python
# Correct - 充分利用 FastAPI 的类型校验
def create_bank(data: BankCreateRequest, ...):
```

### Don't: 忘记检查文件上传大小

```python
# Wrong - 无大小限制
content = await file.read()
```

### Do: 校验后读取

```python
# Correct
content = await file.read()
if len(content) > settings.upload_max_size_bytes:
    raise HTTPException(status_code=413, detail="File too large")
```
