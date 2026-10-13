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
import tailwindcss from '@tailwindcss/vite'

/**
 * 复盘页旧会话兼容标记的渲染证据。
 *
 * 后端契约已由 `backend/tests/test_quiz_review_api.py` 锁定；这里只验证前端消费：
 * `status_unknown` 优先于 `status`（`status` 只是占位）、`has_snapshot=false` 的提示，
 * 以及不可核实题既不显示「未答」也不显示「错误」。
 */

const exec = promisify(execFile)
const root = fileURLToPath(new URL('../', import.meta.url))

test('复盘页：不可核实的题显示「未知」而不是「未答」或「错误」，旧会话显示快照提示', { timeout: 120000 }, async t => {
  try {
    await exec('agent-browser', ['--version'])
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
    t.skip('浏览器展示测试需要 agent-browser')
    return
  }
  const payload = {
    session: {
      id: 7, bank_id: 1, bank_name: '旧会话题库', mode: 'sequential',
      total_questions: 4, answered_count: 2, correct_count: 1, is_completed: true,
      wrong_count: 1, unanswered_count: 2, accuracy: 50.0, accuracy_basis: 'answered',
      has_snapshot: false,
    },
    questions: [
      { id: 1, index: 1, question_type: 'single', content: '旧题一', options: [{ key: 'A', text: '甲' }, { key: 'B', text: '乙' }], user_answer: 'A', is_correct: true, correct_answer: 'A', status: 'correct', status_unknown: false },
      { id: 2, index: 2, question_type: 'single', content: '旧题二', options: [{ key: 'A', text: '甲' }, { key: 'B', text: '乙' }], user_answer: 'B', is_correct: false, correct_answer: 'A', status: 'wrong', status_unknown: false },
      { id: 3, index: 3, question_type: 'single', content: '旧题三', options: [{ key: 'A', text: '甲' }], user_answer: null, is_correct: null, correct_answer: 'A', status: 'unanswered', status_unknown: true },
      { id: 4, index: 4, question_type: 'single', content: '旧题四', options: [{ key: 'A', text: '甲' }], user_answer: null, is_correct: null, correct_answer: 'A', status: 'unanswered', status_unknown: false },
    ],
  }
  const entry = `
    import { createApp, h } from 'vue'
    import { createPinia } from 'pinia'
    import { createRouter, createMemoryHistory } from 'vue-router'
    import { useExamStore } from '/src/stores/exam.js'
    import QuizReviewView from '/src/views/QuizReviewView.vue'
    import '/src/style.css'
    localStorage.setItem('user', JSON.stringify({is_admin:false}))
    localStorage.setItem('token', 'fixture-token')
    const pinia = createPinia()
    const exam = useExamStore(pinia)
    exam.setCurrent({slug:'legacy'})
    exam.loaded = true
    const router = createRouter({history:createMemoryHistory(), routes:[
      {path:'/exams/:examSlug/quiz/:sessionId/review', component:QuizReviewView},
      {path:'/exams/:examSlug/quiz/:sessionId', component:{render:()=>h('p', '答题页')}},
    ]})
    await router.push(window.__reviewTarget)
    createApp({render:()=>h(QuizReviewView)}).use(pinia).use(router).mount('#app')
  `
  const server = await createServer({
    root, configFile: false, cacheDir: join(root, 'node_modules', '.vite-review-tests', String(process.pid)),
    plugins: [vue(), tailwindcss(), {
      name: 'quiz-review-legacy-fixture',
      resolveId(id) { if (id === '/__review-entry.js') return id },
      load(id) { if (id === '/__review-entry.js') return entry },
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const url = new URL(req.url, 'http://localhost')
          if (url.pathname === '/__review-test') {
            res.setHeader('Content-Type', 'text/html')
            res.end(`<meta name="viewport" content="width=device-width, initial-scale=1"><main id="app" class="mx-auto max-w-6xl px-4 py-6"></main><script>window.__reviewTarget = ${JSON.stringify(url.searchParams.get('target') || '/exams/legacy/quiz/7/review')}</script><script type="module" src="/__review-entry.js"></script>`)
            return
          }
          if (!url.pathname.startsWith('/api/')) return next()
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(url.pathname === '/api/quiz/session/7' ? payload : {}))
        })
      },
    }],
    server: { host: '127.0.0.1', port: 0 },
  })
  await server.listen()
  const profile = await mkdtemp(join(homedir(), 'review-legacy-'))
  const session = `review-legacy-${process.pid}`
  const browser = async (...args) => (await exec('agent-browser', ['--session', session, '--profile', profile, ...args], { timeout: 30000, maxBuffer: 1024 * 1024 })).stdout
  t.after(async () => {
    try { await browser('close') } finally {
      await server.close()
      await rm(profile, { recursive: true, force: true })
    }
  })
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  await browser('set', 'viewport', '1280', '900')
  await browser('open', `${origin}/__review-test`)
  await browser('wait', '--text', '旧题一')

  assert.equal((await browser('get', 'text', '[data-testid=snapshot-warning]')).trim(), '历史题目未保存快照，当前内容可能已变更')
  assert.deepEqual(JSON.parse(await browser('eval', `Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelectorAll('span')[2].textContent.trim())`)),
    ['正确', '错误', '未知', '未答'])

  // 不可核实的题：中性标记，不推断成错误或未答，且不显示用户选择
  await browser('click', '[data-testid=review-nav-3]')
  await browser('wait', '--text', '记录不完整，无法核实本题的作答与判定')
  assert.deepEqual(JSON.parse(await browser('eval', `({
    status: document.querySelector('[data-testid=review-status]').textContent.trim(),
    kind: document.querySelector('[data-testid=review-question]').getAttribute('data-status'),
    userBadge: Boolean(document.querySelector('[data-testid=badge-user-answer]')),
    errorText: document.body.textContent.includes('回答错误'),
  })`)), { status: '未知', kind: 'unknown', userBadge: false, errorText: false })

  // 筛选归类：不可核实题既不在错误筛选，也不在未答筛选
  await browser('click', '[data-testid=review-filter-wrong]')
  await browser('wait', '--fn', `document.querySelectorAll('[data-testid=review-question]').length === 1`)
  assert.equal(JSON.parse(await browser('eval', `document.querySelector('[data-testid=review-question]').getAttribute('data-index')`)), '2')
  await browser('click', '[data-testid=review-filter-unanswered]')
  await browser('wait', '--fn', `document.querySelectorAll('[data-testid=review-question]').length === 1`)
  assert.equal(JSON.parse(await browser('eval', `document.querySelector('[data-testid=review-question]').getAttribute('data-index')`)), '4')

  // 真正未答的题：显示「未答」，不显示用户选择
  assert.deepEqual(JSON.parse(await browser('eval', `({
    status: document.querySelector('[data-testid=review-status]').textContent.trim(),
    userBadge: Boolean(document.querySelector('[data-testid=badge-user-answer]')),
    userAnswerLine: document.body.textContent.includes('你的答案:'),
  })`)), { status: '未答', userBadge: false, userAnswerLine: false })

  const errors = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errors), errors)
})
