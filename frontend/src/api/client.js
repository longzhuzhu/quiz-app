import axios from 'axios'
import router from '../router'

// 优先使用环境变量配置的后端地址；本地开发未配置时走 Vite 代理（/api）
const baseURL = import.meta.env.VITE_API_BASE_URL
  ? `${import.meta.env.VITE_API_BASE_URL.replace(/\/$/, '')}/api`
  : '/api'

const client = axios.create({
  baseURL,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
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
