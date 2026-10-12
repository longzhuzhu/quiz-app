import test from 'node:test'
import assert from 'node:assert/strict'
import { flipStudyCard, startStudyBrowser } from './helpers/studyBrowser.js'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const evidenceDir = fileURLToPath(new URL('../../docs/verification/issue64/', import.meta.url))

test('翻面直接展示英文释义且不再折叠，缺失不留空节点，长释义仍可内部滚动', { timeout: 120000 }, async t => {
  const definition = 'A long English definition that stays visible on the translation side.\n'.repeat(60)
  const { browser, origin } = await startStudyBrowser(t, { contentOverrides: [{ definition }, { definition: '  ' }] })
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const card = 'section[aria-label="单词卡"]'
  assert.doesNotMatch(await browser('get', 'text', card), /A long English definition|阿尔法/)
  await flipStudyCard(browser)
  assert.equal((await browser('is', 'visible', `${card} .study-card-body p[lang="en"]:last-child`)).trim(), 'true')
  assert.equal(Number(await browser('get', 'count', `${card} details, ${card} summary`)), 0)
  assert.doesNotMatch(await browser('get', 'text', card), /展开英文释义/)
  assert.match(await browser('get', 'text', card), /A long English definition/)
  await browser('scroll', 'down', '400', '--selector', '.study-card-body')
  await browser('wait', '--fn', `document.querySelector('${card} .study-card-body').scrollTop > 0`)
  assert.match(await browser('get', 'text', card), /点击卡片返回英文/)
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'beta')
  await flipStudyCard(browser)
  assert.equal(Number(await browser('get', 'count', `${card} .study-card-body p[lang="en"]`)), 1, '只有英文词条，没有空的英文释义段落')
  assert.match(await browser('get', 'text', card), /贝塔/)
})

test('刷新按钮替代本轮状态，更新三项内容并可刷新续学，位置进度不依赖标记', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t, { contentOverrides: [{ term_zh: null, definition_zh: null }] })
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  assert.equal((await browser('get', 'attr', 'progress', 'value')).trim(), '1')
  assert.match(await browser('get', 'text', '.study-header'), /第 1 \/ 3 个词/)
  assert.doesNotMatch(await browser('get', 'text', '.study-actions'), /本轮未标记|本轮已记住|本轮未记住/)
  await flipStudyCard(browser)
  await browser('find', 'role', 'button', 'click', '--name', '刷新', '--exact')
  await browser('wait', '--text', '已刷新翻译与中英文释义')
  const card = 'section[aria-label="单词卡"]'
  assert.match(await browser('get', 'text', card), /更新后的 alpha 翻译/)
  assert.match(await browser('get', 'text', card), /更新后的 alpha 中文释义/)
  assert.equal((await browser('is', 'visible', `${card} .study-card-body p[lang="en"]:last-child`)).trim(), 'true')
  assert.match(await browser('get', 'text', card), /Updated English definition for alpha/)
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'beta')
  assert.equal((await browser('get', 'attr', 'progress', 'value')).trim(), '2')
  await browser('press', 'ArrowLeft')
  await browser('wait', '--text', 'alpha')
  assert.equal((await browser('get', 'attr', 'progress', 'value')).trim(), '1')
  await browser('reload')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', 'alpha')
  await flipStudyCard(browser)
  assert.match(await browser('get', 'text', card), /更新后的 alpha 中文释义/)
  assert.deepEqual((await state()).refreshes, [{ vocabulary_id: 1 }])
  assert.deepEqual((await state()).writes, [])
})

test('AI 刷新期间防重复但可切词，响应不串卡；失败保留旧内容并可原位重试', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  await fetch(`${origin}/__study-test/delay-refresh`)
  const busy = JSON.parse(await browser('eval', `(async()=>{
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='刷新');button.click();button.click();await Promise.resolve();
    return {disabled:button.disabled,busy:button.getAttribute('aria-busy'),nextDisabled:document.querySelector('.study-actions > div:first-child button:last-child').disabled};
  })()`))
  assert.deepEqual(busy, { disabled: true, busy: 'true', nextDisabled: false })
  await browser('press', 'ArrowRight')
  await browser('wait', '--text', 'beta')
  await browser('wait', '--fn', `[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='刷新'&&!b.disabled)`)
  const card = 'section[aria-label="单词卡"]'
  assert.doesNotMatch(await browser('get', 'text', 'main'), /更新后的 alpha|已刷新/)
  assert.deepEqual((await state()).refreshes, [{ vocabulary_id: 1 }])
  await browser('press', 'ArrowLeft')
  await browser('wait', '--text', 'alpha')
  await flipStudyCard(browser)
  assert.match(await browser('get', 'text', card), /更新后的 alpha 中文释义/)
  await fetch(`${origin}/__study-test/fail-refresh`)
  await browser('find', 'role', 'button', 'click', '--name', '刷新', '--exact')
  await browser('wait', '--text', '词条刷新失败或结果未确认')
  assert.match(await browser('get', 'text', card), /更新后的 alpha 中文释义/)
  assert.doesNotMatch(await browser('get', 'text', 'main'), /AI generation failed/)
  await browser('find', 'role', 'button', 'click', '--name', '刷新', '--exact')
  await browser('wait', '--text', '已刷新翻译与中英文释义')
  assert.deepEqual((await state()).writes, [])
  assert.equal((await state()).refreshes.length, 3)
  assert.equal((await browser('get', 'attr', 'progress', 'value')).trim(), '1')
})

