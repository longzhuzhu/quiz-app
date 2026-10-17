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
  await browser('wait', '--fn', 'Boolean(document.querySelector("[data-reader=model-b]"))')
  const modelLabels = async () => JSON.parse(await browser('eval', `Array.from(document.querySelector('[aria-label="解析模型"]')?.querySelectorAll('button') || []).map(button => button.textContent.trim())`))
  const desktopLabels = await modelLabels()
  assert.equal(desktopLabels.length, 5, '桌面也应显示模型选择条')
  await browser('click', '[aria-label="解析模型"] button:nth-child(2)')
  const selectionStyle = async () => JSON.parse(await browser('eval', `(() => {
    const selected = document.querySelector('[aria-label="解析模型"] [aria-selected=true], [aria-label="解析模型"] [aria-pressed=true]');
    const style = getComputedStyle(selected);
    return { borderWidth: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth],
      radius: style.borderTopLeftRadius, shadow: style.boxShadow, background: style.backgroundColor, color: style.color, fontWeight: style.fontWeight };
  })()`))
  const desktopSelectionStyle = await selectionStyle()
  assert.deepEqual(desktopSelectionStyle.borderWidth, ['1px', '1px', '1px', '1px'], '选中模型应显示完整边框而不是仅下划线')
  assert.notEqual(desktopSelectionStyle.radius, '0px', '选中模型应是圆角框')
  assert.equal(desktopSelectionStyle.shadow, 'none', '选中模型不应出现深色粗外框')
  assert.equal(JSON.parse(await browser('eval', 'document.querySelectorAll("[data-model-id]").length')), 5, '桌面选择模型后仍保留并排比较')
  const refreshControl = JSON.parse(await browser('eval', `(() => {
    const card = document.querySelector('[data-model-id="model-b"]');
    const button = card.querySelector('button');
    const heading = card.querySelector('h3');
    const reader = card.querySelector('[data-reader]');
    const icon = button.querySelector('svg');
    const buttonRect = button.getBoundingClientRect(), headingRect = heading.getBoundingClientRect(), iconRect = icon.getBoundingClientRect();
    return { inHeading: button.parentElement !== card && button.parentElement.contains(heading), aboveBody: buttonRect.top < reader.getBoundingClientRect().top,
      centeredWithHeading: Math.abs((iconRect.top + iconRect.bottom) / 2 - (headingRect.top + headingRect.bottom) / 2) <= 2,
      icon: Boolean(icon), text: button.textContent.trim(), busy: button.getAttribute('aria-busy'),
      animation: getComputedStyle(icon).animationName };
  })()`))
  assert.deepEqual(refreshControl, { inHeading: true, aboveBody: true, centeredWithHeading: true, icon: true, text: '', busy: 'false', animation: 'none' }, '更新图标应与模型 ID 垂直居中，空闲时保持静态')
  assert.equal(JSON.parse(await browser('eval', 'Array.from(document.querySelectorAll("button")).some(b=>b.textContent.trim()==="更新全部解析")')), true)
  const cardColors = async () => JSON.parse(await browser('eval', `Array.from(document.querySelectorAll('[data-model-id]')).map(card => ({
    model: card.dataset.modelId, background: getComputedStyle(card).backgroundColor, border: getComputedStyle(card).borderTopColor,
  }))`))
  const lightColors = await cardColors()
  assert.equal(new Set(lightColors.map(card => card.background)).size, 5, '每个模型的卡片底色应不同')
  assert.equal(new Set(lightColors.map(card => card.border)).size, 5, '每个模型的卡片边框应不同')
  assert.equal(JSON.parse(await browser('eval', `getComputedStyle(document.querySelector('[data-reader="model-b"]')).overflowY`)), 'auto', '桌面保留正文内部滚动')
  await browser('eval', 'document.documentElement.classList.add("dark"); true')
  const darkColors = await cardColors()
  assert.equal(new Set(darkColors.map(card => card.background)).size, 5, '深色模式也应区分各模型')
  assert.equal(new Set(darkColors.map(card => card.border)).size, 5)
  assert.ok(darkColors.every((card, i) => card.background !== lightColors[i].background), '卡片应适配深色模式')
  await browser('eval', 'document.documentElement.classList.remove("dark"); true')
  const state = async () => JSON.parse(await browser('eval', '(async()=>await(await fetch("/api/__test/ai-state")).json())()'))
  // 移动端底部有固定主导航和题号导航，卡片右侧图标按钮必须先滚到视口上部，避免点击被遮挡。
  const scrollToCardAction = async name => {
    await browser('eval', `(() => {
      const label = ${JSON.stringify(name)};
      const target = Array.from(document.querySelectorAll('button')).find(button =>
        button.getAttribute('aria-label') === label || button.textContent.trim() === label);
      target.scrollIntoView({ block: 'center' });
      const rect = target.getBoundingClientRect();
      if (rect.top < 80) window.scrollBy(0, rect.top - 80);
      return true;
    })()`)
  }
  assert.ok((await state()).peak <= 3)
  await browser('wait', '--fn', '(async()=>{const s=await(await fetch("/api/__test/ai-state")).json();return s.calls.length===10 && s.active===0})()')
  let initialCalls = (await state()).calls.length
  assert.equal(initialCalls, 10)
  // 只延迟真实 XHR 的发出；所有业务请求仍走真实 API、worker 和 PostgreSQL。
  const pendingRefresh = JSON.parse(await browser('eval', `(async () => {
    const proto = XMLHttpRequest.prototype;
    const open = proto.open, send = proto.send;
    const probe = window.aiRequestProbe = { active: 0, peak: 0, posts: 0 };
    proto.open = function(method, url, ...args) {
      this.aiProbePath = String(url); this.aiProbeMethod = method;
      return open.call(this, method, url, ...args);
    };
    proto.send = function(...args) {
      if (this.aiProbePath.includes('/ai/explanations')) {
        setTimeout(() => send.apply(this, args), 350);
      } else if (this.aiProbePath.includes('/ai/explain') && this.aiProbeMethod.toUpperCase() === 'POST') {
        probe.active++; probe.posts++; probe.peak = Math.max(probe.peak, probe.active);
        this.addEventListener('loadend', () => probe.active--, { once: true });
        setTimeout(() => send.apply(this, args), 500);
      } else send.apply(this, args);
    };
    probe.restore = () => { proto.open = open; proto.send = send; };
    document.querySelectorAll('[data-model-id] button').forEach(button => button.click());
    await new Promise(resolve => setTimeout(resolve, 0));
    const button = document.querySelector('[data-model-id] button');
    return { busy: button.getAttribute('aria-busy'), disabled: button.disabled,
      spinning: button.querySelector('svg') ? getComputedStyle(button.querySelector('svg')).animationName !== 'none' : false };
  })()`))
  assert.deepEqual(pendingRefresh, { busy: 'true', disabled: true, spinning: true }, '读取状态和发出更新请求期间立即旋转，并防止重复点击')
  await browser('wait', '--fn', 'window.aiRequestProbe.posts > 0 && window.aiRequestProbe.active === 0 && !Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  const requests = JSON.parse(await browser('eval', '({peak: window.aiRequestProbe.peak, posts: window.aiRequestProbe.posts})'))
  assert.ok(requests.peak <= 3, JSON.stringify(requests))
  assert.equal(requests.posts, 1, '状态读取期间重复单卡操作不能进入另一条生成队列')
  const stoppedRefresh = JSON.parse(await browser('eval', `Array.from(document.querySelectorAll('[data-model-id] button')).every(button =>
    button.getAttribute('aria-busy') === 'false' && getComputedStyle(button.querySelector('svg')).animationName === 'none')`))
  assert.equal(stoppedRefresh, true, '任务成功或失败后刷新图标均应恢复静态')
  await browser('eval', 'window.aiRequestProbe.restore()')
  initialCalls += 1
  assert.equal((await state()).calls.length, initialCalls)
  await browser('set', 'viewport', '375', '812')
  await browser('wait', '--fn', 'document.querySelectorAll("[role=tab]").length === 5')
  await browser('find', 'role', 'tab', 'click', '--name', 'model-b', '--exact')
  await browser('wait', '--fn', 'document.querySelector("[data-model-id]")?.dataset.modelId === "model-b"')
  assert.deepEqual(await modelLabels(), desktopLabels)
  assert.deepEqual(await selectionStyle(), desktopSelectionStyle, '移动与桌面选中模型的展示应一致')
  assert.equal(JSON.parse(await browser('eval', 'document.querySelectorAll("[data-model-id]").length')), 1)
  assert.equal(JSON.parse(await browser('eval', 'document.documentElement.scrollWidth > innerWidth')), false)
  const mobileReader = JSON.parse(await browser('eval', `(() => {
    const reader = document.querySelector('[data-reader="model-b"]');
    const style = getComputedStyle(reader);
    return { maxHeight: style.maxHeight, overflowY: style.overflowY, nestedScroll: reader.scrollHeight > reader.clientHeight + 1 };
  })()`))
  assert.deepEqual(mobileReader, { maxHeight: 'none', overflowY: 'visible', nestedScroll: false })
  const selectedColors = async () => JSON.parse(await browser('eval', `(() => {
    const card = document.querySelector('[data-model-id]');
    const tab = document.querySelector('[role=tab][aria-selected=true]');
    return { model: card.dataset.modelId, card: getComputedStyle(card).backgroundColor, tab: getComputedStyle(tab).backgroundColor };
  })()`))
  assert.deepEqual(await selectedColors(), { model: 'model-b', card: lightColors[1].background, tab: lightColors[1].background })
  await browser('eval', 'document.documentElement.classList.add("dark"); true')
  assert.deepEqual(await selectedColors(), { model: 'model-b', card: darkColors[1].background, tab: darkColors[1].background })
  await browser('eval', 'document.documentElement.classList.remove("dark"); true')
  await browser('eval', `document.querySelector('[data-reader="model-b"]').scrollIntoView({block:'start'}); true`)
  const pageScroll = JSON.parse(await browser('eval', 'window.scrollY'))
  await browser('scroll', 'down', '300')
  assert.ok(JSON.parse(await browser('eval', 'window.scrollY')) > pageScroll, '移动端长正文应随页面滚动')
  await browser('find', 'role', 'tab', 'click', '--name', 'model-b', '--exact')
  await browser('press', 'ArrowRight')
  await browser('wait', '--fn', 'document.querySelector("[data-model-id]")?.dataset.modelId === "model-c"')
  assert.deepEqual(await selectedColors(), { model: 'model-c', card: lightColors[2].background, tab: lightColors[2].background })
  assert.equal((await state()).calls.length, initialCalls)
  assert.deepEqual(JSON.parse(await browser('eval', `(() => {
    const reader = document.querySelector('[data-reader="model-c"]');
    return { overflowY: getComputedStyle(reader).overflowY, nestedScroll: reader.scrollHeight > reader.clientHeight + 1 };
  })()`)), { overflowY: 'visible', nestedScroll: false })
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
  await scrollToCardAction('更新 model-b')
  await browser('find', 'role', 'button', 'click', '--name', '更新 model-b', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal((await state()).calls.length, initialCalls + 1)
  await scrollToCardAction('更新全部解析')
  await browser('find', 'role', 'button', 'click', '--name', '更新全部解析', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal((await state()).calls.length, initialCalls + 6)
  assert.equal(JSON.parse(await browser('eval', 'document.querySelector("[role=tab][aria-selected=true]").textContent.trim()')), 'model-b')
  await browser('open', origin + '/admin/settings')
  await browser('wait', '--text', 'AI API 配置')
  // 模型行来自 onMounted 的设置请求，标题先于数据出现；高负载下立刻计数会读到 0 行。
  await browser('wait', '--fn', 'document.querySelectorAll("[data-model-row]").length === 5')
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
  await scrollToCardAction('重试 model-e')
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
  await scrollToCardAction('更新全部解析')
  await browser('find', 'role', 'button', 'click', '--name', '更新全部解析', '--exact')
  await browser('wait', '--fn', '!Array.from(document.querySelectorAll("button")).some(b=>/解析中|更新中/.test(b.textContent))')
  assert.equal(JSON.parse(await browser('eval', 'document.body.textContent.includes("题目已变化，请刷新页面后重新解析")')), true)
  assert.equal((await state()).calls.length, initialCalls + 8)
  const errorConsole = await browser('errors')
  assert.ok(!/TypeError|ReferenceError|SyntaxError/.test(errorConsole), errorConsole)
})
