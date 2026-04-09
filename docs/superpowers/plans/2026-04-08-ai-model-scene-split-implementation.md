# AI Scene Model Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持在系统 AI 设置中分别配置翻译模型与 AI 解析模型，并在未配置场景模型时默认回退到 `ai_model`。

**Architecture:** 后端继续复用 `SystemSetting` 键值存储，在设置服务层集中实现按场景解析模型的逻辑；AI 调用层通过 `scene` 参数路由到翻译或解析模型；前端设置页增加两个可选模型字段并复用现有保存与连接测试流程。

**Tech Stack:** Flask、SQLAlchemy、pytest、Vue 3、Vite

---

## File Map

- Modify: `backend/services/settings_service.py` — 增加场景模型解析逻辑
- Modify: `backend/routes/settings.py` — 设置接口读写新增字段
- Modify: `backend/services/ai_service.py` — AI 调用按场景选择模型
- Modify: `backend/tests/test_settings_ai_api_key.py` — 覆盖新增设置字段和测试连接行为
- Create: `backend/tests/test_ai_service_scene_models.py` — 覆盖翻译/解析场景模型选择逻辑
- Modify: `frontend/src/views/AdminSettingsView.vue` — 设置页新增翻译模型/解析模型输入项

### Task 1: 扩展后端设置接口与模型解析逻辑

**Files:**
- Modify: `backend/services/settings_service.py`
- Modify: `backend/routes/settings.py`
- Modify: `backend/tests/test_settings_ai_api_key.py`

- [ ] **Step 1: 先写失败测试，覆盖新增设置字段读写与测试连接默认模型**

```python
def test_get_ai_settings_returns_scene_model_fields(app):
    token = create_admin_token(app)
    client = app.test_client()

    with app.app_context():
        SystemSetting.set("ai_api_base_url", "https://gateway.example.com")
        SystemSetting.set("ai_model", "gpt-5.4")
        SystemSetting.set("ai_translate_model", "gpt-5-nano")
        SystemSetting.set("ai_explain_model", "gpt-5.4")

    res = client.get("/api/settings/ai", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200
    assert res.get_json()["ai_translate_model"] == "gpt-5-nano"
    assert res.get_json()["ai_explain_model"] == "gpt-5.4"


def test_save_ai_settings_persists_scene_models(app):
    token = create_admin_token(app)
    client = app.test_client()

    res = client.put(
        "/api/settings/ai",
        json={
            "ai_api_base_url": "https://api.example.com",
            "ai_api_key": "sk-test-secret-12345678",
            "ai_model": "gpt-5.4",
            "ai_translate_model": "gpt-5-nano",
            "ai_explain_model": "gpt-5.4",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200
    with app.app_context():
        assert SystemSetting.get("ai_translate_model") == "gpt-5-nano"
        assert SystemSetting.get("ai_explain_model") == "gpt-5.4"
```

- [ ] **Step 2: 运行失败测试，确认新增行为尚未实现**

Run:
```bash
pytest backend/tests/test_settings_ai_api_key.py -k "scene_model or returns_scene_model_fields or persists_scene_models" -v
```

Expected: FAIL，提示响应字段缺失或设置未保存。

- [ ] **Step 3: 实现最小后端改动**

在 `backend/services/settings_service.py` 中新增按场景取模型的解析逻辑，并在 `backend/routes/settings.py` 中读写新增字段，保持测试连接继续使用 `ai_model`。

