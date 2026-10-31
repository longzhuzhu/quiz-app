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

附属表 upsert（如练习日）也走同一模式，但 **savepoint 里的 `flush()` 会写出该 Session 里所有脏对象**。唯一冲突回滚 savepoint 时，可能把同事务里尚未提交的 `QuizAnswer` 改答一并撤掉。约定：先按唯一键查重，已存在则直接返回；插入前先 `db.flush()` 落盘主路径，再 `begin_nested()` 只包附属插入。见 `backend/app/services/practice_service.py` 的 `record_question_touch`。

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

## JSONB 配置快照：改代码常量对存量行无效

迁移把代码里的默认配置**硬编码写入** JSONB 列后，该列就是一份独立快照。取值形如
`profile.get(key) or DEFAULT_CONST` 时，存量行的 key 非空，`or` 分支永远走不到，
**只改 Python 常量对存量数据完全没有效果**——新建的行用新默认值，存量行停在旧值，两边行为分叉。

典型例子：`migration 003` 把当时的 `explanation_system_prompt` 写进 `exams.ai_profile`，
`ai_service._exam_ai_profile()` 按上述模式取值。

```python
# Wrong：只改常量就以为生效了
DEFAULT_EXPLANATION_SYSTEM_PROMPT = "...新 prompt..."

# Correct：常量 + 配套迁移，只升级从未被用户改动过的行
UPDATE exams
SET ai_profile = jsonb_set(ai_profile, '{explanation_system_prompt}',
                           to_jsonb(CAST(:new_prompt AS text)), true)
WHERE ai_profile->>'explanation_system_prompt' = :old_prompt   -- 逐字节相等才替换
```

约定：

- 迁移只在存储值与**旧默认值逐字节相等**时替换，用户自定义过的配置一律不动。
- 迁移里的旧值字面量必须与写入它的那个迁移完全一致；差一个字符 `WHERE` 就匹配不到任何行，
  迁移静默无效。用测试锁住两个迁移文件之间的字面量相等。
- 再用一个测试断言新迁移的新值 == 当前代码常量。它是一个 tripwire：以后有人改了常量却没补迁移，
  测试会失败并提示补迁移（参见 `backend/tests/test_explanation_prompt_structure.py`）。
- 如果这份配置的产物被缓存到别的列（如 `Question.explanation`），换默认值后还要清缓存才能看到新行为，
  否则命中缓存就不会重算。
- **平台输出契约不要写进 JSONB。** `explanation_system_prompt` 只存领域角色 / 术语 / 讲解偏好；
  三段式 JSON 形状、干扰项枚举与质量规则由 `build_explanation_system_prompt(persona)` 在运行时追加。
  否则自定义 Profile 会整段替换平台结构（`migration 006` 把 004 写入的默认全文收成 persona）。
  改 persona 常量仍要配套迁移 + tripwire：`006` old == `004` new，`006` new == 当前 persona。
- **运行时后缀不等于 004 全文。** `004` tripwire 锁的是当时写入的 `persona + EXPLANATION_OUTPUT_CONTRACT`，
  不是「当前组装全文」。独立判断等后续规则用运行时后缀追加（如 `EXPLANATION_INDEPENDENT_JUDGMENT_CONTRACT`）；
  只加后缀不必写 Alembic，也不要把 004 NEW 改成含后缀的全文，否则历史迁移测试会逼你改 004 字面量。

---

## JSON 列类型

跨后端列类型统一使用 `app/core/db_types.py` 的 `JSONType`（PostgreSQL 编译为 JSONB，SQLite 为 JSON）。后端选择、迁移分支与并发契约见 [数据库后端可选部署](database-backends.md)。

历史测试文件里的 `@compiles(JSONB, "sqlite")` 只是旧测试的本地兼容钩子，**不是**生产兼容方案，也不适用于 Alembic 迁移；新增代码不要复制该写法。迁移必须由真实 SQLite 文件库与真实 PostgreSQL 各自执行 `upgrade head` 验证。

---

## SQLite 测试必须显式开启外键强制

