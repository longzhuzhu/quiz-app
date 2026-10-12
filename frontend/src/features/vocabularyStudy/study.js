import { contextKey, MASTERY_LABELS, refKey, STUDY_VERSION, validContext, validRefs, validateDraft } from './identity.js'
import { createContentLoader } from './contentLoader.js'
import { createMemoryResume } from './resume.js'

const clone = value => structuredClone(value)
let fallbackSequence = 0
const newId = () => globalThis.crypto?.randomUUID?.()
  || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${++fallbackSequence}`
const chunks = (items, size) => Array.from({ length: Math.ceil(items.length / size) }, (_, i) => items.slice(i * size, (i + 1) * size))

/** 公开学习模块：界面只订阅状态并发出意图，不自行读取、保存或协调身份。 */
export function createVocabularyStudy({ api, resume, accountId, context, mastery = 'unmastered', isIdentityCurrent = () => true }) {
  if (!Number.isSafeInteger(accountId) || accountId < 1 || !validContext(context) || !Object.hasOwn(MASTERY_LABELS, mastery))
    throw new Error('学习身份或范围无效，请返回来源选择')
  const key = contextKey(accountId, context)
  const listeners = new Set()
  let manifest = null
  let checkpoint = null
  let restored = null
  let loader = null
  let epoch = 0
  let disposed = false
  let contextStopped = false
  let leaving = false
  let held = false
  let writing = null
  let savingTask = null
  let moving = false
  let storageEnabled = resume.durable
  let backgroundVerification = null
  let refreshing = null
  let refreshOutcome = null
  let metricsDirty = true
  let metrics = null
  const view = { phase: 'idle', flipped: false, saving: false, loading: false, contextChanging: false, error: '', warning: resume.warning || '', verificationError: '', uncertain: null }
  let snapshot = null

  function live(token = epoch) { return !disposed && !contextStopped && token === epoch && isIdentityCurrent() }
  function roundMetrics() {
    if (!metricsDirty) return metrics
    const unavailable = new Set(checkpoint?.unavailable || [])
    const positions = new Map()
    const counts = { remembered: 0, forgotten: 0, unmarked: 0, marked: 0, available: 0, unavailable: unavailable.size, original: manifest?.total || 0 }
    for (const ref of manifest?.refs || []) {
      const wordKey = refKey(ref)
      if (unavailable.has(wordKey)) continue
      positions.set(wordKey, ++counts.available)
      if (checkpoint.results[wordKey] === true) counts.remembered++
      else if (checkpoint.results[wordKey] === false) counts.forgotten++
      else counts.unmarked++
    }
    counts.marked = counts.remembered + counts.forgotten
    metrics = { positions, counts }; metricsDirty = false
    return metrics
  }
  function publish() {
    const { positions, counts } = roundMetrics()
    const currentRef = manifest?.refs[checkpoint?.index]
    const position = currentRef ? positions.get(refKey(currentRef)) || 0 : 0
    const currentKey = currentRef ? refKey(currentRef) : null
    snapshot = {
      ...view, context: clone(context), manifest: manifest ? { roundId: manifest.roundId, mastery: manifest.mastery, kind: manifest.kind, total: manifest.total, top_limit: manifest.top_limit } : null,
      busy: view.saving || moving || !!writing || leaving,
      requestedMastery: mastery,
      current: currentRef && position ? loader?.peek(currentRef) || null : null,
      currentRef: currentRef ? clone(currentRef) : null,
      currentKey,
      refreshPending: !!refreshing,
      refreshing: !!refreshing && refreshing.key === currentKey,
      refreshError: refreshOutcome?.key === currentKey ? refreshOutcome.error || '' : '',
      refreshMessage: refreshOutcome?.key === currentKey ? refreshOutcome.message || '' : '',
      canRefresh: view.phase === 'studying' && position > 0 && !view.loading && !view.saving && !writing
        && !moving && !leaving && !refreshing && !!loader?.peek(currentRef)?.content,
      position,
      result: currentRef ? checkpoint.results[refKey(currentRef)] : undefined,
      counts: { ...counts },
      complete: view.phase === 'summary' && counts.available > 0 && counts.marked === counts.available,
      canPrevious: position > 1,
      canJudge: view.phase === 'studying' && !view.loading && !view.saving && !writing && !moving && !leaving && !!currentRef
        && (!checkpoint.pending || checkpoint.pending.key === refKey(currentRef)) && !!loader?.peek(currentRef)?.can_mark_mastered,
      resumable: !!restored,
      resumeInfo: restored ? { total: restored.manifest.total, mastery: restored.manifest.mastery, kind: restored.manifest.kind } : null,
    }
    for (const listener of listeners) listener(snapshot)
  }
  function fail(error, token = epoch) {
    if (!live(token)) return
    if (error.contextInvalid) {
      contextStopped = true
      loader?.stop(); view.phase = 'invalid'; view.loading = false
    }
    view.error = error.message || '学习请求失败，请重试'
    publish()
  }
  async function persist(replace = false, token = epoch) {
    if (!live(token) || !storageEnabled || !held || !manifest) return
    try {
      if (replace) await resume.replace(key, { manifest: clone(manifest), checkpoint: clone(checkpoint) })
      else await resume.checkpoint(key, clone(checkpoint))
    } catch {
      if (!live(token)) return
      storageEnabled = false
      view.warning = '续学存储失败：服务端掌握仍可保存，但当前进度可能无法恢复。请勿依赖刷新或关闭后续学。'
      // 不能留下看似可用但落后于当前页的草稿。
      try { await resume.remove(key) } catch { /* 无法访问存储时只能明确降级 */ }
    }
    if (live(token)) publish()
  }
  function install(nextManifest, nextCheckpoint) {
    cancelRefresh()
    refreshOutcome = null
    epoch++; loader?.stop()
    backgroundVerification = null
    writing = null; savingTask = null
    manifest = clone(nextManifest); checkpoint = clone(nextCheckpoint); restored = null
    manifest.kind ||= 'fresh'
    mastery = manifest.mastery
    metricsDirty = true
    const token = epoch
    loader = createContentLoader(api, {
      isCurrent: () => live(token),
      onUnavailable(wordKey) {
        if (!live(token)) return
        if (!checkpoint.unavailable.includes(wordKey)) { checkpoint.unavailable.push(wordKey); metricsDirty = true }
        if (checkpoint.pending?.key === wordKey) { checkpoint.pending = null; view.uncertain = null }
      },
    })
    Object.assign(view, { flipped: false, saving: false, error: '', verificationError: '', uncertain: checkpoint.pending ? { key: checkpoint.pending.key, mastered: null } : null, phase: 'studying', loading: false })
  }
  async function newRound(refs, selectedMastery, topLimit, kind = 'fresh') {
    const roundId = newId()
    install({ schema_version: STUDY_VERSION, accountId, context, mastery: selectedMastery, kind, refs, total: refs.length, top_limit: topLimit, roundId }, {
      schema_version: STUDY_VERSION, roundId, index: 0, results: {}, unavailable: [], phase: 'study', pending: null,
    })
    await persist(true)
    await showCurrent()
  }
  function indexInDirection(from, direction) {
    const unavailable = new Set(checkpoint.unavailable)
    for (let i = from; i >= 0 && i < manifest.refs.length; i += direction)
      if (!unavailable.has(refKey(manifest.refs[i]))) return i
    return -1
  }
  async function showCurrent() {
    const token = epoch
    if (!live(token) || leaving) return
    if (!manifest.refs.length || checkpoint.unavailable.length === manifest.total) {
      checkpoint.phase = 'summary'
      view.phase = 'empty'; view.loading = false; publish(); await persist(); return
    }
    if (checkpoint.unavailable.includes(refKey(manifest.refs[checkpoint.index]))) {
      const next = indexInDirection(checkpoint.index + 1, 1)
      checkpoint.index = next < 0 ? indexInDirection(checkpoint.index - 1, -1) : next
    }
    view.phase = 'studying'; view.error = ''; view.flipped = false
    const current = manifest.refs[checkpoint.index]
    if (!loader.peek(current)) {
      view.loading = true; publish()
      const start = Math.floor(checkpoint.index / 20) * 20
      try {
        await loader.load(manifest.refs.slice(start, start + 20).filter(ref => !checkpoint.unavailable.includes(refKey(ref))))
        if (!live(token) || leaving) return
        view.loading = false
        if (checkpoint.unavailable.includes(refKey(current))) { await persist(); return showCurrent() }
      } catch (error) { if (live(token)) view.loading = false; fail(error, token); return }
    }
    await persist(false, token)
    if (!live(token) || leaving) return
    publish()
    const batchEnd = (Math.floor(checkpoint.index / 20) + 1) * 20
    const remaining = manifest.refs.slice(checkpoint.index, batchEnd).filter(ref => !checkpoint.unavailable.includes(refKey(ref))).length
    if (remaining <= 5 && batchEnd < manifest.total) {
      loader.load(manifest.refs.slice(batchEnd, batchEnd + 20).filter(ref => !checkpoint.unavailable.includes(refKey(ref))), false)
        .then(() => { if (live(token)) publish() }).catch(error => { if (error.contextInvalid) fail(error, token) })
    }
  }
  async function verifyAll() {
    const token = epoch
    const refs = manifest.refs.filter(ref => !checkpoint.unavailable.includes(refKey(ref)))
    // 只有所有批次成功才应用核验，避免基于部分数据发布最终小结。
    const batches = await Promise.all(chunks(refs, 500).map(batch => loader.verify(batch)))
    if (!live(token)) return false
    for (const item of batches.flat()) {
      const wordKey = refKey(item.ref)
      if (!item.available) {
        if (!checkpoint.unavailable.includes(wordKey)) { checkpoint.unavailable.push(wordKey); metricsDirty = true }
        if (checkpoint.pending?.key === wordKey) { checkpoint.pending = null; view.uncertain = null }
      }
      if (checkpoint.pending?.key === wordKey && item.available)
        view.uncertain = { key: wordKey, mastered: item.is_mastered }
    }
    await persist(false, token)
    return live(token)
  }
  async function summary() {
    if (!live() || view.saving || moving || leaving || !manifest || (view.phase === 'verifying' && view.loading)) return
    view.phase = 'verifying'; view.loading = true; view.error = ''; publish()
    const token = epoch
    try {
      if (backgroundVerification) await backgroundVerification
      if (!live(token) || leaving) return
      if (!await verifyAll() || leaving) return
      checkpoint.phase = 'summary'
      view.phase = 'summary'; view.loading = false; view.verificationError = ''
      await persist(false, token); publish()
    } catch (error) {
      if (!live(token)) return
      view.loading = false; view.phase = 'verifying'; fail(error, token)
    }
  }
  async function open({ roundId } = {}) {
    if (!live() || held || view.phase === 'loading') return
    leaving = false; view.phase = 'loading'; view.error = ''; publish()
    const token = epoch
    try {
      const handoff = async () => {
        if (disposed || leaving) return
        await leave(); view.phase = 'handed-off'; publish()
      }
      try { held = await resume.acquire(key, handoff) }
      catch {
        await resume.close()
        resume = createMemoryResume({ durable: false }); storageEnabled = false
        view.warning = resume.warning
        held = await resume.acquire(key, handoff)
      }
      if (!live(token)) { await resume.release(); return }
      if (!held) { view.phase = 'blocked'; view.error = '此来源正在另一标签页学习。可请求接管；原页无响应时，请关闭原页后重试。'; publish(); return }
      let draft = null
      if (storageEnabled) {
        try { draft = await resume.read(key) }
        catch { storageEnabled = false; view.warning = '无法读取续学存储，本页使用内存学习，刷新后无法恢复位置。' }
      }
      if (!live(token)) return
      if (draft) {
        try { draft = validateDraft(draft, accountId, context) }
        catch (error) { try { await resume.remove(key) } catch { storageEnabled = false }; view.warning = error.message; draft = null }
      }
      if (!live(token)) return
      if (roundId && draft?.manifest.roundId !== roundId) {
        view.phase = 'error'; view.error = '本浏览器已无此轮草稿，请重新开始'; publish(); return
      }
      if (draft && (draft.checkpoint.phase === 'study' || roundId)) {
        restored = draft
        view.phase = 'resume'; publish()
        if (draft.checkpoint.phase === 'summary') await continueRound()
      } else await restart()
    } catch (error) { view.phase = 'error'; fail(error, token) }
  }
  async function restart(selectedMastery = mastery) {
    if (!live() || !held || view.saving || moving || leaving || !Object.hasOwn(MASTERY_LABELS, selectedMastery)) return
    const token = ++epoch
    mastery = selectedMastery
    backgroundVerification = null
    writing = null; savingTask = null
    loader?.stop(); view.phase = 'loading'; view.loading = true; view.error = ''; publish()
    try {
      const deck = await api.deck(selectedMastery)
      if (!live(token) || leaving) return
      if (deck.schema_version !== STUDY_VERSION || contextKey(accountId, deck.context) !== key
        || !validRefs(deck.refs, context) || deck.total !== deck.refs.length || deck.mastery !== selectedMastery
        || deck.top_limit !== (context.scope === 'frequent' ? 5000 : null)) throw new Error('学习卡组响应不完整，请重试')
      await newRound(deck.refs, selectedMastery, deck.top_limit)
    } catch (error) { if (live(token)) { view.phase = 'error'; view.loading = false; fail(error, token) } }
  }
  async function continueRound() {
    if (!live() || !restored || leaving) return
    const draft = restored
    install(draft.manifest, draft.checkpoint)
    if (checkpoint.phase === 'summary') return summary()
    await showCurrent()
    if (!live() || view.phase !== 'studying') return
    const token = epoch
    backgroundVerification = verifyAll().then(() => {
      if (live(token)) { publish(); if (!view.saving && !moving && checkpoint.unavailable.includes(refKey(manifest.refs[checkpoint.index]))) return showCurrent() }
    }).catch(error => {
      if (live(token)) { view.verificationError = '续学核验未完成，请重试；网络失败不会移除词条。'; if (error.contextInvalid) fail(error, token); else publish() }
    }).finally(() => { if (live(token)) backgroundVerification = null })
  }
  async function navigate(direction) {
    if (!live() || view.phase !== 'studying' || view.saving || writing || moving || leaving || ![-1, 1].includes(direction)) return
    const next = indexInDirection(checkpoint.index + direction, direction)
    if (next < 0) { if (direction === 1) await summary(); return }
    moving = true; checkpoint.index = next; view.flipped = false; publish()
    try { await persist(); await showCurrent() } finally { moving = false; publish() }
  }
  async function judge(mastered) {
    if (!snapshot.canJudge || typeof mastered !== 'boolean' || !live()) return
    const token = epoch
    const ref = clone(manifest.refs[checkpoint.index])
    const wordKey = refKey(ref)
    view.saving = true; view.error = ''; publish()
    savingTask = (async () => {
      checkpoint.pending = { id: newId(), key: wordKey, is_mastered: mastered }
      await persist(false, token)
      if (!live(token)) return { success: false }
      try {
        await api.mark(ref, mastered)
        if (!live(token)) return { success: false }
        checkpoint.results[wordKey] = mastered; checkpoint.pending = null; view.uncertain = null
        metricsDirty = true
        loader.update(ref, mastered)
        const next = indexInDirection(checkpoint.index + 1, 1)
        if (next >= 0) { checkpoint.index = next; view.flipped = false }
        await persist(false, token)
        if (!live(token)) return { success: false }
        view.saving = false; publish()
        return { success: true, next }
      } catch (error) {
        if (!live(token)) return { success: false }
        if (!error.uncertain) { checkpoint.pending = null; await persist(false, token) }
        else view.uncertain = { key: wordKey, mastered: null }
        view.saving = false
        fail(error, token)
        return { success: false, verifyAvailability: error.verifyAvailability }
      }
    })()
    const operation = savingTask.then(async result => {
      if (!live(token) || leaving) return
      if (result.success) {
        if (result.next < 0) await summary()
        else await showCurrent()
      } else if (result.verifyAvailability) {
        // 写入 404 仍需通过读取契约确认，不能把代理／上下文错误当成词条删除。
        try {
          const [item] = await loader.verify([ref])
          if (!live(token) || leaving) return
          if (!item.available) {
            if (!checkpoint.unavailable.includes(wordKey)) { checkpoint.unavailable.push(wordKey); metricsDirty = true }
            checkpoint.pending = null; view.uncertain = null
            await persist(false, token); await showCurrent()
          }
        } catch (error) { fail(error, token) }
      }
    }).finally(() => {
      if (token === epoch) { writing = null; savingTask = null }
      if (live(token)) { view.saving = false; publish() }
    })
    writing = operation
    await operation
  }
  function cancelRefresh() {
    refreshing?.controller.abort()
    refreshing = null
  }
  async function refresh() {
    if (!live() || !snapshot.canRefresh) return
    const token = epoch, ref = clone(snapshot.currentRef), term = snapshot.current.content.term
    const operation = { key: refKey(ref), controller: new AbortController() }
    refreshing = operation; refreshOutcome = null; publish()
    try {
      const result = await api.refresh(ref, operation.controller.signal)
      if (!live(token) || operation.controller.signal.aborted) return
      if (!result?.ref || refKey(result.ref) !== operation.key || result.content?.term !== term
        || ['term_zh', 'definition', 'definition_zh'].some(field => typeof result.content[field] !== 'string' || !result.content[field].trim()))
        throw new Error('刷新响应不完整，请重试')
      if (!checkpoint.unavailable.includes(operation.key)) loader.updateContent(ref, result.content)
      refreshOutcome = { key: operation.key, message: '已刷新翻译与中英文释义。' }
    } catch (error) {
      if (!live(token) || operation.controller.signal.aborted) return
      if (error.contextInvalid) fail(error, token)
      else refreshOutcome = { key: operation.key, error: error.message || '词条刷新失败，请重试' }
    } finally {
      // 切词仍可继续；迟到结果只更新目标词，不能落到另一张卡或新的轮次。
      if (refreshing === operation) { refreshing = null; if (live(token)) publish() }
    }
  }
  async function repeat(kind) {
    if (!live() || view.phase !== 'summary' || !['forgotten', 'unmarked'].includes(kind) || leaving) return
    const refs = manifest.refs.filter(ref => !checkpoint.unavailable.includes(refKey(ref))
      && (kind === 'forgotten' ? checkpoint.results[refKey(ref)] === false : !Object.hasOwn(checkpoint.results, refKey(ref))))
    if (refs.length) await newRound(refs, manifest.mastery, manifest.top_limit, kind)
  }
  async function leave() {
    cancelRefresh()
    leaving = true; publish()
    await savingTask
    if (!disposed) await persist()
    epoch++; loader?.stop(); view.loading = false
    api.abortReads?.()
    held = false; await resume.release(); publish()
  }
  async function dispose({ clearAccount = false } = {}) {
    cancelRefresh()
    // 鉴权失效必须立即失效，不能等待迟到响应后再次写入。
    disposed = true; leaving = true; epoch++; loader?.stop(); restored = null
    api.abortReads?.()
    manifest = null; checkpoint = null; metricsDirty = true; view.phase = 'invalid'; view.error = '登录身份已变化，请重新进入学习'; publish()
    if (clearAccount) { try { await resume.clearAccount(accountId) } catch { /* 身份隔离仍阻止其他账号读取 */ } }
    await resume.close(); listeners.clear()
  }
  publish()
  return {
    get state() { return snapshot },
    subscribe(listener) { listeners.add(listener); listener(snapshot); return () => listeners.delete(listener) },
    open, restart, continueRound, navigate, judge, refresh, summary, repeat, leave, dispose,
    flip() { if (live() && view.phase === 'studying' && snapshot.current && !snapshot.busy && !view.loading) { view.flipped = !view.flipped; publish() } },
    async retry() {
      if (view.phase === 'blocked' || view.phase === 'handed-off') return open()
      if (view.phase === 'error') return restart()
      if (view.phase === 'verifying') return summary()
      if (view.phase === 'studying') { await showCurrent(); if (view.verificationError || checkpoint.pending) { try { await verifyAll(); view.verificationError = ''; publish() } catch (error) { fail(error) } } }
    },
    async takeOver() { if (view.phase === 'blocked') { await resume.requestHandoff(key); await open() } },
    async waitForSave() { await savingTask },
    async suspendForContextChange() {
      if (!live() || !held) return
      cancelRefresh()
      leaving = true; view.contextChanging = true; publish()
      await savingTask; await persist()
    },
    async resumeAfterContextFailure() {
      if (!live() || !held || !view.contextChanging) return
      leaving = false; view.contextChanging = false
      const ref = manifest?.refs[checkpoint?.index]
      if (ref && !checkpoint.unavailable.includes(refKey(ref)) && loader.peek(ref)) { view.loading = false; publish() }
      else if (manifest) await showCurrent()
    },
    async returnToPending() {
      if (!live() || !checkpoint?.pending || view.saving || writing || moving || leaving || view.phase === 'verifying') return
      const index = manifest.refs.findIndex(ref => refKey(ref) === checkpoint.pending.key)
      if (index >= 0) { checkpoint.index = index; checkpoint.phase = 'study'; await persist(); await showCurrent() }
    },
    async checkCurrent() {
      if (!live() || view.phase !== 'studying' || view.saving || moving || leaving || !manifest?.refs.length) return
      const token = epoch, ref = manifest.refs[checkpoint.index]
      try {
        const [item] = await loader.verify([ref])
        if (!live(token)) return
        if (!item.available && !checkpoint.unavailable.includes(refKey(ref))) {
          checkpoint.unavailable.push(refKey(ref)); metricsDirty = true
          if (checkpoint.pending?.key === refKey(ref)) { checkpoint.pending = null; view.uncertain = null }
          await persist(false, token)
          if (live(token) && !view.saving && !moving && !writing && refKey(manifest.refs[checkpoint.index]) === refKey(ref)) await showCurrent()
          else if (live(token)) publish()
        }
        else if (checkpoint.pending?.key === refKey(ref)) { view.uncertain = { key: refKey(ref), mastered: item.is_mastered }; publish() }
      } catch (error) { fail(error, token) }
    },
  }
}
