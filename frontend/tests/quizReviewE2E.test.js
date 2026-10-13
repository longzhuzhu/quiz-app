import test from 'node:test'
import assert from 'node:assert/strict'
import { startStudyBrowser } from './helpers/studyBrowser.js'
import { startStudyBackend } from './helpers/studyBackend.js'

/** 真实后端（隔离 PostgreSQL + 真实 worker）与真实浏览器：复盘页只读契约与 Issue #63 回归。 */

const api = (browser, path, options = {}) => browser('eval', `(async () => {
  const response = await fetch(${JSON.stringify(path)}, {
    headers: { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current', 'Content-Type': 'application/json' },
    ${options.method ? `method: ${JSON.stringify(options.method)},` : ''}
    ${options.body ? `body: ${JSON.stringify(JSON.stringify(options.body))},` : ''}
  });
  return { status: response.status, data: await response.json() };
})()`)

/**
 * 等待复盘页首题渲染完成。
 *
 * 不能等待某道具体题干的文案：模拟考试按 `ORDER BY random()` 抽题（11 题抽 10 题），
 * 长题干题可能落在第一位，短题干文案就不再出现。这里只等「会话已加载且当前题已渲染」。
 */
const waitForReview = browser => browser('wait', '--fn',
  `Boolean(document.querySelector('[data-testid=review-question]'))
   && Boolean(document.querySelector('[data-testid=summary-correct]'))`)

async function signIn(browser, origin) {
  await browser('open', `${origin}/exams/current/dashboard`)
  await browser('find', 'placeholder', '请输入用户名', 'fill', 'study-user')
  await browser('find', 'placeholder', '请输入密码', 'fill', 'StudyTest123!')
  await browser('find', 'role', 'button', 'click', '--name', '登录', '--exact')
  await browser('wait', '--url', '**/dashboard')
}

/** 完成一场模拟考试：前 7 题答 A（正确），后 3 题答 B（错误）。 */
async function finishExamSession(browser, { answerFirst = 10, correctFirst = 7 } = {}) {
  const started = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 1, mode: 'exam', question_count: 10 },
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

