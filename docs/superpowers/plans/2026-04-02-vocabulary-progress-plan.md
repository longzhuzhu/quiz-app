# Vocabulary Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为单词本页面的我的单词本、专业词汇和高频词汇三个列表补齐按用户记录的掌握状态、掌握筛选和管理员删除能力。

**Architecture:** 后端保持词条资源与用户学习状态分离建模，`Vocabulary` 与 `BankWordFrequency` 继续承载词条资源，新增用户进度表与高频词排除表承载用户状态和管理员删除语义。前端继续沿用现有单页 `VocabularyView.vue`，统一三个 tab 的工具栏、筛选状态和词条操作按钮，高频词维持题库与分页结构。

**Tech Stack:** Flask 3, SQLAlchemy, SQLite, Vue 3, Axios, Vite, Pytest, npm build

---

## File Map

- Modify: `backend/models.py`
  - 新增 `UserVocabProgress`、`UserBankWordProgress`、`BankWordExclusion`
- Modify: `backend/app.py`
  - 新增集中化 schema ensure 逻辑
- Modify: `backend/routes/vocab.py`
  - 扩展三个列表接口
  - 新增 `Vocabulary` 词条掌握状态接口
  - 新增高频词掌握状态接口
  - 新增统一的 `Vocabulary` 删除接口与高频词删除接口
- Modify: `backend/routes/banks.py`
  - 题库导入后重建词频时过滤 `BankWordExclusion`
- Create: `backend/tests/test_vocab_progress_api.py`
  - 覆盖个人词汇、专业词汇、高频词的掌握、筛选、删除与 exclusion 行为
- Modify: `frontend/src/views/VocabularyView.vue`
  - 统一三类列表工具栏、掌握状态、筛选与删除交互

### Task 1: 写 `Vocabulary` 词条进度和删除的失败测试

**Files:**
- Create: `backend/tests/test_vocab_progress_api.py`
- Test: `backend/tests/test_vocab_progress_api.py`

- [ ] **Step 1: 写失败测试**

```python
def test_list_personal_vocab_includes_user_mastery_state(client, learner_headers, seed_vocab):
    response = client.get('/api/vocab/personal', headers=learner_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload[0]['is_mastered'] is True
    assert payload[0]['can_delete'] is False
    assert payload[0]['can_mark_mastered'] is True


def test_filter_personal_vocab_by_mastered_state(client, learner_headers, seed_vocab):
    response = client.get('/api/vocab/personal?mastered=false', headers=learner_headers)
    assert response.status_code == 200
    assert [item['term'] for item in response.get_json()] == ['processor']


def test_update_vocab_progress_creates_or_updates_user_state(client, learner_headers, seed_vocab):
    response = client.put(
        f"/api/vocab/items/{seed_vocab['personal_id']}/progress",
        json={'is_mastered': True},
        headers=learner_headers,
    )
    assert response.status_code == 200
    assert response.get_json()['message'] == '已标记为掌握'


def test_delete_vocab_item_requires_admin(client, learner_headers, seed_vocab):
    response = client.delete(f"/api/vocab/items/{seed_vocab['personal_id']}", headers=learner_headers)
    assert response.status_code == 403
    assert response.get_json()['error'] == '仅管理员可操作'
```

- [ ] **Step 2: 跑失败测试**

Run: `pytest backend/tests/test_vocab_progress_api.py -k "personal or progress or delete_vocab_item_requires_admin" -v`

Expected:
- FAIL，因为新表、返回字段和新接口都还不存在

- [ ] **Step 3: 补 admin 删除成功用例**

```python
def test_admin_can_delete_personal_vocab_item(client, admin_headers, seed_vocab, app):
    response = client.delete(f"/api/vocab/items/{seed_vocab['personal_id']}", headers=admin_headers)
    assert response.status_code == 200
    with app.app_context():
        assert Vocabulary.query.get(seed_vocab['personal_id']) is None


def test_admin_can_delete_professional_vocab_item(client, admin_headers, seed_vocab, app):
    response = client.delete(f"/api/vocab/items/{seed_vocab['professional_id']}", headers=admin_headers)
    assert response.status_code == 200
    with app.app_context():
        assert Vocabulary.query.get(seed_vocab['professional_id']) is None
```

- [ ] **Step 4: 再跑一次测试确认仍红**

Run: `pytest backend/tests/test_vocab_progress_api.py -k "delete or personal or progress" -v`

Expected:
- FAIL，且失败集中在缺失 schema 或接口

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_vocab_progress_api.py
git commit -m "test: add failing vocabulary progress api coverage"
```

### Task 2: 实现 `Vocabulary` 词条进度模型、schema ensure 和接口

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/app.py`
- Modify: `backend/routes/vocab.py`
- Test: `backend/tests/test_vocab_progress_api.py`

- [ ] **Step 1: 写最小模型和 ensure 代码**

```python
class UserVocabProgress(db.Model):
    __tablename__ = 'user_vocab_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    vocabulary_id = db.Column(db.Integer, db.ForeignKey('vocabularies.id'), nullable=False, index=True)
    is_mastered = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'vocabulary_id'),)
```

