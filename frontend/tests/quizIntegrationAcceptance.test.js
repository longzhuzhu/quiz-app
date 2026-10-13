import test from 'node:test'
import assert from 'node:assert/strict'
import { startStudyBrowser } from './helpers/studyBrowser.js'
import { startStudyBackend } from './helpers/studyBackend.js'

/**
 * 父任务集成验收：`10-13-quiz-review-retry/implement.md` §5 表格中
 * 前三项 E2E（quizReviewE2E / quizResultE2E）未覆盖的场景。
 *
 * 覆盖：多选题完整渲染、越权与跨项目拒绝、跨题库重做保留全部原题、
 * 新场刷新不继承原场、完成后删除原题仍可复盘。
 */

const api = (browser, path, options = {}) => browser('eval', `(async () => {
  const response = await fetch(${JSON.stringify(path)}, {
    headers: Object.assign(
      { 'X-Exam-Slug': ${JSON.stringify(options.examSlug || 'current')}, 'Content-Type': 'application/json' },
      localStorage.getItem('token') === null ? {} : { Authorization: 'Bearer ' + localStorage.getItem('token') },
    ),
    ${options.method ? `method: ${JSON.stringify(options.method)},` : ''}
    ${options.body ? `body: ${JSON.stringify(JSON.stringify(options.body))},` : ''}
  });
  return { status: response.status, data: await response.json() };
})()`)

const reviewUrl = (origin, sessionId, query = '') => `${origin}/exams/current/quiz/${sessionId}/review${query}`

const waitForReview = browser => browser('wait', '--fn',
  `Boolean(document.querySelector('[data-testid=review-question]'))
   && Boolean(document.querySelector('[data-testid=summary-correct]'))`)

async function signIn(browser, origin, { slug = 'current' } = {}) {
  await browser('open', `${origin}/exams/${slug}/dashboard`)
  await browser('find', 'placeholder', '请输入用户名', 'fill', 'study-user')
  await browser('find', 'placeholder', '请输入密码', 'fill', 'StudyTest123!')
  await browser('find', 'role', 'button', 'click', '--name', '登录', '--exact')
  await browser('wait', '--url', '**/dashboard')
}

/** 直接建会话并作答，返回 sessionId。answerFor 决定每题提交什么。 */
async function buildSession(browser, { mode = 'sequential', answers, bankId = 1, questionCount } = {}) {
  const started = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST',
    body: { bank_id: bankId, mode, ...(questionCount ? { question_count: questionCount } : {}) },
  }))
  assert.equal(started.status, 200, JSON.stringify(started))
  const sessionId = started.data.session.id
  for (const [position, question] of started.data.questions.entries()) {
    const answer = answers(position, question)
    if (answer === null || answer === undefined) continue
    const posted = JSON.parse(await api(browser, '/api/quiz/answer', {
      method: 'POST', body: { session_id: sessionId, question_id: question.id, user_answer: answer },
    }))
    assert.equal(posted.status, 200, JSON.stringify(posted))
  }
  assert.equal(JSON.parse(await api(browser, '/api/quiz/finish', { method: 'POST', body: { session_id: sessionId } })).status, 200)
  return sessionId
}