test('左右滑动按方向淡出旧词并进入新词，期间不可误判且布局与焦点稳定', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  for (const [dx, oldTerm, newTerm] of [[-80, 'alpha', 'beta'], [80, 'beta', 'alpha']]) {
    const measured = JSON.parse(await browser('eval', `(async()=>{
      const card=document.querySelector('section[aria-label="单词卡"]');card.focus();
      const initial=card.getBoundingClientRect().toJSON(), frames=[];
      const fire=(type,x)=>card.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:'touch',isPrimary:true,pointerId:1,button:0,clientX:initial.left+initial.width/2+x,clientY:initial.top+initial.height/2}));
      fire('pointerdown',0);fire('pointermove',${dx});fire('pointerup',${dx});
      for(let i=0;i<600;i++){
        await new Promise(requestAnimationFrame);
        const content=card.querySelector('.study-card-content')||card, style=getComputedStyle(content);
        frames.push({text:card.textContent,x:new DOMMatrixReadOnly(style.transform).m41,opacity:Number(style.opacity),busy:card.getAttribute('aria-busy'),judgesDisabled:[...document.querySelectorAll('.study-judge')].every(b=>b.disabled),bounds:card.getBoundingClientRect().toJSON()});
        if(card.textContent.includes('${newTerm}')&&card.getAttribute('aria-busy')==='false')break;
      }
      return {initial,frames,focus:document.activeElement===card,width:document.documentElement.scrollWidth,viewport:innerWidth};
    })()`))
    const direction = dx < 0 ? 1 : -1
    assert.ok(measured.frames.some(f => f.text.includes(oldTerm) && f.x * direction < -1 && f.opacity < 1), '旧词应沿滑动方向淡出')
    assert.ok(measured.frames.some(f => f.text.includes(newTerm) && f.x * direction > 1 && f.opacity < 1), '新词应从另一侧淡入')
    assert.ok(measured.frames.filter(f => f.busy === 'true').every(f => f.judgesDisabled), '显示旧词时不能误判已切换的新词')
    assert.ok(measured.frames.every(f => f.bounds.height === measured.initial.height && f.bounds.top === measured.initial.top))
    assert.equal(measured.focus, true)
    assert.equal(measured.width, measured.viewport)
    assert.equal(measured.frames.at(-1).judgesDisabled, false, '动画结束后应恢复判断操作')
    assert.doesNotMatch(measured.frames.at(-1).text, /阿尔法|贝塔/)
  }
  assert.deepEqual((await state()).writes, [])
})

test('按钮与方向键复用切词动效，桌面暗色可用，减少动态效果时即时切换且不影响翻转', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('set', 'viewport', '1440', '900')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  await browser('eval', 'document.documentElement.classList.add("dark")')
  for (const [action, term, direction] of [['button', 'beta', 1], ['keyboard', 'alpha', -1]]) {
    const observed = JSON.parse(await browser('eval', `(async()=>{
      const card=document.querySelector('section[aria-label="单词卡"]'), frames=[];
      if('${action}'==='button')[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='下一张').click();
      else card.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
      for(let i=0;i<600;i++){
        await new Promise(requestAnimationFrame);
        const content=card.querySelector('.study-card-content'),style=getComputedStyle(content||card);
        frames.push({text:card.textContent,x:new DOMMatrixReadOnly(style.transform).m41});
        if(card.textContent.includes('${term}')&&card.getAttribute('aria-busy')==='false')break;
      }
      return {frames,background:getComputedStyle(card).backgroundColor,animations:card.getAnimations({subtree:true}).length};
    })()`))
    assert.ok(observed.frames.some(f => f.text.includes(term) && f.x * direction > 1))
    assert.equal(observed.animations, 0)
    assert.notEqual(observed.background, 'rgb(255, 255, 255)')
  }
  await browser('set', 'media', 'dark', 'reduced-motion')
  const reduced = JSON.parse(await browser('eval', `(async()=>{
    const card=document.querySelector('section[aria-label="单词卡"]');window.navigationAnimations=0;
    const animate=Element.prototype.animate;
    Element.prototype.animate=function(...args){window.navigationAnimations++;return animate.apply(this,args)};
    try{
      for(const [key,term] of [['ArrowRight','beta'],['ArrowLeft','alpha']]){
        card.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true}));
        for(let i=0;i<600;i++){await new Promise(requestAnimationFrame);if(card.textContent.includes(term)&&card.getAttribute('aria-disabled')==='false')break;}
      }
      return {animations:window.navigationAnimations,text:card.textContent,busy:card.getAttribute('aria-busy')};
    }finally{Element.prototype.animate=animate;}
  })()`))
  assert.equal(reduced.animations, 0)
  assert.equal(reduced.busy, 'false')
  assert.match(reduced.text, /alpha/)
  await flipStudyCard(browser)
  assert.match(await browser('get', 'text', 'section[aria-label="单词卡"]'), /阿尔法/)
  assert.deepEqual((await state()).writes, [])
})