```python
SCENE_MODEL_SETTING_KEYS = {
    'translate': 'ai_translate_model',
    'explain': 'ai_explain_model',
}


def get_effective_ai_settings(*, base_url=None, api_key=None, model=None, scene='default'):
    config = current_app.config
    default_model = _resolve_value(
        override=model,
        stored=SystemSetting.get('ai_model', ''),
        fallback=config.get('AI_MODEL', 'gpt-4o-mini'),
    )
    return {
        'base_url': _resolve_value(
            override=base_url,
            stored=SystemSetting.get('ai_api_base_url', ''),
            fallback=config.get('AI_API_BASE_URL', 'https://api.openai.com'),
        ),
        'api_key': _resolve_api_key(api_key),
        'model': _resolve_scene_model(scene=scene, explicit_model=model, default_model=default_model),
    }


def _resolve_scene_model(*, scene, explicit_model, default_model):
    explicit = (explicit_model or '').strip()
    if explicit:
        return explicit
    scene_key = SCENE_MODEL_SETTING_KEYS.get(scene)
    if scene_key:
        scene_model = SystemSetting.get(scene_key, '').strip()
        if scene_model:
            return scene_model
    return default_model
```

并在 `backend/routes/settings.py` 返回/保存：

```python
return jsonify({
    'ai_api_base_url': SystemSetting.get('ai_api_base_url', ''),
    'ai_api_key': get_masked_effective_ai_api_key(),
    'ai_api_key_configured': has_effective_ai_api_key(),
    'ai_model': SystemSetting.get('ai_model', ''),
    'ai_translate_model': SystemSetting.get('ai_translate_model', ''),
    'ai_explain_model': SystemSetting.get('ai_explain_model', ''),
})
```

- [ ] **Step 4: 重新运行目标测试，确认通过**

Run:
```bash
pytest backend/tests/test_settings_ai_api_key.py -v
```

Expected: PASS，且新增字段相关断言通过。

- [ ] **Step 5: 提交 Task 1**

```bash
git add backend/services/settings_service.py backend/routes/settings.py backend/tests/test_settings_ai_api_key.py
git commit -m "feat: add scene-specific AI model settings"
```

### Task 2: 让 AI 调用按翻译/解析场景选择模型

**Files:**
- Modify: `backend/services/ai_service.py`
- Create: `backend/tests/test_ai_service_scene_models.py`

- [ ] **Step 1: 先写失败测试，覆盖翻译/解析场景选模与回退逻辑**

```python
def test_translate_question_uses_translate_scene_model(app, monkeypatch):
    question = build_question(app)
    captured = {}

    def fake_post(url, json, headers, timeout, verify):
        captured['model'] = json['model']
        return FakeTranslateResponse()

    monkeypatch.setattr(ai_service.requests, 'post', fake_post)

    with app.app_context():
        SystemSetting.set('ai_api_base_url', 'https://api.example.com')
        set_encrypted_ai_api_key('sk-test-secret-12345678')
        SystemSetting.set('ai_model', 'gpt-5.4')
        SystemSetting.set('ai_translate_model', 'gpt-5-nano')
        ai_service.translate_question(question)

    assert captured['model'] == 'gpt-5-nano'


def test_explain_question_falls_back_to_default_model_when_scene_model_missing(app, monkeypatch):
    question = build_question(app)
    captured = {}

    def fake_post(url, json, headers, timeout, verify):
        captured['model'] = json['model']
        return FakeExplainResponse()

    monkeypatch.setattr(ai_service.requests, 'post', fake_post)

    with app.app_context():
        SystemSetting.set('ai_api_base_url', 'https://api.example.com')
        set_encrypted_ai_api_key('sk-test-secret-12345678')
        SystemSetting.set('ai_model', 'gpt-5.4')
        SystemSetting.set('ai_explain_model', '')
        ai_service.explain_question(question)

    assert captured['model'] == 'gpt-5.4'
```

- [ ] **Step 2: 运行失败测试，确认当前 AI 调用还未区分场景**

Run:
```bash
pytest backend/tests/test_ai_service_scene_models.py -v
```

Expected: FAIL，翻译与解析请求仍命中同一个默认模型。

- [ ] **Step 3: 实现最小 AI 调用改动**

在 `backend/services/ai_service.py` 中给调用入口增加 `scene` 参数，并在各业务方法中明确传入场景。

