import test from 'node:test'
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'
import { mkdtemp, rm } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

const exec = promisify(execFile)
const root = fileURLToPath(new URL('../', import.meta.url))

// 用真实 Vue 组件和浏览器测试交互，仅在 HTTP 边界替换外部服务。
async function startFixture(initialPersonalWords = 0) {
  let nextId = 4
  let words = [
    { id: 1, term: 'shared word', scope_label: 'personal', is_mastered: false },
    { id: 2, term: 'project glossary', scope_label: 'exam_personal', exam: 'current', is_mastered: false, can_delete: true, can_mark_mastered: true },
    { id: 3, term: 'other project word', scope_label: 'exam_personal', exam: 'other', is_mastered: false },
  ]
  for (let i = 0; i < initialPersonalWords; i++) {
    words.push({ id: nextId++, term: `personal word ${i}`, scope_label: 'personal', is_mastered: false })
  }
  const entry = `
    import { createApp, h, ref } from 'vue'
    import { createPinia } from 'pinia'
    import { useExamStore } from '/src/stores/exam.js'
    import AddVocabButton from '/src/components/AddVocabButton.vue'
    import VocabularyView from '/src/views/VocabularyView.vue'
    localStorage.setItem('user', JSON.stringify({ is_admin: true }))
    const pinia = createPinia()
    const exam = useExamStore(pinia)
    exam.setCurrent({ slug: 'current', name: 'Current' })
    exam.loaded = true
    createApp({ setup() {
      const book = ref(false)
      return () => h('main', [
        h('button', { onClick: () => { book.value = true } }, '打开单词本'),
        book.value ? h(VocabularyView) : h(AddVocabButton),
      ])
    } }).use(pinia).mount('#app')
  `
  const server = await createServer({
    root,
    configFile: false,
    define: { 'import.meta.env.VITE_API_BASE_URL': 'undefined' },
    plugins: [vue(), {
      name: 'vocabulary-test-fixture',
      resolveId(id) { if (id === '/__vocab-test-entry.js') return id },
      load(id) { if (id === '/__vocab-test-entry.js') return entry },
      configureServer(server) {
        server.middlewares.use(async (req, res, next) => {
          const url = new URL(req.url, 'http://localhost')
          const send = (data, status = 200) => {
            res.writeHead(status, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify(data))
          }
          if (url.pathname === '/__vocab-test') {
            res.setHeader('Content-Type', 'text/html')
            res.end('<div id="app"></div><script type="module" src="/__vocab-test-entry.js"></script>')
            return
          }
          if (!url.pathname.startsWith('/api/')) return next()
          if (url.pathname === '/api/banks') return send([])
          const visible = words.filter(w => w.scope_label === 'personal' || w.exam === req.headers['x-exam-slug'])
          if (url.pathname === '/api/vocab/stats') {
            return send({
              personal: visible.filter(w => w.scope_label === 'personal').length,
              exam_personal: visible.filter(w => w.scope_label === 'exam_personal').length,
              all: visible.length,
            })
          }
          if (url.pathname === '/api/vocab' && req.method === 'GET') {
            const scope = url.searchParams.get('scope')
            const mastered = url.searchParams.get('mastered')
            const items = visible.filter(w => (scope === 'all' || w.scope_label === scope)
              && (mastered === null || w.is_mastered === (mastered === 'true')))
            const pageSize = Number(url.searchParams.get('page_size') || 20)
            const start = (Number(url.searchParams.get('page') || 1) - 1) * pageSize
            return send({
              items: items.slice().reverse().slice(start, start + pageSize),
              pagination: { total_pages: Math.max(1, Math.ceil(items.length / pageSize)), total_items: items.length },
            })
          }
          let body = ''
          for await (const chunk of req) body += chunk
          const data = body ? JSON.parse(body) : {}
          if (url.pathname === '/api/vocab' && req.method === 'POST') {
            const word = {
              ...data, id: nextId++, scope_label: url.searchParams.get('scope'),
              exam: req.headers['x-exam-slug'], is_mastered: false,
              can_delete: true, can_mark_mastered: true,
            }
            words.push(word)
            return send(word, 201)
          }
          const item = url.pathname.match(/^\/api\/vocab\/items\/(\d+)(\/progress)?$/)
          if (item) {
            const id = Number(item[1])
            if (req.method === 'DELETE') words = words.filter(w => w.id !== id)
            if (req.method === 'PUT') Object.assign(words.find(w => w.id === id), data)
            return send({ message: '已更新' })
          }
          send({ detail: `Unexpected test request: ${req.method} ${url.pathname}` }, 500)
        })
      },
    }],
    server: { host: '127.0.0.1', port: 0 },
  })
  await server.listen()
  return server
}

async function startBrowser(t, initialPersonalWords = 0) {
  try {
    await exec('agent-browser', ['--version'])
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
    t.skip('浏览器回归测试需要安装 agent-browser 并运行 agent-browser install')
    return null
  }
  const server = await startFixture(initialPersonalWords)
  // Snap Chromium 的 /tmp 与宿主机隔离，独立 profile 放在可访问的用户目录。
  const profile = await mkdtemp(join(homedir(), 'vocab-browser-'))
  const session = `vocab-test-${process.pid}-${initialPersonalWords}`
  const browser = async (...args) => (await exec('agent-browser', ['--session', session, '--profile', profile, ...args], {
    timeout: 30000, maxBuffer: 1024 * 1024,
  })).stdout
  const text = () => browser('get', 'text', 'main')
  t.after(async () => {
    try { await browser('close') } finally {
      await server.close()
      await rm(profile, { recursive: true, force: true })
    }
  })
  await browser('open', `http://127.0.0.1:${server.httpServer.address().port}/__vocab-test`)
  return { browser, text }
}

