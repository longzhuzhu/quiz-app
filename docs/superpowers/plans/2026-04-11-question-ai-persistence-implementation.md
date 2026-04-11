# Question AI Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure question translation and AI explanation results persist on `Question`, return consistent cached payloads, invalidate correctly on question edits, and reuse persisted explanations in the UI without unnecessary re-requests.

**Architecture:** Keep `Question` as the only persistence layer. Add small AI payload/invalidation helpers in the backend service layer, update the AI and question routes to consume them, then pass existing explanation data into reusable Vue components so the UI can short-circuit API calls when the question payload already includes persisted data. Backend behavior is covered with pytest regression tests; frontend behavior is verified with a production build plus explicit manual network checks because this repo has no component-test harness.

**Tech Stack:** Python 3 + Flask + SQLAlchemy + pytest; Vue 3 + Vite + Axios

---

## File Structure

- Create: `backend/tests/test_question_ai_persistence_api.py` — regression tests for cached AI payloads and question-edit invalidation rules.
- Modify: `backend/services/ai_service.py:1-202` — add helper functions for cache payload building / invalidation and reuse them in translate / explain flows.
- Modify: `backend/routes/ai.py:1-70` — switch cached branches to helper-based payloads and broader explanation cache detection.
- Modify: `backend/routes/questions.py:1-97` — detect meaningful question-field changes and clear stale AI fields before saving edits.
- Modify: `frontend/src/components/ExplainButton.vue:1-43` — accept preloaded explanation data and avoid calling `/api/ai/explain` when not needed.
- Modify: `frontend/src/components/QuestionCard.vue:1-197` — pass persisted explanation payloads into `ExplainButton` and keep AI panel rendering compatible with partial explanation data.
- Modify: `frontend/src/views/WrongAnswersView.vue:128-190` — wire the same persisted-explanation shortcut into the wrong-answers screen for consistency.

> **Commit hygiene:** `git status --short` already shows unrelated untracked directories `.agents/` and `plugins/`. Do **not** stage them in any commit for this feature.

### Task 1: Add backend regression tests for cached AI payload behavior

**Files:**
- Create: `backend/tests/test_question_ai_persistence_api.py`
- Test: `backend/tests/test_question_ai_persistence_api.py`

- [ ] **Step 1: Write the failing tests for cached translate / explain responses**

```python
import json
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import db, Question, QuestionBank, User
from routes import ai as ai_routes


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "quiz_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-0123456789012345")
    monkeypatch.setenv("SECRET_KEY", "test-app-secret-0123456789012345")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def seed_user_and_question(
    app,
    *,
    content_zh="已有中文题干",
    explanation="Existing explanation",
    explanation_zh="已有中文解析",
):
    with app.app_context():
        user = User(
            username="cached-user",
            email="cached-user@test.com",
            password_hash="x",
            is_admin=True,
        )
        bank = QuestionBank(name="AI Bank", description="")
        db.session.add_all([user, bank])
        db.session.flush()

        question = Question(
            bank_id=bank.id,
            question_type="single",
            content="What is privacy by design?",
            content_zh=content_zh,
            options=json.dumps(
                [
                    {"key": "A", "text": "A design principle", "text_zh": "一种设计原则"},
                    {"key": "B", "text": "A legal basis", "text_zh": "一种法律依据"},
                ],
                ensure_ascii=False,
            ),
            correct_answer="A",
            explanation=explanation,
            explanation_zh=explanation_zh,
            order_index=0,
        )
        db.session.add(question)
        db.session.commit()

        token = create_access_token(identity=str(user.id))
        return {"token": token, "question_id": question.id}


def test_cached_translate_returns_options_zh_without_calling_ai(app, monkeypatch):
    seeded = seed_user_and_question(app)

    def fail_translate(_question):
        raise AssertionError("translate_question should not be called when translation is cached")

    monkeypatch.setattr(ai_routes, "translate_question", fail_translate)

    client = app.test_client()
    res = client.post(
        "/api/ai/translate",
        json={"question_id": seeded["question_id"]},
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    assert res.status_code == 200
    assert res.get_json() == {
        "content_zh": "已有中文题干",
        "options_zh": [
            {"key": "A", "text_zh": "一种设计原则"},
            {"key": "B", "text_zh": "一种法律依据"},
        ],
        "cached": True,
    }


def test_cached_explain_uses_existing_partial_payload_without_calling_ai(app, monkeypatch):
    seeded = seed_user_and_question(app, explanation=None, explanation_zh="已有中文解析")

    def fail_explain(_question):
        raise AssertionError("explain_question should not be called when explanation payload already exists")

    monkeypatch.setattr(ai_routes, "explain_question", fail_explain)

    client = app.test_client()
    res = client.post(
        "/api/ai/explain",
        json={"question_id": seeded["question_id"]},
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    assert res.status_code == 200
    assert res.get_json() == {
        "explanation": None,
        "explanation_zh": "已有中文解析",
        "cached": True,
    }
```