test('切词出入场均可被反向或连续导航取消，首张边界不动画，离页无残留', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const card = 'section[aria-label="单词卡"]'
  const boundary = JSON.parse(await browser('eval', `(async()=>{
    const card=document.querySelector('${card}');card.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));await Promise.resolve();
    return {text:card.textContent,animations:card.getAnimations({subtree:true}).length,busy:card.getAttribute('aria-busy')};
  })()`))
  assert.match(boundary.text, /alpha/)
  assert.equal(boundary.animations, 0)
  assert.equal(boundary.busy, 'false')
  for (const phase of ['outgoing', 'incoming']) {
    await browser('eval', `(async()=>{
      const card=document.querySelector('${card}');card.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));await Promise.resolve();
      if('${phase}'==='incoming'){await card.getAnimations({subtree:true})[0].finished;await new Promise(requestAnimationFrame);}
      window.oldNavigation=card.getAnimations({subtree:true})[0];window.oldNavigation.pause();
    })()`)
    await browser('wait', '--fn', `!document.querySelector('.study-actions button').disabled`)
    await browser('press', 'ArrowLeft')
    await browser('wait', '--text', 'alpha')
    await browser('wait', '--fn', `document.querySelector('${card}').getAttribute('aria-busy')==='false'`)
    const fresh = JSON.parse(await browser('eval', `({text:document.querySelector('${card}').textContent,animations:document.querySelector('${card}').getAnimations({subtree:true}).length,oldState:window.oldNavigation.playState})`))
    assert.equal(fresh.oldState, 'idle')
    assert.equal(fresh.animations, 0)
    assert.doesNotMatch(fresh.text, /beta|阿尔法|贝塔/)
  }
  await browser('eval', `(async()=>{
    const card=document.querySelector('${card}');card.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));await Promise.resolve();
    window.oldNavigation=card.getAnimations({subtree:true})[0];window.oldNavigation.pause();
  })()`)
  await browser('wait', '--fn', `!document.querySelector('.study-actions > div:first-child button:last-child').disabled`)
  await browser('press', 'ArrowRight')
  await browser('wait', '--text', 'gamma')
  await browser('wait', '--fn', `document.querySelector('${card}').getAttribute('aria-busy')==='false'`)
  assert.equal(JSON.parse(await browser('eval', 'window.oldNavigation.playState')), 'idle')
  await browser('eval', `(async()=>{
    const card=document.querySelector('${card}');card.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));await Promise.resolve();
    window.oldNavigation=card.getAnimations({subtree:true})[0];window.oldNavigation.pause();
  })()`)
  await browser('find', 'role', 'link', 'click', '--name', '退出学习')
  await browser('wait', '--text', '选择词汇来源')
  assert.equal(JSON.parse(await browser('eval', 'window.oldNavigation.playState')), 'idle')
  assert.deepEqual((await state()).writes, [])
  assert.doesNotMatch(await browser('errors'), /AbortError|Unhandled|TypeError/)
})

test('未缓存词先显示加载状态，正文到达后保留导航方向入场，不闪回旧词或中文', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t, { count: 21, nextItemsDelay: 3000 })
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'word0000')
  const measured = JSON.parse(await browser('eval', `(async()=>{
    const card=document.querySelector('section[aria-label="单词卡"]'),next=document.querySelector('.study-actions > div:first-child button:last-child');
    for(let word=1;word<=20;word++){
      for(let i=0;i<600&&next.disabled;i++)await new Promise(requestAnimationFrame);
      next.click();await new Promise(requestAnimationFrame);
    }
    const loadingText=card.textContent,loadingAnimations=card.getAnimations({subtree:true}).length,frames=[];
    for(let i=0;i<600;i++){
      await new Promise(requestAnimationFrame);
      const content=card.querySelector('.study-card-content'),style=getComputedStyle(content);
      frames.push({text:card.textContent,x:new DOMMatrixReadOnly(style.transform).m41});
      if(card.textContent.includes('word0020')&&card.getAttribute('aria-busy')==='false')break;
    }
    return {loadingText,loadingAnimations,frames,animations:card.getAnimations({subtree:true}).length,judgesEnabled:[...document.querySelectorAll('.study-judge')].every(b=>!b.disabled)};
  })()`))
  assert.match(measured.loadingText, /正在加载单词/)
  assert.equal(measured.loadingAnimations, 0)
  assert.ok(measured.frames.some(f => f.text.includes('word0020') && f.x > 1))
  assert.ok(measured.frames.every(f => !/word0019|阿尔法|贝塔|伽马/.test(f.text)))
  assert.equal(measured.animations, 0)
  assert.equal(measured.judgesEnabled, true)
  assert.deepEqual((await state()).writes, [])
})

