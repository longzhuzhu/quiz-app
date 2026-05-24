<template>
  <div class="flex min-h-screen items-center justify-center bg-gradient-to-br from-primary-50 via-white to-sky-50 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900 -m-6 px-4">
    <div class="w-full max-w-md">
      <!-- 品牌标识 -->
      <div class="mb-8 text-center">
        <div class="text-4xl mb-3">🎯</div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">备考助手</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">通用考试项目练习与题库管理</p>
      </div>

      <!-- 注册卡片 -->
      <div class="rounded-2xl bg-white dark:bg-slate-800 p-8 shadow-lg">
        <h2 class="mb-6 text-center text-xl font-semibold text-gray-900 dark:text-white">注册</h2>

        <!-- 错误提示 -->
        <div v-if="error" class="mb-4 rounded-lg bg-rose-50 dark:bg-rose-900/20 p-3 text-sm text-rose-600 dark:text-rose-400">
          {{ error }}
        </div>

        <!-- 成功提示 -->
        <div v-if="success" class="mb-4 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 p-3 text-sm text-emerald-600 dark:text-emerald-400">
          {{ success }}
        </div>

        <form @submit.prevent="handleRegister" class="space-y-5">
          <!-- 用户名 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">用户名</label>
            <div class="relative">
              <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <UserIcon class="h-5 w-5 text-gray-400" />
              </div>
              <input v-model="username" type="text" required placeholder="请输入用户名"
                class="w-full rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 pl-10 pr-3 py-2.5 text-gray-900 dark:text-white placeholder-gray-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 transition-colors" />
            </div>
          </div>

          <!-- 邮箱 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">邮箱</label>
            <div class="relative">
              <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <EnvelopeIcon class="h-5 w-5 text-gray-400" />
              </div>
              <input v-model="email" type="email" required placeholder="请输入邮箱"
                class="w-full rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 pl-10 pr-3 py-2.5 text-gray-900 dark:text-white placeholder-gray-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 transition-colors" />
            </div>
          </div>

          <!-- 密码 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">密码</label>
            <div class="relative">
              <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <LockClosedIcon class="h-5 w-5 text-gray-400" />
              </div>
              <input v-model="password" :type="showPassword ? 'text' : 'password'" required minlength="6" placeholder="请输入密码（至少6位）"
                class="w-full rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 pl-10 pr-10 py-2.5 text-gray-900 dark:text-white placeholder-gray-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 transition-colors" />
              <button type="button" @click="showPassword = !showPassword"
                class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-500">
                <EyeIcon v-if="!showPassword" class="h-5 w-5" />
                <EyeSlashIcon v-else class="h-5 w-5" />
              </button>
            </div>
          </div>

          <BaseButton type="submit" variant="primary" size="lg" :loading="loading" :disabled="loading" class="w-full">
            注册
          </BaseButton>
        </form>

        <p class="mt-6 text-center text-sm text-gray-600 dark:text-gray-400">
          已有账号？<router-link to="/login" class="font-medium text-primary-600 hover:text-primary-500">登录</router-link>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import BaseButton from '../components/BaseButton.vue'
import { UserIcon, LockClosedIcon, EnvelopeIcon, EyeIcon, EyeSlashIcon } from '@heroicons/vue/24/outline'

const authStore = useAuthStore()
const router = useRouter()
const username = ref('')
const email = ref('')
const password = ref('')
const error = ref('')
const success = ref('')
const loading = ref(false)
const showPassword = ref(false)

async function handleRegister() {
  error.value = ''
  success.value = ''
  loading.value = true
  try {
    await authStore.register(username.value, email.value, password.value)
    success.value = '注册成功，请登录'
    setTimeout(() => router.push('/login'), 1500)
  } catch (e) {
    error.value = e.response?.data?.error || '注册失败'
  } finally {
    loading.value = false
  }
}
</script>
