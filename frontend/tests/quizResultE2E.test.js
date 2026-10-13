import test from 'node:test'
import assert from 'node:assert/strict'
import { startStudyBrowser } from './helpers/studyBrowser.js'
import { startStudyBackend } from './helpers/studyBackend.js'

/** 完成页统计与四个入口：真实后端（隔离 PostgreSQL）与真实浏览器。 */

const api = (browser, path, options = {}) => browser('eval', `(async () => {
  const response = await fetch(${JSON.stringify(path)}, {
    headers: { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current', 'Content-Type': 'application/json' },
    ${options.method ? `method: ${JSON.stringify(options.method)},` : ''}
    ${options.body ? `body: ${JSON.stringify(JSON.stringify(options.body))},` : ''}
  });
  return { status: response.status, data: await response.json() };
})()`)

const resultUrl = (origin, sessionId) => `${origin}/exams/current/quiz/${sessionId}/result`

/** 等待结果页渲染：统计与四个入口都出现。不等具体题干——模拟考试按 random() 抽题。 */
const waitForResult = browser => browser('wait', '--fn',
  `Boolean(document.querySelector('[data-testid=result-correct]'))
   && Boolean(document.querySelector('[data-testid=result-retry]'))`)

async function signIn(browser, origin) {
  await browser('open', `${origin}/exams/current/dashboard`)
  await browser('find', 'placeholder', '请输入用户名', 'fill', 'study-user')
  await browser('find', 'placeholder', '请输入密码', 'fill', 'StudyTest123!')
  await browser('find', 'role', 'button', 'click', '--name', '登录', '--exact')
  await browser('wait', '--url', '**/dashboard')
}

/** 完成一场会话：前 correctFirst 题答 A（正确），其余答 B（错误），超出 answerFirst 的题不答。 */
async function finishSession(browser, { mode = 'exam', questionCount = 10, answerFirst = 10, correctFirst = 7 } = {}) {
  const started = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 1, mode, question_count: questionCount },
  }))
  assert.equal(started.status, 200, JSON.stringify(started))
  const sessionId = started.data.session.id
  for (const [position, question] of started.data.questions.entries()) {
    if (position >= answerFirst) break
    const answer = position < correctFirst ? 'A' : 'B'
    const posted = JSON.parse(await api(browser, '/api/quiz/answer', {
      method: 'POST', body: { session_id: sessionId, question_id: question.id, user_answer: answer },
    }))
    assert.equal(posted.status, 200, JSON.stringify(posted))
  }
  const finished = JSON.parse(await api(browser, '/api/quiz/finish', { method: 'POST', body: { session_id: sessionId } }))
  assert.equal(finished.status, 200, JSON.stringify(finished))
  return sessionId
}

/** 历史里仍需存在的会话数（含未完成），用于证明重做只创建一场新会话。 */
const sessionCount = async browser => JSON.parse(await api(browser, '/api/quiz/history?per_page=100')).data.total