SQLite **默认不强制外键**（`PRAGMA foreign_keys` 默认为 OFF）。`ForeignKey(..., ondelete="...")` 声明在
SQLite 上完全不生效——级联删除不发生，`SET NULL` 也不置空。测试于是会在一个生产上不可能出现的
状态下断言通过。

比「约束不生效」更危险的是**语义反转**：以 `ondelete="SET NULL"` 为例，SQLite 下外键列会**保留悬空 id**，
而 PostgreSQL 下会**变成 NULL**。任何以「该列是否为空」判断业务状态的代码，在两种引擎下结论相反。

```python
# backend/tests/test_quiz_retry.py —— 依赖 quiz_sessions.topic_id 的 SET NULL 语义
from sqlalchemy import event

@pytest.fixture
def quiz_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    ...
```

约定：

- 测试文件若依赖任何 `ondelete` 行为（`CASCADE` / `SET NULL` / `RESTRICT`），夹具必须开这个 PRAGMA。
- 只在 `connect` 事件里设置，不要写进生产代码。**注意 PRAGMA 是每连接生效的**，
  必须挂在 engine 的 `connect` 事件上而不是建库后执行一次。
- 建议留一条**金丝雀用例**断言真实 PG 语义（如 `topic_id is None`）。把 PRAGMA 改回 OFF 时该用例
  应当立即失败——这是验证「PRAGMA 真的在把关」而非摆设的唯一办法。
- 无法用 PRAGMA 覆盖的差异（如 PG 独有类型、`DISTINCT ON`、时区）仍需连真实 PostgreSQL，
  参考 `backend/tests/test_job_claim_datetime_compare.py` 与 `test_quiz_snapshot.py` 的迁移测试。

---

## ORM UPDATE 的时间比较：必须禁用 Python 端求值同步

无时区列（`DateTime`，PG 中为 `timestamp without time zone`）参与 WHERE 条件时，如果条件值来自 `datetime.now(timezone.utc)`（aware），ORM 的 `update()` 默认走 `evaluate` 同步策略，会在 session 中已有该表对象时对条件做 **Python 端求值**，把数据库读回的 naive 值与 aware 值相比：

```
TypeError: can't compare offset-naive and offset-aware datetimes
```

### 触发条件

同时满足三条才触发：

1. 该行对象已加载进当前 session（`db.get(...)` 之后紧接 `update()` 就会）
2. WHERE 条件包含时间列与 aware datetime 的比较
3. 时间列在该行有**非 NULL 值**（`IS NULL` 会短路求值，掩盖问题）

第 3 条最容易骗过测试：新插入的行往往是 `NULL`，一旦有值（如重试任务写入 `next_run_at`）就开始崩。`background_jobs.next_run_at` 曾因此让 worker 反复崩溃重启。

### 处理

对这类 UPDATE 显式关闭会话同步；后续需要最新状态就重新查一次：

```python
# backend/app/services/job_service.py（try_claim_job_by_id）
result = db.execute(
    update(BackgroundJob).where(
        BackgroundJob.id == job_id,
        BackgroundJob.status == "queued",
        or_(BackgroundJob.next_run_at.is_(None), BackgroundJob.next_run_at <= now),
    ).values(...),
    execution_options={"synchronize_session": False},
)
...
db.commit()
claimed = db.get(BackgroundJob, job_id)  # 重新读取，不依赖同步
```

`connection.exec_driver_sql()` 与 `update(...).execution_options()` 都**不是**正确写法：前者绕过 ORM，后者不是 `Update` 构造的合法参数。

### 纯 SELECT 不受影响

只读 `select()` 不做 Python 端求值，比较在数据库端完成，aware 值由驱动转换处理，无需改动。

### 测试要求

naive/aware 比较是**驱动层行为**，SQLite 会掩盖（SQLite 无时区概念）。该缺陷的回归测试必须连真实 PostgreSQL，参考 `backend/tests/test_job_claim_datetime_compare.py`。

---

## 参与算术的新列：`server_default` 不是可选项

给既有表新增一列时，如果这一列会**参与运算**（`+= 1`、比较大小、累加），`nullable=False` 必须配
`server_default`，否则存量行的该列值是 NULL，运算结果恒为 NULL，功能对存量数据永久失效。