test('复盘页只读呈现：区分对错与未答、保留原场题号、无作答或改判入口', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await finishExamSession(browser)
  const reviewUrl = `${origin}/exams/current/quiz/${sessionId}/review`

  // 1) 模拟 10 题 7 对 3 错完成：统计与逐题判定（Issue #63 原始症状回归）
  await browser('open', reviewUrl)
  await waitForReview(browser)
  assert.deepEqual(JSON.parse(await browser('eval', `({
    correct: document.querySelector('[data-testid=summary-correct]').textContent.trim(),
    wrong: document.querySelector('[data-testid=summary-wrong]').textContent.trim(),
    unanswered: document.querySelector('[data-testid=summary-unanswered]').textContent.trim(),
    accuracy: document.querySelector('[data-testid=summary-accuracy]').textContent.trim(),
    counters: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelector('span').textContent.trim()),
    statuses: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelectorAll('span')[2].textContent.trim()),
    correctAnswers: Array.from(document.querySelectorAll('[data-testid=badge-correct-answer]')).map(e => e.textContent.trim()),
    warning: Boolean(document.querySelector('[data-testid=snapshot-warning]')),
    forbidden: ['提交答案', '完成答题', '更正答案'].filter(text => Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === text)),
    forbiddenInCard: ['提交答案', '完成答题', '更正答案', '下一题'].filter(text => Array.from(document.querySelectorAll('[data-testid=review-question] button')).some(b => b.textContent.trim() === text)),
    optionButtons: document.querySelectorAll('[data-testid=review-option] button, [data-testid=review-option] input, [data-testid=review-option] label').length,
  })`)), {
    correct: '7', wrong: '3', unanswered: '0', accuracy: '70%',
    counters: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
    statuses: ['正确', '正确', '正确', '正确', '正确', '正确', '正确', '错误', '错误', '错误'],
    correctAnswers: ['当场正确答案'],
    warning: false,
    forbidden: [],
    forbiddenInCard: [],
    optionButtons: 0,
  })

  // 未答题的显示：单独一场只答 2 题
  const partialId = await finishExamSession(browser, { answerFirst: 2, correctFirst: 2 })
  await browser('open', `${origin}/exams/current/quiz/${partialId}/review`)
  await waitForReview(browser)
  assert.deepEqual(JSON.parse(await browser('eval', `({
    correct: document.querySelector('[data-testid=summary-correct]').textContent.trim(),
    wrong: document.querySelector('[data-testid=summary-wrong]').textContent.trim(),
    unanswered: document.querySelector('[data-testid=summary-unanswered]').textContent.trim(),
    accuracy: document.querySelector('[data-testid=summary-accuracy]').textContent.trim(),
    statuses: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelectorAll('span')[2].textContent.trim()).join(','),
  })`)), {
    correct: '2', wrong: '0', unanswered: '8', accuracy: '20%',
    statuses: '正确,正确,未答,未答,未答,未答,未答,未答,未答,未答',
  })

  // 2) 点击选项不改变选中状态、不发起请求（只读回归防线）
  // 用 CDP 层网络记录而非替换 window.fetch：axios 在浏览器里优先走 XHR 适配器
  // （`['xhr','http','fetch']`），只埋 fetch 会让「无请求」断言恒真、失去防线意义。
  await browser('open', reviewUrl)
  await waitForReview(browser)
  await browser('wait', '--fn', `!Array.from(document.querySelectorAll('button')).some(b => /解析中|更新中/.test(b.textContent))`)
  await browser('network', 'requests', '--clear')
  // 阳性对照：同页面发起一次真实请求，证明网络记录通道确实抓得到流量
  await browser('eval', `(async () => { await fetch('/api/quiz/history').then(() => true, () => true); return true })()`)
  let controlCaptured = false
  for (let attempt = 0; attempt < 20 && !controlCaptured; attempt++) {
    const logged = JSON.parse(await browser('network', 'requests', '--json')).data.requests
    controlCaptured = logged.some(r => String(r.url || '').includes('/api/quiz/history'))
    if (!controlCaptured) await new Promise(resolve => setTimeout(resolve, 50))
  }
  assert.ok(controlCaptured, '网络记录通道必须能抓到请求，否则「无请求」断言恒真')
  await browser('network', 'requests', '--clear')
  const readonly = JSON.parse(await browser('eval', `(async () => {
    const snapshot = () => ({
      status: document.querySelector('[data-testid=review-status]').textContent.trim(),
      kind: document.querySelector('[data-testid=review-question]').getAttribute('data-status'),
      options: Array.from(document.querySelectorAll('[data-testid=review-option]')).map(o => o.outerHTML).join(''),
      badges: Array.from(document.querySelectorAll('[data-testid=review-question] [data-testid^=badge-]')).map(b => b.textContent.trim()).join(','),
    });
    const before = snapshot();
    const option = document.querySelector('[data-testid=review-option]');
    option.click(); option.click();
    await new Promise(resolve => setTimeout(resolve, 600));
    return {
      unchanged: JSON.stringify(snapshot()) === JSON.stringify(before),
      checkboxesChecked: document.querySelectorAll('[data-testid=review-option] input:checked').length,
    };
  })()`))
  assert.equal(readonly.unchanged, true, '点击选项不得改变判定、选择与选项状态')
  const clickRequests = JSON.parse(await browser('network', 'requests', '--json')).data.requests
  assert.deepEqual(clickRequests.filter(r => /\/quiz\/answer|\/questions\/\d+\/correct-answer/.test(r.url || '')), [],
    '点击选项不得调用 /quiz/answer 或 correct-answer')
  assert.equal(readonly.checkboxesChecked, 0)

  // 3) ?filter=wrong 直达错误筛选，题号仍是原场题号
  await browser('open', `${reviewUrl}?filter=wrong`)
  await waitForReview(browser)
  assert.deepEqual(JSON.parse(await browser('eval', `({
    pressed: document.querySelector('[data-testid=review-filter-wrong]').getAttribute('aria-pressed'),
    counters: Array.from(document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])')).map(b => b.querySelector('span').textContent.trim()),
    index: document.querySelector('[data-testid=review-question]').getAttribute('data-index'),
  })`)), { pressed: 'true', counters: ['8', '9', '10'], index: '8' })

  // 4) 空状态：没有未答题时不跳走、不留 dangling 提示
  await browser('open', `${reviewUrl}?filter=unanswered`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=review-empty]'))`)
  assert.equal(JSON.parse(await browser('eval', `({
    text: document.querySelector('[data-testid=review-empty]').textContent.trim(),
    cards: document.querySelectorAll('[data-testid=review-question]').length,
    url: location.pathname,
  })`)).text, '本场没有未答的题目')
  assert.equal(JSON.parse(await browser('eval', `document.querySelectorAll('[data-testid=review-question]').length`)), 0)
  assert.match(await browser('get', 'url'), /\/review\?filter=unanswered/)

  // 5) 桌面与手机：长题干完整可读、不被固定导航遮挡
  const longSession = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 1, mode: 'sequential' },
  }))
  const longQuestion = longSession.data.questions.at(-1)
  const longId = longSession.data.session.id
  assert.equal(JSON.parse(await api(browser, '/api/quiz/answer', {
    method: 'POST', body: { session_id: longId, question_id: longQuestion.id, user_answer: 'A' },
  })).status, 200)
  assert.equal(JSON.parse(await api(browser, '/api/quiz/finish', {
    method: 'POST', body: { session_id: longId },
  })).status, 200)
  await browser('open', `${origin}/exams/current/quiz/${longId}/review`)
  await waitForReview(browser)
  await browser('click', '[data-testid=review-nav-11]')
  await browser('wait', '--text', 'Which control is MOST effective for the international transfer')
  const longStem = JSON.parse(await browser('eval', `(() => {
    const stem = document.querySelector('[data-testid=review-question] p');
    return { full: stem.textContent.trim(), truncate: stem.className.includes('truncate'), options: document.querySelectorAll('[data-testid=review-option]').length };
  })()`))
  assert.match(longStem.full, /international transfer scenario described above\? Which control is MOST effective for the international transfer scenario described above\?/)
  assert.equal(longStem.truncate, false)
  assert.equal(longStem.options, 4)
  await browser('set', 'viewport', '375', '812')
  await browser('wait', '--fn', `document.querySelector('[data-testid^=review-nav-mobile-]') !== null`)
  const mobile = JSON.parse(await browser('eval', `(() => {
    const nav = document.querySelector('[data-testid^=review-nav-mobile-]').parentElement.parentElement;
    const card = document.querySelector('[data-testid=review-question]');
    card.scrollIntoView({ block: 'end' });
    const option = document.querySelectorAll('[data-testid=review-option]')[3].getBoundingClientRect();
    return { navFixed: getComputedStyle(nav).position, navBottom: nav.getBoundingClientRect().bottom, optionBottom: option.bottom, navTop: nav.getBoundingClientRect().top, overflow: document.documentElement.scrollWidth > innerWidth };
  })()`))
  assert.equal(mobile.navFixed, 'fixed')
  assert.equal(mobile.overflow, false)
  assert.ok(mobile.optionBottom <= mobile.navTop + 1, `最后一个选项不应被底部导航遮挡：${JSON.stringify(mobile)}`)

  // 6) 保留翻译与 AI 解析
  await browser('set', 'viewport', '1280', '900')
  await browser('open', reviewUrl)
  await waitForReview(browser)
  await browser('find', 'role', 'button', 'click', '--name', '翻译', '--exact')
  await browser('wait', '--text', '复盘翻译内容')
  await browser('find', 'role', 'button', 'click', '--name', 'AI 解析', '--exact')
  await browser('wait', '--fn', `!Array.from(document.querySelectorAll('button')).some(b => /解析中|更新中/.test(b.textContent))`)
  assert.equal(JSON.parse(await browser('eval', `document.querySelectorAll('[data-model-id]').length`)), 2, '复盘页应展示每个配置模型的解析')
  assert.match(await browser('get', 'text', '[data-model-id="model-alpha"]'), /模型认定答案：A/)

  // 7) 未完成会话不能借复盘路由提前查看答案与对错：前端回答题页，后端也不返回判定
  const inProgress = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 1, mode: 'exam', question_count: 10 },
  }))
  const inProgressId = inProgress.data.session.id
  assert.equal(JSON.parse(await api(browser, '/api/quiz/answer', {
    method: 'POST', body: { session_id: inProgressId, question_id: inProgress.data.questions[0].id, user_answer: 'A' },
  })).status, 200)
  const inProgressDetail = JSON.parse(await api(browser, `/api/quiz/session/${inProgressId}`))
  assert.deepEqual(inProgressDetail.data.questions.map(q => Object.keys(q).filter(key => ['is_correct', 'correct_answer', 'status', 'status_unknown'].includes(key))), Array(10).fill([]))
  assert.equal('accuracy' in inProgressDetail.data.session, false)
  await browser('open', `${origin}/exams/current/quiz/${inProgressId}/review`)
  await browser('wait', '--url', `**/exams/current/quiz/${inProgressId}`)
  assert.equal(JSON.parse(await browser('eval', `({
    leaked: document.body.textContent.includes('当场正确答案') || document.body.textContent.includes('本场正确率'),
    reviewing: Boolean(document.querySelector('[data-testid=review-question]')),
  })`)).leaked, false, '未结束模拟不得在复盘页泄露答案与对错')
  assert.equal(JSON.parse(await browser('eval', `Boolean(document.querySelector('[data-testid=review-question]'))`)), false)

  // 8) 完成后删除其中一道错题：有快照仍能复盘该题的题干、选择与判定（R1/R8）
  const finishedDetail = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`))
  const removedQuestion = finishedDetail.data.questions[7]
  assert.equal(removedQuestion.status, 'wrong')
  assert.equal(JSON.parse(await api(browser, `/api/questions/${removedQuestion.id}`, { method: 'DELETE' })).status, 200)
  await browser('open', `${reviewUrl}?filter=wrong`)
  await waitForReview(browser)
  await browser('wait', '--fn', `document.querySelectorAll('button[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])').length === 3`)
  assert.deepEqual(JSON.parse(await browser('eval', `(() => {
    const card = document.querySelector('[data-testid=review-question]');
    return {
      index: card.getAttribute('data-index'),
      status: card.getAttribute('data-status'),
      content: card.querySelector('p').textContent.trim(),
      corrected: document.querySelector('[data-testid=badge-correct-answer]').textContent.trim(),
      userAnswer: document.querySelector('[data-testid=badge-user-answer]').textContent.trim(),
      options: document.querySelectorAll('[data-testid=review-option]').length,
    };
  })()`)), {
    // 与卡片一致地 trim：兜底数据里长题干以空格结尾，模拟抽题可能把它排到第 8 题
    index: '8', status: 'wrong', content: removedQuestion.content.trim(),
    corrected: '当场正确答案', userAnswer: '你的答案', options: 4,
  })

  // 9) 未登录访问复盘路由回到登录页（既有守卫，不新增权限边界）
  await browser('eval', `localStorage.removeItem('token'); localStorage.removeItem('user'); true`)
  await browser('open', reviewUrl)
  await browser('wait', '--url', '**/login')
  assert.equal(JSON.parse(await browser('eval', `Boolean(document.querySelector('[data-testid=review-question]'))`)), false)

  const errors = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errors), errors)
})
