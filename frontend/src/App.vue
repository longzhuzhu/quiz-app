<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors">
    <NavBar v-if="showAuthenticatedShell" />
    <main class="mx-auto max-w-6xl px-4 py-6 pb-24 md:pb-6">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
    <!-- 答题页自带底部操作条，隐藏全局底栏避免双栏叠加 -->
    <MobileNav v-if="showAuthenticatedShell && !route.meta.quizFocus" />
    <ToastNotification />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import NavBar from './components/NavBar.vue'
import MobileNav from './components/MobileNav.vue'
import ToastNotification from './components/ToastNotification.vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()
const route = useRoute()

const showAuthenticatedShell = computed(() => authStore.isLoggedIn && !route.meta.guest)
</script>
