<template>
  <nav class="border-b border-gray-200 bg-white">
    <div class="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
      <router-link to="/" class="text-lg font-bold text-indigo-600">CIPT 备考</router-link>
      <div class="flex items-center gap-4">
        <router-link to="/" class="text-sm text-gray-600 hover:text-indigo-600">首页</router-link>
        <router-link to="/wrong" class="text-sm text-gray-600 hover:text-indigo-600">错题本</router-link>
        <router-link to="/history" class="text-sm text-gray-600 hover:text-indigo-600">历史</router-link>
        <router-link to="/vocabulary" class="text-sm text-gray-600 hover:text-indigo-600">单词本</router-link>
        <router-link v-if="authStore.isAdmin" to="/admin/banks" class="text-sm text-gray-600 hover:text-indigo-600">管理</router-link>
        <router-link v-if="authStore.isAdmin" to="/admin/settings" class="text-sm text-gray-600 hover:text-indigo-600">设置</router-link>
        <span class="text-sm text-gray-400">{{ authStore.user?.username }}</span>
        <button @click="handleLogout" class="text-sm text-red-500 hover:text-red-700">退出</button>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const router = useRouter()

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>