test('多选题在复盘中完整渲染多个正确项，不截断不误判', { timeout: 240000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  // 多选题在第二题库（正确答案 A,C）。只答 A —— 漏选，判错
  const sessionId = await buildSession(browser, {
    mode: 'sequential', bankId: 2,
    answers: () => 'A',
  })
  const detail = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`)).data
  const multi = detail.questions.find(q => q.question_type === 'multiple')
  assert.ok(multi, '夹具必须包含一道多选题')
  assert.equal(multi.correct_answer, 'A,C')
  // 只答 A 时判错，且当场正确答案保留完整两个 key
  assert.equal(multi.is_correct, false)

  await browser('open', reviewUrl(origin, sessionId))
  await waitForReview(browser)
  const rendered = JSON.parse(await browser('eval', `(() => {
    const nav = Array.from(document.querySelectorAll('[data-testid^=review-nav-]:not([data-testid^=review-nav-mobile-])'));
    const target = nav.find(b => b.getAttribute('data-testid') === 'review-nav-' + ${multi.index});
    if (target) target.click();
    return null;
  })()`))
  assert.equal(rendered, null)
  await browser('wait', '--fn', `document.querySelector('[data-testid=review-question]').getAttribute('data-index') === '${multi.index}'`)

  const multiView = JSON.parse(await browser('eval', `(() => {
    const card = document.querySelector('[data-testid=review-question]');
    const options = Array.from(document.querySelectorAll('[data-testid=review-option]'));
    const badges = Array.from(card.querySelectorAll('[data-testid^=badge-]')).map(b => b.textContent.trim());
    const correctText = card.querySelector('[data-testid=badge-correct-answer]');
    return {
      optionCount: options.length,
      optionTexts: options.map(o => o.textContent.trim()),
      badges,
      correctAnswerText: correctText ? correctText.textContent.trim() : null,
      bodyText: card.textContent,
    };
  })()`))
  assert.equal(multiView.optionCount, 4, '多选题四个选项必须全部渲染')
  assert.ok(multiView.optionTexts.every(text => text.length > 0), '选项文本不得为空')
  assert.ok(multiView.bodyText.includes('A,C') || multiView.bodyText.includes('A、C'),
    `多选题当场正确答案必须标注完整两个 key，实际: ${multiView.bodyText}`)
  // 只读：不得出现在选项上的表单控件
  const interactive = JSON.parse(await browser('eval',
    `document.querySelectorAll('[data-testid=review-option] input, [data-testid=review-option] button, [data-testid=review-option] label').length`))
  assert.equal(interactive, 0, '多选题选项同样不得带任何表单控件')
})

test('跨项目与越权访问被拒绝，不泄露题目、快照或新会话', { timeout: 240000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  const sessionId = await buildSession(browser, { mode: 'sequential', answers: () => 'A' })

  // 1) 跨考试项目：同一会话用 other 项目的 slug 访问必须 404
  const crossExamDetail = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`, { examSlug: 'other' }))
  assert.equal(crossExamDetail.status, 404, JSON.stringify(crossExamDetail))
  assert.equal(crossExamDetail.data.questions, undefined, '跨项目响应不得包含题目')

  // 2) 跨项目重做必须同样拒绝，且不得创建新会话
  const sessionsBefore = JSON.parse(await api(browser, '/api/quiz/history?per_page=100')).data.total
  const crossExamRetry = JSON.parse(await api(browser, '/api/quiz/retry', {
    method: 'POST', body: { session_id: sessionId }, examSlug: 'other',
  }))
  assert.equal(crossExamRetry.status, 404, JSON.stringify(crossExamRetry))
  assert.equal(JSON.parse(await api(browser, '/api/quiz/history?per_page=100')).data.total, sessionsBefore,
    '被拒绝的重做不得创建会话')

  // 3) 未认证访问必须拒绝且不返回题目
  const anonymous = JSON.parse(await browser('eval', `(async () => {
    const token = localStorage.getItem('token');
    localStorage.removeItem('token');
    const response = await fetch('/api/quiz/session/${sessionId}', { headers: { 'X-Exam-Slug': 'current' } });
    const body = await response.text();
    localStorage.setItem('token', token);
    return { status: response.status, body };
  })()`))
  assert.equal(anonymous.status, 401, JSON.stringify(anonymous))
  assert.ok(!anonymous.body.includes('correct_answer'), '未认证响应不得包含正确答案')
})

test('跨题库错题重做保留全部原题，已掌握也不剔除', { timeout: 240000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  // 主库第一题答错、第二题库的题答错 —— 形成跨题库错题集
  const started = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 1, mode: 'sequential', question_count: 11 },
  }))
  assert.equal(started.status, 200, JSON.stringify(started))
  const firstSession = started.data.session.id
  const wrongTargets = []
  for (const [position, question] of started.data.questions.entries()) {
    const answer = position === 0 ? 'D' : 'A' // 第 1 题答错，其余答对
    const posted = JSON.parse(await api(browser, '/api/quiz/answer', {
      method: 'POST', body: { session_id: firstSession, question_id: question.id, user_answer: answer },
    }))
    assert.equal(posted.status, 200, JSON.stringify(posted))
    if (answer === 'D') wrongTargets.push(question.id)
  }
  assert.equal(JSON.parse(await api(browser, '/api/quiz/finish', { method: 'POST', body: { session_id: firstSession } })).status, 200)

  // 第二题库的题也答错，凑成跨题库
  const second = JSON.parse(await api(browser, '/api/quiz/start', {
    method: 'POST', body: { bank_id: 2, mode: 'sequential' },
  }))
  assert.equal(second.status, 200, JSON.stringify(second))
  const secondSession = second.data.session.id
  const crossBankQuestion = second.data.questions[0]
  const crossAnswer = crossBankQuestion.correct_answer === 'D' ? 'A' : 'D'
  assert.equal(JSON.parse(await api(browser, '/api/quiz/answer', {
    method: 'POST', body: { session_id: secondSession, question_id: crossBankQuestion.id, user_answer: crossAnswer },
  })).status, 200)
  assert.equal(JSON.parse(await api(browser, '/api/quiz/finish', { method: 'POST', body: { session_id: secondSession } })).status, 200)
  wrongTargets.push(crossBankQuestion.id)

  // 错题练习会话：必须走 /wrong/practice（/quiz/start 按题库出题，做不出跨题库成员）
  const practice = JSON.parse(await api(browser, '/api/wrong/practice', { method: 'POST', body: {} }))
  assert.equal(practice.status, 200, JSON.stringify(practice))
  const practiceSession = practice.data.session.id
  const practiceIds = practice.data.questions.map(q => q.id)
  assert.ok(practiceIds.length >= 2, `错题练习应至少含两题，实际 ${practiceIds.length}`)
  for (const question of practice.data.questions) {
    assert.equal(JSON.parse(await api(browser, '/api/quiz/answer', {
      method: 'POST', body: { session_id: practiceSession, question_id: question.id, user_answer: 'D' },
    })).status, 200)
  }
  assert.equal(JSON.parse(await api(browser, '/api/quiz/finish', { method: 'POST', body: { session_id: practiceSession } })).status, 200)

  // 把其中一题标记掌握，重做时不得因此被剔除
  const wrongEntry = JSON.parse(await api(browser, '/api/wrong')).data.find(item => item.question_id === practiceIds[0])
  assert.ok(wrongEntry, '错题本应含该题')
  assert.equal(JSON.parse(await api(browser, `/api/wrong/${wrongEntry.id}/resolve`, { method: 'PUT' })).status, 200,
    '标记掌握应成功')

  const retried = JSON.parse(await api(browser, '/api/quiz/retry', { method: 'POST', body: { session_id: practiceSession } }))
  assert.equal(retried.status, 200, JSON.stringify(retried))
  assert.deepEqual(retried.data.questions.map(q => q.id), practiceIds,
    '跨题库重做必须保留全部原题且顺序一致，已掌握的原题不得剔除')
  assert.equal(retried.data.session.mode, 'wrong_practice')
  assert.equal(retried.data.session.total_questions, practiceIds.length)
})

