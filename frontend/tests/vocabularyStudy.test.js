import test from 'node:test'
import assert from 'node:assert/strict'
import { createVocabularyStudy } from '../src/features/vocabularyStudy/study.js'
import { createMemoryResume } from '../src/features/vocabularyStudy/resume.js'
import { createBrowserResume } from '../src/features/vocabularyStudy/resume.js'
import { contextKey } from '../src/features/vocabularyStudy/identity.js'

const context = { scope: 'personal', exam_id: null, bank_id: null }
function fixture(count = 3, options = {}) {
  const refs = Array.from({ length: count }, (_, i) => ({ vocabulary_id: i + 1 }))
  const writes = []
  const api = {
    async deck(mastery) { return { schema_version: 1, context, mastery, refs, total: count, top_limit: null } },
    async items(requested, include_content) { return requested.map(ref => ({ ref, available: true, is_mastered: true, can_mark_mastered: true, can_delete: true, content: include_content ? { term: `word${ref.vocabulary_id}`, term_zh: '词', definition: null, definition_zh: null, frequency: null } : null })) },
    async mark(ref, mastered) { writes.push([ref.vocabulary_id, mastered]) },
    ...options.api,
  }
  const resume = options.resume || createMemoryResume()
  const study = createVocabularyStudy({ api, resume, accountId: 1, context, mastery: 'unmastered' })
  return { study, api, resume, writes }
}

test('刷新一次更新翻译和中英文释义，保留当前面、位置、掌握与本轮结果', async () => {
  const refreshed = { term: 'word1', term_zh: '新的翻译', definition: 'New English definition.', definition_zh: '新的中文释义', frequency: null }
  const calls = []
  const { study, writes } = fixture(3, { api: {
    async refresh(ref) { calls.push(ref); return { ref, content: refreshed } },
  } })
  await study.open()
  await study.judge(true)
  await study.navigate(-1)
  study.flip()
  const counts = study.state.counts
  await study.refresh()
  assert.deepEqual(study.state.current.content, refreshed)
  assert.equal(study.state.current.is_mastered, true)
  assert.equal(study.state.flipped, true)
  assert.equal(study.state.position, 1)
  assert.equal(study.state.result, true)
  assert.deepEqual(study.state.counts, counts)
  assert.deepEqual(calls, [{ vocabulary_id: 1 }])
  assert.deepEqual(writes, [[1, true]])
  assert.equal(study.state.refreshing, false)
  assert.equal(study.state.canRefresh, true)
  assert.match(study.state.refreshMessage, /已刷新/)
  await study.leave()
})

test('刷新防重复但不阻塞切词与判断，迟到内容只更新原词且不覆盖新的掌握结果', async () => {
  let finish, calls = 0
  const { study, writes } = fixture(3, { api: {
    refresh(ref) { calls++; return new Promise(resolve => { finish = content => resolve({ ref, content }) }) },
  } })
  await study.open()
  const pending = study.refresh()
  assert.equal(study.state.refreshing, true)
  assert.equal(study.state.canRefresh, false)
  await study.refresh()
  assert.equal(calls, 1)
  await study.judge(false)
  assert.equal(study.state.current.content.term, 'word2')
  assert.equal(study.state.refreshing, false)
  assert.equal(study.state.refreshPending, true, '切词后仍应说明其他词条正在刷新，不能无故禁用按钮')
  assert.equal(study.state.canRefresh, false)
  finish({ term: 'word1', term_zh: '新词义', definition: 'Updated.', definition_zh: '新释义', frequency: null })
  await pending
  assert.equal(study.state.current.content.term, 'word2')
  assert.equal(study.state.refreshPending, false)
  assert.equal(study.state.refreshMessage, '')
  await study.navigate(-1)
  assert.equal(study.state.current.content.definition, 'Updated.')
  assert.equal(study.state.current.is_mastered, false)
  assert.equal(study.state.result, false)
  assert.deepEqual(writes, [[1, false]])
  await study.leave()
})

