import test from 'node:test'
import assert from 'node:assert/strict'
import { startStudyBrowser } from './helpers/studyBrowser.js'
import { startStudyBackend } from './helpers/studyBackend.js'

test('多模型解析：真实登录、预热、独立答案、移动Tab、更正与更新；真实worker/PostgreSQL', { timeout: 150000 }, async t => {
  const apiTarget = await startStudyBackend(t, { script: 'run_explanation_backend.py' })
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await browser('open', origin + '/exams/current/dashboard')
  await browser('find', 'placeholder', '请输入用户名', 'fill', 'study-user')
  await browser('find', 'placeholder', '请输入密码', 'fill', 'StudyTest123!')
  await browser('find', 'role', 'button', 'click', '--name', '登录', '--exact')
  await browser('wait', '--url', '**/dashboard')
  const session = JSON.parse(await browser('eval', '(async()=>{const r=await fetch("/api/quiz/start",{method:"POST",headers:{Authorization:"Bearer "+localStorage.getItem("token"),"X-Exam-Slug":"current","Content-Type":"application/json"},body:JSON.stringify({bank_id:1,mode:"sequential"})});return(await r.json()).session})()'))
  await browser('set', 'viewport', '1280', '900')
  await browser('open', origin + '/exams/current/quiz/' + session.id)
  await browser('wait', '--text', 'Which control is MOST effective? 1')
  assert.equal(JSON.parse(await browser('eval', `Boolean(document.querySelector('[aria-label="AI 推荐答案"]'))`)), false)
  await browser('find', 'role', 'button', 'click', '--name', 'AI 解析', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal(JSON.parse(await browser('eval', `Boolean(document.querySelector('[aria-label="AI 推荐答案"]'))`)), true)
  await browser('wait', '--fn', 'document.querySelectorAll("[data-model-id]").length === 5')
  const desktop = JSON.parse(await browser('eval', `({
    count: document.querySelectorAll('[data-model-id]').length,
    columns: new Set(Array.from(document.querySelectorAll('[data-model-id]')).map(e=>Math.round(e.getBoundingClientRect().left))).size,
    overflow: document.documentElement.scrollWidth>innerWidth,
    failed: document.querySelector('[data-model-id="model-e"]').textContent.includes('生成失败'),
    conflict: document.querySelector('[data-model-id="model-b"]').textContent.includes('与题库答案不同')
  })`))
  assert.deepEqual(desktop, { count: 5, columns: 2, overflow: false, failed: true, conflict: true })
  const state = async () => JSON.parse(await browser('eval', '(async()=>await(await fetch("/api/__test/ai-state")).json())()'))
  assert.ok((await state()).peak <= 3)
  await browser('wait', '--fn', '(async()=>{const s=await(await fetch("/api/__test/ai-state")).json();return s.calls.length===10 && s.active===0})()')
  const initialCalls = (await state()).calls.length
  assert.equal(initialCalls, 10)
  await browser('set', 'viewport', '375', '812')
  await browser('wait', '--fn', 'document.querySelectorAll("[role=tab]").length === 5')
  await browser('find', 'role', 'tab', 'click', '--name', 'model-b', '--exact')
  await browser('wait', '--fn', 'document.querySelector("[data-model-id]")?.dataset.modelId === "model-b"')
  assert.equal(JSON.parse(await browser('eval', 'document.querySelectorAll("[data-model-id]").length')), 1)
  assert.equal(JSON.parse(await browser('eval', 'document.documentElement.scrollWidth > innerWidth')), false)
  await browser('press', 'ArrowRight')
  await browser('wait', '--fn', 'document.querySelector("[data-model-id]")?.dataset.modelId === "model-c"')
  assert.equal((await state()).calls.length, initialCalls)
  await browser('scroll', 'up', '10000')
  await browser('click', 'label:has(input[type=radio]):first-of-type')
  await browser('find', 'role', 'button', 'click', '--name', '提交答案', '--exact')
  await browser('wait', '--text', '回答错误')
  await browser('find', 'role', 'button', 'click', '--name', '更正答案', '--exact')
  await browser('scroll', 'up', '10000')
  await browser('click', 'label:has(input[type=radio]):first-of-type')
  await browser('scroll', 'down', '350')
  await browser('find', 'role', 'button', 'click', '--name', '确认更正', '--exact')
  await browser('click', '[role=dialog] .justify-end > button:last-child')
  await browser('wait', '--text', '答案已更正')
  await browser('wait', '--fn', '!document.querySelector("[role=dialog]")')
  await browser('find', 'role', 'tab', 'click', '--name', 'model-b', '--exact')
  await browser('wait', '--fn', '!document.querySelector("[data-model-id=model-b]").textContent.includes("与题库答案不同")')
  assert.equal((await state()).calls.length, initialCalls)
  assert.equal(JSON.parse(await browser('eval', 'Boolean(document.querySelector("details"))')), false)
  await browser('find', 'role', 'button', 'click', '--name', '更新 model-b', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal((await state()).calls.length, initialCalls + 1)
  await browser('find', 'role', 'button', 'click', '--name', '更新解析', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal((await state()).calls.length, initialCalls + 6)
  assert.equal(JSON.parse(await browser('eval', 'document.querySelector("[role=tab][aria-selected=true]").textContent.trim()')), 'model-b')
  await browser('open', origin + '/admin/settings')
  await browser('wait', '--text', 'AI API 配置')
  assert.equal(JSON.parse(await browser('eval', 'document.querySelectorAll("[data-model-row]").length')), 5)
  await browser('click', '[data-model-row="4"] summary')
  await browser('fill', '#explain-effort-4', 'high')
  await browser('find', 'role', 'button', 'click', '--name', '保存设置', '--exact')
  await browser('wait', '--text', '设置已保存')
  assert.equal((await state()).calls.length, initialCalls + 6)
  await browser('open', origin + '/exams/current/quiz/' + session.id)
  await browser('wait', '--text', 'Which control is MOST effective? 2')
  await browser('find', 'role', 'button', 'click', '--name', '上一题', '--exact')
  await browser('wait', '--fn', 'document.querySelectorAll("[role=tab]").length === 5')
  await browser('find', 'role', 'tab', 'click', '--name', 'model-e', '--exact')
  await browser('find', 'role', 'button', 'click', '--name', '重试 model-e', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal((await state()).calls.length, initialCalls + 7)
  assert.equal((await state()).calls.at(-1).reasoning_effort, 'high')
  assert.equal(JSON.parse(await browser('eval', 'document.querySelector("[data-model-id=model-e]").textContent.includes("生成失败")')), false)
  await browser('open', origin + '/exams/current/wrong')
  await browser('wait', '--text', 'Which control is MOST effective? 1')
  assert.equal(JSON.parse(await browser('eval', 'document.querySelectorAll("[data-model-id]").length')), 0)
  await browser('find', 'role', 'button', 'click', '--name', '查看 model-b 解析', '--exact')
  await browser('wait', '--fn', 'document.querySelector("[data-model-id]")?.dataset.modelId === "model-b"')
  assert.equal((await state()).calls.length, initialCalls + 7)
  await browser('eval', `(async () => {
    const headers = { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current', 'Content-Type': 'application/json' };
    await fetch('/api/settings/ai', { method: 'PUT', headers, body: JSON.stringify({ ai_explain_models: [{ model_id: '__proto__' }] }) });
    await fetch('/api/ai/explain', { method: 'POST', headers, body: JSON.stringify({ question_id: 1, model_id: '__proto__' }) });
  })()`)
  await browser('wait', '--fn', `(async () => {
    const headers = { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current' };
    const state = await (await fetch('/api/ai/explanations?question_id=1', { headers })).json();
    return state.models[0].result !== null;
  })()`)
  await browser('find', 'text', 'Which control is MOST effective? 1', 'click')
  await browser('find', 'text', 'Which control is MOST effective? 1', 'click')
  await browser('wait', '--fn', 'document.querySelector("[data-model-id]")?.dataset.modelId === "__proto__"')
  await browser('wait', '--text', '该措施减少数据暴露')
  assert.equal((await state()).calls.length, initialCalls + 8)
  const edited = JSON.parse(await browser('eval', `(async () => {
    const response = await fetch('/api/questions/1', {
      method: 'PUT',
      headers: { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current', 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: 'Updated stem MOST effective?' }),
    });
    return response.status;
  })()`))
  assert.equal(edited, 200)
  await browser('find', 'role', 'button', 'click', '--name', '更新解析', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal(JSON.parse(await browser('eval', 'document.body.textContent.includes("题目已变化，请刷新页面后重新解析")')), true)
  assert.equal((await state()).calls.length, initialCalls + 8)
  const errorConsole = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errorConsole), errorConsole)
})