test('新场刷新不继承原场答案与进度', { timeout: 240000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  const originalId = await buildSession(browser, { mode: 'sequential', answers: () => 'A' })
  const retried = JSON.parse(await api(browser, '/api/quiz/retry', { method: 'POST', body: { session_id: originalId } }))
  assert.equal(retried.status, 200, JSON.stringify(retried))
  const newId = retried.data.session.id
  assert.notEqual(newId, originalId, '重做必须创建新会话')

  // 新会话初始状态：未作答、未完成、无冻结判定
  const detail = JSON.parse(await api(browser, `/api/quiz/session/${newId}`)).data
  assert.equal(detail.session.is_completed, false)
  assert.equal(detail.session.answered_count, 0)
  assert.equal(detail.session.correct_count, 0)

  // 打开答题页并刷新：进度必须是起点，不继承原场
  await browser('open', `${origin}/exams/current/quiz/${newId}`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=quiz-question]')) || document.body.textContent.includes('第')`)
  await browser('eval', `(() => { location.reload(); return true })()`)
  await browser('wait', '--fn', `Boolean(document.querySelector('[data-testid=quiz-question]')) || document.body.textContent.includes('第')`)
  const afterReload = JSON.parse(await api(browser, `/api/quiz/session/${newId}`)).data
  assert.equal(afterReload.session.answered_count, 0, '刷新后新场进度仍为起点')
  assert.equal(afterReload.session.resume_index, 0, '刷新不得继承原场恢复位置')
})

test('删除原题后复盘仍可读，重做整场失败且无部分会话', { timeout: 240000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_quiz_review_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await signIn(browser, origin)

  const sessionId = await buildSession(browser, { mode: 'sequential', answers: () => 'A' })
  const before = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`)).data
  const victim = before.questions[1]
  assert.ok(victim.content, '删除前先确认题干非空')

  // 删除该题
  const deleted = JSON.parse(await api(browser, `/api/questions/${victim.id}`, { method: 'DELETE' }))
  assert.equal(deleted.status, 200, JSON.stringify(deleted))

  // 复盘：有快照，题干仍可读，题号占位不变
  const after = JSON.parse(await api(browser, `/api/quiz/session/${sessionId}`)).data
  assert.equal(after.questions.length, before.questions.length, '删除后题目数量与占位不变')
  const stillThere = after.questions.find(q => q.index === victim.index)
  assert.ok(stillThere, '被删题目仍按原场题号占位')
  assert.equal(stillThere.content, victim.content, '有快照时仍显示当时题干')
  assert.equal(stillThere.correct_answer, victim.correct_answer, '当场正确答案不受影响')
  assert.equal(stillThere.is_correct, victim.is_correct, '判定不受删除影响')

  const rendered = JSON.parse(await browser('eval', `(async () => {
    const response = await fetch('/api/quiz/session/${sessionId}', { headers: { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current' } });
    return (await response.json()).questions.find(q => q.index === ${victim.index});
  })()`))
  assert.equal(rendered.content, victim.content)

  // 重做：整场失败，列出不可用题号，且不创建新会话
  const sessionsBefore = JSON.parse(await api(browser, '/api/quiz/history?per_page=100')).data.total
  const retried = JSON.parse(await api(browser, '/api/quiz/retry', { method: 'POST', body: { session_id: sessionId } }))
  assert.equal(retried.status, 400, JSON.stringify(retried))
  assert.ok(String(retried.data.detail).includes(String(victim.id)), `失败提示应列出不可用题目 ID，实际: ${retried.data.detail}`)
  assert.equal(JSON.parse(await api(browser, '/api/quiz/history?per_page=100')).data.total, sessionsBefore,
    '整场失败不得留下部分会话')
})