- [ ] **Step 2: Run the new tests and verify they fail for the current implementation**

Run:

```bash
pytest backend/tests/test_question_ai_persistence_api.py -k "cached_translate or cached_explain" -q
```

Expected: FAIL
- `cached_translate` fails because `/api/ai/translate` currently omits `options_zh` in the cached branch.
- `cached_explain` fails because `/api/ai/explain` currently only checks `question.explanation` and will try to call the AI service when only `explanation_zh` exists.

- [ ] **Step 3: Implement helper-based cached payloads in the backend service and AI routes**

Update `backend/services/ai_service.py` with these helpers and call sites:

```python
import json

import requests

from models import db
from services.settings_service import get_effective_ai_settings


def _get_ai_config(scene='default'):
    """从数据库读取 AI 配置，回退到环境变量/默认值"""
    return get_effective_ai_settings(scene=scene)


def _load_question_options(question):
    return json.loads(question.options)


def _strip_code_fence(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1]
        text = text.rsplit('```', 1)[0]
    return text


def has_question_translation(question):
    return bool(question.content_zh)


def has_question_explanation(question):
    return bool(question.explanation or question.explanation_zh)


def build_question_translation_payload(question):
    options_zh = []
    for option in _load_question_options(question):
        if option.get('text_zh'):
            options_zh.append({'key': option['key'], 'text_zh': option['text_zh']})
    return {
        'content_zh': question.content_zh,
        'options_zh': options_zh,
    }


def build_question_explanation_payload(question):
    return {
        'explanation': question.explanation,
        'explanation_zh': question.explanation_zh,
    }


def clear_question_translation(question):
    options = _load_question_options(question)
    question.content_zh = None
    for option in options:
        option.pop('text_zh', None)
    question.options = json.dumps(options, ensure_ascii=False)


def clear_question_explanation(question):
    question.explanation = None
    question.explanation_zh = None


def translate_question(question):
    options = _load_question_options(question)
    options_text = '\n'.join([f"{o['key']}. {o['text']}" for o in options])

    messages = [
        {
            'role': 'system',
            'content': (
                '你是一位专业的隐私技术领域翻译专家。请将以下 CIPT 考试题目从英文翻译为中文。'
                '保留技术缩写（如 GDPR、PII、DPO、DPIA 等）不翻译。'
                '返回 JSON 格式：{"content_zh": "中文题目", "options_zh": [{"key": "A", "text_zh": "中文选项"}, ...]}'
                '只返回 JSON，不要其他内容。'
            ),
        },
        {
            'role': 'user',
            'content': f'题目：{question.content}\n\n选项：\n{options_text}',
        },
    ]

    result_text = _strip_code_fence(call_ai_api(messages, scene='translate'))
    result = json.loads(result_text)

    question.content_zh = result['content_zh']
    for opt in options:
        for opt_zh in result['options_zh']:
            if opt['key'] == opt_zh['key']:
                opt['text_zh'] = opt_zh['text_zh']
                break
    question.options = json.dumps(options, ensure_ascii=False)
    db.session.commit()

    return build_question_translation_payload(question)


def explain_question(question):
    options = _load_question_options(question)
    options_text = '\n'.join([f"{o['key']}. {o['text']}" for o in options])

    messages = [
        {
            'role': 'system',
            'content': (
                '你是一位 CIPT（认证信息隐私技术师）考试辅导专家。'
                '请解析以下题目，说明正确答案的原因以及其他选项为什么不正确。'
                '返回 JSON 格式：{"explanation": "英文解析", "explanation_zh": "中文解析"}'
                '只返回 JSON，不要其他内容。'
            ),
        },
        {
            'role': 'user',
            'content': f'题目：{question.content}\n\n选项：\n{options_text}\n\n正确答案：{question.correct_answer}',
        },
    ]

    result_text = _strip_code_fence(call_ai_api(messages, scene='explain'))
    result = json.loads(result_text)

    question.explanation = result['explanation']
    question.explanation_zh = result['explanation_zh']
    db.session.commit()

    return build_question_explanation_payload(question)
