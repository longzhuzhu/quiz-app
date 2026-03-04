# Quiz Re-answer Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让答题页面支持“已答题回显 + 重新选择并重新提交”，并使成绩统计始终按最后一次作答生效。

**Architecture:** 后端继续沿用 `QuizAnswer(session_id, question_id)` 唯一记录模型，把重复提交从“拒绝”改为“更新现有记录”，并基于旧结果与新结果做计数差量修正。前端在恢复会话时从 `session_detail.answers` 构建每题“历史答案/历史结果”映射，`QuestionCard` 去掉已答锁定，用户可进入编辑态后再次提交覆盖。通过后端 pytest 回归测试与前端手工 RED/GREEN 场景验证完整流程。

**Tech Stack:** Flask + SQLAlchemy + Flask-JWT-Extended + pytest + Vue 3 + Pinia + Axios + Vite

---

**设计文档:** `docs/plans/2026-03-04-quiz-redo-design.md`
**执行时必须使用:** `@superpowers:test-driven-development`、`@superpowers:systematic-debugging`、`@superpowers:verification-before-completion`

### Task 1: 后端先写失败测试，锁定“重答覆盖”行为

**Files:**
- Create: `backend/tests/test_quiz_reanswer_api.py`
- Test: `backend/tests/test_quiz_reanswer_api.py`

**Step 1: 写失败测试（RED）**

```python
# backend/tests/test_quiz_reanswer_api.py
import json
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, User, QuestionBank, Question, QuizSession, QuizAnswer


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "quiz_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def seed_session(app, *, initial_answer, initial_is_correct, correct_count):
    with app.app_context():
        user = User(username="u1", email="u1@test.com", password_hash="x")
        bank = QuestionBank(name="bank", description="d")
        db.session.add_all([user, bank])
        db.session.flush()

        q = Question(
            bank_id=bank.id,
            question_type="single",
            content="question",
            content_zh=None,
            options=json.dumps([
                {"key": "A", "text": "A"},
                {"key": "B", "text": "B"}
            ]),
            correct_answer="A",
            explanation="exp",
            explanation_zh=None,
            order_index=1,
        )
        db.session.add(q)
        db.session.flush()

        session = QuizSession(
            user_id=user.id,
            bank_id=bank.id,
            mode="sequential",
            total_questions=1,
            answered_count=1,
            correct_count=correct_count,
            question_ids=json.dumps([q.id]),
        )
        db.session.add(session)
        db.session.flush()

        existing = QuizAnswer(
            session_id=session.id,
            question_id=q.id,
            user_answer=initial_answer,
            is_correct=initial_is_correct,
        )
        db.session.add(existing)
        db.session.commit()

        token = create_access_token(identity=str(user.id))
        return {
            "token": token,
            "session_id": session.id,
            "question_id": q.id,
        }


def test_reanswer_wrong_to_correct_updates_existing_record_and_counts(app):
    seeded = seed_session(app, initial_answer="B", initial_is_correct=False, correct_count=0)
    client = app.test_client()

    res = client.post(
        "/api/quiz/answer",
        json={
            "session_id": seeded["session_id"],
            "question_id": seeded["question_id"],
            "user_answer": "A",
        },
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    assert res.status_code == 200


def test_reanswer_correct_to_wrong_decrements_correct_count_without_incrementing_answered_count(app):
    seeded = seed_session(app, initial_answer="A", initial_is_correct=True, correct_count=1)
    client = app.test_client()

    res = client.post(
        "/api/quiz/answer",
        json={
            "session_id": seeded["session_id"],
            "question_id": seeded["question_id"],
            "user_answer": "B",
        },
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    assert res.status_code == 200
```

**Step 2: 跑测试确认失败（RED 验证）**

Run:
```bash
PYTHONPATH=backend python -m pytest backend/tests/test_quiz_reanswer_api.py -q
```

Expected:
- 两个用例至少有 1 个失败；
- 典型失败是 `assert 400 == 200`，响应错误为 `该题已作答`。

**Step 3: 先提交失败测试（保留红灯快照）**

```bash
git add backend/tests/test_quiz_reanswer_api.py
git commit -m "test: add failing regression tests for quiz re-answer flow"
```

---

### Task 2: 后端最小实现，让失败测试转绿