test('刷新失败或响应不完整保留旧内容，支持重试；错误只属于原词', async () => {
  let response = null
  const { study } = fixture(3, { api: {
    async refresh(ref) { if (!response) throw new Error('AI 请求失败'); return { ref, content: response } },
  } })
  await study.open()
  const original = study.state.current.content
  await study.refresh()
  assert.deepEqual(study.state.current.content, original)
  assert.match(study.state.refreshError, /AI 请求失败/)
  assert.equal(study.state.canRefresh, true)
  await study.navigate(1)
  assert.equal(study.state.refreshError, '')
  await study.navigate(-1)
  response = { term: 'word1', term_zh: '不能部分更新', definition: 'English', definition_zh: ' ' }
  await study.refresh()
  assert.deepEqual(study.state.current.content, original)
  assert.match(study.state.refreshError, /响应不完整/)
  response = { ...response, definition_zh: '完整释义' }
  await study.refresh()
  assert.deepEqual(study.state.current.content, response)
  assert.equal(study.state.refreshError, '')
  await study.leave()
})

test('离页、重开、身份失效和项目切换均中止刷新，迟到响应不能修改旧卡或新轮', async () => {
  for (const action of ['leave', 'restart', 'dispose', 'suspendForContextChange']) {
    let finish, signal
    const { study } = fixture(3, { api: {
      refresh(ref, requestSignal) {
        signal = requestSignal
        return new Promise(resolve => { finish = () => resolve({ ref, content: { term: 'word1', term_zh: '迟到', definition: 'Late.', definition_zh: '迟到释义', frequency: null } }) })
      },
    } })
    await study.open()
    const pending = study.refresh()
    await study[action]()
    assert.equal(signal.aborted, true)
    finish(); await pending
    if (action === 'suspendForContextChange') await study.resumeAfterContextFailure()
    assert.notEqual(study.state.current?.content.term_zh, '迟到')
    if (action !== 'dispose') await study.dispose()
  }
})

test('本轮结果不等于长期掌握，浏览只改变位置，再练和补学取各自本轮成员', async () => {
  const { study, writes } = fixture()
  await study.open()
  assert.equal(study.state.phase, 'studying')
  assert.deepEqual(study.state.counts, { remembered: 0, forgotten: 0, unmarked: 3, marked: 0, available: 3, unavailable: 0, original: 3 })
  study.flip()
  assert.equal(study.state.flipped, true)
  await study.judge(true)
  assert.equal(study.state.current.content.term, 'word2')
  assert.equal(study.state.flipped, false)
  await study.navigate(1)
  await study.judge(false)
  assert.equal(study.state.phase, 'summary')
  assert.equal(study.state.complete, false)
  assert.deepEqual(study.state.counts, { remembered: 1, forgotten: 1, unmarked: 1, marked: 2, available: 3, unavailable: 0, original: 3 })
  assert.deepEqual(writes, [[1, true], [3, false]])
  await study.repeat('forgotten')
  assert.equal(study.state.current.content.term, 'word3')
  assert.equal(study.state.counts.available, 1)
  assert.equal(study.state.counts.marked, 0)
  await study.leave()
})

test('改判只改变分类，失败保留旧结果，保存期间拒绝连点与切词', async () => {
  let finish
  let reject
  const { study, api } = fixture()
  await study.open()
  await study.judge(true)
  await study.navigate(-1)
  api.mark = () => new Promise((resolve, fail) => { finish = resolve; reject = fail })
  const saving = study.judge(false)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(study.state.saving, true)
  await study.navigate(1)
  await study.judge(true)
  assert.equal(study.state.position, 1)
  reject(new Error('明确保存失败'))
  await saving
  assert.equal(study.state.position, 1)
  assert.equal(study.state.result, true)
  assert.equal(study.state.counts.marked, 1)
  const retry = study.judge(false)
  await new Promise(resolve => setImmediate(resolve))
  finish()
  await retry
  assert.equal(study.state.position, 2)
  assert.equal(study.state.counts.marked, 1)
  assert.equal(study.state.counts.forgotten, 1)
  await study.leave()
})

test('刷新继续原顺序与成功结果，不重筛，不重放未确认保存', async () => {
  const resume = createMemoryResume()
  const first = fixture(3, { resume })
  await first.study.open()
  await first.study.judge(true)
  first.api.mark = async () => { throw Object.assign(new Error('响应丢失'), { uncertain: true }) }
  await first.study.judge(false)
  assert.equal(first.study.state.counts.marked, 1)
  await first.study.leave()
  const second = fixture(3, { resume })
  second.api.deck = async () => { throw new Error('恢复不得重新查询卡组') }
  await second.study.open()
  assert.equal(second.study.state.phase, 'resume')
  await second.study.continueRound()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(second.study.state.position, 2)
  assert.equal(second.study.state.counts.marked, 1)
  assert.deepEqual(second.writes, [])
  assert.deepEqual(second.study.state.uncertain, { key: 'id:2', mastered: true })
  await second.study.leave()
})