```

Update `backend/routes/ai.py` to use those helpers:

```python
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import Question, User
from services.ai_service import (
    build_question_explanation_payload,
    build_question_translation_payload,
    explain_question,
    has_question_explanation,
    has_question_translation,
    translate_question,
)

ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/translate', methods=['POST'])
@jwt_required()
def translate():
    data = request.get_json()
    question = Question.query.get_or_404(data['question_id'])

    if has_question_translation(question):
        return jsonify({
            **build_question_translation_payload(question),
            'cached': True,
        })

    try:
        result = translate_question(question)
        return jsonify({**result, 'cached': False})
    except Exception as e:
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500


@ai_bp.route('/explain', methods=['POST'])
@jwt_required()
def explain():
    data = request.get_json()
    question = Question.query.get_or_404(data['question_id'])

    if has_question_explanation(question):
        return jsonify({
            **build_question_explanation_payload(question),
            'cached': True,
        })

    try:
        result = explain_question(question)
        return jsonify({**result, 'cached': False})
    except Exception as e:
        return jsonify({'error': f'解析失败: {str(e)}'}), 500
```

- [ ] **Step 4: Re-run the cached-payload tests and verify they pass**

Run:

```bash
pytest backend/tests/test_question_ai_persistence_api.py -k "cached_translate or cached_explain" -q
```

Expected: PASS

- [ ] **Step 5: Commit the cached-payload backend change**

```bash
git add backend/tests/test_question_ai_persistence_api.py backend/services/ai_service.py backend/routes/ai.py
git commit -m "fix: reuse cached question ai payloads"
```

### Task 2: Invalidate persisted AI fields when question content changes

**Files:**
- Modify: `backend/tests/test_question_ai_persistence_api.py`
- Modify: `backend/routes/questions.py:1-97`
- Test: `backend/tests/test_question_ai_persistence_api.py`

- [ ] **Step 1: Extend the backend test file with invalidation rules for edits**

Append these tests to `backend/tests/test_question_ai_persistence_api.py`:

```python
@pytest.mark.parametrize(
    ("payload", "expect_translation_cleared", "expect_explanation_cleared"),
    [
        ({"content": "Updated question content"}, True, True),
        ({
            "options": [
                {"key": "A", "text": "Updated option A"},
                {"key": "B", "text": "Updated option B"},
            ]
        }, True, True),
        ({"correct_answer": "B"}, False, True),
        ({"question_type": "multiple"}, False, True),
    ],
)
def test_update_question_invalidates_ai_fields_based_on_changed_inputs(
    app,
    payload,
    expect_translation_cleared,
    expect_explanation_cleared,
):
    seeded = seed_user_and_question(app)
    client = app.test_client()

    res = client.put(
        f"/api/questions/{seeded['question_id']}",
        json=payload,
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )

    assert res.status_code == 200

    with app.app_context():
        question = db.session.get(Question, seeded["question_id"])
        options = json.loads(question.options)

        if expect_translation_cleared:
            assert question.content_zh is None
            assert all(option.get("text_zh") is None for option in options)
        else:
            assert question.content_zh == "已有中文题干"
            assert [option.get("text_zh") for option in options] == ["一种设计原则", "一种法律依据"]

        if expect_explanation_cleared:
            assert question.explanation is None
            assert question.explanation_zh is None
        else:
            assert question.explanation == "Existing explanation"
            assert question.explanation_zh == "已有中文解析"
```

- [ ] **Step 2: Run the new invalidation tests and verify they fail**

Run:

```bash
pytest backend/tests/test_question_ai_persistence_api.py -k "invalidates_ai_fields" -q
```

Expected: FAIL because `backend/routes/questions.py` currently overwrites the edited fields but never clears stale `content_zh`, `options[*].text_zh`, `explanation`, or `explanation_zh`.

- [ ] **Step 3: Implement question-edit invalidation in `backend/routes/questions.py`**

Update the file to import the helper clearers and detect meaningful changes before saving:

```python
import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, Question, QuestionBank, User
from services.ai_service import clear_question_explanation, clear_question_translation

questions_bp = Blueprint('questions', __name__)


def question_to_dict(q, include_answer=True):
    d = {
        'id': q.id,
        'bank_id': q.bank_id,
        'question_type': q.question_type,
        'content': q.content,
        'content_zh': q.content_zh,
        'options': json.loads(q.options),
        'order_index': q.order_index,
        'explanation': q.explanation,
        'explanation_zh': q.explanation_zh,
        'created_at': q.created_at.isoformat(),
    }
    if include_answer:
        d['correct_answer'] = q.correct_answer
    return d


