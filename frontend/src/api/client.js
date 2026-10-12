import axios from 'axios'
import router from '../router'
import { studyGeneration } from '../features/vocabularyStudy/lifecycle.js'

// 优先使用环境变量配置的后端地址；本地开发未配置时走 Vite 代理（/api）
const baseURL = import.meta.env.VITE_API_BASE_URL
  ? `${import.meta.env.VITE_API_BASE_URL.replace(/\/$/, '')}/api`
  : '/api'

const client = axios.create({
  baseURL,
})

const examScopedPrefixes = [
  '/banks',
  '/questions',
  '/quiz',
  '/wrong',
  '/vocab',
  '/ai',
  '/import-jobs',
]

function isExamScopedApi(url = '') {
  const path = url.startsWith('http') ? new URL(url).pathname.replace(/^\/api/, '') : url
  return examScopedPrefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`))
}

client.interceptors.request.use(async (config) => {
  const token = localStorage.getItem('token')
  config.authGeneration = studyGeneration()
  if (config.studyIdentity) {
    let accountId = null
    try { accountId = JSON.parse(localStorage.getItem('user') || 'null')?.id } catch { /* 无效身份不发出学习请求 */ }
    if (config.studyIdentity.token !== token || config.studyIdentity.accountId !== accountId || config.studyIdentity.generation !== studyGeneration())
      return Promise.reject(new Error('Stale study identity'))
  }
  if (token && !config.headers.has('Authorization')) {
    config.headers.Authorization = `Bearer ${token}`
  }

  if (isExamScopedApi(config.url || '') && !config.headers.has('X-Exam-Slug')) {
    const { useExamStore } = await import('../stores/exam')
    const examStore = useExamStore()
    if (examStore.current?.slug) {
      config.headers['X-Exam-Slug'] = examStore.current.slug
    }
  }

  if (config.authGeneration !== studyGeneration() || token !== localStorage.getItem('token')) {
    return Promise.reject(new axios.CanceledError('Stale authentication request'))
  }
  return config
})

client.interceptors.response.use(
  (res) => {
    const originalToken = res.config?.headers?.get?.('Authorization')
    if (res.config.authGeneration !== studyGeneration() || (originalToken && originalToken !== `Bearer ${localStorage.getItem('token')}`)) {
      return Promise.reject(new axios.CanceledError('Stale authentication response'))
    }
    return res
  },
  (err) => {
    const status = err.response?.status
    const message = err.response?.data?.msg || ''
    const isInvalidToken = status === 422 && (
      message.includes('Invalid header') ||
      message.includes('Not enough segments') ||
      message.includes('Signature verification failed') ||
      message.includes('Subject must be a string')
    )

    const originalToken = err.config?.headers?.get?.('Authorization')
    const sameIdentity = err.config?.authGeneration === studyGeneration() && (!originalToken || originalToken === `Bearer ${localStorage.getItem('token')}`)
    if ((status === 401 || isInvalidToken) && sameIdentity) {
      import('../stores/auth').then(({ useAuthStore }) => {
        // 动态 import 期间也可能切换账号，不能让旧 401 登出新身份。
        if (originalToken && originalToken !== `Bearer ${localStorage.getItem('token')}`) return
        if (err.config?.authGeneration !== studyGeneration()) return
        useAuthStore().logout()
        if (router.currentRoute.value.path !== '/login') router.push('/login')
      })
    }
    return Promise.reject(err)
  }
)

export default client