```python
def _ensure_vocab_progress_schema():
    db.create_all()
    _ensure_bank_word_frequency_columns()
```

- [ ] **Step 2: 实现列表字段拼装、掌握更新和统一删除**

```python
@vocab_bp.route('/items/<int:vocabulary_id>/progress', methods=['PUT'])
@jwt_required()
def update_vocab_progress(vocabulary_id):
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    if not isinstance(data.get('is_mastered'), bool):
        return jsonify({'error': '缺少有效的 is_mastered 参数'}), 400

    vocab = Vocabulary.query.get_or_404(vocabulary_id)
    progress = UserVocabProgress.query.filter_by(user_id=user_id, vocabulary_id=vocabulary_id).first()
    if not progress:
        progress = UserVocabProgress(user_id=user_id, vocabulary_id=vocabulary_id)
        db.session.add(progress)
    progress.is_mastered = data['is_mastered']
    db.session.commit()
    return jsonify({'message': '已标记为掌握' if progress.is_mastered else '已取消掌握'})


@vocab_bp.route('/items/<int:vocabulary_id>', methods=['DELETE'])
@jwt_required()
def delete_vocab_item(vocabulary_id):
    user = User.query.get(int(get_jwt_identity()))
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403
    word = Vocabulary.query.get_or_404(vocabulary_id)
    db.session.delete(word)
    db.session.commit()
    return jsonify({'message': '已删除'})
```

- [ ] **Step 3: 扩展个人词汇和专业词汇列表的响应**

```python
def _vocab_to_dict(word, is_mastered, can_delete):
    return {
        'id': word.id,
        'term': word.term,
        'term_zh': word.term_zh,
        'definition': word.definition,
        'definition_zh': word.definition_zh,
        'is_system': word.is_system,
        'is_mastered': is_mastered,
        'can_delete': can_delete,
        'can_mark_mastered': True,
        'created_at': word.created_at.isoformat(),
    }
```

- [ ] **Step 4: 跑测试确认转绿**

Run: `pytest backend/tests/test_vocab_progress_api.py -k "delete or personal or progress" -v`

Expected:
- PASS

- [ ] **Step 5: 提交**

```bash
git add backend/models.py backend/app.py backend/routes/vocab.py backend/tests/test_vocab_progress_api.py
git commit -m "feat: add per-user vocabulary progress api"
```

### Task 3: 写高频词进度、删除和 exclusion 的失败测试

**Files:**
- Modify: `backend/tests/test_vocab_progress_api.py`
- Test: `backend/tests/test_vocab_progress_api.py`

- [ ] **Step 1: 写高频词失败测试**

```python
def test_list_frequent_vocab_includes_user_mastery_state(client, learner_headers, seed_frequent_vocab):
    response = client.get(f"/api/vocab/frequent?bank_id={seed_frequent_vocab['bank_id']}", headers=learner_headers)
    assert response.status_code == 200
    items = response.get_json()['items']
    assert items[0]['term'] == 'privacy'
    assert items[0]['is_mastered'] is True
    assert items[0]['can_delete'] is False


def test_update_frequent_vocab_progress_creates_user_state(client, learner_headers, seed_frequent_vocab):
    response = client.put(
        '/api/vocab/frequent-items/progress',
        json={'bank_id': seed_frequent_vocab['bank_id'], 'term': 'privacy', 'is_mastered': True},
        headers=learner_headers,
    )
    assert response.status_code == 200


def test_admin_can_delete_frequent_vocab_via_exclusion(client, admin_headers, seed_frequent_vocab):
    response = client.delete(
        f"/api/vocab/frequent-items?bank_id={seed_frequent_vocab['bank_id']}&term=privacy",
        headers=admin_headers,
    )
    assert response.status_code == 200
```

- [ ] **Step 2: 补导入重建后仍过滤 exclusion 的测试**

```python
def test_import_rebuild_keeps_excluded_frequent_terms_hidden(client, admin_headers, seed_frequent_vocab, monkeypatch):
    import routes.banks as banks_module

    def fake_parse_file(_file_storage, _filename):
        return [{
            'content': 'Privacy program privacy governance',
            'options': [{'key': 'A', 'text': 'Privacy governance'}],
            'correct_answer': 'A',
            'question_type': 'single',
            'answer_missing': False,
        }]

    monkeypatch.setattr(banks_module, 'parse_file', fake_parse_file)
    response = client.post(
        f"/api/banks/{seed_frequent_vocab['bank_id']}/import",
        data={'file': (BytesIO(b'ignored'), 'questions.docx')},
        content_type='multipart/form-data',
        headers=admin_headers,
    )
    assert response.status_code == 200
```

- [ ] **Step 3: 跑失败测试**

Run: `pytest backend/tests/test_vocab_progress_api.py -k "frequent or exclusion or rebuild" -v`

Expected:
- FAIL，因为高频词进度表、删除接口和 exclusion 过滤逻辑都还不存在

- [ ] **Step 4: 确认失败原因正确后保存测试**

Run: `pytest backend/tests/test_vocab_progress_api.py -k "frequent" -vv`