test('核验失败不删除成员、不发布最终小结，重试后明确移除失效词', async () => {
  const { study, api } = fixture()
  await study.open()
  const original = api.items
  api.items = async (refs, content) => { if (!content) throw new Error('网络超时'); return original(refs, content) }
  await study.summary()
  assert.equal(study.state.phase, 'verifying')
  assert.equal(study.state.counts.available, 3)
  assert.match(study.state.error, /超时/)
  api.items = async (refs, content) => (await original(refs, content)).map(item => item.ref.vocabulary_id === 2 ? { ref: item.ref, available: false } : item)
  await study.retry()
  assert.equal(study.state.phase, 'summary')
  assert.equal(study.state.counts.original, 3)
  assert.equal(study.state.counts.unavailable, 1)
  assert.equal(study.state.counts.unmarked, 2)
  await study.repeat('unmarked')
  assert.equal(study.state.counts.original, 2)
  assert.equal(study.state.current.content.term, 'word1')
  await study.navigate(1)
  assert.equal(study.state.current.content.term, 'word3')
  await study.leave()
})

test('在途保存离开必须等待，身份失效后的迟到响应不能重建草稿', async () => {
  let finish
  const { study, resume } = fixture(3, { api: { mark: () => new Promise(resolve => { finish = resolve }) } })
  await study.open()
  const mark = study.judge(true)
  await new Promise(resolve => setImmediate(resolve))
  let left = false
  const leave = study.leave().then(() => { left = true })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(left, false)
  finish(); await mark; await leave
  const next = fixture(3, { resume, api: { mark: () => new Promise(resolve => { finish = resolve }) } })
  await next.study.open(); await next.study.continueRound()
  const late = next.study.judge(true)
  await new Promise(resolve => setImmediate(resolve))
  await next.study.dispose({ clearAccount: true })
  finish(); await late
  const fresh = fixture(3, { resume })
  await fresh.study.open()
  assert.equal(fresh.study.state.phase, 'studying')
  assert.equal(fresh.study.state.counts.marked, 0)
  await fresh.study.leave()
})

test('存储失败明确降级，但服务端判定仍可成功', async () => {
  const resume = createMemoryResume()
  resume.replace = async () => { throw new Error('QuotaExceededError') }
  const { study, writes } = fixture(3, { resume })
  await study.open()
  assert.match(study.state.warning, /存储失败/)
  await study.judge(true)
  assert.deepEqual(writes, [[1, true]])
  assert.equal(study.state.position, 2)
  await study.leave()
})

test('大卡组首批仅20词，按需加载、回看被淘汰正文、小结只轻量核验10批', async () => {
  const reads = []
  const { study, api } = fixture(5000)
  const original = api.items
  let active = 0, maximum = 0
  api.items = async (refs, content) => {
    reads.push({ count: refs.length, content, refs })
    maximum = Math.max(maximum, ++active)
    await new Promise(resolve => setImmediate(resolve))
    active--
    return original(refs, content)
  }
  await study.open()
  assert.deepEqual(reads.map(r => [r.count, r.content]), [[20, true]])
  for (let i = 0; i < 130; i++) await study.navigate(1)
  const afterForward = reads.length
  for (let i = 0; i < 130; i++) await study.navigate(-1)
  assert.equal(study.state.current.content.term, 'word1')
  assert.ok(reads.length > afterForward, '正文缓存必须有界；回看被淘汰批次需要重新批读')
  for (let i = 0; i < 4999; i++) await study.navigate(1)
  assert.equal(study.state.current.content.term, 'word5000')
  await study.navigate(1)
  assert.equal(study.state.counts.unmarked, 5000)
  assert.equal(reads.filter(r => !r.content).length, 10)
  assert.ok(reads.filter(r => !r.content).every(r => r.count === 500))
  assert.ok(maximum <= 2)
  await study.leave()
})

test('同一上下文禁止双写，请求交接先停止旧页再取得锁', async () => {
  const drafts = new Map(), locks = new Map()
  const first = fixture(3, { resume: createMemoryResume({ drafts, locks }) })
  const second = fixture(3, { resume: createMemoryResume({ drafts, locks }) })
  await first.study.open()
  await first.study.judge(true)
  await second.study.open()
  assert.equal(second.study.state.phase, 'blocked')
  await second.study.takeOver()
  assert.equal(first.study.state.phase, 'handed-off')
  await first.study.judge(false)
  assert.deepEqual(first.writes, [[1, true]])
  assert.equal(second.study.state.phase, 'resume')
  await second.study.continueRound()
  assert.equal(second.study.state.position, 2)
  await second.study.leave()
})

