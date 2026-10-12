import client from '../../api/client.js'
import { studyGeneration } from './lifecycle.js'

function createSessionRequest({ accountId, token, examSlug }) {
  const generation = studyGeneration()
  const reads = new Set()
  const current = () => {
    try { return generation === studyGeneration() && localStorage.getItem('token') === token && JSON.parse(localStorage.getItem('user') || 'null')?.id === accountId }
    catch { return false }
  }
  const headers = { Authorization: `Bearer ${token}`, 'X-Exam-Slug': examSlug }
  async function request(method, url, body, { signal, marking = false, refreshing = false } = {}) {
    if (!current()) throw Object.assign(new Error('登录身份已变化'), { contextInvalid: true })
    const controller = new AbortController()
    if (!marking) reads.add(controller)
    const abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) controller.abort()
    try {
      const response = await client.request({
        method, url, headers, ...(method === 'GET' ? { params: body } : { data: body }),
        timeout: refreshing ? 90000 : 15000, signal: controller.signal,
        studyIdentity: { accountId, token, generation },
      })
      if (!current()) throw Object.assign(new Error('登录身份已变化'), { contextInvalid: true })
      return response.data
    } catch (error) {
      if (error.contextInvalid) throw error
      const status = error.response?.status
      const detail = error.response?.data?.detail
      const contextInvalid = !current() || status === 401 || status === 403
        || detail === 'EXAM_NOT_FOUND' || detail === '题库不存在'
      const unavailableApi = !marking && status === 404 && !contextInvalid
      let message = '词汇加载失败，请重试（不会把网络失败当作词条删除）'
      if (contextInvalid) message = '当前账号、考试项目或题库已失效，请返回来源选择'
      else if (refreshing) {
        message = status === 409 ? '词条内容已变化，请重试刷新' : status === 504 ? 'AI 刷新超时，请稍后重试' : '词条刷新失败或结果未确认，请稍后重试'
      } else if (marking) {
        message = !status || status >= 500 ? '保存结果未确认，请核验服务器状态后重新判断' : '保存失败，仍停留在原卡片，请重试'
      } else if (unavailableApi) message = '学习读取接口暂不可用，请检查后端版本并重试；管理入口仍可使用'
      throw Object.assign(new Error(message), {
        contextInvalid, uncertain: marking && (!status || status >= 500), verifyAvailability: marking && status === 404 && !contextInvalid,
      })
    } finally { reads.delete(controller); signal?.removeEventListener('abort', abort) }
  }
  return { request, isCurrent: current, abortReads() { for (const controller of reads) controller.abort(); reads.clear() } }
}

export function createStudyApi(options) {
  const { context } = options
  const session = createSessionRequest(options)
  const { request } = session
  const source = { scope: context.scope, ...(context.bank_id ? { bank_id: context.bank_id } : {}) }
  return {
    isCurrent: session.isCurrent,
    deck: mastery => request('GET', '/vocab/study/deck', { ...source, mastery }),
    items: (refs, include_content, signal) => request('POST', '/vocab/study/items', { ...source, refs, include_content }, { signal }).then(data => data.results),
    refresh: (ref, signal) => request('POST', '/vocab/study/refresh', { ...source, ref }, { signal, refreshing: true }),
    mark(ref, is_mastered) {
      return context.scope === 'frequent'
        ? request('PUT', '/vocab/frequent-items/progress', { bank_id: context.bank_id, term: ref.term, is_mastered }, { marking: true })
        : request('PUT', `/vocab/items/${ref.vocabulary_id}/progress`, { is_mastered }, { marking: true })
    },
    abortReads: session.abortReads,
  }
}

export function createVocabularyOverviewApi(options) {
  const { request, abortReads } = createSessionRequest(options)
  return {
    async metadata(signal) {
      const [stats, banks] = await Promise.all([request('GET', '/vocab/stats', {}, { signal }), request('GET', '/banks', {}, { signal })])
      return { stats, banks }
    },
    frequentTotal: (bankId, signal) => request('GET', '/vocab/frequent', { bank_id: bankId, per_page: 1 }, { signal }).then(data => data.summary.total_terms),
    abortReads,
  }
}
