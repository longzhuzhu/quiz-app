# User Password Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为管理员新增用户管理页以重置指定用户密码，并为登录用户新增账户页以自助修改自己的密码。

**Architecture:** 后端新增 `admin_users` 与 `account` 两个蓝图，密码哈希与校验逻辑统一收口到 `auth_service.py`；前端新增 `AdminUsersView.vue` 与 `AccountView.vue` 两个页面，并在路由与导航中接入。管理员重置他人密码不需要旧密码，用户修改自己的密码需要校验旧密码。

**Tech Stack:** Flask、SQLAlchemy、Werkzeug、pytest、Vue 3、Vue Router、Pinia、Vite

---

## File Map

- Create: `backend/routes/account.py` — 当前用户账户信息与自助改密接口
- Create: `backend/routes/admin_users.py` — 管理员用户列表与重置密码接口
- Modify: `backend/services/auth_service.py` — 新增密码校验、设置密码、修改密码辅助函数
- Modify: `backend/app.py` — 注册新蓝图
- Create: `backend/tests/test_account_password_api.py` — 账户页接口测试
- Create: `backend/tests/test_admin_users_api.py` — 管理员用户密码管理接口测试
- Create: `frontend/src/views/AccountView.vue` — 账户信息与修改密码页面
- Create: `frontend/src/views/AdminUsersView.vue` — 用户列表与重置密码页面
- Modify: `frontend/src/router/index.js` — 新增 `/account` 和 `/admin/users` 路由
- Modify: `frontend/src/components/NavBar.vue` — 新增“账户设置”和“用户管理”导航入口
- Modify: `frontend/src/components/MobileNav.vue` — 新增移动端“账户设置”和“用户管理”入口

## Spec Coverage Check

本计划覆盖 spec 中的全部要求：

- 管理员用户列表 → Task 2
- 管理员重置指定用户密码 → Task 2
- 当前用户获取账户信息 → Task 1 + Task 3
- 当前用户修改自己密码 → Task 1 + Task 3
- 前端用户管理页 → Task 4
- 前端账户页 → Task 3
- 路由与导航入口 → Task 3 + Task 4
- 联调与全量验证 → Task 5

无额外子项目拆分需求。

### Task 1: 账户接口与自助修改密码后端能力

**Files:**
- Create: `backend/routes/account.py`
- Modify: `backend/services/auth_service.py`
- Modify: `backend/app.py`
- Test: `backend/tests/test_account_password_api.py`

- [ ] **Step 1: 写账户接口失败测试**

```python
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import User, db


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


def create_user_token(app, username="member", password_hash="hashed-password"):
    with app.app_context():
        user = User(username=username, email=f"{username}@test.com", password_hash=password_hash, is_admin=False)
        db.session.add(user)
        db.session.commit()
        return user.id, create_access_token(identity=str(user.id))


def test_get_account_returns_current_user_profile(app, monkeypatch):
    from werkzeug.security import generate_password_hash

    user_id, token = create_user_token(app, password_hash=generate_password_hash("old-password", method="pbkdf2:sha256"))
    client = app.test_client()

    res = client.get("/api/account", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200
    assert res.get_json()["id"] == user_id
    assert res.get_json()["username"] == "member"
    assert res.get_json()["email"] == "member@test.com"
    assert res.get_json()["is_admin"] is False


def test_change_account_password_rejects_wrong_current_password(app, monkeypatch):
    from werkzeug.security import generate_password_hash

    _user_id, token = create_user_token(app, password_hash=generate_password_hash("old-password", method="pbkdf2:sha256"))
    client = app.test_client()

    res = client.put(
        "/api/account/password",
        json={"current_password": "wrong-password", "new_password": "new-password-123"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 400
    assert res.get_json() == {"error": "当前密码错误"}
```

- [ ] **Step 2: 运行失败测试，确认接口尚未实现**

Run:
```bash
pytest backend/tests/test_account_password_api.py -v
```

Expected: FAIL，提示 `/api/account` 或 `/api/account/password` 不存在。

- [ ] **Step 3: 实现最小后端代码**

在 `backend/services/auth_service.py` 中新增统一密码函数：

```python
MIN_PASSWORD_LENGTH = 6


def validate_new_password(new_password):
    password = (new_password or "").strip()
    if not password:
        raise ValueError("新密码不能为空")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("新密码长度不能少于6位")
    return password


def set_user_password(user, new_password):
    password = validate_new_password(new_password)
    user.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    db.session.commit()
    return user


def change_password(user, current_password, new_password):
    if not check_password_hash(user.password_hash, current_password or ''):
        raise ValueError('当前密码错误')
    set_user_password(user, new_password)
    return user
```

创建 `backend/routes/account.py`：

