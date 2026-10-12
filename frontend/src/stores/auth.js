import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '../api/client'
import { invalidateStudyAccount } from '../features/vocabularyStudy/lifecycle.js'
import { clearBrowserStudyAccount } from '../features/vocabularyStudy/resume.js'
import { useToast } from '../composables/useToast'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const token = ref(localStorage.getItem('token') || '')
  let pendingCleanup = Promise.resolve()

  function cleanPreviousAccount(accountId) {
    const invalidated = invalidateStudyAccount()
    pendingCleanup = Promise.all([pendingCleanup, invalidated, clearBrowserStudyAccount(accountId)]).catch(() => {
      useToast().error('本地续学草稿未能清理，请清理本站浏览器数据。已保存的服务端掌握状态不受影响。')
    })
    return pendingCleanup
  }

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.is_admin || false)

  async function login(username, password) {
    const res = await client.post('/auth/login', { username, password })
    const oldAccountId = user.value?.id
    await cleanPreviousAccount(oldAccountId)
    token.value = res.data.access_token
    user.value = res.data.user
    localStorage.setItem('token', token.value)
    localStorage.setItem('user', JSON.stringify(user.value))
    await fetchMe()
  }

  async function register(username, email, password) {
    await client.post('/auth/register', { username, email, password })
  }

  function logout() {
    const oldAccountId = user.value?.id
    cleanPreviousAccount(oldAccountId)
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    import('./exam').then(({ useExamStore }) => useExamStore().reset())
  }

  async function fetchMe() {
    const expectedToken = token.value
    try {
      const res = await client.get('/auth/me')
      if (expectedToken !== token.value) return
      user.value = res.data
      localStorage.setItem('user', JSON.stringify(user.value))
    } catch {
      if (expectedToken === token.value) logout()
    }
  }

  function synchronizeSession() {
    const nextToken = localStorage.getItem('token') || ''
    let nextUser = null
    try { nextUser = JSON.parse(localStorage.getItem('user') || 'null') } catch { /* 不把损坏存储作为有效身份 */ }
    if (nextToken === token.value && nextUser?.id === user.value?.id) return false
    const oldAccountId = user.value?.id
    cleanPreviousAccount(oldAccountId)
    token.value = nextToken; user.value = nextUser
    import('./exam').then(({ useExamStore }) => useExamStore().reset())
    return true
  }

  return { user, token, isLoggedIn, isAdmin, login, register, logout, fetchMe, synchronizeSession }
})