test('完成页统计与四个入口：对错未答分列、详情移除、复盘与重做入口', { timeout: 300000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  // 1) 模拟 10 题 7 对 3 错完成：完成页 70%、正确 7、错误 3、未答 0（Issue #63 原始症状回归）
  const examId = await finishSession(browser)
  await browser('open', resultUrl(origin, examId))
  await waitForResult(browser)
  const examStats = JSON.parse(await browser('eval', `({
    correct: document.querySelector('[data-testid=result-correct]').textContent.trim(),
    wrong: document.querySelector('[data-testid=result-wrong]').textContent.trim(),
    unanswered: document.querySelector('[data-testid=result-unanswered]').textContent.trim(),
    accuracy: document.querySelector('[data-testid=result-accuracy]').textContent.trim(),
    columns: Array.from(document.querySelectorAll('.grid.grid-cols-3 > div')).map(d =>
      Array.from(d.children).map(c => c.textContent.trim()).join('|')),
    body: document.body.textContent,
  })`))
  assert.equal(examStats.accuracy, '70%')
  assert.deepEqual(examStats.columns, ['7|正确', '3|错误', '0|未答'], '三列必须是正确／错误／未答')
  // 原始症状：模拟考试完成后每题都显示「回答错误」。该文案与截断详情列表都必须不再出现。
  assert.equal(examStats.body.includes('回答错误'), false, '模拟考试完成后不得显示「回答错误」')
  assert.equal(examStats.body.includes('答题详情'), false, '完成页不再内嵌截断的答题详情列表')
  assert.equal(examStats.body.includes('你的答案'), false)

  // 2) 10 题只答 2 题且全对：普通练习 100% / 模拟考试 20%，两者都是 2 对 0 错 8 未答
  const ordinaryId = await finishSession(browser, { mode: 'sequential', answerFirst: 2, correctFirst: 2 })
  await browser('open', resultUrl(origin, ordinaryId))
  await waitForResult(browser)
  assert.deepEqual(JSON.parse(await browser('eval', `({
    correct: document.querySelector('[data-testid=result-correct]').textContent.trim(),
    wrong: document.querySelector('[data-testid=result-wrong]').textContent.trim(),
    unanswered: document.querySelector('[data-testid=result-unanswered]').textContent.trim(),
    accuracy: document.querySelector('[data-testid=result-accuracy]').textContent.trim(),
  })`)), { correct: '2', wrong: '0', unanswered: '8', accuracy: '100%' })

  const partialExamId = await finishSession(browser, { answerFirst: 2, correctFirst: 2 })
  await browser('open', resultUrl(origin, partialExamId))
  await waitForResult(browser)
  // 模拟考试以本场总题数为分母：2 / 10 = 20%
  assert.deepEqual(JSON.parse(await browser('eval', `({
    correct: document.querySelector('[data-testid=result-correct]').textContent.trim(),
    wrong: document.querySelector('[data-testid=result-wrong]').textContent.trim(),
    unanswered: document.querySelector('[data-testid=result-unanswered]').textContent.trim(),
    accuracy: document.querySelector('[data-testid=result-accuracy]').textContent.trim(),
  })`)), { correct: '2', wrong: '0', unanswered: '8', accuracy: '20%' })

  // 3) 零答案结束：0%、未答等于总题数，不崩溃、无 NaN / undefined
  const emptyId = await finishSession(browser, { answerFirst: 0 })
  await browser('open', resultUrl(origin, emptyId))
  await waitForResult(browser)
  const emptyStats = JSON.parse(await browser('eval', `({
    correct: document.querySelector('[data-testid=result-correct]').textContent.trim(),
    wrong: document.querySelector('[data-testid=result-wrong]').textContent.trim(),
    unanswered: document.querySelector('[data-testid=result-unanswered]').textContent.trim(),
    accuracy: document.querySelector('[data-testid=result-accuracy]').textContent.trim(),
    panel: document.querySelector('[data-testid=result-correct]').closest('.rounded-2xl').textContent,
  })`))
  assert.deepEqual(
    { c: emptyStats.correct, w: emptyStats.wrong, u: emptyStats.unanswered, a: emptyStats.accuracy },
    { c: '0', w: '0', u: '10', a: '0%' },
  )
  assert.equal(/NaN|undefined|Infinity|null/.test(emptyStats.panel), false, '零答案结束不得出现 NaN / undefined')

  // 4) 查看详情进入复盘页且默认全部筛选（先回到 7 对 3 错那一场，步骤 3 已切到别的会话）
  await browser('open', resultUrl(origin, examId))
  await waitForResult(browser)
  await browser('click', '[data-testid=result-review]')
  await browser('wait', '--url', `**/quiz/${examId}/review`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=review-question]'))`)
  assert.deepEqual(JSON.parse(await browser('eval', `({
    all: document.querySelector('[data-testid=review-filter-all]').getAttribute('aria-pressed'),
    wrong: document.querySelector('[data-testid=review-filter-wrong]').getAttribute('aria-pressed'),
    cards: document.querySelectorAll('[data-testid=review-question]').length,
    counters: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelector('span').textContent.trim()),
    statuses: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelectorAll('span')[2].textContent.trim()),
  })`)), {
    all: 'true', wrong: 'false', cards: 1,
    counters: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
    statuses: ['正确', '正确', '正确', '正确', '正确', '正确', '正确', '错误', '错误', '错误'],
  })

  // 5) 本次错题进入复盘页并默认选中错误筛选（只含本场错误题，题号仍是原场题号）
  await browser('open', resultUrl(origin, examId))
  await waitForResult(browser)
  await browser('click', '[data-testid=result-review-wrong]')
  await browser('wait', '--url', `**/quiz/${examId}/review?filter=wrong`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=review-filter-wrong]'))`)
  assert.deepEqual(JSON.parse(await browser('eval', `({
    pressed: document.querySelector('[data-testid=review-filter-wrong]').getAttribute('aria-pressed'),
    counters: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelector('span').textContent.trim()),
  })`)), { pressed: 'true', counters: ['8', '9', '10'] })

  // 6) 再来一次：新场题数与模式与原场一致，进度从零开始，且不覆盖原会话
  await browser('open', resultUrl(origin, examId))
  await waitForResult(browser)
  const sessionsBeforeRetry = await sessionCount(browser)
  await browser('click', '[data-testid=result-retry]')
  await browser('wait', '--url', '**/quiz/*')
  await browser('wait', '--fn', `/\\/quiz\\/\\d+$/.test(location.pathname)`)
  const retriedId = Number(await browser('eval', `Number(location.pathname.match(/\\/quiz\\/(\\d+)$/)[1])`))
  assert.notEqual(retriedId, examId, '重做必须创建新会话，不覆盖原会话')
  const retried = JSON.parse(await api(browser, `/api/quiz/session/${retriedId}`))
  assert.equal(retried.status, 200)
  assert.deepEqual(
    {
      mode: retried.data.session.mode,
      total: retried.data.session.total_questions,
      answered: retried.data.session.answered_count,
      correct: retried.data.session.correct_count,
      completed: retried.data.session.is_completed,
    },
    { mode: 'exam', total: 10, answered: 0, correct: 0, completed: false },
  )
  assert.equal(await sessionCount(browser), sessionsBeforeRetry + 1, '重做创建且只创建一场新会话')
  const original = JSON.parse(await api(browser, `/api/quiz/session/${examId}`))
  assert.equal(original.data.session.is_completed, true, '原会话保持已完成，不被覆盖')

  // 7) 原题被删除后「再来一次」：留在原页并提示不可用题目，不创建部分会话
  const deleteTarget = JSON.parse(await api(browser, `/api/quiz/session/${examId}`)).data.questions[0]
  assert.equal(JSON.parse(await api(browser, `/api/questions/${deleteTarget.id}`, { method: 'DELETE' })).status, 200)
  const sessionsBeforeFailure = await sessionCount(browser)
  await browser('open', resultUrl(origin, examId))
  await waitForResult(browser)
  await browser('click', '[data-testid=result-retry]')
  // 等请求结束：按钮从 disabled 恢复即代表 finally 已执行
  await browser('wait', '--fn', `(() => {
    const button = document.querySelector('[data-testid=result-retry]');
    return Boolean(button) && !button.disabled;
  })()`)
  const failure = JSON.parse(await browser('eval', `({
    url: location.pathname,
    toast: Array.from(document.querySelectorAll('div.fixed.top-4.right-4 span')).map(s => s.textContent.trim()).join('|'),
    accuracy: document.querySelector('[data-testid=result-accuracy]').textContent.trim(),
  })`))
  assert.match(failure.url, new RegExp(`/quiz/${examId}/result$`), '失败必须留在原结果页')
  assert.equal(failure.accuracy, '70%', '失败不得清空或改写页面内容')
  assert.match(failure.toast, /部分原题已不可用/, '必须提示失败原因而不是空提示')
  assert.match(failure.toast, new RegExp(String(deleteTarget.id)), '提示必须列出不可用题目 ID')
  assert.equal(await sessionCount(browser), sessionsBeforeFailure, '整场失败不得创建部分会话')

  // 8) 历史页已完成会话进入复盘页，不再指向结果页
  await browser('open', `${origin}/exams/current/history`)
  await browser('wait', '--fn', `document.querySelectorAll('a[href*="/quiz/"]').length > 0`)
  const historyHrefs = JSON.parse(await browser('eval',
    `Array.from(document.querySelectorAll('a[href*="/quiz/"]')).map(a => a.getAttribute('href'))`))
  assert.ok(historyHrefs.length > 0, '历史列表必须有可点击的会话')
  assert.equal(historyHrefs.some(href => href.includes('/result')), false, '历史入口不再指向结果页')
  assert.equal(historyHrefs.every(href => /\/quiz\/\d+\/review$/.test(href)), true, historyHrefs.join(','))
  // 明确点已完成的那一场：历史里还有未完成会话，它们进复盘页会被重定向回答题页
  const finishedHref = historyHrefs.find(href => href.includes(`/quiz/${examId}/review`))
  assert.ok(finishedHref, `历史必须包含已完成会话 ${examId} 的复盘入口：${historyHrefs.join(',')}`)
  await browser('click', `a[href="${finishedHref}"]`)
  await browser('wait', '--url', `**/quiz/${examId}/review`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=review-filter-all]'))`)

  const errors = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errors), errors)
})

