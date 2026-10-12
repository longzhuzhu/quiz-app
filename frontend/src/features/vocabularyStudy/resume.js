const DB_NAME = 'quiz-vocabulary-study'
const DB_VERSION = 1
const MEMORY_WARNING = '浏览器无法安全保存续学草稿：本页仍可保存服务端掌握状态，但关闭或刷新后无法恢复位置。'

// 受控、隔离的测试 Adapter；产品降级不使用共享内存模拟持久化。
export function createMemoryResume({ drafts = new Map(), locks = new Map(), durable = true } = {}) {
  let heldKey = null
  let handoff = null
  return {
    durable, warning: durable ? '' : MEMORY_WARNING,
    async acquire(key, callback) {
      if (heldKey === key) return true
      if (locks.has(key)) return false
      heldKey = key; handoff = callback
      locks.set(key, this)
      return true
    },
    async requestHandoff(key) { await locks.get(key)?.handoff() },
    async handoff() { await handoff?.() },
    async read(key) { return structuredClone(drafts.get(key) || null) },
    async replace(key, draft) { drafts.set(key, structuredClone(draft)) },
    async checkpoint(key, checkpoint) {
      const draft = drafts.get(key)
      if (draft?.manifest.roundId === checkpoint.roundId) draft.checkpoint = structuredClone(checkpoint)
    },
    async remove(key) { drafts.delete(key) },
    async clearAccount(id) { for (const [key, draft] of drafts) if (draft.manifest.accountId === id) drafts.delete(key) },
    async release() { if (heldKey && locks.get(heldKey) === this) locks.delete(heldKey); heldKey = null },
    async close() { await this.release() },
  }
}

function openDatabase(environment) {
  return new Promise((resolve, reject) => {
    let finished = false
    const timer = setTimeout(() => { finished = true; reject(new Error('续学存储打开超时')) }, 4000)
    const request = environment.indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('manifest')
      request.result.createObjectStore('checkpoint')
    }
    request.onsuccess = () => { clearTimeout(timer); if (finished) { request.result.close(); return }; finished = true; request.result.onversionchange = () => request.result.close(); resolve(request.result) }
    request.onerror = () => { clearTimeout(timer); finished = true; reject(request.error) }
    request.onblocked = () => { clearTimeout(timer); finished = true; reject(new Error('续学存储被其他页面阻塞')) }
  })
}

function transaction(db, mode, work) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['manifest', 'checkpoint'], mode)
    const result = {}
    tx.oncomplete = () => resolve(result)
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error || new Error('续学事务中止'))
    try { work(tx.objectStore('manifest'), tx.objectStore('checkpoint'), result) }
    catch (error) { tx.abort(); reject(error) }
  })
}

function removeAccount(db, accountId) {
  return transaction(db, 'readwrite', (manifest, checkpoint) => {
    for (const store of [manifest, checkpoint]) {
      store.openCursor().onsuccess = event => {
        const cursor = event.target.result
        if (!cursor) return
        let owner = null
        try { owner = JSON.parse(cursor.key)[0] } catch { /* 非本模块的非法键不猜测归属 */ }
        if (owner === accountId) cursor.delete()
        cursor.continue()
      }
    }
  })
}

export function createBrowserResume(environment = globalThis) {
  const capable = environment.isSecureContext && environment.indexedDB
    && environment.navigator?.locks?.request && environment.BroadcastChannel
  if (!capable) return createMemoryResume({ durable: false })
  let dbPromise = null
  let channel = null
  let heldKey = null
  let unlock = null
  let lockTask = null
  let closed = false
  const database = () => dbPromise ||= openDatabase(environment)
  const requireLock = key => { if (closed || heldKey !== key) throw new Error('未持有本轮续学锁') }
  return {
    durable: true, warning: '',
    async acquire(key, onHandoff) {
      if (heldKey === key) return true
      if (closed) return false
      let settle, failed
      const obtained = new Promise((resolve, reject) => { settle = resolve; failed = reject })
      lockTask = environment.navigator.locks.request(`vocab-study:${key}`, { ifAvailable: true }, async lock => {
        if (!lock || closed) { settle(false); return }
        heldKey = key
        channel = new environment.BroadcastChannel(`vocab-study:${key}`)
        channel.onmessage = event => { if (event.data?.type === 'handoff') Promise.resolve(onHandoff()).catch(() => {}) }
        const held = new Promise(resolve => { unlock = resolve })
        settle(true)
        await held
      }).catch(error => { failed(error); throw error })
      lockTask.catch(() => {})
      return obtained
    },
    async requestHandoff(key) {
      const request = new environment.BroadcastChannel(`vocab-study:${key}`)
      request.postMessage({ type: 'handoff' })
      request.close()
      await new Promise(resolve => setTimeout(resolve, 500))
    },
    async read(key) {
      requireLock(key)
      const db = await database()
      requireLock(key)
      const result = await transaction(db, 'readonly', (manifest, checkpoint, out) => {
        manifest.get(key).onsuccess = e => { out.manifest = e.target.result }
        checkpoint.get(key).onsuccess = e => { out.checkpoint = e.target.result }
      })
      return result.manifest || result.checkpoint ? result : null
    },
    async replace(key, draft) {
      requireLock(key)
      const db = await database()
      requireLock(key)
      await transaction(db, 'readwrite', (manifest, checkpoint) => {
        manifest.put(draft.manifest, key); checkpoint.put(draft.checkpoint, key)
      })
    },
    async checkpoint(key, value) {
      requireLock(key)
      const db = await database()
      requireLock(key)
      await transaction(db, 'readwrite', (manifest, checkpoint) => {
        manifest.get(key).onsuccess = event => {
          if (event.target.result?.roundId !== value.roundId) { checkpoint.transaction.abort(); return }
          checkpoint.put(value, key)
        }
      })
    },
    async remove(key) {
      requireLock(key)
      const db = await database()
      requireLock(key)
      await transaction(db, 'readwrite', (manifest, checkpoint) => { manifest.delete(key); checkpoint.delete(key) })
    },
    async clearAccount(accountId) {
      const db = await database()
      await removeAccount(db, accountId)
    },
    async release() {
      channel?.close(); channel = null
      unlock?.(); unlock = null
      if (lockTask) await lockTask.catch(() => {})
      heldKey = null; lockTask = null
    },
    async close() {
      closed = true
      await this.release()
      if (dbPromise) { try { (await dbPromise).close() } catch { /* 失败已由学习模块提示 */ } }
    },
  }
}

// 清理不依赖页面存活；先失效 Module，再调用，以免旧回调重建草稿。
export async function clearBrowserStudyAccount(accountId) {
  if (!accountId || !globalThis.indexedDB) return
  // 即使当前缺少锁能力，也应尝试删除原账号敏感草稿；这不是共享续学写入。
  const db = await openDatabase(globalThis)
  try { await removeAccount(db, accountId) } finally { db.close() }
}