test('整张卡片点击翻面，无独立按钮；中途切换内容并保持尺寸，减少动态效果设置不关闭翻转', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const card = 'section[aria-label="单词卡"]'
  assert.equal(Number(await browser('get', 'count', `${card} button`)), 0)
  assert.equal((await browser('get', 'attr', card, 'tabindex')).trim(), '0')
  for (const reduced of [false, true]) {
    if (reduced) await browser('set', 'media', 'light', 'reduced-motion')
    await browser('eval', `(()=>{
      const card=document.querySelector('${card}');
      window.flipFrames=[];window.flipHeight=card.offsetHeight;window.flipBounds=card.getBoundingClientRect().toJSON();
      const sample=()=>{window.flipFrames.push({text:card.textContent, bounds:card.getBoundingClientRect().toJSON(), transform:getComputedStyle(card).transform, durations:card.getAnimations().map(a=>a.effect.getTiming().duration)});window.flipFrame=requestAnimationFrame(sample)};
      window.flipFrame=requestAnimationFrame(sample);
    })()`)
    await browser('click', card)
    await browser('wait', '--text', '阿尔法')
    await browser('wait', '--fn', `document.querySelector('${card}').getAnimations().length === 0`)
    const measured = JSON.parse(await browser('eval', `(()=>{
      cancelAnimationFrame(window.flipFrame);const card=document.querySelector('${card}');
      return {frames:window.flipFrames, initialBounds:window.flipBounds, height:card.offsetHeight, initialHeight:window.flipHeight, focus:document.activeElement===card};
    })()`))
    const moving = measured.frames.filter(f => f.transform.startsWith('matrix3d'))
    assert.ok(moving.some(f => !f.text.includes('阿尔法')), '英文面应先旋转离场')
    assert.ok(moving.some(f => f.text.includes('阿尔法')), '中文面应旋转入场')
    assert.ok(moving.every(f => f.durations.includes(160)), '两段翻转各 160ms')
    assert.ok(moving.every(f => f.bounds.top >= measured.initialBounds.top - 8 && f.bounds.bottom <= measured.initialBounds.bottom + 8), '翻转不应越过卡片间距遮住进度或导航')
    assert.equal(measured.height, measured.initialHeight)
    assert.equal(measured.focus, true)
    await browser('click', `${card} .study-card-meta`)
    await browser('wait', '--text', '点击卡片查看中文')
    await browser('wait', '--fn', `document.querySelector('${card}').getAnimations().length === 0`)
    assert.doesNotMatch(await browser('get', 'text', card), /阿尔法/)
  }
  assert.deepEqual((await state()).writes, [])
})

test('连续点击只翻一次；翻转两个阶段切词或离页均取消旧动画，保存中不能翻面', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const card = 'section[aria-label="单词卡"]'
  await browser('eval', `(()=>{const card=document.querySelector('${card}');card.click();card.click();card.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,repeat:true}))})()`)
  await browser('wait', '--text', '阿尔法')
  await browser('wait', '--fn', `document.querySelector('${card}').getAttribute('aria-busy') === 'false'`)
  await flipStudyCard(browser, 'english')
  for (const phase of ['outgoing', 'incoming']) {
    await browser('eval', `(async()=>{
      const card=document.querySelector('${card}');card.click();await Promise.resolve();
      if ('${phase}'==='incoming') {
        await card.getAnimations()[0].finished;
        await new Promise(requestAnimationFrame);
      }
      card.getAnimations()[0].pause();
    })()`)
    await browser('press', 'ArrowRight')
    await browser('wait', '--text', 'beta')
    await browser('wait', '--fn', `document.querySelector('${card}').getAttribute('aria-busy') === 'false'`)
    const fresh = JSON.parse(await browser('eval', `(()=>{const card=document.querySelector('${card}');return {text:card.textContent, animations:card.getAnimations().length, busy:card.getAttribute('aria-busy'), transform:getComputedStyle(card).transform}})()`))
    assert.doesNotMatch(fresh.text, /alpha|阿尔法|贝塔/)
    assert.equal(fresh.animations, 0)
    assert.equal(fresh.busy, 'false')
    assert.equal(fresh.transform, 'none')
    await browser('press', 'ArrowLeft')
    await browser('wait', '--text', 'alpha')
    await browser('wait', '--fn', `document.querySelector('${card}').getAttribute('aria-busy') === 'false'`)
  }
  await fetch(`${origin}/__study-test/delay-mark`)
  const saving = JSON.parse(await browser('eval', `(async()=>{
    [...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='已记住').click();await Promise.resolve();
    const card=document.querySelector('${card}');card.click();card.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true}));await Promise.resolve();
    return {disabled:card.getAttribute('aria-disabled'), animations:card.getAnimations().length, text:card.textContent};
  })()`))
  assert.equal(saving.disabled, 'true')
  assert.equal(saving.animations, 0)
  assert.doesNotMatch(saving.text, /阿尔法/)
  await browser('wait', '--text', 'beta')
  await browser('wait', '--fn', `document.querySelector('${card}').getAttribute('aria-busy') === 'false'`)
  await browser('eval', `(async()=>{const card=document.querySelector('${card}');card.click();await Promise.resolve();card.getAnimations()[0].pause()})()`)
  await browser('find', 'role', 'link', 'click', '--name', '退出学习')
  await browser('wait', '--text', '选择词汇来源')
  assert.deepEqual((await state()).writes, [[1, true]])
  assert.doesNotMatch(await browser('errors'), /AbortError|Unhandled|TypeError/)
})