test('再来一次请求期间禁用：连点只发出一次请求、只创建一场会话', { timeout: 240000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const examId = await finishSession(browser)
  await browser('open', resultUrl(origin, examId))
  await waitForResult(browser)

  const sessionsBefore = await sessionCount(browser)
  await browser('network', 'requests', '--clear')
  // 阳性对照：同页面真实发一次请求，证明网络记录通道确实抓得到流量
  await browser('eval', `(async () => { await fetch('/api/quiz/history').then(() => true, () => true); return true })()`)
  let controlCaptured = false
  for (let attempt = 0; attempt < 20 && !controlCaptured; attempt++) {
    const logged = JSON.parse(await browser('network', 'requests', '--json')).data.requests
    controlCaptured = logged.some(r => String(r.url || '').includes('/api/quiz/history'))
    if (!controlCaptured) await new Promise(resolve => setTimeout(resolve, 50))
  }
  assert.ok(controlCaptured, '网络记录通道必须能抓到请求，否则「连点只发一次」断言恒真')
  await browser('network', 'requests', '--clear')

  // 在 XHR 层延迟 /quiz/retry 的请求，让按钮停在 pending 状态，从而能观测连点行为。
  // 不能对 window.fetch 打桩：axios 浏览器适配器优先走 XHR，fetch 桩会绕过真实请求。
  await browser('eval', `(() => {
    localStorage.setItem('retry-posts', '0');
    const xhrOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      if (String(url).includes('/quiz/retry')) {
        localStorage.setItem('retry-posts', String(Number(localStorage.getItem('retry-posts')) + 1));
        const send = this.send.bind(this);
        this.send = (...args) => setTimeout(() => send(...args), 900);
      }
      return xhrOpen.call(this, method, url, ...rest);
    };
    return true;
  })()`)

  // 连点 5 次：首次点击进入 pending 后按钮禁用，后续点击不再发出请求。
  // Vue 的 DOM 更新在微任务里，点击后先让出一拍再读 disabled，否则读到的是更新前的 false。
  const clicks = JSON.parse(await browser('eval', `(async () => {
    const button = document.querySelector('[data-testid=result-retry]');
    button.click();
    await new Promise(resolve => setTimeout(resolve, 30));
    const disabledAfterFirstClick = button.disabled;
    for (let i = 0; i < 4; i++) {
      button.click();
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    return { disabledAfterFirstClick, disabledAtEnd: button.disabled, posted: Number(localStorage.getItem('retry-posts')) };
  })()`))
  assert.equal(clicks.disabledAfterFirstClick, true, '首次点击进入 pending 后按钮必须禁用')
  assert.equal(clicks.disabledAtEnd, true)
  assert.equal(clicks.posted, 1, `连点只应发出一次 /quiz/retry，实际 ${clicks.posted} 次`)
  await browser('wait', '--fn', `/\\/quiz\\/\\d+$/.test(location.pathname)`)
  assert.equal(await sessionCount(browser), sessionsBefore + 1, '连点只应创建一场新会话')

  // 反向金丝雀：证明计数器不是「最多只记 1」的假通道——真实并发发出 3 次请求时必须如实计数为 3。
  // 上面的 patch 仍在当前页面生效，这里只重置计数并直接发请求，不重复注入（叠加会重复计数）。
  const capacity = JSON.parse(await browser('eval', `(async () => {
    localStorage.setItem('retry-posts', '0');
    const post = () => new Promise(resolve => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/quiz/retry');
      xhr.setRequestHeader('Authorization', 'Bearer ' + localStorage.getItem('token'));
      xhr.setRequestHeader('X-Exam-Slug', 'current');
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.onloadend = () => resolve(xhr.status);
      xhr.send(JSON.stringify({ session_id: ${examId} }));
    });
    const statuses = await Promise.all([post(), post(), post()]);
    return { posted: Number(localStorage.getItem('retry-posts')), statuses };
  })()`))
  assert.equal(capacity.posted, 3, `金丝雀：3 次真实请求必须被计数为 3，实际 ${capacity.posted}`)
  assert.deepEqual(capacity.statuses, [200, 200, 200])

  const errors = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errors), errors)
})

