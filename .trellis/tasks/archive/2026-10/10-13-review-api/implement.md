# 执行计划：复盘详情 API 与统计口径统一

需求见本任务 `prd.md`；技术设计见父任务 `design.md` 第 4.3–4.5 节。

## 0. 开始前检查（依赖门禁）

```bash
python3 ./.trellis/scripts/task.py current        # 应为 10-13-review-api
git log --oneline -5                               # 确认 10-13-snapshot-model 已合入
grep -n 'question_snapshot\|final_answers' backend/app/models/quiz.py
```

**前置：`10-13-snapshot-model` 必须已完成。** 若 `question_snapshot` / `final_answers` 列尚不存在，停止并先完成该子任务，不要在本任务里顺手加列。

同时确认前端两个消费方（`10-13-review-ui`、`10-13-result-page`）尚未开始改同一接口的消费代码；本任务冻结契约。

## 1. 统计口径共享函数

先抽出共享实现，避免三处各写一遍公式。建议放在 `backend/app/services/` 下（如 `quiz_stats.py`）：

```python
def session_stats(*, total: int, answered: int, correct: int, mode: str) -> dict:
    """本场统计：错误数为已答减正确，未答数为总题数减已答。"""
    wrong = max(answered - correct, 0)
    unanswered = max(total - answered, 0)
    basis = "total" if mode == "exam" else "answered"
    denominator = total if basis == "total" else answered
    accuracy = round(correct / denominator * 100, 1) if denominator else 0.0
    return {"wrong_count": wrong, "unanswered_count": unanswered,
            "accuracy_basis": basis, "accuracy": accuracy}
```

**先替换既有三处调用点**（`backend/app/api/routes/quiz.py`）：

- `/finish`（416 行）
- `/history`（468 行）
- `session_detail`（617 行）