test('完整应用：来源→翻面→判断→滑过→小结；真实IndexedDB刷新续学', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab`)
  await browser('wait', '--text', '选择词汇来源')
  await browser('wait', '--fn', "document.querySelector('section[aria-labelledby=\"vocab-title\"]').getAttribute('aria-busy')==='false'")
  await mkdir(evidenceDir, { recursive: true })
  await browser('screenshot', `${evidenceDir}source-overview.png`, '--full')
  await browser('find', 'role', 'button', 'click', '--name', '学习我的单词本')
  await browser('wait', '--text', 'alpha')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /阿尔法/)
  await flipStudyCard(browser)
  await browser('wait', '--text', '阿尔法')
  await browser('find', 'role', 'button', 'click', '--name', '已记住', '--exact')
  await browser('wait', '--text', 'beta')
  await browser('reload')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', 'beta')
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'gamma')
  await browser('wait', '--fn', `document.querySelector('section[aria-label="单词卡"]').getAttribute('aria-busy') === 'false'`)
  await browser('find', 'role', 'button', 'click', '--name', '未记住', '--exact')
  await browser('wait', '--text', '本轮小结')
  await browser('screenshot', `${evidenceDir}round-summary.png`)
  const content = await browser('get', 'text', 'main')
  assert.match(content, /已记住\s+1/)
  assert.match(content, /未记住\s+1/)
  assert.match(content, /未标记\s+1/)
  assert.doesNotMatch(content, /本轮完成/)
  assert.deepEqual((await state()).writes, [[1, true], [3, false]])
  await browser('find', 'role', 'button', 'click', '--name', '再练未记住的词')
  await browser('wait', '--text', 'gamma')
  assert.match(await browser('get', 'text', '.study-header'), /第 1 \/ 1 个词/)
})

test('真实Web Locks交接、原页停止交互、关闭接管页可续学、跨页退出清理草稿', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  await browser('find', 'role', 'button', 'click', '--name', '已记住', '--exact')
  await browser('wait', '--text', 'beta')
  const url = (await browser('get', 'url')).trim()
  await browser('tab', 'new', url)
  await browser('wait', '--text', '此轮正在另一标签页学习')
  assert.deepEqual((await state()).writes, [[1, true]])
  await browser('find', 'role', 'button', 'click', '--name', '请求接管')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', 'beta')
  await browser('tab', 't1')
  await browser('wait', '--text', '学习已交接到另一标签页')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /阿尔法|贝塔/)
  await browser('tab', 'close', 't2')
  await browser('find', 'role', 'link', 'click', '--name', '退出学习')
  await browser('wait', '--text', '选择词汇来源')
  await browser('find', 'role', 'button', 'click', '--name', '学习我的单词本')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', 'beta')
  await browser('tab', 'new', `${origin}/exams/current/vocab`)
  await browser('eval', "localStorage.removeItem('token');localStorage.removeItem('user')")
  await browser('tab', 't1')
  await browser('wait', '--url', '**/login')
  const count = JSON.parse(await browser('eval', `(async()=>{const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('quiz-vocabulary-study');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)}); const n=await new Promise(resolve=>{const r=db.transaction('manifest').objectStore('manifest').count();r.onsuccess=()=>resolve(r.result)});db.close();return n})()`))
  assert.equal(count, 0)
})

test('保存失败留原卡，核验失败不发布小结，已结束小结可刷新且入口不误续学', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  await fetch(`${origin}/__study-test/fail-mark`)
  await browser('find', 'role', 'button', 'click', '--name', '已记住', '--exact')
  await browser('wait', '--text', '保存失败')
  assert.match(await browser('get', 'text', 'main'), /alpha/)
  assert.deepEqual((await state()).writes, [])
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'beta')
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'gamma')
  await fetch(`${origin}/__study-test/fail-verify`)
  await browser('find', 'role', 'button', 'click', '--name', '查看小结')
  await browser('wait', '--text', '小结核验未完成')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /补学未标记的词/)
  await browser('find', 'role', 'button', 'click', '--name', '核验／重试')
  await browser('wait', '--text', '本轮小结')
  await browser('reload')
  await browser('wait', '--text', '本轮小结')
  await browser('find', 'role', 'link', 'click', '--name', '结束并返回来源选择')
  await browser('wait', '--text', '选择词汇来源')
  await browser('find', 'role', 'button', 'click', '--name', '学习我的单词本')
  await browser('wait', '--text', 'alpha')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /继续上轮/)
})

test('横滑只导航，纵向／取消／复制不翻面；释义纯文本且中文缺失组合清晰', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t, { contentOverrides: [
    { term_zh: '  ', definition_zh: '\n' }, { term_zh: null, definition_zh: '仅有中文释义' }, { term_zh: '重复中文', definition_zh: '重复中文' },
  ] })
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const gesture = (dx, dy, cancel = false, verticalFirst = false) => browser('eval', `(()=>{
    const target=document.querySelector('section[aria-label="单词卡"] h2');const r=target.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2;
    const fire=(type,dx,dy)=>target.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:'touch',isPrimary:true,pointerId:1,button:0,clientX:x+dx,clientY:y+dy}));
    fire('pointerdown',0,0);${verticalFirst ? "fire('pointermove',2,30);" : ''}fire('pointermove',${dx},${dy});fire('${cancel ? 'pointercancel' : 'pointerup'}',${dx},${dy});
  })()`)
  await gesture(80, 0) // 首张不环绕。
  assert.match(await browser('get', 'text', 'main'), /alpha/)
  await gesture(-80, 0)
  await browser('wait', '--text', 'beta')
  assert.deepEqual((await state()).writes, [])
  await gesture(80, 0)
  await browser('wait', '--text', 'alpha')
  await gesture(-80, 0, true)
  await gesture(-100, 30, false, true)
  assert.match(await browser('get', 'text', 'main'), /alpha/)
  assert.doesNotMatch(await browser('get', 'text', 'main'), /缺少中文/)
  await browser('eval', "const range=document.createRange();range.selectNodeContents(document.querySelector('section[aria-label=\"单词卡\"] h2'));getSelection().addRange(range)")
  await gesture(-80, 0)
  assert.match(await browser('get', 'text', 'main'), /alpha/)
  await browser('eval', 'getSelection().removeAllRanges()')
  const touchAtEdge = JSON.parse(await browser('eval', `(async()=>{
    const card=document.querySelector('section[aria-label="单词卡"]'),r=card.getBoundingClientRect();
    const fire=type=>card.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:'touch',isPrimary:true,pointerId:1,button:0,clientX:r.left+2,clientY:r.top+r.height/2}));
    fire('pointerdown');await new Promise(resolve=>setTimeout(resolve,400));fire('pointerup');await Promise.resolve();
    const longPressAnimations=card.getAnimations().length;
    fire('pointerdown');fire('pointerup');await Promise.resolve();
    return {longPressAnimations,tapAnimations:card.getAnimations().length};
  })()`))
  assert.deepEqual(touchAtEdge, { longPressAnimations: 0, tapAnimations: 1 })
  await browser('wait', '--text', '当前缺少中文')
  await browser('wait', '--fn', `document.querySelector('section[aria-label="单词卡"]').getAttribute('aria-busy') === 'false'`)
  assert.match(await browser('get', 'text', 'main'), /<b>plain text<\/b>/)
  assert.equal(JSON.parse(await browser('eval', "document.querySelector('section[aria-label=\"单词卡\"]').querySelectorAll('b').length")), 0)
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'beta')
  await flipStudyCard(browser)
  await browser('wait', '--text', '仅有中文释义')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /当前缺少中文/)
  assert.equal((await browser('is', 'visible', 'section[aria-label="单词卡"] .study-card-body p[lang="en"]:last-child')).trim(), 'true')
  assert.match(await browser('get', 'text', 'main'), /<b>plain text<\/b>/)
  assert.match(await browser('get', 'text', 'main'), /仅有中文释义/)
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'gamma')
  await flipStudyCard(browser)
  assert.equal((await browser('get', 'text', 'main')).match(/重复中文/g)?.length, 1)
})

test('实际外壳屏幕矩阵、长词与长释义、安全按钮（桌面模拟，不替代真机）', { timeout: 120000 }, async t => {
  const term = 'pneumonoultramicroscopicsilicovolcanoconiosis'.repeat(3)
  const { browser, origin } = await startStudyBrowser(t, { coarsePointer: true, contentOverrides: [{ term, definition_zh: '中文释义的一段详细说明，用于验证内部滚动与底部按钮可达。\n'.repeat(60) }] })
  await mkdir(evidenceDir, { recursive: true })
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', term)
  const geometry = () => browser('eval', `(()=>{
    const main=document.querySelector('main');const buttons=[...main.querySelectorAll('button')].filter(b=>/^(未记住|已记住)$/.test(b.textContent.trim())).map(b=>{const r=b.getBoundingClientRect();return {height:r.height,bottom:r.bottom,width:r.width}});
    const global=[...document.querySelectorAll('.global-navigation')].some(n=>getComputedStyle(n).display!=='none' && n.getBoundingClientRect().height>0);
    return {width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,buttons,global};
  })()`)
  const results = []
  for (const [width, height] of [[320,568],[390,844],[767,800],[768,800],[769,800],[1024,800],[1440,900]]) {
    await browser('set', 'viewport', String(width), String(height))
    for (const dark of [false, true]) {
      await browser('eval', `document.documentElement.classList.toggle('dark',${dark})`)
      for (const scale of [1, 2]) {
        await browser('eval', `document.documentElement.style.fontSize='${scale * 16}px'`)
        const measured = JSON.parse(await geometry())
        assert.equal(measured.overflow, false, `${width}px ${dark?'dark':'light'} ${scale*100}%`)
        assert.equal(measured.global, width >= 768)
        assert.equal(measured.buttons.length, 2)
        assert.ok(measured.buttons.every(b => b.height >= 52 && b.bottom <= height + 1 && b.width >= 48), JSON.stringify(measured))
        results.push({ viewport: [width,height], dark, textScale: scale, ...measured })
      }
    }
  }
  await browser('eval', "document.documentElement.style.fontSize='16px';document.documentElement.classList.remove('dark')")
  await browser('set', 'viewport', '390', '844')
  await browser('screenshot', `${evidenceDir}mobile-front.png`)
  await flipStudyCard(browser)
  await browser('screenshot', `${evidenceDir}mobile-long-back.png`)
  assert.equal(JSON.parse(await browser('eval', "(()=>{const p=document.querySelector('section[aria-label=\"单词卡\"] p.whitespace-pre-wrap');return p.parentElement.scrollHeight>p.parentElement.clientHeight})()")), true)
  await browser('scroll', 'down', '400', '--selector', '.study-card-body')
  await browser('wait', '--fn', "document.querySelector('.study-card-body').scrollTop > 0")
  assert.match(await browser('get', 'text', 'section[aria-label="单词卡"]'), /点击卡片返回英文/)
  await browser('eval', "document.querySelector('.study-card-body').scrollTop=0")
  await browser('set', 'viewport', '1440', '900')
  await browser('screenshot', `${evidenceDir}desktop-back.png`)
  await browser('set', 'viewport', '844', '390')
  assert.equal(JSON.parse(await browser('eval', "matchMedia('(pointer: coarse)').matches")), true)
  const landscape = JSON.parse(await geometry())
  assert.equal(landscape.global, false)
  assert.equal(landscape.overflow, false)
  assert.ok(landscape.buttons.every(b => b.bottom <= 391))
  await browser('screenshot', `${evidenceDir}touch-landscape.png`)
  await writeFile(`${evidenceDir}screen-matrix.json`, JSON.stringify({ note: '桌面浏览器模拟；200% 为文本放大；无真机或真实浏览器页面缩放证据', results, landscape }, null, 2))
})

test('5000词首卡性能证据：仅成员快照+20词正文，DOM不随词数展开', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t, { count: 5000 })
  await browser('open', `${origin}/exams/current/vocab`)
  await browser('wait', '--text', '选择词汇来源')
  await browser('eval', `(()=>{document.addEventListener('click',()=>{
    window.studyStart=performance.now();const observer=new MutationObserver(()=>{if(document.querySelector('section[aria-label="单词卡"] h2')?.textContent==='word0000'){window.studyFirstCardMs=performance.now()-window.studyStart;observer.disconnect()}});observer.observe(document.body,{childList:true,subtree:true});
  },{once:true,capture:true})})()`)
  await browser('find', 'role', 'button', 'click', '--name', '学习我的单词本')
  await browser('wait', '--text', 'word0000')
  const metrics = JSON.parse(await browser('eval', `({firstCardMs:window.studyFirstCardMs,domNodes:document.querySelector('main').querySelectorAll('*').length, resources:performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/vocab/study/')).map(r=>({path:new URL(r.name).pathname,transferBytes:r.transferSize,bodyBytes:r.encodedBodySize,durationMs:r.duration}))})`))
  const observed = await state()
  assert.deepEqual(observed.reads.filter(r => r.path === 'items').map(r => [r.count,r.content]), [[20,true]])
  assert.equal(observed.reads.filter(r => r.path === 'deck').length, 1)
  assert.ok(metrics.domNodes < 150)
  assert.ok(metrics.firstCardMs > 0)
  await flipStudyCard(browser)
  await flipStudyCard(browser, 'english')
  assert.equal((await state()).reads.length, observed.reads.length, '已缓存翻面不能发网络请求')
  await mkdir(evidenceDir, { recursive: true })
  await writeFile(`${evidenceDir}performance.json`, JSON.stringify({ note: '本地5000词HTTP fixture样例，不是生产或真机性能保证', ...metrics, responses: observed.responses }, null, 2))
})

