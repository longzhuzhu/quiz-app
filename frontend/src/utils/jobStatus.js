export function getFailedJobMessage(job) {
  const baseMessage = job?.status_message?.trim() || '任务已自动执行 3 次仍失败'
  if (baseMessage.includes('可重新点击继续翻译剩余未翻译内容')) {
    return baseMessage
  }
  return `${baseMessage}，可重新点击继续翻译剩余未翻译内容`
}

export function formatJobBannerMessage(job, { idleMessage } = {}) {
  const fallback = idleMessage || '任务正在后台执行，可离开页面后稍后回来查看'
  if (!job) return fallback
  if (job.status === 'failed') return getFailedJobMessage(job)

  const statusText = (job.status_message || fallback).replace(/[，,]\s*已处理\s*\d+\s*\/\s*\d+/, '')
  const done = job.progress_done ?? 0
  const total = job.progress_total ?? 0
  const attempt = job.attempt_count ?? 0
  const maxAttempts = job.max_attempts ?? 3

  return `${statusText} · 已处理 ${done}/${total} · 第 ${attempt}/${maxAttempts} 次 · 刷新页面不会中断`
}
