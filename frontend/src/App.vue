<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors">
    <NavBar v-if="showAuthenticatedShell" :class="{ 'hidden md:block': prototypeStudy }" />
    <main :class="prototypeStudy ? 'mx-auto max-w-6xl md:px-4 md:py-6' : 'mx-auto max-w-6xl px-4 py-6 pb-24 md:pb-6'">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
    <MobileNav v-if="showAuthenticatedShell && !prototypeStudy" />
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

const prototypeStudy = computed(() => import.meta.env.DEV && import.meta.env.VITE_VOCAB_PROTOTYPE === '1'
  && route.name === 'ExamVocabulary' && ['study', 'result'].includes(route.query.screen))

const showAuthenticatedShell = computed(() => authStore.isLoggedIn && !route.meta.guest)
</script>

<!-- PROTOTYPE：移动端学习模式隐藏共享导航，桌面端仍使用原来的导航。 -->