@questions_bp.route('/<int:question_id>', methods=['PUT'])
@jwt_required()
def update_question(question_id):
    user = User.query.get(int(get_jwt_identity()))
    if not user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    q = Question.query.get_or_404(question_id)
    data = request.get_json()

    current_options = json.loads(q.options)
    content_changed = 'content' in data and data['content'] != q.content
    options_changed = 'options' in data and data['options'] != current_options
    correct_answer_changed = 'correct_answer' in data and data['correct_answer'] != q.correct_answer
    question_type_changed = 'question_type' in data and data['question_type'] != q.question_type

    if content_changed or options_changed:
        clear_question_translation(q)
        clear_question_explanation(q)
    elif correct_answer_changed or question_type_changed:
        clear_question_explanation(q)

    if 'content' in data:
        q.content = data['content']
    if 'options' in data:
        q.options = json.dumps(data['options'], ensure_ascii=False)
    if 'correct_answer' in data:
        q.correct_answer = data['correct_answer']
    if 'question_type' in data:
        q.question_type = data['question_type']

    db.session.commit()
    return jsonify(question_to_dict(q))
```

- [ ] **Step 4: Re-run the invalidation tests and verify they pass**

Run:

```bash
pytest backend/tests/test_question_ai_persistence_api.py -k "invalidates_ai_fields" -q
```

Expected: PASS

- [ ] **Step 5: Commit the invalidation change**

```bash
git add backend/tests/test_question_ai_persistence_api.py backend/routes/questions.py
git commit -m "fix: invalidate question ai fields on edit"
```

### Task 3: Reuse persisted explanations in the Vue UI before calling the API

**Files:**
- Modify: `frontend/src/components/ExplainButton.vue:1-43`
- Modify: `frontend/src/components/QuestionCard.vue:1-197`
- Modify: `frontend/src/views/WrongAnswersView.vue:128-190`
- Test: manual verification in browser

- [ ] **Step 1: Capture the current failing manual repro**

With the app running, reproduce the current bug before changing code:

```bash
# Terminal 1
python run.py