```python
def call_ai_api(messages, scene='default'):
    ai = _get_ai_config(scene=scene)
    ...


def _get_ai_config(scene='default'):
    return get_effective_ai_settings(scene=scene)


def translate_question(question):
    ...
    result_text = call_ai_api(messages, scene='translate')


def translate_term(term):
    ...
    result_text = call_ai_api(messages, scene='translate')


def batch_translate_terms(terms_data):
    ...
    result_text = call_ai_api(messages, scene='translate')


def explain_question(question):
    ...
    result_text = call_ai_api(messages, scene='explain')
```

- [ ] **Step 4: 重新运行目标测试，确认通过**

Run:
```bash
pytest backend/tests/test_ai_service_scene_models.py -v
```

Expected: PASS，翻译命中 `ai_translate_model`，解析未配置场景模型时回退 `ai_model`。

- [ ] **Step 5: 提交 Task 2**

```bash
git add backend/services/ai_service.py backend/tests/test_ai_service_scene_models.py
git commit -m "feat: route AI calls by scene model"
```

### Task 3: 更新管理后台设置页以支持两个场景模型字段

**Files:**
- Modify: `frontend/src/views/AdminSettingsView.vue`

- [ ] **Step 1: 先写前端最小验证目标并准备失败验证**

把本任务的验证目标固定为：页面表单包含 `ai_translate_model` 和 `ai_explain_model` 两个字段，且 `npm run build` 能成功编译。

在修改前先运行：

```bash
npm run build
```

Workdir:
```bash
frontend
```

Expected: PASS（建立前端基线）。随后修改页面后若字段绑定缺失或语法错误，构建会失败。

- [ ] **Step 2: 实现前端最小改动**

在 `frontend/src/views/AdminSettingsView.vue` 中：

```javascript
const form = ref({
  ai_api_base_url: '',
  ai_api_key: '',
  ai_model: '',
  ai_translate_model: '',
  ai_explain_model: '',
})
```

加载设置时：

```javascript
form.value = {
  ai_api_base_url: res.data.ai_api_base_url || '',
  ai_api_key: '',
  ai_model: res.data.ai_model || '',
  ai_translate_model: res.data.ai_translate_model || '',
  ai_explain_model: res.data.ai_explain_model || '',
}
```

模板中新增两个输入项和说明文案：

```vue
<div>
  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">翻译模型</label>
  <input v-model="form.ai_translate_model" type="text" placeholder="gpt-5-nano" ... />
  <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">用于题目翻译、词汇翻译等场景；留空时默认使用“默认模型”</p>
</div>
<div>
  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">AI 解析模型</label>
  <input v-model="form.ai_explain_model" type="text" placeholder="gpt-5.4" ... />
  <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">用于题目 AI 解析场景；留空时默认使用“默认模型”</p>
</div>
```

- [ ] **Step 3: 运行前端构建验证，确认页面改动可编译**

Run:
```bash
npm run build
```

Workdir:
```bash
frontend
```

Expected: PASS，Vite 构建成功。

- [ ] **Step 4: 提交 Task 3**

```bash
git add frontend/src/views/AdminSettingsView.vue
git commit -m "feat: add scene model inputs to admin settings"
```

### Task 4: 做整体验证并整理结果

**Files:**
- Modify: 无

- [ ] **Step 1: 运行本需求相关后端测试**

Run:
```bash
pytest backend/tests/test_settings_ai_api_key.py backend/tests/test_ai_service_scene_models.py -v
```

Expected: PASS。

- [ ] **Step 2: 运行前端构建验证**

Run:
```bash
npm run build
```

Workdir:
```bash
frontend
```

Expected: PASS。

- [ ] **Step 3: 运行完整 pytest 并记录已有基线失败**

Run:
```bash
pytest
```

Expected: 仍可能包含与本需求无关的既有失败；需在总结中明确列出，不把它们误报为本次回归。

- [ ] **Step 4: 准备总结，不在没有新验证证据前宣称全部完成**

总结需包含：

- 本次新增的设置字段
- 翻译/解析的模型路由规则
- 已运行的验证命令与结果
- 若完整 pytest 仍失败，明确指出失败项是基线遗留还是本次引入