```python
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import User, db
from services.auth_service import change_password, user_to_dict

account_bp = Blueprint('account', __name__)


@account_bp.route('', methods=['GET'])
@jwt_required()
def get_account():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在或登录已失效'}), 401
    return jsonify(user_to_dict(user))


@account_bp.route('/password', methods=['PUT'])
@jwt_required()
def update_password():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': '用户不存在或登录已失效'}), 401

    data = request.get_json() or {}
    try:
        change_password(user, data.get('current_password'), data.get('new_password'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'message': '密码修改成功'})
```

在 `backend/app.py` 注册：

```python
from routes.account import account_bp
...
app.register_blueprint(account_bp, url_prefix='/api/account')
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest backend/tests/test_account_password_api.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```bash
git add backend/routes/account.py backend/services/auth_service.py backend/app.py backend/tests/test_account_password_api.py
git commit -m "feat: add account password management api"
```

### Task 2: 管理员用户列表与重置密码后端能力

**Files:**
- Create: `backend/routes/admin_users.py`
- Modify: `backend/app.py`
- Modify: `backend/services/auth_service.py`
- Test: `backend/tests/test_admin_users_api.py`

- [ ] **Step 1: 写管理员密码管理失败测试**

```python
from pathlib import Path
import sys

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from models import User, db


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


def seed_users(app):
    with app.app_context():
        admin = User(username="admin", email="admin@test.com", password_hash=generate_password_hash("admin-pass", method="pbkdf2:sha256"), is_admin=True)
        member = User(username="member", email="member@test.com", password_hash=generate_password_hash("member-pass", method="pbkdf2:sha256"), is_admin=False)
        db.session.add_all([admin, member])
        db.session.commit()
        admin_token = create_access_token(identity=str(admin.id))
        member_token = create_access_token(identity=str(member.id))
        return admin.id, member.id, admin_token, member_token


def test_admin_can_list_users(app):
    _admin_id, member_id, admin_token, _member_token = seed_users(app)
    client = app.test_client()

    res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})

    assert res.status_code == 200
    users = res.get_json()
    assert any(item["id"] == member_id and item["username"] == "member" for item in users)