test('my wordbook contains quiz favorites but not project vocabulary', { timeout: 120000 }, async (t) => {
  const context = await startBrowser(t)
  if (!context) return
  const { browser, text } = context
  await browser('find', 'role', 'button', 'click', '--name', '收藏单词')
  await browser('find', 'placeholder', '输入英文单词或短语', 'fill', 'privacy')
  await browser('find', 'role', 'button', 'click', '--name', '保存', '--exact')
  await browser('wait', '--text', '已保存')
  await browser('find', 'role', 'button', 'click', '--name', '打开单词本')
  await browser('wait', '--text', 'project glossary')
  assert.doesNotMatch(await text(), /privacy/, '主动收藏不能写入项目词汇')
  await browser('find', 'text', '我的单词本', 'click', '--exact')
  const content = await text()
  assert.match(content, /privacy/, '答题收藏必须在“我的单词本”显示')
  assert.match(content, /shared word/)
  assert.doesNotMatch(content, /project glossary/)
  assert.doesNotMatch(content, /other project word/)
  assert.match(content, /我的单词本\s+2/, '统计只包含手动添加和主动收藏的个人词汇')
  assert.match(content, /项目词汇\s+1/)

  await t.test('mastery and filters do not mix personal and project words', async () => {
    await browser('find', 'role', 'button', 'click', '--name', '掌握', '--exact')
    await browser('wait', '--text', '取消掌握')
    await browser('find', 'role', 'button', 'click', '--name', '未掌握', '--exact')
    await browser('wait', '--text', 'shared word')
    assert.doesNotMatch(await text(), /privacy/)
    assert.match(await text(), /shared word/)
    await browser('find', 'role', 'button', 'click', '--name', '已掌握', '--exact')
    await browser('wait', '--text', 'privacy')
    assert.doesNotMatch(await text(), /shared word/)
    assert.match(await text(), /我的单词本\s+2/, '筛选不改变个人词汇总数')
    await browser('find', 'text', '项目词汇', 'click', '--exact')
    assert.doesNotMatch(await text(), /privacy|取消掌握/)
    await browser('find', 'role', 'button', 'click', '--name', '掌握', '--exact')
    await browser('wait', '--text', '取消掌握')
    await browser('find', 'text', '我的单词本', 'click', '--exact')
    assert.match(await text(), /privacy/)
    assert.doesNotMatch(await text(), /project glossary/)
    await browser('find', 'role', 'button', 'click', '--name', '全部', '--exact')
    await browser('wait', '--text', 'shared word')
  })

  await t.test('adding project vocabulary does not change my wordbook or its count', async () => {
    await browser('find', 'text', '项目词汇', 'click', '--exact')
    await browser('find', 'role', 'button', 'click', '--name', '添加词汇', '--exact')
    await browser('find', 'placeholder', '英文术语', 'fill', 'project addition')
    await browser('find', 'role', 'button', 'click', '--name', '确认添加', '--exact')
    await browser('wait', '--text', 'project addition')
    await browser('find', 'text', '我的单词本', 'click', '--exact')
    assert.doesNotMatch(await text(), /project addition|project glossary/)
    assert.match(await text(), /我的单词本\s+2/)
    assert.match(await text(), /项目词汇\s+2/)
  })

  await t.test('manually adding a word updates only the personal wordbook', async () => {
    await browser('find', 'role', 'button', 'click', '--name', '添加单词', '--exact')
    await browser('find', 'placeholder', '英文单词/短语', 'fill', 'zebra manual')
    await browser('find', 'role', 'button', 'click', '--name', '确认添加', '--exact')
    await browser('wait', '--text', 'zebra manual')
    assert.match(await text(), /我的单词本\s+3/)
    await browser('find', 'text', '项目词汇', 'click', '--exact')
    assert.doesNotMatch(await text(), /zebra manual/)
    assert.match(await text(), /项目词汇\s+2/)
    await browser('find', 'text', '我的单词本', 'click', '--exact')
  })

  await t.test('deleting a personal favorite does not change project vocabulary', async () => {
    await browser('find', 'first', 'main .space-y-2 button:last-child', 'click')
    await browser('wait', '--text', '确定要删除这个词汇吗？')
    await browser('find', 'role', 'button', 'click', '--name', '删除', '--exact')
    await browser('wait', '--fn', "!document.querySelector('[role=dialog]')")
    await browser('wait', '--text', 'zebra manual')
    assert.doesNotMatch(await text(), /privacy/)
    assert.match(await text(), /我的单词本\s+2/)
    assert.match(await text(), /shared word/)
    assert.match(await text(), /zebra manual/)
    await browser('find', 'text', '项目词汇', 'click', '--exact')
    assert.match(await text(), /项目词汇\s+2/)
    assert.match(await text(), /project glossary/)
    assert.match(await text(), /project addition/)
  })
})

test('my wordbook displays personal words beyond the first 100 items', { timeout: 60000 }, async (t) => {
  const context = await startBrowser(t, 110)
  if (!context) return
  const { browser, text } = context
  await browser('find', 'role', 'button', 'click', '--name', '打开单词本')
  await browser('wait', '--text', 'project glossary')
  await browser('find', 'text', '我的单词本', 'click', '--exact')
  await browser('wait', '--text', 'personal word 109')
  const content = await text()
  assert.match(content, /shared word/)
  assert.match(content, /personal word 0\b/)
  assert.match(content, /我的单词本\s+111/)
  assert.doesNotMatch(content, /project glossary|other project word/)
})