`default=0`（ORM 层）只管新建对象，`server_default="0"`（DDL 层）管存量行 —— 两者都要写。

```python
# backend/app/models/wrong.py
correct_streak: Mapped[int] = mapped_column(
    Integer, nullable=False, default=0, server_default="0"
)
```

```python
# backend/alembic/versions/013_wrong_correct_streak.py
op.add_column(
    "wrong_answers",
    sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0"),
)
```

**与「可空 + 不回填」的取舍区分**：`012` 给 `quiz_sessions` 加的 `question_snapshot` / `final_answers`
是「没有就是没有」的语义（NULL 表示旧会话无快照，读侧走兼容分支），那种情况可空、不回填是正确的。
判断标准是**读侧如何处理 NULL**：走兼容分支 → 可空；进算术 → 必须 `server_default`。

**SQLite 掩盖这一差异**：它不会让 `nullable=False` 缺 `server_default` 的迁移失败，测试全绿而生产
存量行为 NULL。该契约必须由连真实 PostgreSQL 的迁移测试锁住，参考
`backend/tests/test_wrong_mastery_streak.py::test_migration_013_adds_not_null_default_zero_for_existing_rows`
（先升到前一版本 → 插入存量行 → 升到新版本 → 断言值非 NULL）。

---

## 场景：system_settings 平台参数（读取侧回落，不预置行）

### 1. Scope / Trigger

需要新增或修改 `system_settings` 里的平台级参数时（`backend/app/models/system_setting.py` 的
`key`/`value` KV 表，无 schema 约束）。触发条件：新配置项、跨层下发、或改既有配置项的语义。

### 2. Signatures

```python
# backend/app/services/settings_service.py
WRONG_MASTERY_CORRECT_STREAK_SETTING = "wrong_mastery_correct_streak"
WRONG_MASTERY_CORRECT_STREAK_DEFAULT = 2
WRONG_MASTERY_CORRECT_STREAK_MIN = 1
WRONG_MASTERY_CORRECT_STREAK_MAX = 9

def get_wrong_mastery_correct_streak(db: Session) -> int: ...

# 通用读写（已存在）
def get_key(db: Session, key: str, default: str = "") -> str: ...
def set_key(db: Session, key: str, value: str) -> None: ...
```

接口与读取路径：

```python
# backend/app/api/routes/settings.py  — 管理员读写
GET  /api/settings/quiz   -> {"quiz_ai_prewarm_enabled": bool, "wrong_mastery_correct_streak": int}
PUT  /api/settings/quiz   <  {"wrong_mastery_correct_streak": int | None}

# backend/app/api/routes/wrong.py     — 认证用户只读（普通用户拿不到 /api/settings/quiz）
GET  /api/wrong/stats     -> {..., "mastery_correct_streak": int}
```

### 3. Contracts

- 存储：`value` 列存十进制整数字符串（`"2"`）。**不预置数据库行**——键不存在即「未配置」。
- 缺省语义：键不存在 / 值为空 / 无法解析 / 超出合法范围 → 一律回落 `*_DEFAULT`。
- 读取侧**永不抛异常**。校验只在写入侧做；读取侧的兜底针对绕过接口手工写库。
- 判定点每次现读配置，**不加进程内缓存**：多 worker 下缓存会产生「改了配置但部分请求仍用旧值」
  的静默偏差；单行唯一索引点查（`key` 有 `unique=True`）相对延迟预算可忽略。

### 4. Validation & Error Matrix

| 条件 | 结果 |
|---|---|
| 键不存在 / 空串 | 200，回落默认值（不写库） |
| 值为 `"abc"` / `"3.7"` / `"999"` | 200，回落默认值 |
| `PUT` 传 `1..9` 整数 | 200，写入并立即生效 |
| `PUT` 传 `0` / `10` / `-1` | **400**，`detail` 为中文**字符串** |
| `PUT` 传 `1.5` / `"abc"` | **422**，`detail` 为**数组**（Pydantic 类型约束，既有行为，不改） |
| `PUT` 传 `null` / 省略字段 | 200，该字段不改动（`is not None` 语义） |
| 非 admin 访问 `GET/PUT /api/settings/quiz` | 403 |