def test_admin_can_reset_user_password(app):
    _admin_id, member_id, admin_token, _member_token = seed_users(app)
    client = app.test_client()

    res = client.put(
        f"/api/admin/users/{member_id}/password",
        json={"new_password": "member-new-pass"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert res.status_code == 200
    assert res.get_json() == {"message": "密码已重置"}

    with app.app_context():
        member = db.session.get(User, member_id)
        assert check_password_hash(member.password_hash, "member-new-pass")
```

- [ ] **Step 2: 运行失败测试，确认接口尚未实现**

Run:
```bash
pytest backend/tests/test_admin_users_api.py -v
```

Expected: FAIL，提示 `/api/admin/users` 或重置密码接口不存在。

- [ ] **Step 3: 实现最小管理员接口代码**

创建 `backend/routes/admin_users.py`：

```python
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import User, db
from services.auth_service import set_user_password, user_to_dict

admin_users_bp = Blueprint('admin_users', __name__)


def _require_admin():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return None, (jsonify({'error': '用户不存在或登录已失效'}), 401)
    if not user.is_admin:
        return None, (jsonify({'error': '需要管理员权限'}), 403)
    return user, None


@admin_users_bp.route('', methods=['GET'])
@jwt_required()
def list_users():
    _user, error = _require_admin()
    if error:
        return error
    users = User.query.order_by(User.created_at.asc(), User.id.asc()).all()
    return jsonify([user_to_dict(user) for user in users])


@admin_users_bp.route('/<int:user_id>/password', methods=['PUT'])
@jwt_required()
def reset_password(user_id):
    _user, error = _require_admin()
    if error:
        return error

    target = db.session.get(User, user_id)
    if not target:
        return jsonify({'error': '用户不存在'}), 404

    data = request.get_json() or {}
    try:
        set_user_password(target, data.get('new_password'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'message': '密码已重置'})
```

在 `backend/app.py` 注册：

```python
from routes.admin_users import admin_users_bp
...
app.register_blueprint(admin_users_bp, url_prefix='/api/admin/users')
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest backend/tests/test_admin_users_api.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交 Task 2**

```bash
git add backend/routes/admin_users.py backend/app.py backend/tests/test_admin_users_api.py
git commit -m "feat: add admin user password management api"
```

### Task 3: 新增账户页并接入个人导航

**Files:**
- Create: `frontend/src/views/AccountView.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/components/NavBar.vue`
- Modify: `frontend/src/components/MobileNav.vue`

- [ ] **Step 1: 先跑前端构建建立基线**

Run:
```bash
npm run build
```

Workdir:
```bash
frontend
```

Expected: PASS。

- [ ] **Step 2: 实现账户页与路由接入**

创建 `frontend/src/views/AccountView.vue`：

```vue
<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">账户设置</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">查看账户信息并修改自己的登录密码。</p>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">账户信息</h2>
      <div v-if="loading" class="mt-4 text-sm text-gray-500 dark:text-gray-400">加载中...</div>
      <div v-else class="mt-4 space-y-2 text-sm text-gray-700 dark:text-gray-300">
        <div><span class="font-medium">用户名：</span>{{ account.username }}</div>
        <div><span class="font-medium">邮箱：</span>{{ account.email }}</div>
        <div><span class="font-medium">管理员：</span>{{ account.is_admin ? '是' : '否' }}</div>
        <div><span class="font-medium">注册时间：</span>{{ formatDate(account.created_at) }}</div>
      </div>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6 space-y-4">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">修改密码</h2>
      <input v-model="form.current_password" type="password" placeholder="当前密码" class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2" />
      <input v-model="form.new_password" type="password" placeholder="新密码（至少6位）" class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2" />
      <input v-model="form.confirm_password" type="password" placeholder="确认新密码" class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2" />
      <BaseButton :loading="saving" :disabled="saving" @click="submitPasswordChange">{{ saving ? '提交中...' : '修改密码' }}</BaseButton>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import { useToast } from '../composables/useToast'

const toast = useToast()
const loading = ref(true)
const saving = ref(false)
const account = reactive({ id: null, username: '', email: '', is_admin: false, created_at: '' })
const form = reactive({ current_password: '', new_password: '', confirm_password: '' })

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : '-'
}

async function loadAccount() {
  loading.value = true
  try {
    const res = await client.get('/account')
    Object.assign(account, res.data)
  } catch (e) {
    toast.error(e.response?.data?.error || '加载账户信息失败')
  } finally {
    loading.value = false
  }
}

async function submitPasswordChange() {
  if (!form.current_password.trim()) return toast.error('请输入当前密码')
  if (!form.new_password.trim()) return toast.error('请输入新密码')
  if (form.new_password.length < 6) return toast.error('新密码长度不能少于6位')
  if (form.new_password !== form.confirm_password) return toast.error('两次输入的新密码不一致')

  saving.value = true
  try {
    const res = await client.put('/account/password', {
      current_password: form.current_password,
      new_password: form.new_password,
    })
    form.current_password = ''
    form.new_password = ''
    form.confirm_password = ''
    toast.success(res.data.message || '密码修改成功')
  } catch (e) {
    toast.error(e.response?.data?.error || '密码修改失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadAccount)
</script>
```

在 `frontend/src/router/index.js` 增加：

```javascript
{ path: '/account', name: 'Account', component: () => import('../views/AccountView.vue'), meta: { auth: true } },
```

在 `frontend/src/components/NavBar.vue` 用户菜单增加：

```vue
<MenuItem v-slot="{ active }">
  <router-link
    to="/account"
    :class="[
      'block w-full text-left px-4 py-2 text-sm',
      active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
    ]"
  >账户设置</router-link>
</MenuItem>
```

在 `frontend/src/components/MobileNav.vue` 更多菜单增加：

```vue
<router-link
  to="/account"
  @click="showMore = false"
  class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
>账户设置</router-link>
```

- [ ] **Step 3: 运行前端构建验证**

Run:
```bash
npm run build
```

Workdir:
```bash
frontend
```

Expected: PASS。

- [ ] **Step 4: 提交 Task 3**

```bash
git add frontend/src/views/AccountView.vue frontend/src/router/index.js frontend/src/components/NavBar.vue frontend/src/components/MobileNav.vue
git commit -m "feat: add account page for self password updates"
```

### Task 4: 新增用户管理页并接入管理员导航

**Files:**
- Create: `frontend/src/views/AdminUsersView.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/components/NavBar.vue`
- Modify: `frontend/src/components/MobileNav.vue`
- Reuse: `frontend/src/components/BaseModal.vue`

- [ ] **Step 1: 实现管理员用户管理页面**

创建 `frontend/src/views/AdminUsersView.vue`：

```vue
<template>
  <div class="space-y-6">
    <div>
      <router-link to="/admin/banks" class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">返回管理入口</router-link>
      <h1 class="mt-1 text-2xl font-bold text-gray-900 dark:text-white">用户管理</h1>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <div v-if="loading" class="text-sm text-gray-500 dark:text-gray-400">加载中...</div>
      <div v-else-if="users.length === 0" class="text-sm text-gray-500 dark:text-gray-400">暂无用户</div>
      <div v-else class="space-y-3">
        <div v-for="user in users" :key="user.id" class="rounded-card border border-gray-200 dark:border-slate-700 px-4 py-3 flex items-center justify-between gap-4">
          <div class="min-w-0">
            <div class="font-medium text-gray-900 dark:text-white">{{ user.username }}</div>
            <div class="text-sm text-gray-500 dark:text-gray-400">{{ user.email }}</div>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-400 dark:text-gray-500">{{ user.is_admin ? '管理员' : '普通用户' }}</span>
            <BaseButton size="sm" @click="openResetModal(user)">重置密码</BaseButton>
          </div>
        </div>
      </div>
    </div>

    <BaseModal :open="modal.open" title="重置用户密码" max-width="md" @close="closeModal">
      <div class="space-y-4">
        <div class="text-sm text-gray-600 dark:text-gray-300">正在为用户 <span class="font-semibold">{{ modal.username }}</span> 重置密码</div>
        <input v-model="modal.new_password" type="password" placeholder="新密码（至少6位）" class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2" />
        <input v-model="modal.confirm_password" type="password" placeholder="确认新密码" class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2" />
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="closeModal">取消</BaseButton>
        <BaseButton :loading="saving" :disabled="saving" @click="submitReset">{{ saving ? '提交中...' : '确认重置' }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import { useToast } from '../composables/useToast'

const toast = useToast()
const loading = ref(true)
const saving = ref(false)
const users = ref([])
const modal = reactive({ open: false, user_id: null, username: '', new_password: '', confirm_password: '' })

async function loadUsers() {
  loading.value = true
  try {
    const res = await client.get('/admin/users')
    users.value = res.data || []
  } catch (e) {
    toast.error(e.response?.data?.error || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function openResetModal(user) {
  modal.open = true
  modal.user_id = user.id
  modal.username = user.username
  modal.new_password = ''
  modal.confirm_password = ''
}

function closeModal() {
  modal.open = false
  modal.user_id = null
  modal.username = ''
  modal.new_password = ''
  modal.confirm_password = ''
}

async function submitReset() {
  if (!modal.new_password.trim()) return toast.error('请输入新密码')
  if (modal.new_password.length < 6) return toast.error('新密码长度不能少于6位')
  if (modal.new_password !== modal.confirm_password) return toast.error('两次输入的新密码不一致')

  saving.value = true
  try {
    const res = await client.put(`/admin/users/${modal.user_id}/password`, { new_password: modal.new_password })
    toast.success(res.data.message || '密码已重置')
    closeModal()
  } catch (e) {
    toast.error(e.response?.data?.error || '重置密码失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadUsers)
</script>
```

在 `frontend/src/router/index.js` 增加：

```javascript
{ path: '/admin/users', name: 'AdminUsers', component: () => import('../views/AdminUsersView.vue'), meta: { auth: true, admin: true } },
```

在 `frontend/src/components/NavBar.vue` 管理菜单增加：

```vue
<MenuItem v-slot="{ active }">
  <router-link
    to="/admin/users"
    :class="[
      'block w-full text-left px-4 py-2 text-sm',
      active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
    ]"
  >用户管理</router-link>
</MenuItem>
```

在 `frontend/src/components/MobileNav.vue` 更多菜单增加：

```vue
<router-link
  v-if="authStore.isAdmin"
  to="/admin/users"
  @click="showMore = false"
  class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
>用户管理</router-link>
```

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

- [ ] **Step 3: 提交 Task 4**

```bash
git add frontend/src/views/AdminUsersView.vue frontend/src/router/index.js frontend/src/components/NavBar.vue frontend/src/components/MobileNav.vue
git commit -m "feat: add admin user password reset page"
```

### Task 5: 全量验证与交付前检查

**Files:**
- Modify: 无

- [ ] **Step 1: 运行后端测试**

Run:
```bash
pytest backend/tests/test_account_password_api.py backend/tests/test_admin_users_api.py -v
```

Expected: PASS。

- [ ] **Step 2: 运行全量后端测试**

Run:
```bash
pytest
```

Expected: PASS。

- [ ] **Step 3: 运行前端构建**

Run:
```bash
npm run build
```

Workdir:
```bash
frontend
```

Expected: PASS。

- [ ] **Step 4: 做最小手工联调**

Run the app, then verify:

```text
1. 管理员登录后可在导航看到“用户管理”
2. 管理员可打开用户列表并为普通用户重置密码
3. 普通用户可打开“账户设置”页面
4. 普通用户输入旧密码后可成功修改密码
5. 旧密码登录失败，新密码登录成功
```

- [ ] **Step 5: 提交最终收尾说明（如有必要）**

```bash
git status --short
```

Expected: 工作区干净；若还有文档补充，则提交：

```bash
git add <changed-files>
git commit -m "docs: polish password management rollout notes"
```
