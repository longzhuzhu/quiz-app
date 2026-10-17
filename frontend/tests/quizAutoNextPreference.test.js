import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick } from 'vue'
import { useQuizAutoNext } from '../src/composables/useQuizAutoNext.js'

async function withStorage(seed, run) {
  const store = new Map(Object.entries(seed))
  const original = globalThis.localStorage
  globalThis.localStorage = {
    getItem: key => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: key => store.delete(key),
  }
  try {
    await run(store)
  } finally {
    globalThis.localStorage = original
  }
}

test('偏好默认关闭，按用户键读写，刷新后恢复', async () => {
  await withStorage({ user: JSON.stringify({ id: 7 }) }, async store => {
    const first = useQuizAutoNext()
    assert.equal(first.autoNext.value, false)

    first.autoNext.value = true
    await nextTick()
    assert.equal(store.get('quiz_auto_next:7'), 'true')

    const reloaded = useQuizAutoNext()
    assert.equal(reloaded.autoNext.value, true)
  })
})

test('不同用户互不影响，损坏的用户数据按未登录处理', async () => {
  await withStorage({
    user: JSON.stringify({ id: 7 }),
    'quiz_auto_next:7': 'true',
    'quiz_auto_next:8': 'false',
  }, async () => {
    assert.equal(useQuizAutoNext().autoNext.value, true)
  })

  await withStorage({
    user: JSON.stringify({ id: 8 }),
    'quiz_auto_next:7': 'true',
  }, async store => {
    const { autoNext } = useQuizAutoNext()
    assert.equal(autoNext.value, false, '其他用户的偏好不得串用')

    autoNext.value = true
    await nextTick()
    assert.equal(store.get('quiz_auto_next:8'), 'true')
    assert.equal(store.get('quiz_auto_next:7'), 'true', '不得改写其他用户的键')
  })

  await withStorage({ user: '{not json' }, async store => {
    const { autoNext } = useQuizAutoNext()
    assert.equal(autoNext.value, false)
    autoNext.value = true
    await nextTick()
    assert.equal(store.has('quiz_auto_next:null'), false, '无法识别用户时不写入偏好键')
    assert.equal(store.size, 1, '只保留原有的 user 键')
  })
})

test('非 true 的存储值一律视为关闭', async () => {
  await withStorage({
    user: JSON.stringify({ id: 3 }),
    'quiz_auto_next:3': '1',
  }, async () => {
    assert.equal(useQuizAutoNext().autoNext.value, false)
  })
})