# Terminal 2
npm --prefix frontend run dev
```

Manual repro to record:
1. Open a question that already returns `explanation` / `explanation_zh` in the page payload.
2. Open browser DevTools → Network.
3. Click `AI 解析` in the quiz view.
4. Observe a `POST /api/ai/explain` request still fires even though the question already contains persisted explanation data.
5. Repeat the same check in the wrong-answers page.

Expected current behavior: **FAIL** (unnecessary request is still sent).

- [ ] **Step 2: Implement prop-driven explanation reuse in the shared button and both consumers**

Replace `frontend/src/components/ExplainButton.vue` with this version:

```vue
<template>
  <div>
    <button @click="handleExplain" :disabled="loading"
      class="inline-flex items-center gap-1.5 rounded-button px-3 py-1.5 text-sm font-medium
             bg-gray-100 text-gray-700 hover:bg-gray-200
             dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600
             disabled:opacity-50 transition-colors">
      <LightBulbIcon class="h-4 w-4" />
      {{ loading ? '解析中...' : 'AI 解析' }}
    </button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { LightBulbIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

const props = defineProps({
  questionId: Number,
  initialExplanation: {
    type: Object,
    default: null,
  },
})
const emit = defineEmits(['explained'])
const loading = ref(false)
const explanation = ref(null)

watch(
  () => props.initialExplanation,
  (value) => {
    explanation.value = value && (value.explanation || value.explanation_zh) ? value : null
  },
  { immediate: true }
)

async function handleExplain() {
  if (explanation.value) {
    emit('explained', explanation.value)
    return
  }

  loading.value = true
  try {
    const res = await client.post('/ai/explain', { question_id: props.questionId })
    explanation.value = res.data
    emit('explained', res.data)
  } catch (e) {
    toast.error(e.response?.data?.error || '解析失败')
  } finally {
    loading.value = false
  }
}
</script>
```

Update the `frontend/src/components/QuestionCard.vue` imports, computed state, button props, and panel rendering:

```vue
<script setup>
import { computed, ref, watch } from 'vue'
import { CheckCircleIcon, XCircleIcon } from '@heroicons/vue/24/outline'
import TranslateButton from './TranslateButton.vue'
import ExplainButton from './ExplainButton.vue'
import AddVocabButton from './AddVocabButton.vue'
import BaseButton from './BaseButton.vue'

const props = defineProps({
  question: Object,
  currentIndex: Number,
  total: Number,
  hideProgress: { type: Boolean, default: false },
  initialAnswer: { type: String, default: '' },
  initialResult: { type: Object, default: null },
  examMode: { type: Boolean, default: false },
  answerCount: { type: Number, default: 0 },
})

const emit = defineEmits(['submit', 'next', 'prev', 'finish', 'translated'])

const selectedAnswers = ref([])
const answered = ref(false)
const result = ref(null)
const showTranslation = ref(false)
const explainData = ref(null)

const persistedExplanation = computed(() => {
  if (!props.question) return null
  if (!props.question.explanation && !props.question.explanation_zh) return null

  return {
    explanation: props.question.explanation || null,
    explanation_zh: props.question.explanation_zh || null,
    cached: true,
  }
})

watch(
  [() => props.currentIndex, () => props.initialAnswer, () => props.initialResult],
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
</script>
```

```vue
<ExplainButton
  v-if="!examMode"
  :key="question.id"
  :question-id="question.id"
  :initial-explanation="persistedExplanation"
  @explained="(e) => explainData = e"
/>
```

```vue
<div v-if="explainData && !examMode"
  class="mt-3 rounded-card border border-sky-200 bg-sky-50 p-4 text-sm
         dark:border-sky-800 dark:bg-sky-900/20">
  <p class="font-medium text-sky-800 dark:text-sky-300">AI 解析</p>
  <p v-if="explainData.explanation" class="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-300">
    {{ explainData.explanation }}
  </p>
  <p v-if="explainData.explanation_zh"
    class="mt-2 whitespace-pre-wrap text-gray-600 dark:text-gray-400">
    {{ explainData.explanation_zh }}
  </p>
</div>
```

Update `frontend/src/views/WrongAnswersView.vue` to pass the same persisted payload and avoid blank English blocks:

```vue
<ExplainButton
  :question-id="w.question.id"
  :initial-explanation="persistedExplanation(w.question)"
  @explained="(e) => explainResults[w.id] = e"
/>
```

```vue
<div v-if="explainResults[w.id]"
  class="mt-3 rounded-card border border-sky-200 bg-sky-50 p-4 text-sm
         dark:border-sky-800 dark:bg-sky-900/20">
  <p class="font-medium text-sky-800 dark:text-sky-300">AI 解析</p>
  <p v-if="explainResults[w.id].explanation"
    class="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-300">
    {{ explainResults[w.id].explanation }}
  </p>
  <p v-if="explainResults[w.id].explanation_zh"
    class="mt-2 whitespace-pre-wrap text-gray-600 dark:text-gray-400">
    {{ explainResults[w.id].explanation_zh }}
  </p>
</div>
```

```vue
<script setup>
// keep existing imports

function persistedExplanation(question) {
  if (!question?.explanation && !question?.explanation_zh) return null
  return {
    explanation: question.explanation || null,
    explanation_zh: question.explanation_zh || null,
    cached: true,
  }
}
</script>
```

- [ ] **Step 3: Run the frontend production build as the first automated smoke check**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS

- [ ] **Step 4: Re-run the manual network verification and confirm the requests disappear only when persisted data exists**

Manual verification checklist:
1. Open a quiz question whose payload already includes `explanation` or `explanation_zh`.
2. Click `AI 解析` and confirm the panel opens immediately.
3. Confirm DevTools Network shows **no** `POST /api/ai/explain` request.
4. Repeat on the wrong-answers page.
5. Open a question with no persisted explanation.
6. Click `AI 解析` and confirm exactly one `POST /api/ai/explain` request is sent, then the returned data renders.

Expected: PASS

- [ ] **Step 5: Commit the frontend reuse change**

```bash
git add frontend/src/components/ExplainButton.vue frontend/src/components/QuestionCard.vue frontend/src/views/WrongAnswersView.vue
git commit -m "fix: reuse persisted question explanations in ui"
```

### Task 4: Run final regression checks and confirm the workspace is clean

**Files:**
- Verify: `backend/tests/test_question_ai_persistence_api.py`
- Verify: `backend/tests/test_ai_service_scene_models.py`
- Verify: `frontend/src/components/ExplainButton.vue`
- Verify: `frontend/src/components/QuestionCard.vue`
- Verify: `frontend/src/views/WrongAnswersView.vue`

- [ ] **Step 1: Run the backend regression suite for this feature and adjacent AI behavior**

Run:

```bash
pytest backend/tests/test_question_ai_persistence_api.py backend/tests/test_ai_service_scene_models.py -q
```

Expected: PASS

- [ ] **Step 2: Run the frontend build one last time after all commits are in place**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS

- [ ] **Step 3: Inspect git status and confirm only intentional tracked changes were committed**

Run:

```bash
git status --short
```

Expected:
- No modified tracked files.
- The unrelated untracked `.agents/` and `plugins/` entries may still appear; leave them untouched.
