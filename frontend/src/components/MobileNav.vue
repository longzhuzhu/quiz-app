<template>
  <nav class="fixed bottom-0 left-0 right-0 z-40 border-t border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 md:hidden">
    <div class="flex items-center justify-around px-2" style="padding-bottom: env(safe-area-inset-bottom, 0)">
      <router-link
        v-for="tab in tabs"
        :key="tab.to"
        :to="tab.to"
        class="flex flex-col items-center gap-0.5 px-3 py-2 text-xs transition-colors"
        :class="isActive(tab) ? 'text-primary-600 dark:text-primary-400' : 'text-gray-400 dark:text-gray-500'"
      >
        <component
          :is="tab.icon"
          class="h-6 w-6 transition-transform"
          :class="isActive(tab) ? '-translate-y-0.5' : ''"
        />
        <span>{{ tab.label }}</span>
      </router-link>

      <!-- 更多按钮 -->
      <button
        @click="showMore = !showMore"
        class="flex flex-col items-center gap-0.5 px-3 py-2 text-xs transition-colors"
        :class="showMore ? 'text-primary-600 dark:text-primary-400' : 'text-gray-400 dark:text-gray-500'"
      >
        <EllipsisHorizontalIcon class="h-6 w-6" />
        <span>更多</span>
      </button>
    </div>

    <!-- 更多菜单（弹出浮层） -->
    <transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="translate-y-4 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="translate-y-4 opacity-0"
    >
      <div
        v-if="showMore"
        class="absolute bottom-full left-0 right-0 mb-0 rounded-t-2xl bg-white dark:bg-slate-800 shadow-lg border-t border-gray-200 dark:border-slate-700 p-4 space-y-2"
      >
        <router-link
          to="/account"
          @click="showMore = false"
          class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
        >账户设置</router-link>
        <router-link
          v-if="authStore.isAdmin"
          to="/admin/banks"
          @click="showMore = false"
          class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
        >题库管理</router-link>
        <router-link
          v-if="authStore.isAdmin"
          to="/import-jobs"
          @click="showMore = false"
          class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
        >导入任务</router-link>
        <router-link
          v-if="authStore.isAdmin"
          to="/admin/settings"
          @click="showMore = false"
          class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
        >系统设置</router-link>
        <router-link
          v-if="authStore.isAdmin"
          to="/admin/users"
          @click="showMore = false"
          class="block rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
        >用户管理</router-link>
        <button
          @click="darkMode.toggle(); showMore = false"
          class="block w-full rounded-lg px-4 py-3 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
        >
          {{ darkMode.isDark.value ? '切换到浅色模式' : '切换到深色模式' }}
        </button>
        <button
          @click="handleLogout"
          class="block w-full rounded-lg px-4 py-3 text-left text-sm text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20"
        >退出登录</button>
      </div>
    </transition>
  </nav>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useDarkMode } from '../composables/useDarkMode'
import {
  HomeIcon,
  ExclamationCircleIcon,
  ClockIcon,
  BookOpenIcon,
  EllipsisHorizontalIcon
} from '@heroicons/vue/24/outline'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const darkMode = useDarkMode()
const showMore = ref(false)

const tabs = [
  { to: '/', label: '首页', icon: HomeIcon, exact: true },
  { to: '/wrong', label: '错题', icon: ExclamationCircleIcon },
  { to: '/history', label: '历史', icon: ClockIcon },
  { to: '/vocabulary', label: '单词', icon: BookOpenIcon },
]

function isActive(tab) {
  if (tab.exact) {
    return route.path === tab.to
  }
  return route.path.startsWith(tab.to)
}

function handleLogout() {
  showMore.value = false
  authStore.logout()
  router.push('/login')
}
</script>
