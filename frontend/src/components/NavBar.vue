<template>
  <nav class="sticky top-0 z-30 border-b border-gray-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md">
    <div class="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
      <!-- 左侧品牌 -->
      <router-link to="/" class="flex items-center gap-2 text-lg font-bold text-primary-600">
        <span>🎯</span>
        <span>CIPT 备考</span>
      </router-link>

      <!-- 中部导航链接（仅桌面端） -->
      <div class="hidden md:flex items-center gap-1">
        <router-link
          to="/"
          exact-active-class="text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/30"
          class="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
        >首页</router-link>
        <router-link
          to="/wrong"
          active-class="text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/30"
          class="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
        >错题本</router-link>
        <router-link
          to="/history"
          active-class="text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/30"
          class="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
        >历史</router-link>
        <router-link
          to="/vocabulary"
          active-class="text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/30"
          class="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
        >单词本</router-link>
      </div>

      <!-- 右侧操作区 -->
      <div class="flex items-center gap-2">
        <!-- 管理员下拉菜单（仅桌面端） -->
        <div v-if="authStore.isAdmin" class="hidden md:block relative">
          <Menu as="div" class="relative">
            <MenuButton class="flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors">
              管理
              <ChevronDownIcon class="h-4 w-4" />
            </MenuButton>
            <transition
              enter-active-class="transition duration-100 ease-out"
              enter-from-class="transform scale-95 opacity-0"
              enter-to-class="transform scale-100 opacity-100"
              leave-active-class="transition duration-75 ease-in"
              leave-from-class="transform scale-100 opacity-100"
              leave-to-class="transform scale-95 opacity-0"
            >
              <MenuItems class="absolute right-0 mt-2 w-48 rounded-card bg-white dark:bg-slate-800 shadow-lg ring-1 ring-black/5 focus:outline-none overflow-hidden">
                <MenuItem v-slot="{ active }">
                  <router-link
                    to="/admin/banks"
                    :class="[
                      'block w-full text-left px-4 py-2 text-sm',
                      active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
                    ]"
                  >题库管理</router-link>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <router-link
                    to="/import-jobs"
                    :class="[
                      'block w-full text-left px-4 py-2 text-sm',
                      active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
                    ]"
                  >导入任务</router-link>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <router-link
                    to="/admin/settings"
                    :class="[
                      'block w-full text-left px-4 py-2 text-sm',
                      active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
                    ]"
                  >系统设置</router-link>
                </MenuItem>
                <MenuItem v-slot="{ active }">
                  <router-link
                    to="/admin/users"
                    :class="[
                      'block w-full text-left px-4 py-2 text-sm',
                      active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
                    ]"
                  >用户管理</router-link>
                </MenuItem>
              </MenuItems>
            </transition>
          </Menu>
        </div>

        <!-- 暗色模式切换 -->
        <button @click="darkMode.toggle()" class="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-slate-800 transition-colors">
          <SunIcon v-if="darkMode.isDark.value" class="h-5 w-5" />
          <MoonIcon v-else class="h-5 w-5" />
        </button>

        <!-- 用户下拉菜单 -->
        <Menu as="div" class="relative">
          <MenuButton class="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors">
            {{ authStore.user?.username }}
            <ChevronDownIcon class="h-4 w-4" />
          </MenuButton>
          <transition
            enter-active-class="transition duration-100 ease-out"
            enter-from-class="transform scale-95 opacity-0"
            enter-to-class="transform scale-100 opacity-100"
            leave-active-class="transition duration-75 ease-in"
            leave-from-class="transform scale-100 opacity-100"
            leave-to-class="transform scale-95 opacity-0"
          >
            <MenuItems class="absolute right-0 mt-2 w-36 rounded-card bg-white dark:bg-slate-800 shadow-lg ring-1 ring-black/5 focus:outline-none overflow-hidden">
              <MenuItem v-slot="{ active }">
                <router-link
                  to="/account"
                  :class="[
                    'block w-full text-left px-4 py-2 text-sm',
                    active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
                  ]"
                >账户设置</router-link>
              </MenuItem>
              <MenuItem v-slot="{ active }">
                <button
                  @click="handleLogout"
                  :class="[
                    'block w-full text-left px-4 py-2 text-sm',
                    active ? 'bg-gray-100 dark:bg-slate-700 text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'
                  ]"
                >退出登录</button>
              </MenuItem>
            </MenuItems>
          </transition>
        </Menu>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useDarkMode } from '../composables/useDarkMode'
import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/vue'
import { SunIcon, MoonIcon, ChevronDownIcon } from '@heroicons/vue/24/outline'

const authStore = useAuthStore()
const router = useRouter()
const darkMode = useDarkMode()

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>