test('草稿不兼容清理后可重开，缺安全能力不读写共享草稿，空轮不误提示未完成', async () => {
  const resume = createMemoryResume()
  const first = fixture(3, { resume })
  await first.study.open(); await first.study.leave()
  const key = contextKey(1, context)
  const damaged = await resume.read(key)
  damaged.manifest.schema_version = 99
  await resume.replace(key, damaged)
  const second = fixture(3, { resume })
  await second.study.open()
  assert.equal(second.study.state.phase, 'studying')
  assert.match(second.study.state.warning, /损坏或版本不兼容/)
  await second.study.leave()
  let accessed = false
  const unavailable = createBrowserResume({ isSecureContext: false, get indexedDB() { accessed = true; throw new Error('禁止访问共享草稿') } })
  const memory = fixture(3, { resume: unavailable })
  await memory.study.open()
  assert.match(memory.study.state.warning, /无法恢复位置/)
  assert.equal(accessed, false)
  await memory.study.judge(true)
  assert.equal(memory.study.state.counts.marked, 1)
  await memory.study.leave()
  const emptyResume = createMemoryResume()
  const empty = fixture(0, { resume: emptyResume })
  await empty.study.open()
  assert.equal(empty.study.state.phase, 'empty')
  assert.equal(empty.study.state.complete, false)
  await empty.study.leave()
  const reopen = fixture(0, { resume: emptyResume })
  await reopen.study.open()
  assert.equal(reopen.study.state.phase, 'empty')
  assert.equal(reopen.study.state.resumable, false)
  await reopen.study.leave()
})

test('新轮不等待旧轮迟到核验；整个上下文失效后不可重新显示缓存内容', async () => {
  const resume = createMemoryResume()
  const first = fixture(3, { resume })
  await first.study.open(); await first.study.leave()
  let finish
  const restored = fixture(3, { resume })
  const original = restored.api.items
  restored.api.items = (refs, content) => content ? original(refs, content) : new Promise(resolve => { finish = resolve })
  await restored.study.open(); await restored.study.continueRound()
  await new Promise(resolve => setImmediate(resolve))
  await restored.study.restart()
  restored.api.items = original
  await restored.study.summary()
  assert.equal(restored.study.state.phase, 'summary')
  finish([{ ref: { vocabulary_id: 1 }, available: false }])
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(restored.study.state.counts.unavailable, 0)
  await restored.study.repeat('unmarked')
  restored.api.items = async () => { throw Object.assign(new Error('项目失效'), { contextInvalid: true }) }
  await restored.study.checkCurrent()
  assert.equal(restored.study.state.phase, 'invalid')
  assert.equal(restored.study.state.current, null)
  await restored.study.summary()
  await restored.study.navigate(1)
  assert.equal(restored.study.state.phase, 'invalid')
  await restored.study.leave()
})

test('保存已确认后离开不等待下一词正文；中止读取不会撤销服务端掌握', async () => {
  const { study, api, writes } = fixture(21)
  const original = api.items
  let finishRead
  api.items = (refs, content) => content && refs.some(ref => ref.vocabulary_id === 21)
    ? new Promise(resolve => { finishRead = () => original(refs, content).then(resolve) }) : original(refs, content)
  await study.open()
  for (let i = 0; i < 19; i++) await study.navigate(1)
  const judging = study.judge(true)
  await new Promise(resolve => setImmediate(resolve))
  let left = false
  const leaving = study.leave().then(() => { left = true })
  try {
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(writes, [[20,true]])
    assert.equal(left, true, '保存已结束，下一词正文的迟到响应不应阻塞离开')
  } finally { finishRead(); await judging; await leaving }
})

test('项目切换等待期间暂停新判断与切词，切换失败恢复原卡片而不清空结果', async () => {
  const { study, writes } = fixture()
  await study.open(); study.flip()
  await study.suspendForContextChange()
  assert.equal(study.state.contextChanging, true)
  assert.equal(study.state.canJudge, false)
  await study.judge(true); await study.navigate(1)
  assert.deepEqual(writes, [])
  assert.equal(study.state.position, 1)
  await study.resumeAfterContextFailure()
  assert.equal(study.state.flipped, true)
  await study.judge(true)
  assert.equal(study.state.position, 2)
  assert.equal(study.state.flipped, false)
  await study.leave()
})
