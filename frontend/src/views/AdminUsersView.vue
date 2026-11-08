<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <router-link
          to="/exams"
          class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline"
        >
          <ArrowLeftIcon class="h-4 w-4" />
          返回管理首页
        </router-link>
        <h1 class="mt-1 text-2xl font-bold text-gray-900 dark:text-white">用户管理</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          创建和停用账号、调整管理员权限、重置密码
        </p>
      </div>
      <BaseButton :disabled="submitting" @click="openCreateModal">创建用户</BaseButton>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <div v-if="loading" class="py-8 text-sm text-gray-500 dark:text-gray-400">加载中...</div>
      <div v-else-if="loadError" class="py-8">
        <div class="rounded-card border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300">
          <p>{{ loadError }}</p>
          <BaseButton class="mt-3" size="sm" variant="secondary" @click="fetchUsers">重试</BaseButton>
        </div>
      </div>
      <div v-else-if="users.length === 0" class="py-8 text-sm text-gray-500 dark:text-gray-400">暂无用户</div>
      <div v-else class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="text-left text-gray-500 dark:text-gray-400">
            <tr class="border-b border-gray-200 dark:border-slate-700">
              <th class="py-3 pr-4 font-medium">用户名</th>
              <th class="py-3 pr-4 font-medium">邮箱</th>
              <th class="py-3 pr-4 font-medium">角色</th>
              <th class="py-3 pr-4 font-medium">状态</th>
              <th class="py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="user in users"
              :key="user.id"
              class="border-b border-gray-100 dark:border-slate-700/70 last:border-b-0"
            >
              <td class="py-3 pr-4 text-gray-900 dark:text-white">
                {{ user.username }}
                <span v-if="user.id === currentUserId" class="ml-1 text-xs text-gray-400 dark:text-gray-500">（我）</span>
              </td>
              <td class="py-3 pr-4 text-gray-600 dark:text-gray-300">{{ user.email }}</td>
              <td class="py-3 pr-4">
                <span
                  class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="user.is_admin
                    ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                    : 'bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-gray-200'"
                >
                  {{ user.is_admin ? '管理员' : '普通用户' }}
                </span>
              </td>
              <td class="py-3 pr-4">
                <span
                  class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="user.is_active
                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                    : 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300'"
                >
                  {{ user.is_active ? '已启用' : '已停用' }}
                </span>
              </td>
              <td class="py-3">
                <div class="flex flex-wrap justify-end gap-2">
                  <BaseButton size="sm" variant="secondary" :disabled="submitting" @click="openResetModal(user)">
                    重置密码
                  </BaseButton>
                  <BaseButton
                    size="sm"
                    variant="secondary"
                    :disabled="submitting || isSelf(user)"
                    :title="isSelf(user) ? '不能停用自己的账号' : ''"
                    @click="toggleActive(user)"
                  >
                    {{ user.is_active ? '停用' : '启用' }}
                  </BaseButton>
                  <BaseButton
                    size="sm"
                    variant="secondary"
                    :disabled="submitting || (isSelf(user) && user.is_admin)"
                    :title="isSelf(user) && user.is_admin ? '不能取消自己的管理员权限' : ''"
                    @click="toggleAdmin(user)"
                  >
                    {{ user.is_admin ? '取消管理员' : '设为管理员' }}
                  </BaseButton>
                  <BaseButton
                    size="sm"
                    variant="danger"
                    :disabled="submitting || isSelf(user)"
                    :title="isSelf(user) ? '不能删除自己的账号' : ''"
                    @click="askDelete(user)"
                  >
                    删除
                  </BaseButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <BaseModal :open="showCreateModal" title="创建用户" @close="closeCreateModal">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">用户名</label>
          <input
            v-model="createForm.username"
            type="text"
            autocomplete="off"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">邮箱</label>
          <input
            v-model="createForm.email"
            type="email"
            autocomplete="off"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">初始密码</label>
          <input
            v-model="createForm.password"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">确认密码</label>
          <input
            v-model="createForm.confirm_password"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input
            v-model="createForm.is_admin"
            type="checkbox"
            class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          />
          创建为管理员
        </label>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          请把初始密码告知该用户，由其在「账户设置」中自行修改。
        </p>
        <p v-if="createError" class="text-sm text-rose-600 dark:text-rose-400">{{ createError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" :disabled="submitting" @click="closeCreateModal">取消</BaseButton>
        <BaseButton :loading="submitting" :disabled="submitting" @click="submitCreateUser">
          {{ submitting ? '创建中...' : '创建' }}
        </BaseButton>
      </template>
    </BaseModal>

    <BaseModal :open="showResetModal" title="重置密码" @close="closeResetModal">
      <div class="space-y-4">
        <div class="text-sm text-gray-600 dark:text-gray-300">
          目标用户名：<span class="font-medium text-gray-900 dark:text-white">{{ selectedUser?.username || '-' }}</span>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">新密码</label>
          <input
            v-model="resetForm.new_password"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">确认新密码</label>
          <input
            v-model="resetForm.confirm_password"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          已登录的会话不会立即失效，最长可使用到登录凭证过期。
        </p>
        <p v-if="resetError" class="text-sm text-rose-600 dark:text-rose-400">{{ resetError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" :disabled="submitting" @click="closeResetModal">取消</BaseButton>
        <BaseButton :loading="submitting" :disabled="submitting" @click="submitResetPassword">
          {{ submitting ? '重置中...' : '确认重置' }}
        </BaseButton>
      </template>
    </BaseModal>

    <ConfirmDialog
      :open="!!pendingDelete"
      title="删除用户"
      :message="deleteMessage"
      confirm-text="确认删除"
      danger
      @confirm="confirmDelete"
      @cancel="pendingDelete = null"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowLeftIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import { validateNewPasswordWithConfirmation } from '../utils/passwordValidation'

const toast = useToast()
const authStore = useAuthStore()
const users = ref([])
const loading = ref(true)
const loadError = ref('')
const submitting = ref(false)

const showCreateModal = ref(false)
const createError = ref('')
const createForm = ref({ username: '', email: '', password: '', confirm_password: '', is_admin: false })

const showResetModal = ref(false)
const selectedUser = ref(null)
const resetError = ref('')
const resetForm = ref({ new_password: '', confirm_password: '' })

const pendingDelete = ref(null)

const currentUserId = computed(() => authStore.user?.id)

const deleteMessage = computed(() =>
  pendingDelete.value
    ? `将永久删除用户「${pendingDelete.value.username}」及其拥有的全部考试项目、题库、练习与错题记录。此操作不可撤销。`
    : ''
)

function isSelf(user) {
  return user.id === currentUserId.value
}

function errorText(e, fallback) {
  return e.response?.data?.detail || fallback
}

async function fetchUsers() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await client.get('/admin/users')
    users.value = res.data || []
  } catch (e) {
    loadError.value = errorText(e, '加载用户失败，请稍后重试')
    users.value = []
    toast.error(loadError.value)
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  if (submitting.value) return
  createForm.value = { username: '', email: '', password: '', confirm_password: '', is_admin: false }
  createError.value = ''
  showCreateModal.value = true
}

function closeCreateModal() {
  if (submitting.value) return
  showCreateModal.value = false
  createError.value = ''
}

function validateCreateForm() {
  if (!createForm.value.username.trim()) return '用户名不能为空'
  if (!createForm.value.email.trim()) return '邮箱不能为空'
  return validateNewPasswordWithConfirmation(createForm.value.password, createForm.value.confirm_password)
}

async function submitCreateUser() {
  createError.value = validateCreateForm()
  if (createError.value) return

  submitting.value = true
  try {
    await client.post('/admin/users', {
      username: createForm.value.username.trim(),
      email: createForm.value.email.trim(),
      password: createForm.value.password,
      is_admin: createForm.value.is_admin,
    })
    toast.success('用户已创建')
    showCreateModal.value = false
    await fetchUsers()
  } catch (e) {
    createError.value = errorText(e, '创建用户失败')
    toast.error(createError.value)
  } finally {
    submitting.value = false
  }
}

function openResetModal(user) {
  if (submitting.value) return
  selectedUser.value = user
  resetForm.value = { new_password: '', confirm_password: '' }
  resetError.value = ''
  showResetModal.value = true
}

function closeResetModal() {
  if (submitting.value) return
  showResetModal.value = false
  selectedUser.value = null
  resetError.value = ''
}

async function submitResetPassword() {
  resetError.value = validateNewPasswordWithConfirmation(
    resetForm.value.new_password,
    resetForm.value.confirm_password
  )
  if (resetError.value || !selectedUser.value) return

  submitting.value = true
  try {
    await client.put(`/admin/users/${selectedUser.value.id}/password`, {
      new_password: resetForm.value.new_password,
    })
    toast.success('密码已重置')
    showResetModal.value = false
    selectedUser.value = null
  } catch (e) {
    resetError.value = errorText(e, '重置密码失败')
    toast.error(resetError.value)
  } finally {
    submitting.value = false
  }
}

async function patchUser(user, payload) {
  submitting.value = true
  try {
    await client.patch(`/admin/users/${user.id}`, payload)
    await fetchUsers()
    return true
  } catch (e) {
    toast.error(errorText(e, '更新用户失败'))
    return false
  } finally {
    submitting.value = false
  }
}

async function toggleActive(user) {
  if (submitting.value || isSelf(user)) return
  const active = !user.is_active
  if (await patchUser(user, { is_active: active })) {
    toast.success(active ? '账号已启用' : '账号已停用')
  }
}

async function toggleAdmin(user) {
  if (submitting.value) return
  if (isSelf(user) && user.is_admin) return
  const isAdmin = !user.is_admin
  if (await patchUser(user, { is_admin: isAdmin })) {
    toast.success(isAdmin ? '已设为管理员' : '已取消管理员权限')
  }
}

function askDelete(user) {
  if (submitting.value || isSelf(user)) return
  pendingDelete.value = user
}

async function confirmDelete() {
  const user = pendingDelete.value
  if (!user) return
  submitting.value = true
  try {
    await client.delete(`/admin/users/${user.id}`)
    toast.success('用户已删除')
    pendingDelete.value = null
    await fetchUsers()
  } catch (e) {
    toast.error(errorText(e, '删除用户失败'))
  } finally {
    submitting.value = false
  }
}

onMounted(fetchUsers)
</script>
