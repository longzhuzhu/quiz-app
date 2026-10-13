# 执行计划：原题原序重开答题会话 API

需求见本任务 `prd.md`；技术设计见父任务 `design.md` 第 4.6 节。

## 0. 开始前检查（依赖门禁）

```bash
python3 ./.trellis/scripts/task.py current     # 应为 10-13-retry-api
grep -n 'question_snapshot' backend/app/models/quiz.py          # 需要 snapshot-model 已完成
grep -n 'def session_detail' backend/app/api/routes/quiz.py     # 需要 review-api 已定契约
```

**前置：`10-13-snapshot-model` 必须已完成。** `10-13-review-api` 若已完成，复用其响应构造；若未完成，先与其约定新会话返回的 `session` 字段集，避免结果页拿到不一致的结构。

## 1. 端点实现

在 `backend/app/api/routes/quiz.py` 新增 `POST /quiz/retry`。

```python
@router.post("/retry")
def retry_quiz(
    data: QuizRetryRequest,
    current_user: User = Depends(get_current_user),
    exam: Exam = Depends(get_exam_context),
    db: Session = Depends(get_db),
):
```

`backend/app/schemas/quiz.py` 新增：

```python
class QuizRetryRequest(BaseModel):
    session_id: int
```

### 1.1 校验顺序

严格按 `prd.md` R2：

1. `db.get(QuizSession, session_id)` → 无则 404「答题会话不存在」。
2. `_ensure_session_in_exam(session, exam)` → 失败 404（沿用 `quiz.py:130-132`）。
3. `session.user_id != current_user.id` → 403「无权限」。
4. `not session.is_completed` → 400（不能从未结束会话重开）。
5. `question_ids` 解析为空 → 400，**不查题库猜范围**。

### 1.2 逐题校验可访问性

按 `question_ids` 顺序查题目，并确保每题都在当前考试项目内：

```python
rows = (
    db.query(Question)
    .join(QuestionBank, Question.bank_id == QuestionBank.id)
    .filter(Question.id.in_(question_ids), QuestionBank.exam_id == exam.id)
    .all()
)
q_map = {q.id: q for q in rows}
missing = [qid for qid in question_ids if qid not in q_map]
if missing:
    raise HTTPException(status_code=400, detail=...)
```

**关键点：**

- 必须按 `question_ids` 顺序重建列表，**不能**依赖查询返回顺序。
- `missing` 要**全部**列出，让用户知道哪些题不可用。
- 跨题库错题会话的题目分属不同题库，**不能**加 `bank_id == session.bank_id` 过滤。
- 校验失败时**不得**已创建会话：先校验后创建，或在同一事务中失败即回滚。

### 1.3 创建新会话

```python
new_session = QuizSession(
    user_id=current_user.id,
    bank_id=session.bank_id,                     # 沿用原会话，跨题库时只是首个题库
    mode=session.mode,
    topic_id=session.topic_id,                   # 保留仍有效的考点上下文
    total_questions=len(ordered_questions),
    question_ids=json.dumps(question_ids),
    question_snapshot=snapshot_entries(ordered_questions),   # 取自「当前」题目内容
)
db.add(new_session)
db.commit()
db.refresh(new_session)
```

要点：

- `answered_count`、`correct_count` 依赖模型默认值（0）；`is_completed` 默认 `False`；`final_answers` 保持 `None`。
- 快照取自这些原题**当前**的题干、选项与正确答案——「原题指成员与顺序，不是恢复题库旧版本」。
- **不**写 `UserQuestionStat`、**不**写练习日、**不**复制 `QuizAnswer`。

### 1.4 考点已删除的情况

`topic_id` 外键为 `ondelete="SET NULL"`（`backend/app/models/quiz.py:24-26`）。若原 `topic_id` 已为空或指向不存在的考点，保留原题集合照常创建，并在响应中明确原考点已不可用。

### 1.5 响应

返回新会话与题目列表，形态与 `/quiz/start`（`quiz.py:247-256`）对齐，便于前端复用跳转与加载逻辑。模拟考试模式按 `is_exam` 隐藏解析与 `ai_explanations`（对齐 `quiz.py:230-244`）。

## 2. 测试

新增 `backend/tests/test_quiz_retry.py`（参考 `test_topic_question_selection.py` 构造多题库与考点场景）。

必须覆盖 `prd.md` 全部验收条目，重点：

1. **原题原序**：新会话 `question_ids` 与原会话逐一相等（含顺序），含原场未答题。
2. **不重新筛选**：原场题库之后新增题目，新会话不含它们。
3. **不因掌握而剔除**：原题标记 `WrongAnswer.is_resolved=True` 后重开，仍包含该题。
4. **跨题库**：构造两个题库的错题练习会话，重开后全部原题保留。
5. **模式与题数**：exam / wrong_practice / topic 分别断言 `mode` 与 `total_questions`。
6. **整场失败**：删除其中一道原题后重开返回 400，且断言 `QuizSession` 总数**未增加**（无部分会话）。
7. **旧会话无列表**：手工置 `question_ids=NULL` 或 `"[]"` → 400。
8. **未完成会话**：400。
9. **权限**：他人用户 403、跨项目 404，且响应体不含题目内容。
10. **初始状态**：`answered_count=0`、`correct_count=0`、`is_completed=false`、`final_answers IS NULL`、`question_snapshot` 非空。
11. **原会话不变**：重开后原会话的 `is_completed`、计数、`final_answers` 与重开前一致。
12. **无副作用**：重开后 `UserQuestionStat` 与练习日记录数未增加。

### 验证命令

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_quiz_retry.py -q

# 相关回归（错题练习路径与考点选题最相关）
cd backend && ../.venv/bin/python -m pytest \
  tests/test_topic_question_selection.py tests/test_quiz_answer_duration.py \
  tests/test_correct_answer.py tests/test_quiz_history_order.py -q

# 全量
python3 backend/tests/run_isolated_suite.py
```

## 3. 契约交付

本任务完成后通知 `10-13-result-page`：端点路径、请求体、成功响应结构、失败时的 `detail` 文本形态（前端要展示不可用题目）。

## 4. 回滚点

- 端点新增前 → 单一回滚点；端点只增不改，回滚只需移除该路由与 schema。

## 5. 风险文件与禁止顺手改动

**本任务改动：** `backend/app/api/routes/quiz.py`（新增 `/retry`）、`backend/app/schemas/quiz.py`（新增请求模型）、新增测试文件；若 `10-13-review-api` 已抽出共享响应构造，复用它而不是复制。

**禁止顺手改动：** 不改 `session_detail` 契约（属 `10-13-review-api`）；不改模型与迁移（属 `10-13-snapshot-model`）；不改前端；不改「更正答案」逻辑；不重构 `_ensure_session_in_exam` 的既有语义。
