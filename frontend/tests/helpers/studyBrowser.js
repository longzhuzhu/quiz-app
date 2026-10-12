import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'
import { mkdtemp, rm } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const exec = promisify(execFile)
const root = fileURLToPath(new URL('../../', import.meta.url))

export async function flipStudyCard(browser, face = 'chinese') {
  await browser('wait', '--fn', `document.querySelector('section[aria-label="单词卡"]').getAttribute('aria-busy') === 'false'`)
  await browser('click', 'section[aria-label="单词卡"]')
  await browser('wait', '--text', face === 'english' ? '点击卡片查看中文' : '点击卡片返回英文')
  await browser('wait', '--fn', `document.querySelector('section[aria-label="单词卡"]').getAttribute('aria-busy') === 'false'`)
}

export async function startStudyBrowser(t, { count = 3, apiTarget, contentOverrides = [], coarsePointer = false, nextItemsDelay = 0 } = {}) {
  await exec('agent-browser', ['--version']) // 缺失工具必须失败，不能 skip。
  const exams = [{ id: 1, slug: 'current', name: 'Current', short_name: 'Current' }, { id: 2, slug: 'other', name: 'Other', short_name: 'Other' }]
  const user = { id: 1, username: 'learner', is_admin: true, active_exam: exams[0] }
  const words = Array.from({ length: count }, (_, i) => ({ id: i + 1, term: count === 3 ? ['alpha', 'beta', 'gamma'][i] : `word${String(i).padStart(4, '0')}`, term_zh: ['阿尔法', '贝塔', '伽马'][i % 3], definition_zh: '中文释义\n第二段', definition: '<b>plain text</b>', is_mastered: false }))
  contentOverrides.forEach((content, index) => Object.assign(words[index], content))
  const reads = [], writes = [], responses = [], refreshes = []
  let failMark = false, failVerify = false, markDelay = 0, missingStudyApi = false, failRefresh = false, refreshDelay = 0
  const server = await createServer({
    root, configFile: false, cacheDir: join(root, 'node_modules', '.vite-study-tests', String(process.pid)),
    plugins: [vue(), tailwindcss(), {
      name: 'complete-study-http-fixture',
      configureServer(server) {
        server.middlewares.use(async (req, res, next) => {
          const url = new URL(req.url, 'http://localhost')
          const send = (data, status = 200) => { const body = JSON.stringify(data); if (url.pathname.startsWith('/api/vocab/study/')) responses.push({ path: url.pathname, bytes: Buffer.byteLength(body), status }); res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(body) }
          if (url.pathname === '/__study-test/state') return send({ words, reads, writes, responses, refreshes })
          if (url.pathname === '/__study-test/fail-refresh') { failRefresh = true; return send({}) }
          if (url.pathname === '/__study-test/delay-refresh') { refreshDelay = 1500; return send({}) }
          if (url.pathname === '/__study-test/fail-mark') { failMark = true; return send({}) }
          if (url.pathname === '/__study-test/fail-verify') { failVerify = true; return send({}) }
          if (url.pathname === '/__study-test/delay-mark') { markDelay = 1500; return send({}) }
          if (url.pathname === '/__study-test/missing-api') { missingStudyApi = true; return send({}) }
          if (url.pathname === '/__study-test/enable-api') { missingStudyApi = false; return send({}) }
          if (req.headers.accept?.includes('text/html') && !url.pathname.startsWith('/api/')) {
            res.setHeader('Content-Type', 'text/html')
            res.end(`<!doctype html><html lang="zh-CN"><head><title>备考助手</title><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body><div id="app"></div><script>
              if (!localStorage.getItem('study-test-initialized')) {localStorage.setItem('study-test-initialized','1');${apiTarget ? '' : `localStorage.setItem('token','test-token');localStorage.setItem('user',${JSON.stringify(JSON.stringify(user))});`}}
              </script><script type="module" src="/src/main.js"></script></body></html>`)
            return
          }
          if (apiTarget || !url.pathname.startsWith('/api/')) return next()
          let body = ''
          for await (const chunk of req) body += chunk
          const data = body ? JSON.parse(body) : {}
          if (url.pathname === '/api/auth/me') return send(user)
          if (url.pathname === '/api/exams') return send({ items: exams })
          if (url.pathname === '/api/account/active-exam') { user.active_exam = exams.find(e => e.slug === data.slug); return send({ active_exam: user.active_exam }) }
          if (url.pathname === '/api/banks') return send([{ id: 7, name: 'Bank One' }, { id: 8, name: 'Bank Two' }])
          if (url.pathname === '/api/jobs/active') return send({ job: null })
          if (url.pathname === '/api/vocab/stats') return send({ personal: words.length, exam_personal: 0, all: words.length })
          if (url.pathname === '/api/vocab/frequent') return send({ summary: { total_terms: 5000, top_terms_limit: 5000 }, pagination: { total_pages: 1 }, items: [] })
          if (url.pathname === '/api/vocab/study/deck') {
            if (missingStudyApi) return send({ detail: 'Not Found' }, 404)
            reads.push({ path: 'deck', params: Object.fromEntries(url.searchParams), exam: req.headers['x-exam-slug'] })
            const scope = url.searchParams.get('scope'), mastery = url.searchParams.get('mastery')
            const selected = words.filter(w => scope === 'personal' && (mastery === 'all' || w.is_mastered === (mastery === 'mastered')))
            return send({ schema_version: 1, context: { scope, exam_id: scope === 'personal' ? null : user.active_exam.id, bank_id: null }, mastery, top_limit: null, total: selected.length, refs: selected.map(w => ({ vocabulary_id: w.id })) })
          }
          if (url.pathname === '/api/vocab/study/items') {
            reads.push({ path: 'items', content: data.include_content, count: data.refs.length, exam: req.headers['x-exam-slug'] })
            if (data.include_content && data.refs[0]?.vocabulary_id > 20 && nextItemsDelay)
              await new Promise(resolve => setTimeout(resolve, nextItemsDelay))
            if (!data.include_content && failVerify) { failVerify = false; return send({ detail: 'network failure' }, 503) }
            return send({ results: data.refs.map(ref => {
              const word = words.find(w => w.id === ref.vocabulary_id)
              return word ? { ref, available: true, is_mastered: word.is_mastered, can_delete: true, can_mark_mastered: true, content: data.include_content ? { ...word, frequency: null } : null } : { ref, available: false }
            }) })
          }
          if (url.pathname === '/api/vocab/study/refresh') {
            refreshes.push(data.ref)
            if (refreshDelay) { const delay = refreshDelay; refreshDelay = 0; await new Promise(resolve => setTimeout(resolve, delay)) }
            if (failRefresh) { failRefresh = false; return send({ detail: 'AI generation failed' }, 502) }
            const word = words.find(w => w.id === data.ref.vocabulary_id)
            if (!word) return send({ detail: '词汇不存在' }, 404)
            Object.assign(word, { term_zh: `更新后的 ${word.term} 翻译`, definition: `Updated English definition for ${word.term}.`, definition_zh: `更新后的 ${word.term} 中文释义。` })
            return send({ ref: data.ref, content: { term: word.term, term_zh: word.term_zh, definition: word.definition, definition_zh: word.definition_zh, frequency: null } })
          }
          const progress = url.pathname.match(/^\/api\/vocab\/items\/(\d+)\/progress$/)
          if (progress) {
            if (failMark) { failMark = false; return send({ detail: 'explicit failure' }, 409) }
            const word = words.find(w => w.id === Number(progress[1]))
            word.is_mastered = data.is_mastered; writes.push([word.id, data.is_mastered])
            if (markDelay) { const delay = markDelay; markDelay = 0; await new Promise(resolve => setTimeout(resolve, delay)) }
            return send({ message: '已保存' })
          }
          if (url.pathname === '/api/vocab') return send({ items: [], pagination: { total_pages: 1 } })
          return send({ detail: `Unexpected fixture request: ${req.method} ${url.pathname}` }, 500)
        })
      },
    }],
    server: { host: '127.0.0.1', port: 0, ...(apiTarget ? { proxy: { '/api': { target: apiTarget } } } : {}) },
  })
  await server.listen()
  const profile = await mkdtemp(join(homedir(), 'study-browser-'))
  const session = `study-${process.pid}-${Date.now()}`
  const browser = async (...args) => (await exec('agent-browser', ['--session', session, '--profile', profile, ...(coarsePointer ? ['--args', '--blink-settings=primaryPointerType=2'] : []), ...args], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 })).stdout
  t.after(async () => { try { await browser('close') } finally { await server.close(); await rm(profile, { recursive: true, force: true }) } })
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  return { browser, origin, state: () => fetch(`${origin}/__study-test/state`).then(r => r.json()) }
}
