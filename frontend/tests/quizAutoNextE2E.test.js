import test from 'node:test'
import assert from 'node:assert/strict'
import { startStudyBrowser } from './helpers/studyBrowser.js'
import { startStudyBackend } from './helpers/studyBackend.js'

/**
 * 「自动下一题」回归：偏好持久化、单选点击即提交、失败停留、
 * 多选/改答 300ms、最后一题不跳、解析不自动展开。
 * 使用真实认证、真实 /api/quiz 与隔离 PostgreSQL。
 */

const autoNextBox = '[data-testid=auto-next]'
// 选项 label 都以 space-y-3 容器内的 radio/checkbox 呈现；用 :has(> input) 排除外层偏好 label。
const option = n => `.space-y-3 > label:nth-child(${n})`
const optionRadio = option(1)

async function API(browser, path, { method = 'GET', body } = {}) {
  const result = await browser('eval', `(async () => {
    const response = await fetch(${JSON.stringify(path)}, {
      method: ${JSON.stringify(method)},
      headers: {
        'X-Exam-Slug': 'current',
        'Content-Type': 'application/json',
        ...(localStorage.getItem('token') === null ? {} : { Authorization: 'Bearer ' + localStorage.getItem('token') }),
      },
      ${body ? `body: ${JSON.stringify(JSON.stringify(body))},` : ''}
    });
    return { status: response.status, data: await response.json().catch(() => null) };
  })()`)
  return JSON.parse(result)
}

const evalJson = async (browser, expression) => JSON.parse(await browser('eval', expression))

const waitForQuizReady = browser => browser('wait', '--fn',
  `Boolean(document.querySelector('.space-y-3 > label:has(> input)'))`)

const headingPosition = browser => evalJson(browser,
  `document.querySelector('[data-testid=quiz-position]')?.textContent.split('/')[0].trim() ?? null`)
const waitForPosition = (browser, position) => browser('wait', '--fn',
  `(document.querySelector('[data-testid=quiz-position]')?.textContent || '').startsWith('${position} /')`)

const checkedOptionText = browser => evalJson(browser,
  `(() => {
    const input = document.querySelector('.space-y-3 > label > input:checked');
    return input ? input.closest('label').textContent.trim() : null;
  })()`)

const autoNextChecked = browser => evalJson(browser,
  `document.querySelector('${autoNextBox}').checked`)

async function signIn(browser, origin) {
  await browser('open', `${origin}/exams/current/dashboard`)
  await browser('find', 'placeholder', '请输入用户名', 'fill', 'study-user')
  await browser('find', 'placeholder', '请输入密码', 'fill', 'StudyTest123!')
  await browser('find', 'role', 'button', 'click', '--name', '登录', '--exact')
  await browser('wait', '--url', '**/dashboard')
}

async function startSession(browser, { bankId = 1, mode = 'sequential' } = {}) {
  const started = await API(browser, '/api/quiz/start', { method: 'POST', body: { bank_id: bankId, mode } })
  assert.equal(started.status, 200, JSON.stringify(started))
  return started.data.session.id
}

async function openQuiz(browser, origin, sessionId) {
  await browser('open', `${origin}/exams/current/quiz/${sessionId}`)
  await waitForQuizReady(browser)
}

const noScriptErrors = async browser => {
  const errors = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errors), errors)
}

test('自动下一题：偏好按用户持久化，单选点击即提交并立即切题', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser)
  await openQuiz(browser, origin, sessionId)
  assert.equal(await autoNextChecked(browser), false, '首次使用默认关闭')

  await browser('check', autoNextBox)
  assert.equal(await evalJson(browser, `localStorage.getItem('quiz_auto_next:1')`), 'true',
    '偏好必须按用户写入 localStorage')

  await browser('eval', '(() => { location.reload(); return true })()')
  await waitForQuizReady(browser)
  assert.equal(await autoNextChecked(browser), true, '刷新后偏好必须保持')

  await browser('open', `${origin}/exams/current/dashboard`)
  await openQuiz(browser, origin, sessionId)
  assert.equal(await autoNextChecked(browser), true, '新开页面后偏好必须保持')

  // 单选点击即提交并立即切题；下一题不继承选择
  await browser('click', optionRadio)
  await waitForPosition(browser, 2)
  assert.equal(await checkedOptionText(browser), null, '下一题不得沿用上一题的选择')
  assert.match(await evalJson(browser, `document.body.textContent`),
    /第 1 题[\s\S]*?(正确|错误)/, '导航必须立即标记上一题判定')

  // 关闭后回到手动提交
  await browser('uncheck', autoNextBox)
  await browser('click', option(2))
  await browser('wait', '250')
  assert.equal(await headingPosition(browser), '2', '关闭自动下一题后点击选项不得自动跳转')
  await browser('find', 'role', 'button', 'click', '--name', '提交答案', '--exact')
  await browser('wait', '--text', '回答错误')
  assert.equal(await headingPosition(browser), '2', '关闭时提交后仍需手动点下一题')
  await noScriptErrors(browser)
})