**Files:**
- Modify: `backend/routes/quiz.py`
- Test: `backend/tests/test_quiz_reanswer_api.py`

**Step 1: 写最小实现（GREEN）**

在 `submit_answer()` 中把“已作答即报错”改成“已作答则更新”。

```python
existing = QuizAnswer.query.filter_by(
    session_id=session_id, question_id=question_id
).first()

question = Question.query.get_or_404(question_id)
is_correct = user_answer.strip().upper() == question.correct_answer.strip().upper()

if existing:
    old_is_correct = existing.is_correct
    existing.user_answer = user_answer
    existing.is_correct = is_correct
    existing.answered_at = datetime.now(timezone.utc)

    if (not old_is_correct) and is_correct:
        session.correct_count += 1
    elif old_is_correct and (not is_correct):
        session.correct_count = max(session.correct_count - 1, 0)

    if not is_correct:
        wrong = WrongAnswer.query.filter_by(
            user_id=user_id, question_id=question_id
        ).first()
        if wrong:
            wrong.wrong_count += 1
            wrong.last_wrong_at = datetime.now(timezone.utc)
            wrong.is_resolved = False
        else:
            db.session.add(WrongAnswer(user_id=user_id, question_id=question_id))
else:
    answer = QuizAnswer(
        session_id=session_id,
        question_id=question_id,
        user_answer=user_answer,
        is_correct=is_correct,
    )
    db.session.add(answer)

    session.answered_count += 1
    if is_correct:
        session.correct_count += 1
    else:
        wrong = WrongAnswer.query.filter_by(
            user_id=user_id, question_id=question_id
        ).first()
        if wrong:
            wrong.wrong_count += 1
            wrong.last_wrong_at = datetime.now(timezone.utc)
            wrong.is_resolved = False
        else:
            db.session.add(WrongAnswer(user_id=user_id, question_id=question_id))
```

**Step 2: 跑同一组测试确认转绿**

Run:
```bash
PYTHONPATH=backend python -m pytest backend/tests/test_quiz_reanswer_api.py -q
```

Expected:
- 全部 PASS。

**Step 3: 补断言（防止“只变 200 不变行为”）**

把 Task 1 测试补成“状态 + 数据”断言：

```python
with app.app_context():
    answers = QuizAnswer.query.filter_by(
        session_id=seeded["session_id"], question_id=seeded["question_id"]
    ).all()
    assert len(answers) == 1

    s = QuizSession.query.get(seeded["session_id"])
    assert s.answered_count == 1
    assert s.correct_count == 1  # 或 0（取决于用例）
```

**Step 4: 再跑测试确认仍为绿灯**

Run:
```bash
PYTHONPATH=backend python -m pytest backend/tests/test_quiz_reanswer_api.py -q
```

Expected:
- 全部 PASS。

**Step 5: Commit**

```bash
git add backend/routes/quiz.py backend/tests/test_quiz_reanswer_api.py
git commit -m "fix: allow re-answer updates and keep quiz session counters consistent"
```

---

### Task 3: QuizView 恢复“已答题目的已选答案与结果”

**Files:**
- Modify: `frontend/src/views/QuizView.vue`
- Modify: `frontend/src/stores/quiz.js`（仅当需要扩展 submit 返回结构时）

**Step 1: 先做手工 RED 场景（记录失败）**

Run:
```bash
python run.py
```

Run:
```bash
cd frontend && npm run dev
```

手工步骤（当前应失败）：
1. 进入任意未完成会话；
2. 切换到已答题；
3. 观察“提示已作答但选项不回显历史选择”。

**Step 2: 写最小实现（GREEN）**

在 `QuizView.vue` 增加两份映射状态：
- `questionAnswerMap[questionId] = user_answer`
- `questionResultMap[questionId] = { is_correct, correct_answer, explanation, explanation_zh }`

并在 `onMounted` 的会话恢复逻辑中用 `res.data.answers` 构建映射。

```js
const questionAnswerMap = reactive({})
const questionResultMap = reactive({})

res.data.answers?.forEach((a) => {
  questionAnswerMap[a.question_id] = a.user_answer
  questionResultMap[a.question_id] = {
    is_correct: a.is_correct,
    correct_answer: a.correct_answer,
    explanation: a.explanation,
    explanation_zh: a.explanation_zh,
  }
})

res.data.questions.forEach((q, i) => {
  const r = questionResultMap[q.id]
  if (r) answerResults[i] = r.is_correct
})
```

