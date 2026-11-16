// 平台题库界面共用的纯展示/错误处理工具

// 导入任务仍在写入的状态；与后端活动写者判定保持一致。
export const ACTIVE_IMPORT_STATUSES = [
  'pending',
  'extracting',
  'chunking',
  'parsing',
  'validating',
  'importing',
]

const IMPORT_STATUS_LABELS = {
  pending: '待处理',
  extracting: '抽取中',
  chunking: '切片中',
  parsing: '解析中',
  validating: '校验中',
  importing: '导入中',
  imported: '已入库',
  review_required: '待复核',
  partial_imported: '部分入库',
  unimported: '未入库',
  failed: '失败',
  cancelled: '已取消',
}

export function isActiveImportStatus(status) {
  return ACTIVE_IMPORT_STATUSES.includes(status)
}

export function importStatusLabel(status) {
  return IMPORT_STATUS_LABELS[status] || status || '未知'
}

export function importStatusClass(status) {
  if (isActiveImportStatus(status)) return 'text-sky-600 dark:text-sky-400'
  if (status === 'imported') return 'text-emerald-600 dark:text-emerald-400'
  if (status === 'review_required' || status === 'partial_imported') {
    return 'text-amber-600 dark:text-amber-400'
  }
  if (status === 'failed') return 'text-rose-600 dark:text-rose-400'
  return 'text-gray-500 dark:text-gray-400'
}

export function questionTypeLabel(type) {
  const map = { single: '单选', multiple: '多选', truefalse: '判断' }
  return map[type] || type || '未知'
}

export function formatSourceTopic(topic) {
  if (typeof topic === 'string') return topic.trim()
  if (topic && typeof topic === 'object') {
    return [topic.code, topic.name].filter(Boolean).join(' ').trim()
  }
  return ''
}

export function shortId(id, length = 8) {
  if (!id) return ''
  const text = String(id)
  return text.length > length ? `${text.slice(0, length)}…` : text
}

export function formatDateTime(value) {
  if (!value) return '未知时间'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未知时间' : date.toLocaleString('zh-CN', { hour12: false })
}

// 后端错误既可能用 detail（平台/新接口），也可能沿用 error（旧个人接口）。
export function errorMessage(error, fallback) {
  const data = error?.response?.data
  const detail = data?.detail
  if (Array.isArray(detail)) {
    const joined = detail.map((item) => item?.msg).filter(Boolean).join('；')
    if (joined) return joined
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  if (typeof data?.error === 'string' && data.error.trim()) return data.error
  return fallback
}