Expected:
- FAIL，集中在 missing table 或 missing route

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_vocab_progress_api.py
git commit -m "test: add failing frequent vocabulary progress coverage"
```

### Task 4: 实现高频词后端与前端交互并完成验证

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/routes/vocab.py`
- Modify: `backend/routes/banks.py`
- Modify: `frontend/src/views/VocabularyView.vue`
- Test: `backend/tests/test_vocab_progress_api.py`

- [ ] **Step 1: 实现高频词模型和接口**

```python
class UserBankWordProgress(db.Model):
    __tablename__ = 'user_bank_word_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    bank_id = db.Column(db.Integer, db.ForeignKey('question_banks.id'), nullable=False, index=True)
    term = db.Column(db.String(200), nullable=False)
    is_mastered = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'bank_id', 'term'),)


class BankWordExclusion(db.Model):
    __tablename__ = 'bank_word_exclusions'
    id = db.Column(db.Integer, primary_key=True)
    bank_id = db.Column(db.Integer, db.ForeignKey('question_banks.id'), nullable=False, index=True)
    term = db.Column(db.String(200), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('bank_id', 'term'),)
```

```python
@vocab_bp.route('/frequent-items/progress', methods=['PUT'])
@jwt_required()
def update_frequent_progress():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    bank_id = data.get('bank_id')
    term = (data.get('term') or '').strip()
    is_mastered = data.get('is_mastered')
    if not bank_id or not term or not isinstance(is_mastered, bool):
        return jsonify({'error': '缺少有效的 bank_id、term 或 is_mastered 参数'}), 400

    word = BankWordFrequency.query.filter_by(bank_id=bank_id, term=term).first()
    if not word:
        return jsonify({'error': '高频词不存在'}), 404

    progress = UserBankWordProgress.query.filter_by(
        user_id=user_id,
        bank_id=bank_id,
        term=term,
    ).first()
    if not progress:
        progress = UserBankWordProgress(user_id=user_id, bank_id=bank_id, term=term)
        db.session.add(progress)
    progress.is_mastered = is_mastered
    db.session.commit()
    return jsonify({'message': '已标记为掌握' if is_mastered else '已取消掌握'})


@vocab_bp.route('/frequent-items', methods=['DELETE'])
@jwt_required()
def delete_frequent_item():
    user = User.query.get(int(get_jwt_identity()))
    if not user or not user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    bank_id = request.args.get('bank_id', type=int)
    term = (request.args.get('term') or '').strip()
    if not bank_id or not term:
        return jsonify({'error': '缺少有效的 bank_id 或 term 参数'}), 400

    word = BankWordFrequency.query.filter_by(bank_id=bank_id, term=term).first()
    if not word:
        return jsonify({'error': '高频词不存在'}), 404

    exclusion = BankWordExclusion.query.filter_by(bank_id=bank_id, term=term).first()
    if not exclusion:
        exclusion = BankWordExclusion(bank_id=bank_id, term=term, created_by=user.id)
        db.session.add(exclusion)
    db.session.commit()
    return jsonify({'message': '已删除'})
```

- [ ] **Step 2: 在导入重建和列表查询中应用 exclusion 过滤**

```python
excluded_terms = {
    item.term for item in BankWordExclusion.query.filter_by(bank_id=bank_id).all()
}
```

- [ ] **Step 3: 改造前端统一工具栏和掌握操作**

```js
const masteredFilters = reactive({
  professional: 'all',
  personal: 'all',
  frequent: 'all',
})

async function updateVocabularyMastery(id, isMastered) {
  await client.put(`/vocab/items/${id}/progress`, { is_mastered: isMastered })
}

async function updateFrequentMastery(term, isMastered) {
  await client.put('/vocab/frequent-items/progress', {
    bank_id: selectedBankId.value,
    term,
    is_mastered: isMastered,
  })
}
```

```vue
<BaseButton
  variant="secondary"
  size="sm"
  @click.stop="updateVocabularyMastery(w.id, !w.is_mastered)"
>
  {{ w.is_mastered ? '取消掌握' : '标记已掌握' }}
</BaseButton>

<BaseButton
  v-if="w.can_delete"
  variant="danger"
  size="sm"
  @click.stop="confirmDeleteWord(w.id, 'item')"
>
  删除
</BaseButton>
```

- [ ] **Step 4: 跑完整验证**

Run: `pytest backend/tests/test_vocab_progress_api.py -v`

Run:
```bash
cd frontend
npm run build
```

Manual verification:
- 普通用户看到三个列表的掌握按钮，看不到删除
- admin 看到三个列表的删除按钮
- “未掌握”筛选下标记已掌握后，当前项即时消失
- 高频词删除后，如果当前页空了，自动回退上一页

Expected:
- Pytest PASS
- Vite build PASS

- [ ] **Step 5: 提交**

```bash
git add backend/models.py backend/routes/vocab.py backend/routes/banks.py backend/tests/test_vocab_progress_api.py frontend/src/views/VocabularyView.vue
git commit -m "feat: finish vocabulary mastery and admin delete flow"
```