test('回归门禁：完成态不再输出 answers，未完成会话刷新恢复仍可续答', { timeout: 240000 }, async t => {
  // design.md §8：session_detail 是答题页恢复与结果页共用的接口，完成态删 `answers`
  // 是本任务最大的回归风险。这里同时锁两侧：完成态不输出、未完成态必须在，
  // 且答题页刷新后能靠它恢复判定与进度。
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  const started = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 1, mode: 'sequential', question_count: 10 },
  }))
  assert.equal(started.status, 200, JSON.stringify(started))
  const sessionId = started.data.session.id
  const questionIds = started.data.questions.map(question => question.id)
  // 夹具每题正确答案都是 A：第 1 题答对、第 2 题答错
  for (const [position, answer] of [[0, 'A'], [1, 'B']]) {
    assert.equal(JSON.parse(await api(browser, '/api/quiz/answer', {
      method: 'POST', body: { session_id: sessionId, question_id: questionIds[position], user_answer: answer },
    })).status, 200)
  }

  // 未完成：`answers` 必须仍在，且答题页刷新后恢复判定与恢复索引
  const inProgress = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`))
  assert.equal(inProgress.data.session.is_completed, false)
  assert.equal(Array.isArray(inProgress.data.answers), true, '未完成会话必须保留 answers 供答题页恢复')
  assert.deepEqual(inProgress.data.answers.map(a => a.is_correct), [true, false])
  assert.equal(inProgress.data.session.resume_index, 2)

  await browser('open', `${origin}/exams/current/quiz/${sessionId}`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=question-timer]'))`)
  assert.equal(JSON.parse(await browser('eval', `location.pathname`)), `/exams/current/quiz/${sessionId}`)
  assert.equal(JSON.parse(await browser('eval', `document.body.textContent.includes('3 / 10')`)), true, '恢复索引指向第 3 题')
  await browser('eval', `(() => { location.reload(); return true })()`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=question-timer]'))`)
  assert.equal(JSON.parse(await browser('eval', `document.body.textContent.includes('3 / 10')`)), true, 'reload 后恢复索引必须保持')
  const nav = JSON.parse(await browser('eval', `(() => {
    const items = Array.from(document.querySelectorAll('nav button, .overflow-y-auto button')).map(b => b.textContent.replace(/\\s+/g, ' ').trim());
    return items.filter(text => /第 \\d+ 题/.test(text));
  })()`))
  assert.equal(nav.length, 10, nav.join('|'))
  assert.match(nav[0], /正确/, '第 1 题刷新后必须恢复「正确」')
  assert.match(nav[1], /错误/, '第 2 题刷新后必须恢复「错误」')
  assert.match(nav[2], /未答/, '未答题恢复为「未答」')

  // 完成态：同一个接口不再输出 `answers`，避免两套题号口径并存
  assert.equal(JSON.parse(await api(browser, '/api/quiz/finish', {
    method: 'POST', body: { session_id: sessionId },
  })).status, 200)
  const finished = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`))
  assert.equal(finished.data.session.is_completed, true)
  assert.equal('answers' in finished.data, false, '完成态只给复盘结构 questions')
  assert.equal(finished.data.questions.length, 10)

  const errors = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errors), errors)
})
