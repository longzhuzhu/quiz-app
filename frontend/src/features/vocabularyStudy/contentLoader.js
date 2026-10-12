import { refKey } from './identity.js'

// 一个调度器服务前台正文与后台核验。最多两个请求；排队的前台请求优先。
export function createContentLoader(api, { onUnavailable, isCurrent }) {
  const cache = new Map()
  const pending = new Map()
  const queue = []
  const controller = new AbortController()
  let running = 0
  let stopped = false

  function pump() {
    while (!stopped && running < 2 && queue.length) {
      const job = queue.shift()
      running++
      Promise.resolve().then(() => api.items(job.refs, job.content, controller.signal)).then(results => {
        if (stopped || !isCurrent()) throw new Error('学习轮次已失效')
        if (!Array.isArray(results) || results.length !== job.refs.length || results.some((item, i) =>
          !item || typeof item.available !== 'boolean' || refKey(item.ref || {}) !== refKey(job.refs[i])
          || (item.available && (typeof item.is_mastered !== 'boolean' || typeof item.can_mark_mastered !== 'boolean'
            || (job.content && (!item.content || typeof item.content.term !== 'string'))))))
          throw new Error('词汇读取响应不完整，请重试')
        job.resolve(results)
      }, job.reject).catch(job.reject).finally(() => { running--; pump() })
    }
  }

  function read(refs, content, priority = true) {
    if (!refs.length) return Promise.resolve([])
    if (stopped) return Promise.reject(new Error('学习轮次已失效'))
    return new Promise((resolve, reject) => {
      const job = { refs, content, resolve, reject }
      if (priority) queue.unshift(job)
      else queue.push(job)
      pump()
    })
  }

  function peek(ref) {
    const key = refKey(ref)
    const item = cache.get(key)
    if (item) { cache.delete(key); cache.set(key, item) }
    return item || null
  }

  async function load(refs, priority = true) {
    const missing = refs.filter(ref => !cache.has(refKey(ref)) && !pending.has(refKey(ref)))
    if (missing.length) {
      const task = read(missing, true, priority).then(results => {
        for (const item of results) {
          if (!item.available) onUnavailable(refKey(item.ref))
          else { cache.delete(refKey(item.ref)); cache.set(refKey(item.ref), item) }
        }
        while (cache.size > 100) cache.delete(cache.keys().next().value)
      }).finally(() => { for (const ref of missing) pending.delete(refKey(ref)) })
      for (const ref of missing) pending.set(refKey(ref), task)
    }
    await Promise.all([...new Set(refs.map(ref => pending.get(refKey(ref))).filter(Boolean))])
  }

  return {
    peek, load,
    verify: refs => read(refs, false, false),
    update(ref, mastered) { const item = cache.get(refKey(ref)); if (item) item.is_mastered = mastered },
    updateContent(ref, content) {
      const key = refKey(ref), item = cache.get(key)
      // 只替换内容，保留可能在 AI 请求期间已更新的权限与掌握状态。
      if (item && !stopped && isCurrent()) cache.set(key, { ...item, content: { ...content } })
    },
    stop() {
      stopped = true; controller.abort(); cache.clear(); pending.clear()
      for (const job of queue.splice(0)) job.reject(new Error('学习轮次已失效'))
    },
  }
}
