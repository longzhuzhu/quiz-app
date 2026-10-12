<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors" :class="{ 'vocabulary-study-shell': route.meta.vocabularyStudy }">
    <NavBar v-if="showAuthenticatedShell" class="global-navigation" />
    <main class="app-main mx-auto max-w-6xl px-4 py-6 pb-24 md:pb-6">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" :key="studyRouteKey" />
        </transition>
      </router-view>
    </main>
    <MobileNav v-if="showAuthenticatedShell" class="global-navigation" />
    <ToastNotification />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NavBar from './components/NavBar.vue'
import MobileNav from './components/MobileNav.vue'
import ToastNotification from './components/ToastNotification.vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()

const showAuthenticatedShell = computed(() => authStore.isLoggedIn && !route.meta.guest)
const studyRouteKey = computed(() => route.meta.vocabularyStudy ? JSON.stringify([route.params.examSlug, route.query.scope, route.query.mastery, route.query.bank_id]) : undefined)
function storageChanged(event) {
  if (event.key !== 'token' && event.key !== 'user' && event.key !== null) return
  if (authStore.synchronizeSession()) router.replace(authStore.isLoggedIn ? '/' : '/login')
}
onMounted(() => window.addEventListener('storage', storageChanged))
onUnmounted(() => window.removeEventListener('storage', storageChanged))
</script>
