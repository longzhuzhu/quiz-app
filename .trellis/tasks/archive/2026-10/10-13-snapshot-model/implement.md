# 执行计划：答题会话本场题目快照模型与迁移

需求见本任务 `prd.md`；技术设计见父任务 `design.md` 第 3 节；现状见父任务 `research/current-implementation.md`。

## 0. 开始前检查

```bash
python3 ./.trellis/scripts/task.py current       # 应为 10-13-snapshot-model
ls backend/alembic/versions/                      # 确认 head 仍为 011；若已有 012 则顺延
grep -n 'down_revision' backend/alembic/versions/011_multi_model_explanations.py
```

- 读 `.trellis/spec/backend/database-guidelines.md` 的「JSONB 字段写入：必须重新赋值」与「ORM UPDATE 的时间比较」两节。
- 确认没有其他分支正在改 `backend/app/models/quiz.py` 与 `backend/app/models/wrong.py`。

## 1. 模型改动

### 1.1 `backend/app/models/quiz.py`

`QuizSession` 增加两列：

```python
question_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)
final_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

补充中文注释说明：`question_snapshot` 与 `question_ids` 同序、只含判分依据不含 AI 辅助内容；`final_answers` 在完成时冻结，显式 `null` 表示未答。

`JSONB` 已在该文件 import（`from sqlalchemy.dialects.postgresql import JSONB`）。

### 1.2 `backend/app/models/wrong.py`

`WrongAnswer` 增加两列：

```python
last_wrong_answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
last_wrong_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

注释说明：记录**最近一次错误答案**，后来答对不覆写；旧数据为空表示无可靠错误证据。

## 2. 迁移

新建 `backend/alembic/versions/012_quiz_session_snapshots.py`，风格对齐 `009_quiz_answer_duration.py`（模块 docstring 说明「旧记录不回填」、`revision`/`down_revision`/`upgrade`/`downgrade`）。

```python
revision = "012"
down_revision = "011"
```

`upgrade()`：四个 `op.add_column`（均 nullable）。
`downgrade()`：逆序 `op.drop_column`。

**验证（必做，不能只跑 import）：**

```bash
cd backend && ../.venv/bin/python -m alembic upgrade head
cd backend && ../.venv/bin/python -m alembic downgrade 011
cd backend && ../.venv/bin/python -m alembic upgrade head   # 回到 head
```

若 `.venv` 路径不同，先用 `ls -d .venv backend/.venv` 确认。**注意**：本步骤会连接 `backend/.env` 中的 `DATABASE_URL`。若那是业务库，改用临时库执行（参考 `backend/tests/postgres_support.py` 的隔离方式），不要对业务库做验证性 downgrade。

## 3. 快照写入

新增一个共享的构造／写入函数（建议放新文件 `backend/app/services/quiz_snapshot_service.py`，或并入既有服务；避免重复实现）：

```python
def snapshot_entries(questions: list[Question]) -> list[dict]:
    """按题目顺序构造本场快照；只含判分依据，不含 AI 辅助内容。"""
```

要点：

- `options` 复用既有 `_load_options` 逻辑（`quiz.py:122-127`、`wrong.py:33-37` 各有一份，注意不要引入第三份重复实现——可把该 helper 提到共享位置，但要评估改动面）。
- 写入时**整字段重新赋值**，不做就地 mutate。

### 3.1 `/quiz/start`（`backend/app/api/routes/quiz.py:181-256`）

创建 `QuizSession` 时一并写入 `question_snapshot`。

### 3.2 `/wrong/practice`（`backend/app/api/routes/wrong.py:89-150`）

**这是容易遗漏的第二个入口。** 按 `ordered_questions` 逐题写快照。注意该会话可跨题库，`session.bank_id` 只是 `first_bank_id`（`wrong.py:114`），快照必须逐题取各自内容。

### 3.3 进行中更正答案（`backend/app/services/question_service.py:71-116`）

`update_question_correct_answer` 已重算当前会话该题对错（`apply_session_regrade`，`:108`）。在同一事务内同步更新该会话快照中对应题的 `correct_answer`，其他会话不动。

## 4. 完成冻结

`/quiz/finish`（`backend/app/api/routes/quiz.py:390-418`）：置 `is_completed` 时构建 `final_answers`。

- 值取自 `QuizAnswer`：`{"user_answer": a.user_answer, "is_correct": a.is_correct}`。
- 遍历 `question_ids`，**没有对应作答的题显式写 `null`**（未答）。
- 键统一为字符串形式的 `question_id`。

## 5. 错题证据写入

`/quiz/answer` 判错分支（`backend/app/api/routes/quiz.py:332-343`）：

- 已有 `WrongAnswer` 时：更新 `last_wrong_answer`、`last_wrong_session_id`、`wrong_count`、`last_wrong_at`、`is_resolved=False`。
- 新建时：一并设置这两列。
- **答对时不改这两列**——错误证据按规格保留，不因后来答对而覆写。

## 6. 测试

新增 `backend/tests/test_quiz_snapshot.py`（`pytest` 风格，参考 `test_quiz_answer_duration.py` 的 fixture 用法）。

必须覆盖：

1. 顺序练习会话快照元素数与顺序 == `question_ids`，每题含五个必需字段。
2. 随机／模拟／专项／错题练习均写快照；跨题库错题会话逐题取内容（构造两个题库的错题）。
3. 未完成会话 `final_answers IS NULL`；完成后含未答题的 `null` 值。
4. 完成会话后改题干／选项／正确答案，快照不变。
5. 完成会话后删除原题，`final_answers` 仍可读出该题判定。
6. 进行中更正答案更新当前会话快照、不影响其他会话。
7. 迁移前的旧会话（手工置 `question_snapshot=NULL`）不被回填。
8. 答错写入 `last_wrong_answer`；同题后来答对不覆写。
9. 迁移可用：在隔离 PostgreSQL 上 `upgrade` / `downgrade` 不报错。

### 验证命令

```bash
# 单文件
cd backend && ../.venv/bin/python -m pytest tests/test_quiz_snapshot.py -q

# 相关回归
cd backend && ../.venv/bin/python -m pytest tests/test_quiz_answer_duration.py tests/test_correct_answer.py tests/test_topic_question_selection.py -q

# 全量（临时 PostgreSQL，不碰业务库）
python3 backend/tests/run_isolated_suite.py
```

## 7. 回滚点

- 迁移提交前：直接丢弃工作区改动。
- 迁移已提交但应用未改：`alembic downgrade 011`。
- 应用已上线：回滚应用版本即可（列保留无害）。

## 8. 风险文件与禁止顺手改动

**本任务改动：** `backend/app/models/quiz.py`、`backend/app/models/wrong.py`、新迁移、`backend/app/api/routes/quiz.py`（start/finish/answer）、`backend/app/api/routes/wrong.py`（practice）、`backend/app/services/question_service.py`。

**禁止顺手改动：** 不改 `session_detail` 的响应契约（属 `10-13-review-api`）；不改正确率公式（属 `10-13-review-api`）；不动前端；不重构 `_load_options` 的既有调用方行为；不改变题目／题库／项目删除语义。