test('自动下一题：提交失败停留本题并保留选项，可重试', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser)
  await openQuiz(browser, origin, sessionId)
  await browser('check', autoNextBox)

  assert.equal((await API(browser, '/api/__test/fail-next-answer', { method: 'POST', body: {} })).status, 200)
  await browser('click', optionRadio)
  await browser('wait', '--text', '提交失败')

  assert.equal(await headingPosition(browser), '1', '失败不得跳转')
  assert.match(await checkedOptionText(browser) || '', /Choice A/, '失败后必须保留已选项')
  assert.equal(await evalJson(browser,
    `Array.from(document.querySelectorAll('button')).find(b => /提交/.test(b.textContent)).disabled`),
  false, '失败后提交按钮必须可重试')

  await browser('find', 'role', 'button', 'click', '--name', '提交并下一题', '--exact')
  await waitForPosition(browser, 2)
  await noScriptErrors(browser)
})

test('自动下一题：多选需手动提交；最后一题不跳转', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  const multiSession = await startSession(browser, { bankId: 2 })
  await openQuiz(browser, origin, multiSession)
  await browser('check', autoNextBox)
  await browser('click', option(1))
  await browser('wait', '250')
  assert.equal(await evalJson(browser,
    `document.body.textContent.includes('回答正确') || document.body.textContent.includes('回答错误')`),
  false, '多选勾选不得自动提交')
  await browser('click', option(3))
  await browser('find', 'role', 'button', 'click', '--name', '提交答案', '--exact')
  await browser('wait', '--text', '回答正确')
  assert.equal(await evalJson(browser,
    `Array.from(document.querySelectorAll('button')).some(b => b.textContent.trim() === '完成答题')`),
  true, '最后一题提交后必须展示完成答题')

  const sessionId = await startSession(browser, { bankId: 1 })
  await openQuiz(browser, origin, sessionId)
  await browser('check', autoNextBox)
  for (let position = 1; position < 6; position += 1) {
    await browser('click', optionRadio)
    await waitForPosition(browser, position + 1)
  }
  await browser('click', optionRadio)
  await browser('wait', '--text', '回答正确')
  await browser('wait', '400')
  assert.equal(await headingPosition(browser), '6', '最后一题提交后不得跳转')
  await noScriptErrors(browser)
})

test('自动下一题：已答题点击不自动提交，改答成功后切题；不自动展开解析', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser)
  await openQuiz(browser, origin, sessionId)
  await browser('check', autoNextBox)

  // 第 1 题提交后立即到第 2 题；第 2 题提交后停留（最后一题之前的自动跳转已覆盖）
  await browser('click', optionRadio)
  await waitForPosition(browser, 2)

  // 返回第 1 题：已答状态，不自动展开解析
  await browser('eval', `(() => {
    const button = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('第 1 题'));
    button.click(); return true;
  })()`)
  await browser('wait', '--text', '回答正确')
  assert.equal(await evalJson(browser,
    `Boolean(document.querySelector('[data-model-id], [data-reader]'))`),
  false, '自动下一题开启时不得自动展开解析')

  const before = await API(browser, `/api/quiz/session/${sessionId}`)
  await browser('click', option(2))
  await browser('wait', '250')
  assert.equal(await headingPosition(browser), '1', '已答题点击选项不得自动跳转')
  const after = await API(browser, `/api/quiz/session/${sessionId}`)
  assert.equal(after.data.answers[0].user_answer, before.data.answers[0].user_answer,
    '已答题点击选项不得发提交')

  await browser('find', 'role', 'button', 'click', '--name', '提交并下一题', '--exact')
  await waitForPosition(browser, 2)
  await noScriptErrors(browser)
})