test('真实浏览器强制关闭在途保存：恢复pending不当作成功、不重放写入，核验后手动重判', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const originalUrl = (await browser('get', 'url')).trim()
  await fetch(`${origin}/__study-test/delay-mark`)
  await browser('eval', "const b=[...document.querySelectorAll('main button')].find(b=>b.textContent.trim()==='已记住');b.click();b.click()")
  for (let attempt = 0; attempt < 100 && (await state()).writes.length === 0; attempt++) await new Promise(resolve => setTimeout(resolve, 10))
  assert.deepEqual((await state()).writes, [[1,true]])
  await browser('tab', 'new', 'about:blank')
  await browser('tab', 'close', 't1')
  await browser('open', originalUrl)
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', '服务器当前为已掌握')
  assert.match(await browser('get', 'text', 'main'), /alpha/)
  assert.match(await browser('get', 'text', '.study-header'), /第 1 \/ 3 个词/)
  assert.deepEqual((await state()).writes, [[1,true]])
  await browser('find', 'role', 'button', 'click', '--name', '未记住', '--exact')
  await browser('wait', '--text', 'beta')
  assert.deepEqual((await state()).writes, [[1,true],[1,false]])
})

test('无效学习参数不换源；真实应用的管理入口与浏览器后退无残留沉浸导航', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=all&bank_id=7`)
  await browser('wait', '--text', '学习参数无效')
  assert.equal((await state()).reads.length, 0)
  await browser('find', 'role', 'link', 'click', '--name', '返回来源选择')
  await browser('wait', '--text', '选择词汇来源')
  await browser('find', 'role', 'button', 'click', '--name', '更多', '--exact')
  await browser('wait', '--text', '退出登录')
  await browser('back')
  await browser('wait', '--text', '学习参数无效')
  await browser('forward')
  await browser('wait', '--text', '选择词汇来源')
  assert.doesNotMatch(await browser('get', 'text', 'body'), /退出登录/, '沉浸学习退出不能恢复此前打开的全局浮层')
  await browser('scrollintoview', 'a[aria-label="管理我的单词本"]')
  await browser('find', 'role', 'link', 'click', '--name', '管理我的单词本')
  await browser('wait', '--text', '添加单词')
  assert.match((await browser('get', 'url')).trim(), /mode=manage.*scope=personal/)
  await browser('back')
  await browser('wait', '--text', '选择词汇来源')
  const shown = JSON.parse(await browser('eval', "[...document.querySelectorAll('.global-navigation')].some(n=>getComputedStyle(n).display!=='none')"))
  assert.equal(shown, true)
})

test('双击选词不翻面；卡片键盘翻面与左右导航有效且不泄露隐藏中文', { timeout: 120000 }, async t => {
  const { browser, origin } = await startStudyBrowser(t)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  await browser('dblclick', 'section[aria-label="单词卡"] h2')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /阿尔法/)
  assert.equal(JSON.parse(await browser('eval', 'getSelection().toString()')), 'alpha')
  await browser('eval', 'getSelection().removeAllRanges()')
  await browser('focus', 'section[aria-label="单词卡"]')
  await browser('press', 'Enter')
  await browser('wait', '--text', '阿尔法')
  await browser('wait', '--fn', `document.querySelector('section[aria-label="单词卡"]').getAttribute('aria-busy') === 'false'`)
  // 反面的 h2 占满行，元素中心是留白；按实际文字范围拖选，不能把留白双击当成选词。
  const bounds = JSON.parse(await browser('eval', `(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('section[aria-label="单词卡"] h2'));return range.getBoundingClientRect().toJSON()})()`))
  await browser('mouse', 'move', String(bounds.left), String(bounds.top + bounds.height / 2))
  await browser('mouse', 'down')
  await browser('mouse', 'move', String(bounds.right), String(bounds.top + bounds.height / 2))
  await browser('mouse', 'up')
  assert.equal(JSON.parse(await browser('eval', 'getSelection().toString()')).trim(), '阿尔法')
  assert.match(await browser('get', 'text', 'main'), /阿尔法/)
  await browser('eval', 'getSelection().removeAllRanges()')
  assert.equal((await browser('is', 'visible', 'section[aria-label="单词卡"] .study-card-body p[lang="en"]:last-child')).trim(), 'true')
  await browser('eval', `(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('section[aria-label="单词卡"] .study-card-body p[lang="en"]:last-child'));getSelection().addRange(range)})()`)
  await browser('press', 'Space')
  assert.match(await browser('get', 'text', 'main'), /阿尔法/)
  await browser('eval', 'getSelection().removeAllRanges()')
  await browser('focus', 'section[aria-label="单词卡"]')
  await browser('press', 'Space')
  await browser('wait', '--text', '点击卡片查看中文')
  await browser('wait', '--fn', `document.querySelector('section[aria-label="单词卡"]').getAttribute('aria-busy') === 'false'`)
  assert.doesNotMatch(await browser('get', 'text', 'main'), /阿尔法/)
  await browser('press', 'ArrowRight')
  await browser('wait', '--text', 'beta')
})

test('学习正反面明暗主题的自动无障碍检查，无隐藏中文节点（不能替代真人读屏）', { timeout: 120000 }, async t => {
  const { browser, origin } = await startStudyBrowser(t)
  await browser('set', 'viewport', '390', '844')
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  const reports = []
  for (const dark of [false,true]) {
    await browser('eval', `document.documentElement.classList.toggle('dark',${dark})`)
    for (const flipped of [false,true]) {
      if (flipped) { await flipStudyCard(browser); await browser('wait', '--text', '阿尔法') }
      const audit = JSON.parse(await browser('a11y', '--selector', 'main', '--tags', 'wcag2a,wcag2aa', '--json')).data
      assert.equal(audit.counts.violations, 0, JSON.stringify(audit.violations))
      reports.push({ dark, flipped, ...audit })
    }
    await flipStudyCard(browser, 'english')
  }
  await mkdir(evidenceDir, { recursive: true })
  await writeFile(`${evidenceDir}accessibility.json`, JSON.stringify({ note: '仅学习区axe自动规则，不是全站或真人读屏认证', reports }, null, 2))
})

test('后端尚未发布学习读取接口时明确重试，不误当项目删除，不退换来源', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t)
  await fetch(`${origin}/__study-test/missing-api`)
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', '学习读取接口暂不可用')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /当前范围没有可学词/)
  await fetch(`${origin}/__study-test/enable-api`)
  await browser('find', 'role', 'button', 'click', '--name', '重新开始／重试')
  await browser('wait', '--text', 'alpha')
  assert.deepEqual((await state()).writes, [])
})

test('完全缺释义仍可自行判断；只有中文释义或短翻译不误判缺中文、不补造内容', { timeout: 120000 }, async t => {
  const { browser, origin, state } = await startStudyBrowser(t, { contentOverrides: [
    { term_zh: null, definition_zh: '\n', definition: '  ' },
    { term_zh: '', definition_zh: '只有中文释义', definition: null },
    { term_zh: '只有短翻译', definition_zh: null, definition: null },
  ] })
  await browser('open', `${origin}/exams/current/vocab/study?scope=personal`)
  await browser('wait', '--text', 'alpha')
  await flipStudyCard(browser)
  await browser('wait', '--text', '当前仅有英文词条')
  assert.deepEqual((await state()).writes, [])
  await browser('find', 'role', 'button', 'click', '--name', '已记住', '--exact')
  await browser('wait', '--text', 'beta')
  await flipStudyCard(browser)
  await browser('wait', '--text', '只有中文释义')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /缺少中文|展开英文释义/)
  await browser('find', 'role', 'button', 'click', '--name', '下一张')
  await browser('wait', '--text', 'gamma')
  await flipStudyCard(browser)
  await browser('wait', '--text', '只有短翻译')
  assert.doesNotMatch(await browser('get', 'text', 'main'), /缺少中文|展开英文释义|暂无翻译/)
})