并传入子组件：

```vue
<QuestionCard
  ...
  :initial-answer="currentInitialAnswer"
  :initial-result="currentInitialResult"
  @submit="handleSubmit"
/>
```

`handleSubmit` 成功后同步覆盖映射：

```js
questionAnswerMap[currentQuestion.value.id] = answer
questionResultMap[currentQuestion.value.id] = res
answerResults[quizStore.currentIndex] = res.is_correct
```

**Step 3: 编译验证**

Run:
```bash
cd frontend && npm run build
```

Expected:
- 构建成功，无编译错误。

**Step 4: 手工 GREEN 验证**

重复 Step 1 场景，预期：
- 已答题进入时可以看到历史已选答案。

**Step 5: Commit**

```bash
git add frontend/src/views/QuizView.vue
git commit -m "fix: restore persisted answer and result state in quiz view"
```

---

### Task 4: QuestionCard 去掉“已答锁定”，支持再次提交覆盖

**Files:**
- Modify: `frontend/src/components/QuestionCard.vue`

**Step 1: 先做手工 RED 场景（记录失败）**

当前场景（应失败）：
1. 提交一题后，选项禁用；
2. 无法改选并重新提交。

**Step 2: 写最小实现（GREEN）**

1) 新增 props：
```js
initialAnswer: { type: String, default: '' },
initialResult: { type: Object, default: null },
```

2) 初始化/切题时回填状态：
```js
watch(
  () => [props.currentIndex, props.initialAnswer, props.initialResult],
  () => {
    selectedAnswers.value = props.initialAnswer
      ? props.initialAnswer.split(',').map(s => s.trim()).filter(Boolean)
      : []
    answered.value = !!props.initialResult
    result.value = props.initialResult
    showTranslation.value = false
    explainData.value = null
  },
  { immediate: true }
)
```

3) 去掉已答禁选：
- 删除 `@click="!answered && toggleOption(...)"` 限制；
- 删除 input 的 `:disabled="answered"`。

4) 进入编辑态：
```js
function toggleOption(key) {
  if (answered.value) {
    answered.value = false
    result.value = null
  }
  // 原有单选/多选逻辑保留
}
```

5) 操作栏保留“上一题 + 提交答案 + 下一题/完成”，使已答后仍可再次点击提交。

**Step 3: 编译验证**

Run:
```bash
cd frontend && npm run build
```

Expected:
- 构建成功。

**Step 4: 手工 GREEN 验证**

预期行为：
1. 首次提交后可继续改选；
2. 再次提交后反馈区按新结果刷新；
3. 侧边题号状态（正确/错误）也刷新到最新结果。

**Step 5: Commit**

```bash
git add frontend/src/components/QuestionCard.vue
git commit -m "fix: allow editing answered questions and resubmitting in question card"
```

---

### Task 5: 全链路验证与收尾

**Files:**
- Test: `backend/tests/test_quiz_reanswer_api.py`
- Verify manually: `frontend/src/views/QuizView.vue`, `frontend/src/components/QuestionCard.vue`, `backend/routes/quiz.py`

**Step 1: 跑后端回归测试**

Run:
```bash
PYTHONPATH=backend python -m pytest backend/tests/test_quiz_reanswer_api.py -q
```

Expected:
- PASS。

**Step 2: 跑前端构建**

Run:
```bash
cd frontend && npm run build
```

Expected:
- 构建成功。

**Step 3: 手工验收清单（必须逐条）**

1. 已答题可回显已选答案；
2. 已答题可重新选择并重新提交；
3. 同一题“错→对→错”时，导航状态和统计同步变化；
4. 完成答题后结果页统计与“最后一次作答”一致；
5. 不再出现 `该题已作答` 阻断。

**Step 4: 若发现问题，按 @superpowers:systematic-debugging 逐个修复并重复 Step 1-3**

**Step 5: 最终 Commit（仅当 Step 4 产生新改动）**

```bash
git add backend/routes/quiz.py backend/tests/test_quiz_reanswer_api.py frontend/src/views/QuizView.vue frontend/src/components/QuestionCard.vue
git commit -m "fix: finalize quiz re-answer flow verification adjustments"
```
