<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">账户设置</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">查看账户信息并修改登录密码</p>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">账户信息</h2>
      <div v-if="loadingAccount" class="mt-4 text-sm text-gray-500 dark:text-gray-400">加载中...</div>
      <div v-else-if="account" class="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <div class="text-xs text-gray-500 dark:text-gray-400">用户名</div>
          <div class="text-sm text-gray-900 dark:text-white">{{ account.username }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500 dark:text-gray-400">邮箱</div>
          <div class="text-sm text-gray-900 dark:text-white">{{ account.email }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500 dark:text-gray-400">账号类型</div>
          <div class="text-sm text-gray-900 dark:text-white">{{ account.is_admin ? '管理员' : '普通用户' }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500 dark:text-gray-400">注册时间</div>
          <div class="text-sm text-gray-900 dark:text-white">{{ createdAtText }}</div>
        </div>
      </div>
      <div v-else class="mt-4 text-sm text-gray-500 dark:text-gray-400">暂无账户信息</div>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">修改密码</h2>

      <form class="mt-4 space-y-4" @submit.prevent="handleChangePassword">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">当前密码</label>
          <input
            v-model="form.current_password"
            type="password"
            autocomplete="current-password"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"
          />
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

        <BaseButton type="submit" :loading="savingPassword" :disabled="savingPassword">
          {{ savingPassword ? '提交中...' : '更新密码' }}
        </BaseButton>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import { useToast } from '../composables/useToast'

const toast = useToast()
const loadingAccount = ref(true)
const savingPassword = ref(false)
const account = ref(null)
const validationError = ref('')
const form = ref({
  current_password: '',
  new_password: '',
  confirm_password: '',
})

const createdAtText = computed(() => {
  if (!account.value?.created_at) return '-'
  const date = new Date(account.value.created_at)
  if (Number.isNaN(date.getTime())) return account.value.created_at
  return date.toLocaleString()
})

onMounted(async () => {
  try {
    const res = await client.get('/account')
    account.value = res.data
  } catch {
    toast.error('加载账户信息失败')
  } finally {
    loadingAccount.value = false
  }
})

function clearPasswordForm() {
  form.value.current_password = ''
  form.value.new_password = ''
  form.value.confirm_password = ''
}

function validateForm() {
  if (!form.value.current_password) {
    return '当前密码不能为空'
  }
  if (!form.value.new_password) {
    return '新密码不能为空'
  }
  if (form.value.new_password.length < 6) {
    return '新密码至少 6 位'
  }
  if (form.value.new_password !== form.value.confirm_password) {
    return '两次输入的密码不一致'
  }
  return ''
}

async function handleChangePassword() {
  validationError.value = validateForm()
  if (validationError.value) return

  savingPassword.value = true
  try {
    await client.put('/account/password', {
      current_password: form.value.current_password,
      new_password: form.value.new_password,
    })
    clearPasswordForm()
    toast.success('密码修改成功')
  } catch (e) {
    toast.error(e.response?.data?.error || '密码修改失败')
  } finally {
    savingPassword.value = false
  }
}
</script>