test('自动下一题：键盘方向键只改变选择，不自动提交', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser)
  await openQuiz(browser, origin, sessionId)
  await browser('check', autoNextBox)

  // 键盘方向键是浏览/比较选项的标准交互，不应被当作“点击”而直接判分。
  await browser('focus', `${option(1)} > input`)
  await browser('press', 'ArrowDown')
  await browser('wait', '250')
  assert.equal(await headingPosition(browser), '1', '键盘方向键不得自动跳转')
  assert.match(await checkedOptionText(browser) || '', /Choice B/, '键盘选择仍需同步到选答模型')
  await browser('find', 'role', 'button', 'click', '--name', '提交并下一题', '--exact')
  await waitForPosition(browser, 2)
  await noScriptErrors(browser)
})

test('自动下一题：模拟考试点击选项不自动提交，手动提交后自动跳转', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser, { mode: 'exam' })
  await openQuiz(browser, origin, sessionId)
  await browser('check', autoNextBox)

  await browser('click', optionRadio)
  await browser('wait', '300')
  assert.equal(await headingPosition(browser), '1', '模拟考试点击选项不得自动提交或跳转')
  assert.match(await checkedOptionText(browser) || '', /Choice A/, '模拟考试仍需保留点击选择')

  await browser('find', 'role', 'button', 'click', '--name', '提交答案', '--exact')
  await waitForPosition(browser, 2)
  await noScriptErrors(browser)
})

test('自动下一题关闭时解析仍自动展开（阳性对照）', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser)
  await openQuiz(browser, origin, sessionId)

  assert.equal(await autoNextChecked(browser), false)
  await browser('click', optionRadio)
  await browser('find', 'role', 'button', 'click', '--name', '提交答案', '--exact')
  await browser('wait', '--text', '回答正确')
  await browser('wait', '--fn',
    `Boolean(document.querySelector('[data-model-id], [data-reader], [aria-label="解析模型"]'))`)
  await noScriptErrors(browser)
})

test('自动下一题：提交期间不出灰圈、不漂移，跳转前可见对错反馈', { timeout: 180000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_auto_next_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)
  const sessionId = await startSession(browser)
  await openQuiz(browser, origin, sessionId)
  await browser('check', autoNextBox)

  // 注入 1.2s 的作答延迟，让“提交在途”状态可稳定观察。
  await browser('eval', `(() => {
    const OrigOpen = XMLHttpRequest.prototype.open;
    const OrigSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__testUrl = url;
      return OrigOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      if (String(this.__testUrl || '').includes('/api/quiz/answer')) {
        return setTimeout(() => OrigSend.apply(this, args), 1200);
      }
      return OrigSend.apply(this, args);
    };
    return true;
  })()`)

  await browser('click', optionRadio)
  await browser('wait', '300')

  const inFlight = await evalJson(browser, `(() => {
    const input = document.querySelector('.space-y-3 > label > input');
    return {
      position: document.querySelector('[data-testid=quiz-position]')?.textContent.trim(),
      disabled: input.disabled,
      ariaDisabled: input.getAttribute('aria-disabled'),
      checked: input.checked,
    };
  })()`)
  assert.equal(inFlight.disabled, false, '不得使用原生 disabled（会把选中圆圈渲染成灰色）')
  assert.equal(inFlight.ariaDisabled, 'true', '提交期间必须向辅助技术标明不可操作')
  assert.equal(inFlight.checked, true, '提交在途时已选项必须保持可见的选中态')
  assert.equal(inFlight.position, '1 / 6', '提交在途时不得提前跳题')

  // 提交在途期间点击其他选项不得改变选择。
  await browser('eval', `document.querySelector('.space-y-3 > label:nth-child(2)').click()`)
  await browser('wait', '150')
  assert.equal(await evalJson(browser,
    `document.querySelector('.space-y-3 > label:nth-child(2) > input').checked`), false,
  '提交在途期间不得改变原生选中态')

  // 响应返回后必须先在本题出现对错反馈，再切到下一题。
  await browser('wait', '--text', '回答正确')
  assert.equal(await headingPosition(browser), '1', '反馈必须在跳转前可见')
  await browser('wait', '--fn', `document.querySelector('[data-testid=quiz-position]')?.textContent.trim().startsWith('2 /')`)
  await noScriptErrors(browser)
})