替换后立刻跑相关回归，确认普通练习行为不变（模拟考试会从「已答分母」变为「总题数分母」，这是预期变更）：

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_quiz_answer_duration.py tests/test_quiz_history_order.py -q
```

## 2. `session_detail` 按完成态分支

`backend/app/api/routes/quiz.py:540-626`。

### 2.1 结构

```python
is_exam = session.mode == "exam"
released = session.is_completed          # 完成态才释放答案与对错
has_snapshot = session.question_snapshot is not None
```

- 进行中：沿用现有逻辑（`not is_exam` 才给 `is_correct`/`correct_answer`/解析）。
- 已完成：**无论模式**都给 `is_correct` 与 `correct_answer`。

保留既有 `_ensure_session_in_exam`（551 行）与 `session.user_id != user_id` 403（552-553 行）——越权与跨项目必须继续拒绝。

### 2.2 已完成：按原场顺序返回完整题目

用 `session.question_ids` 作为唯一顺序来源，**不要**依赖 `db.query(QuizAnswer)` 的返回顺序（现状 `quiz.py:556` 无 `order_by`，这是题号错位的根因）。

每题构造：

```python
{
    "id": qid,
    "index": i + 1,                     # 原场题号，1-based
    "question_type": ...,
    "content": ...,
    "options": ...,
    "user_answer": a.user_answer if answered else None,
    "is_correct": a.is_correct if answered else None,
    "correct_answer": snapshot_entry["correct_answer"],
    "status": "correct" | "wrong" | "unanswered",
    "status_unknown": bool,
}
```

- `status` 由保存的 `is_correct` 决定：`True` → `correct`，`False` → `wrong`，无作答记录 → `unanswered`。**不得**用布尔兜底把缺失当作 `False`。
- `status_unknown`：无法从快照与作答记录核实该题状态时为 `True`（旧会话、记录缺失）。
- 每题内容优先取自 `question_snapshot` 对应元素；无快照时退回当前题库数据，并置 `has_snapshot=false` 与相应 `status_unknown`。
- **不加** `content_zh`、`explanation`、`explanation_zh` 到冻结内容——翻译与 AI 解析由现有机制实时提供（前端另有其调用路径）。

### 2.3 进行中：不得泄露

确认新增分支后，进行中的模拟会话响应仍不含 `is_correct`、`correct_answer`、解析、`wrong_count`、`accuracy` 等可推导成绩的字段。这是回归重点，见第 4 节测试。

### 2.4 session 块新增字段

`session` 对象补 `wrong_count`、`unanswered_count`、`accuracy_basis`、`has_snapshot`；`accuracy` 用第 1 节的共享函数。

## 3. 只读写入拒绝（补测试而非改实现）

`/quiz/answer` 的 `if session.is_completed: raise HTTPException(status_code=400, detail="答题已结束")`（`quiz.py:279-280`）保持不变。本任务只补测试锁定：

- 已完成会话提交答案返回 400。
- 提交被拒后 `QuizAnswer` 与 `answered_count`、`correct_count` 均未变化。

## 4. 测试

新增 `backend/tests/test_quiz_review_api.py`（参考 `test_quiz_answer_duration.py` 的 fixture 与 `test_quiz_history_order.py` 的断言风格）。

必须覆盖 `prd.md` 全部验收条目，重点：

1. **模拟完成释放**：10 题 7 对 3 错完成后，响应含每题 `is_correct` 与 `correct_answer`；`accuracy=70.0`、`accuracy_basis="total"`、`wrong_count=3`、`unanswered_count=0`。
2. **模拟进行中隔离**：未完成模拟会话响应**不含** `is_correct`、`correct_answer`、解析、`wrong_count`、`accuracy`。
3. **顺序与未答**：构造跳题与改答场景，断言 `index` 与原场题号一致且含 `status="unanswered"` 的题。
4. **分母为 0**：完全不作答就结束，`accuracy=0.0` 且不抛异常。
5. **两模式对照**：同样 10 题答 2 题全对，普通 `100.0`/`answered`、模拟 `20.0`/`total`。
6. **旧会话兼容**：手工置 `question_snapshot=NULL`，断言 `has_snapshot=false`、已保存判定保留、不重新判分、`status_unknown` 置位。
7. **只读拒绝**：见第 3 节。
8. **历史口径**：`/quiz/history` 与 `session_detail` 对同一会话给出一致的比例。
9. **权限**：越权与跨项目访问返回 403/404。

### 验证命令

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_quiz_review_api.py -q

# 既有回归必须全绿（尤其前两条锁定既有隔离行为）
cd backend && ../.venv/bin/python -m pytest \
  tests/test_quiz_answer_duration.py tests/test_quiz_resume_index.py \
  tests/test_quiz_history_order.py tests/test_correct_answer.py \
  tests/test_topic_question_selection.py tests/test_practice_day.py -q

# 全量
python3 backend/tests/run_isolated_suite.py
```

## 5. 回归门禁：`session_detail` 是双消费方接口

`GET /quiz/session/{id}` 同时服务答题页刷新恢复（`frontend/src/views/QuizView.vue:269`，依赖 `questions` 与 `resume_index`）与结果页（`frontend/src/views/QuizResultView.vue:120`）。

**契约冻结后必须通知 `10-13-review-ui` 与 `10-13-result-page`。** 本任务结束后，用真实浏览器确认：

1. 未完成会话刷新 → 仍能恢复答题与进度（不可白屏）。
2. 已完成会话打开结果页 → 不白屏。

浏览器验证可与前端子任务合并执行；本任务至少要在后端测试中断言 `resume_index` 与未完成会话的 `questions` 结构未变。

## 6. 回滚点

- 共享函数替换三处调用点之后 → 先跑回归再继续。
- `session_detail` 分支改造之前 → 单一回滚点。
- 全部测试通过前不提交。

## 7. 风险文件与禁止顺手改动

**本任务改动：** `backend/app/api/routes/quiz.py`（`session_detail`、`/finish`、`/history`、正确率三处）、新增 `backend/app/services/quiz_stats.py`、新增测试文件。

**禁止顺手改动：** 不改模型与迁移（属 `10-13-snapshot-model`）；不实现 `POST /quiz/retry`（属 `10-13-retry-api`）；不改前端；不改首页 `recent-accuracy`、练习日、当日作答量；不重构 `QuizView.vue` 的恢复逻辑。
