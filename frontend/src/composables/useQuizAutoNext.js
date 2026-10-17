import { ref, watch } from 'vue'

const STORAGE_PREFIX = 'quiz_auto_next:'

function readUserId() {
  try {
    const id = JSON.parse(localStorage.getItem('user') || 'null')?.id
    return id === null || id === undefined ? null : String(id)
  } catch {
    return null
  }
}

function readStoredValue(storageKey) {
  if (!storageKey) return false
  try {
    return localStorage.getItem(storageKey) === 'true'
  } catch {
    return false
  }
}

/** 答题页「自动下一题」偏好：按登录用户隔离，只存在当前浏览器。 */
export function useQuizAutoNext() {
  const userId = readUserId()
  const storageKey = userId === null ? null : `${STORAGE_PREFIX}${userId}`
  const autoNext = ref(readStoredValue(storageKey))

  watch(autoNext, (value) => {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, String(value))
    } catch {
      // 存储不可用时只保留本次页面内状态，不影响答题主流程。
    }
  }, { flush: 'sync' })

  return { autoNext }
}
