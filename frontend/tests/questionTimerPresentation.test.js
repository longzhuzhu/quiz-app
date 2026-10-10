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

const exec = promisify(execFile)
const root = fileURLToPath(new URL('../', import.meta.url))

async function startBrowser(t, { standalone = false, submitted = false } = {}) {
  try {
    await exec('agent-browser', ['--version'])
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
    t.skip('浏览器展示测试需要 agent-browser')
    return null
  }
  const question = {
    id: 101, content: '当前题计时展示测试', question_type: 'multiple',
    options: [{ key: 'A', text: '选项 A' }], user_answer_count: 12345,
  }
  // 真实答题页与 CSS；仅在 HTTP 边界提供隔离会话，不使用线上数据。
  const entry = `
    import { createApp, h } from 'vue'
    import { createPinia } from 'pinia'
    import { createRouter, createMemoryHistory } from 'vue-router'
    import { useExamStore } from '/src/stores/exam.js'
    import QuizView from '/src/views/QuizView.vue'
    import QuestionCard from '/src/components/QuestionCard.vue'
    import '/src/style.css'
    localStorage.setItem('user', JSON.stringify({is_admin:false}))
    const pinia = createPinia()
    const exam = useExamStore(pinia)
    exam.setCurrent({slug:'timer'})
    exam.loaded = true
    const router = createRouter({history:createMemoryHistory(), routes:[
      {path:'/exams/:examSlug/quiz/:sessionId', component:QuizView},
    ]})
    await router.push('/exams/timer/quiz/1')
    createApp({render:() => ${standalone
      ? `h(QuestionCard, {question:${JSON.stringify(question)}, currentIndex:0, total:1, answerCount:12345})`
      : 'h(QuizView)'}}).use(pinia).use(router).mount('#app')
  `
  const server = await createServer({
    root, configFile: false,
    define: { 'import.meta.env.VITE_API_BASE_URL': 'undefined' },
    plugins: [vue(), tailwindcss(), {
      name: 'question-timer-presentation-fixture',
      resolveId(id) { if (id === '/__timer-entry.js') return id },
      load(id) { if (id === '/__timer-entry.js') return entry },
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/__timer-test') {
            res.setHeader('Content-Type', 'text/html')
            res.end('<meta name="viewport" content="width=device-width, initial-scale=1"><main id="app" class="mx-auto max-w-6xl px-4 py-6"></main><script type="module" src="/__timer-entry.js"></script>')
            return
          }
          if (!req.url.startsWith('/api/')) return next()
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(req.url === '/api/quiz/session/1' ? {
            session: { id: 1, mode: 'sequential', bank_name: '计时测试题库', total_questions: 1, resume_index: 0 },
            questions: [question],
            answers: submitted ? [{question_id:101, user_answer:'A', is_correct:true, correct_answer:'A'}] : [],
          } : {}))
        })
      },
    }],
    server: { host: '127.0.0.1', port: 0 },
  })
  await server.listen()
  const profile = await mkdtemp(join(homedir(), 'timer-presentation-'))
  const session = `timer-presentation-${process.pid}-${standalone}-${submitted}`
  const browser = async (...args) => (await exec('agent-browser', ['--session', session, '--profile', profile, ...args], {
    timeout: 30000, maxBuffer: 1024 * 1024,
  })).stdout
  t.after(async () => {
    try { await browser('close') } finally {
      await server.close()
      await rm(profile, {recursive:true, force:true})
    }
  })
  await browser('open', `http://127.0.0.1:${server.httpServer.address().port}/__timer-test`)
  await browser('wait', '--text', '当前题计时展示测试')
  return browser
}

test('current-question time is inside the card immediately left of answer count, with readable contrast', {timeout:120000}, async (t) => {
  const browser = await startBrowser(t)
  if (!browser) return
  const inspectTimer = async () => JSON.parse(await browser('eval', `(() => {
    const timer = document.querySelector('[data-testid="question-timer"]')
    const count = timer.parentElement.querySelector('span:last-child')
    const card = timer.closest('.rounded-xl')
    const style = getComputedStyle(timer)
    const rect = timer.getBoundingClientRect()
    const countRect = count.getBoundingClientRect()
    function luminance(color) {
      const ctx=document.createElement('canvas').getContext('2d')
      ctx.fillStyle=color; ctx.fillRect(0,0,1,1)
      const c=[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(v=>{
        v/=255; return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4
      })
      return c[0]*0.2126+c[1]*0.7152+c[2]*0.0722
    }
    const a=luminance(style.color), b=card?luminance(getComputedStyle(card).backgroundColor):0
    return {text:timer.textContent.trim(), count:count.textContent.trim(), inCard:!!card,
      adjacent:timer.nextElementSibling===count, leftOfCount:rect.right<=countRect.left,
      contrast:(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05), weight:Number(style.fontWeight),
      fits:rect.left>=0 && countRect.right<=innerWidth && document.documentElement.scrollWidth<=innerWidth}
  })()`))
  for (const width of [1280, 375, 320]) {
    await browser('set', 'viewport', String(width), '900')
    for (const dark of [false, true]) {
      await browser('eval', `document.documentElement.classList.toggle('dark', ${dark})`)
      const result = await inspectTimer()
      assert.equal(result.inCard, true, '计时必须属于当前题卡片，而不是题库概览栏')
      assert.match(result.text, /^用时 \d{2}:\d{2}/)
      assert.equal(result.count, '已答 12345 次')
      assert.equal(result.adjacent && result.leftOfCount, true)
      assert.equal(result.fits, true, `${width}px 不应溢出或拆开计时与作答次数`)
      assert.ok(result.contrast >= 7 && result.weight >= 500, JSON.stringify(result))
    }
  }
})

test('cards outside the quiz page do not gain a timer', {timeout:120000}, async (t) => {
  const browser = await startBrowser(t, {standalone:true})
  if (!browser) return
  assert.equal(JSON.parse(await browser('eval', 'document.querySelectorAll("[data-testid=question-timer]").length')), 0)
  assert.match(await browser('get', 'text', 'main'), /已答 12345 次/)
})

test('restored submitted questions keep their unknown-duration status', {timeout:120000}, async (t) => {
  const browser = await startBrowser(t, {submitted:true})
  if (!browser) return
  assert.equal(JSON.parse(await browser('eval', 'document.querySelector("[data-testid=question-timer]").textContent.trim()')), '已提交')
})
