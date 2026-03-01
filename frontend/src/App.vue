<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors">
    <NavBar v-if="authStore.isLoggedIn" />
    <main class="mx-auto max-w-6xl px-4 py-6 pb-24 md:pb-6">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
    <MobileNav v-if="authStore.isLoggedIn" />
    <ToastNotification />
  </div>
</template>

<script setup>
import NavBar from './components/NavBar.vue'
import MobileNav from './components/MobileNav.vue'
import ToastNotification from './components/ToastNotification.vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()
</script>
