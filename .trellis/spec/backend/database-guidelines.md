# 数据库规范

> 项目使用 SQLAlchemy，Flask 版为 1.x 风格，FastAPI 版为 2.x 风格。两套共存，共享同一数据库。

---

## ORM 模型定义对比

### Flask 版：`db.Model` + `db.Column` + `backref`

```python
# backend/models.py 行8-15
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
```

关系使用 `backref`（自动在反向模型创建属性）：

```python
# backend/models.py 行17-18
quiz_sessions = db.relationship('QuizSession', backref='user', lazy='dynamic')
wrong_answers = db.relationship('WrongAnswer', backref='user', lazy='dynamic')
```

### FastAPI 版：`Mapped[]` + `mapped_column()` + `back_populates`

```python
# backend/app/models/user.py 行11-22
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
```

关系使用 `back_populates`（显式双向声明）：

```python
# backend/app/models/user.py 行25-26
quiz_sessions = relationship("QuizSession", back_populates="user", lazy="dynamic")
wrong_answers = relationship("WrongAnswer", back_populates="user", lazy="dynamic")
```

---

## JSON 字段存储对比

### Flask 版：`db.Text` + 兼容式 JSON 读取

```python
# backend/models.py 行41
options = db.Column(db.Text, nullable=False)  # JSON string

# 写入时手动序列化（backend/routes/banks.py）
question = Question(options=json.dumps(q['options']), ...)

# 读取时兼容 SQLite Text 和 PostgreSQL JSON/JSONB 返回值

def _loads_json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value

'options': _loads_json_value(q.options),
```

**Why**: Flask 旧模型声明仍是 `Text`，但迁移到 PostgreSQL 后实际列可能是 JSON/JSONB，驱动会直接返回 list/dict。路由里裸 `json.loads(q.options)` 会在继续答题等接口触发 `TypeError: the JSON object must be str, bytes or bytearray, not list`。

### FastAPI 版：`JSONB` 直接存储，无需手动序列化

```python
# backend/app/models/question.py 行22
options: Mapped[dict] = mapped_column(JSONB, nullable=False)

# 写入时直接传 Python 对象（无需 json.dumps）
question = Question(options=options_list, ...)

# 读取时直接用（无需 json.loads）
'options': question.options,
```

---

## 查询风格对比

### Flask 版：`Model.query.xxx`

```python
# backend/models.py 行279 — SystemSetting 静态方法
setting = SystemSetting.query.filter_by(key=key).first()

# backend/routes/quiz.py 行74
query = Question.query.filter_by(bank_id=bank_id)

# backend/routes/quiz.py 行135
session = QuizSession.query.get_or_404(session_id)
```

### FastAPI 版：`db.query(Model).xxx` + `db.get(Model, pk)`

```python
# backend/app/services/job_service.py 行70-71
db.query(BankWordExclusion).filter_by(bank_id=bank_id).all()

# backend/app/services/job_service.py 行91
bank = db.get(QuestionBank, bank_id)

# backend/app/api/deps.py 行50
user = db.get(User, user_id)
```

进阶查询用 SQLAlchemy 2.x 的 `select()`/`update()` 风格：

```python
# backend/app/services/job_service.py 行249-254
candidate_ids = db.execute(
    select(BackgroundJob.id).where(
        BackgroundJob.status == "queued",
        or_(BackgroundJob.next_run_at.is_(None), BackgroundJob.next_run_at <= now),
    ).order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
).scalars().all()
```

---

## 序列化：手工 `*_to_dict()` 函数

项目不使用 Pydantic `from_attributes` 自动转换（部分 FastAPI endpoint 用 `response_model`，但主流仍手工序列化）。

```python
# backend/routes/banks.py 行81-89
def bank_to_dict(bank):
    return {
        'id': bank.id,
        'name': bank.name,
        'description': bank.description,
        'source_filename': bank.source_filename,
        'question_count': bank.question_count,
        'created_at': bank.created_at.isoformat(),
    }

# backend/routes/vocab.py 行445-457
def _word_to_dict(w, user, progress_by_vocab_id):
    return {
        'id': w.id,
        'term': w.term,
        'created_at': w.created_at.isoformat(),
        ...
    }
```

日期序列化统一用 `.isoformat()`。

---

## 并发 upsert 用 savepoint（nested transaction）

```python
# backend/routes/quiz.py 行45-61
def _upsert_user_question_stat(user_id, question_id):
    now = datetime.now(timezone.utc)
    # 先尝试更新
    rows_updated = UserQuestionStat.query.filter_by(
        user_id=user_id, question_id=question_id
    ).update({...}, synchronize_session=False)
    if rows_updated:
        return ...

    # 不存在则插入，用 savepoint 处理并发冲突
    stat = UserQuestionStat(...)
    nested = db.session.begin_nested()  # savepoint
    try:
        db.session.add(stat)
        db.session.flush()
        nested.commit()
        return stat.answer_count
    except IntegrityError:
        nested.rollback()
        # 并发插入冲突，回退到更新
        UserQuestionStat.query.filter_by(...).update({...}, synchronize_session=False)
        return ...
```

---

## 命名规则

- 表名：`snake_case` 复数（`users`, `question_banks`, `questions`）
- 列名：`snake_case`（`bank_id`, `created_at`）
- 索引名：`idx_<table>_<column>`（如 `idx_background_jobs_status`）
- 外键列：`<referenced_table_singular>_id`（如 `bank_id` 引用 `question_banks.id`）
- 时间戳列：`created_at`, `updated_at`（DEFAULT NOW()）

---

## JSONB 字段写入：必须重新赋值（不要 mutate）

PostgreSQL JSONB 字段在 SQLAlchemy 中默认不会检测**就地变更**，必须整字段重新赋值才会触发 dirty。

```python
# Wrong：就地 mutate，flush 后丢失
import_job.config_json["reconciliation"] = recon
db.commit()  # config_json 视图未变更，不发出 UPDATE

# Correct：dict spread 重新赋值
import_job.config_json = {
    **(import_job.config_json or {}),
    "reconciliation": recon,
}
db.commit()  # 整字段重新赋值，发出 UPDATE
```

项目惯例不依赖 `flag_modified`（保持显式不可变赋值）。

---

## JSONB on SQLite（仅测试用）

测试场景下用 in-memory SQLite 跑真 ORM（避免 fixture 走 mock 失真），但 `JSONB` 是 PostgreSQL 专属类型，SQLite 无法识别。约定通过 `@compiles(JSONB, "sqlite")` 钩子把 JSONB 编译成 SQLite 的 `JSON`，**仅作用于该测试文件，不污染生产模型**：

```python
# backend/tests/test_smart_import_e2e_reconciliation.py（示例）
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"
```

适用条件：

- 仅 in-memory SQLite 测试需要（`sqlite:///:memory:`）
- 同一 ORM 模型在生产（PG）和测试（SQLite）共用
- **不适用于** Alembic 迁移文件（迁移必须在真实 PG 上跑 `upgrade head`）

不要把这段写到生产代码或 `app/models/*.py`；写到具体测试文件顶部即可。