### 5. Good/Base/Bad Cases

- Good：管理员在 `/admin/settings` 把阈值从 2 改成 3 → 保存 → 下一次作答即按 3 判定。
- Base：从未配置过 → 全链路按默认 2，`system_settings` 里没有该键。
- Bad：读取函数在解析失败时抛异常 → 答题提交热路径 500，一个坏配置打挂全站答题。

### 6. Tests Required（断言点）

`backend/tests/test_wrong_mastery_streak.py`：

- 未配置回落 + **不预置数据库键**（`_stored_streak(api) is None`）
- 配置值真实驱动判定（参数化 1/3，含「两次不达标、第三次达标」）
- 越界值 400 且 **`isinstance(body["detail"], str)`**
- 非 admin 403，且只读路径 `/api/wrong/stats` 仍可达
- 存量零重算（改阈值前后逐行对比 `(question_id, correct_streak, is_resolved)`）
- 坏值兜底（绕过接口写 `"abc"` / `"999"` 仍回落默认）

### 7. Wrong vs Correct

#### Wrong

```python
# 预置一行默认值：让「从未配置」与「显式配成默认值」不可区分，
# 也让「读取不写库」的可测试性消失。
db.add(SystemSetting(key=SETTING, value="2"))

# 读取侧抛异常：一个坏配置打挂答题热路径
def get_threshold(db):
    raw = get_key(db, SETTING)
    if not raw.isdigit():
        raise ValueError("阈值未配置")
    return int(raw)
```

#### Correct

```python
def get_wrong_mastery_correct_streak(db: Session) -> int:
    """键缺失、空值或超范围一律回落默认值，不抛异常。"""
    raw = get_key(db, WRONG_MASTERY_CORRECT_STREAK_SETTING, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return WRONG_MASTERY_CORRECT_STREAK_DEFAULT
    if not (WRONG_MASTERY_CORRECT_STREAK_MIN <= value <= WRONG_MASTERY_CORRECT_STREAK_MAX):
        return WRONG_MASTERY_CORRECT_STREAK_DEFAULT
    return value
```

---

## 多字段 PUT：先校验全部输入，再做任何写入

`set_key` 内部会 `flush()`（`backend/app/services/settings_service.py`），即把 UPDATE 发给数据库。因此
「先写合法字段、再校验后面的字段」会让被拒请求留下**已 flush 的未提交改动**。

它当前**恰好安全**，但那只是侥幸：`get_db` 的 `finally` 只 `close()` 不 `rollback`
（`backend/app/core/database.py:27-33`），未提交事务在连接归还时被回滚。一旦会话管理改成显式提交、
或这段逻辑被搬到别处复用，就会变成真实的脏写。

```python
# Wrong：校验晚于写入
if data.quiz_ai_prewarm_enabled is not None:
    set_bool_key(db, QUIZ_AI_PREWARM_ENABLED_SETTING, data.quiz_ai_prewarm_enabled)  # 已 flush
if streak is not None and not (MIN <= streak <= MAX):
    raise HTTPException(status_code=400, detail="...")  # 开关已处于待提交状态
```

```python
# Correct：validate-then-mutate
if streak is not None and not (MIN <= streak <= MAX):
    raise HTTPException(status_code=400, detail="...")
if data.quiz_ai_prewarm_enabled is not None:
    set_bool_key(db, QUIZ_AI_PREWARM_ENABLED_SETTING, data.quiz_ai_prewarm_enabled)
if streak is not None:
    set_setting(db, WRONG_MASTERY_CORRECT_STREAK_SETTING, str(streak))
db.commit()
```

**测试陷阱（务必注意）**：这条契约**无法用 HTTP 层测试锁住**。`TestClient` 每次请求都是新会话，
未提交事务在请求结束时必然回滚，先写后校验与先校验后写的结果完全一致——曾写过 HTTP 版本并用
缺陷顺序的金丝雀验证过它**不会失败**。必须直接调路由函数并**复用同一个会话**，断言
`db.dirty` 为空或读回未改动的字段值。参考
`backend/tests/test_wrong_mastery_streak.py::test_rejected_threshold_does_not_disturb_other_settings`。
