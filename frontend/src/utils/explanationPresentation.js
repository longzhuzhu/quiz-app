export const isGenerating = model => ['queued', 'running'].includes(model.generation?.status)

export function explanationStatus(model) {
  const state = model.generation?.status
  if (state === 'queued') return model.result ? '更新排队中' : '排队中'
  if (state === 'running') return model.result ? '更新中' : '生成中'
  if (state === 'failed') return model.result ? '更新失败，当前显示上次结果' : '生成失败'
  return model.result ? '' : '未生成'
}

export function responseError(error, fallback) {
  const detail = error.response?.data?.detail
  if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join('；') || fallback
  return typeof detail === 'string' ? detail : fallback
}
