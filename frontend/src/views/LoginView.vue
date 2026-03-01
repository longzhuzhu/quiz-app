<template>
  <div class="flex min-h-screen items-center justify-center bg-gradient-to-br from-primary-50 via-white to-sky-50 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900 -m-6 px-4">
    <div class="w-full max-w-md">
      <!-- 品牌标识 -->
      <div class="mb-8 text-center">
        <div class="text-4xl mb-3">🎯</div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">CIPT 备考</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">认证信息隐私技术师考试</p>
      </div>

      <!-- 登录卡片 -->
      <div class="rounded-2xl bg-white dark:bg-slate-800 p-8 shadow-lg">
        <h2 class="mb-6 text-center text-xl font-semibold text-gray-900 dark:text-white">登录</h2>

        <!-- 错误提示 -->
        <div v-if="error" class="mb-4 rounded-lg bg-rose-50 dark:bg-rose-900/20 p-3 text-sm text-rose-600 dark:text-rose-400">
          {{ error }}
        </div>

        <form @submit.prevent="handleLogin" class="space-y-5">
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

          <!-- 密码 -->
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">密码</label>
            <div class="relative">
              <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <LockClosedIcon class="h-5 w-5 text-gray-400" />
              </div>
              <input v-model="password" :type="showPassword ? 'text' : 'password'" required placeholder="请输入密码"
                class="w-full rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 pl-10 pr-10 py-2.5 text-gray-900 dark:text-white placeholder-gray-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 transition-colors" />
              <button type="button" @click="showPassword = !showPassword"
                class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-500">
                <EyeIcon v-if="!showPassword" class="h-5 w-5" />
                <EyeSlashIcon v-else class="h-5 w-5" />
              </button>
            </div>
          </div>

          <BaseButton type="submit" variant="primary" size="lg" :loading="loading" :disabled="loading" class="w-full">
            登录
          </BaseButton>
        </form>

        <p class="mt-6 text-center text-sm text-gray-600 dark:text-gray-400">
          没有账号？<router-link to="/register" class="font-medium text-primary-600 hover:text-primary-500">注册</router-link>
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
import { UserIcon, LockClosedIcon, EyeIcon, EyeSlashIcon } from '@heroicons/vue/24/outline'

const authStore = useAuthStore()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const showPassword = ref(false)

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    await authStore.login(username.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = e.response?.data?.error || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
