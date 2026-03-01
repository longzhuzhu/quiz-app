<template>
  <div class="min-h-screen bg-gray-50">
    <NavBar v-if="authStore.isLoggedIn" />
    <main class="mx-auto max-w-5xl px-4 py-6">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import NavBar from './components/NavBar.vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()
</script>
