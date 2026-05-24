import axios from 'axios'
import router from '../router'

// 优先使用环境变量配置的后端地址；本地开发未配置时走 Vite 代理（/api）
const baseURL = import.meta.env.VITE_API_BASE_URL
  ? `${import.meta.env.VITE_API_BASE_URL.replace(/\/$/, '')}/api`
  : '/api'

const client = axios.create({
  baseURL,
})

let userRefreshPromise = null

function getActiveExamSlug() {
  try {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    return user?.active_exam?.slug || ''
  } catch {
    return ''
  }
}

async function ensureActiveExamLoaded(token) {
  if (getActiveExamSlug()) return

  if (!userRefreshPromise) {
    userRefreshPromise = axios.get(`${baseURL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then((res) => {
      localStorage.setItem('user', JSON.stringify(res.data))
    }).catch(() => {
      // 保持原请求的错误处理路径，不在这里吞掉或改写业务请求结果。
    }).finally(() => {
      userRefreshPromise = null
    })
  }

  await userRefreshPromise
}

client.interceptors.request.use(async (config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
    await ensureActiveExamLoaded(token)
  }

  const activeExamSlug = getActiveExamSlug()
  if (activeExamSlug) {
    config.headers['X-Exam-Slug'] = activeExamSlug
  }

  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    const message = err.response?.data?.msg || ''
    const isInvalidToken = status === 422 && (
      message.includes('Invalid header') ||
      message.includes('Not enough segments') ||
      message.includes('Signature verification failed') ||
      message.includes('Subject must be a string')
    )

    if (status === 401 || isInvalidToken) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      router.push('/login')
    }
    return Promise.reject(err)
  }
)

export default client
