<template>
  <div class="space-y-6">
    <div>
      <router-link
        to="/admin/banks"
        class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline"
      >
        <ArrowLeftIcon class="h-4 w-4" />
        返回管理首页
      </router-link>
      <h1 class="mt-1 text-2xl font-bold text-gray-900 dark:text-white">用户管理</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">查看用户信息并重置用户密码</p>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <div v-if="loading" class="py-8 text-sm text-gray-500 dark:text-gray-400">加载中...</div>
      <div v-else-if="users.length === 0" class="py-8 text-sm text-gray-500 dark:text-gray-400">暂无用户</div>
      <div v-else class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="text-left text-gray-500 dark:text-gray-400">
            <tr class="border-b border-gray-200 dark:border-slate-700">
              <th class="py-3 pr-4 font-medium">用户名</th>
              <th class="py-3 pr-4 font-medium">邮箱</th>
              <th class="py-3 pr-4 font-medium">角色</th>
              <th class="py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="user in users"
              :key="user.id"
              class="border-b border-gray-100 dark:border-slate-700/70 last:border-b-0"
            >
              <td class="py-3 pr-4 text-gray-900 dark:text-white">{{ user.username }}</td>
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
              <td class="py-3 text-right">
                <BaseButton size="sm" variant="secondary" @click="openResetModal(user)">
                  重置密码
                </BaseButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <BaseModal :open="showResetModal" title="重置密码" @close="closeResetModal">
      <div class="space-y-4">
        <div class="text-sm text-gray-600 dark:text-gray-300">
          目标用户名：<span class="font-medium text-gray-900 dark:text-white">{{ selectedUser?.username || '-' }}</span>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">新密码</label>
          <input
            v-model="form.new_password"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">确认新密码</label>
          <input
            v-model="form.confirm_password"
            type="password"
            autocomplete="new-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
        </div>
        <p v-if="validationError" class="text-sm text-rose-600 dark:text-rose-400">{{ validationError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="closeResetModal">取消</BaseButton>
        <BaseButton :loading="submitting" :disabled="submitting" @click="submitResetPassword">
          {{ submitting ? '重置中...' : '确认重置' }}
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ArrowLeftIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import { useToast } from '../composables/useToast'

const toast = useToast()
const users = ref([])
const loading = ref(true)
const submitting = ref(false)
const showResetModal = ref(false)
const selectedUser = ref(null)
const validationError = ref('')
const form = ref({
  new_password: '',
  confirm_password: '',
})

async function fetchUsers() {
  loading.value = true
  try {
    const res = await client.get('/admin/users')
    users.value = res.data || []
  } catch (e) {
    toast.error(e.response?.data?.error || '加载用户失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.value.new_password = ''
  form.value.confirm_password = ''
  validationError.value = ''
}

function openResetModal(user) {
  selectedUser.value = user
  resetForm()
  showResetModal.value = true
}

function closeResetModal() {
  showResetModal.value = false
  selectedUser.value = null
  resetForm()
}

function validateResetForm() {
  if (!form.value.new_password) return '新密码不能为空'
  if (form.value.new_password.length < 6) return '新密码至少 6 位'
  if (form.value.new_password !== form.value.confirm_password) return '两次输入的密码不一致'
  return ''
}

async function submitResetPassword() {
  validationError.value = validateResetForm()
  if (validationError.value || !selectedUser.value) return

  submitting.value = true
  try {
    await client.put(`/admin/users/${selectedUser.value.id}/password`, {
      new_password: form.value.new_password,
    })
    toast.success('密码已重置')
    closeResetModal()
  } catch (e) {
    toast.error(e.response?.data?.error || '重置密码失败')
  } finally {
    submitting.value = false
  }
}

onMounted(fetchUsers)
</script>
