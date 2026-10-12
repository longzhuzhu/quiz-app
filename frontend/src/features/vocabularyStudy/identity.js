export const STUDY_VERSION = 1
export const SOURCE_LABELS = { personal: '我的单词本', exam_personal: '项目词汇', frequent: '高频词汇' }
export const MASTERY_LABELS = { unmastered: '未掌握', all: '全部', mastered: '已掌握' }
export const ROUND_LABELS = { forgotten: '再练未记住', unmarked: '补学未标记' }

export function refKey(ref) {
  return Object.hasOwn(ref, 'vocabulary_id') ? `id:${ref.vocabulary_id}` : `term:${ref.term}`
}

export function contextKey(accountId, context) {
  return JSON.stringify([accountId, context.scope, context.exam_id, context.bank_id])
}

export function validContext(context) {
  const positive = value => Number.isSafeInteger(value) && value > 0
  return !!context && Object.hasOwn(SOURCE_LABELS, context.scope)
    && (context.scope === 'personal' ? context.exam_id === null : positive(context.exam_id))
    && (context.scope === 'frequent' ? positive(context.bank_id) : context.bank_id === null)
}

export function validRefs(refs, context) {
  if (!Array.isArray(refs)) return false
  const frequent = context.scope === 'frequent'
  return refs.every(ref => ref && Object.keys(ref).length === 1 && (frequent
    ? typeof ref.term === 'string' && ref.term.trim() === ref.term && ref.term.length > 0 && [...ref.term].length <= 200
    : Number.isSafeInteger(ref.vocabulary_id) && ref.vocabulary_id > 0))
    && new Set(refs.map(refKey)).size === refs.length
}

export function validateDraft(draft, accountId, context) {
  const { manifest: m, checkpoint: c } = draft || {}
  if (!m || !c || m.schema_version !== STUDY_VERSION || c.schema_version !== STUDY_VERSION
    || m.accountId !== accountId || !validContext(m.context)
    || contextKey(accountId, m.context) !== contextKey(accountId, context)
    || !Object.hasOwn(MASTERY_LABELS, m.mastery) || !validRefs(m.refs, m.context)
    || m.total !== m.refs.length || typeof m.roundId !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(m.roundId)
    || m.top_limit !== (m.context.scope === 'frequent' ? 5000 : null)
    || (m.kind !== undefined && !['fresh', 'forgotten', 'unmarked'].includes(m.kind))
    || c.roundId !== m.roundId || !['study', 'summary'].includes(c.phase)
    || !Number.isSafeInteger(c.index) || c.index < 0 || c.index > Math.max(0, m.refs.length - 1)
    || !c.results || typeof c.results !== 'object' || Array.isArray(c.results)
    || !Array.isArray(c.unavailable)) throw new Error('学习草稿损坏或版本不兼容，请重新开始')
  const keys = new Set(m.refs.map(refKey))
  if (Object.entries(c.results).some(([key, result]) => !keys.has(key) || typeof result !== 'boolean')
    || c.unavailable.some(key => !keys.has(key)) || new Set(c.unavailable).size !== c.unavailable.length
    || (c.pending !== null && (!c.pending || !keys.has(c.pending.key) || typeof c.pending.is_mastered !== 'boolean' || typeof c.pending.id !== 'string')))
    throw new Error('学习草稿损坏或版本不兼容，请重新开始')
  return structuredClone(draft)
}

export function parseStudyParams(query, examId) {
  const scope = query.scope
  const mastery = query.mastery ?? 'unmastered'
  const bank = query.bank_id
  if (typeof scope !== 'string' || !Object.hasOwn(SOURCE_LABELS, scope)
    || typeof mastery !== 'string' || !Object.hasOwn(MASTERY_LABELS, mastery)
    || (scope === 'frequent' ? typeof bank !== 'string' || !/^[1-9]\d*$/.test(bank) : bank !== undefined)
    || (query.round !== undefined && (typeof query.round !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(query.round))))
    throw new Error('学习参数无效，请返回来源选择')
  const context = { scope, exam_id: scope === 'personal' ? null : examId, bank_id: scope === 'frequent' ? Number(bank) : null }
  if (!validContext(context)) throw new Error('学习上下文无效，请返回来源选择')
  return { context, mastery, roundId: query.round }
}
