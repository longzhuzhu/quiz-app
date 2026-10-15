import test from 'node:test'
import assert from 'node:assert/strict'
import { flipStudyCard, startStudyBrowser } from './helpers/studyBrowser.js'
import { startStudyBackend } from './helpers/studyBackend.js'

// 学习顺序随机，只能读取当前卡片上的词，不能预设是哪一个。
// 正面词条为 h2.study-word，翻面后为第一个 lang="en" 段落；动画中不读，避免读到换词前的旧内容。
async function studyTerm(browser, exclude) {
  const read = `(() => {
    const card = document.querySelector('section[aria-label="单词卡"]');
    if (!card || card.getAttribute('aria-busy') !== 'false') return '';
    const word = card.querySelector('.study-word') || card.querySelector('.study-card-body p[lang="en"]');
    return word ? word.textContent.trim() : '';
  })()`
  const differs = exclude ? ` && term !== ${JSON.stringify(exclude)}` : ''
  await browser('wait', '--fn', `(term => !!term${differs})(${read})`)
  return JSON.parse(await browser('eval', read))
}

test('真实后端与隔离PostgreSQL：登录→来源→翻面→保存→刷新→核对持久化；110/5000词契约', { timeout: 120000 }, async t => {
  const apiTarget = await startStudyBackend(t)
  const { browser, origin } = await startStudyBrowser(t, { apiTarget })
  await browser('open', `${origin}/exams/current/vocab`)
  await browser('find', 'placeholder', '请输入用户名', 'fill', 'study-user')
  await browser('find', 'placeholder', '请输入密码', 'fill', 'StudyTest123!')
  await browser('find', 'role', 'button', 'click', '--name', '登录', '--exact')
  await browser('wait', '--url', '**/dashboard')
  await browser('open', `${origin}/exams/current/vocab`)
  await browser('wait', '--text', '选择词汇来源')
  await browser('find', 'role', 'button', 'click', '--name', '学习我的单词本')
  const first = await studyTerm(browser)
  await flipStudyCard(browser)
  await browser('wait', '--text', '真实释义')
  await browser('find', 'role', 'button', 'click', '--name', '刷新', '--exact')
  await browser('wait', '--text', `刷新后的 ${first} 中文释义`)
  await browser('wait', '--text', '已刷新翻译与中英文释义')
  await browser('find', 'role', 'button', 'click', '--name', '已记住', '--exact')
  const second = await studyTerm(browser, first)
  await browser('reload')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', second)
  const persisted = JSON.parse(await browser('eval', `(async () => {
    const headers = { Authorization: 'Bearer ' + localStorage.getItem('token'), 'X-Exam-Slug': 'current' };
    const get = path => fetch(path, {headers}).then(r=>r.json());
    const saved = await get('/api/vocab?scope=personal&mastered=true&q=' + encodeURIComponent(${JSON.stringify(first)}));
    const project = await get('/api/vocab/study/deck?scope=exam_personal');
    const personal = await get('/api/vocab/study/deck?scope=personal&mastery=all');
    const banks = await get('/api/banks');
    const high = await get('/api/vocab/study/deck?scope=frequent&bank_id='+banks[0].id);
    const highTerms = high.refs.map(ref => ref.term).sort();
    const noToken=await fetch('/api/vocab/study/deck?scope=personal',{headers:{'X-Exam-Slug':'current'}});
    const noExam=await fetch('/api/vocab/study/deck?scope=personal',{headers:{Authorization:headers.Authorization}});
    const invalidToken=await fetch('/api/vocab/study/deck?scope=personal',{headers:{Authorization:'Bearer invalid','X-Exam-Slug':'current'}});
    const refreshBody=JSON.stringify({scope:'personal',ref:personal.refs[0]});
    const refreshNoToken=await fetch('/api/vocab/study/refresh',{method:'POST',headers:{'X-Exam-Slug':'current','Content-Type':'application/json'},body:refreshBody});
    const refreshNoExam=await fetch('/api/vocab/study/refresh',{method:'POST',headers:{Authorization:headers.Authorization,'Content-Type':'application/json'},body:refreshBody});
    const refreshInvalidToken=await fetch('/api/vocab/study/refresh',{method:'POST',headers:{Authorization:'Bearer invalid','X-Exam-Slug':'current','Content-Type':'application/json'},body:refreshBody});
    return {saved: saved.items.map(w=>({term:w.term,mastered:w.is_mastered,term_zh:w.term_zh,definition:w.definition,definition_zh:w.definition_zh})), project:project.total, personal:personal.total, high:high.total, highFirst:highTerms[0], highLast:highTerms.at(-1), highExcluded:highTerms.includes('term5000'), limit:high.top_limit, security:[noToken.status,noExam.status,invalidToken.status,refreshNoToken.status,refreshNoExam.status,refreshInvalidToken.status]};
  })()`))
  // 高频词仍取词频最高的 5000 个（term5000 被截断），只是学习顺序不再按词频。
  assert.deepEqual(persisted, { saved: [{ term: first, mastered: true, term_zh: `刷新后的 ${first} 中文`, definition: `A refreshed English definition for ${first}.`, definition_zh: `刷新后的 ${first} 中文释义。` }], project: 110, personal: 110, high: 5000, highFirst: 'term0000', highLast: 'term4999', highExcluded: false, limit: 5000, security: [401,400,401,401,400,401] })
  await browser('find', 'role', 'link', 'click', '--name', '退出学习')
  await browser('wait', '--text', '选择词汇来源')
  await browser('wait', '--fn', "!!document.querySelector('#vocab-bank option[value=\"1\"]')")
  await browser('select', '#vocab-bank', '1')
  await browser('find', 'role', 'button', 'click', '--name', '学习高频词汇')
  const firstFrequent = await studyTerm(browser)
  await flipStudyCard(browser)
  await browser('wait', '--text', '高频词')
  await browser('find', 'role', 'button', 'click', '--name', '刷新', '--exact')
  await browser('wait', '--text', `刷新后的 ${firstFrequent} 中文释义`)
  await browser('wait', '--text', '已刷新翻译与中英文释义')
  assert.equal((await browser('is', 'visible', 'section[aria-label="单词卡"] .study-card-body p[lang="en"]:last-child')).trim(), 'true')
  await browser('wait', '--text', `A refreshed English definition for ${firstFrequent}`)
  await browser('find', 'role', 'button', 'click', '--name', '已记住', '--exact')
  const secondFrequent = await studyTerm(browser, firstFrequent)
  await browser('reload')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', secondFrequent)
  const frequentSaved = JSON.parse(await browser('eval', `(async()=>{const r=await fetch('/api/vocab/frequent?bank_id=1&mastered=true',{headers:{Authorization:'Bearer '+localStorage.getItem('token'),'X-Exam-Slug':'current'}});return(await r.json()).items.map(w=>({term:w.term,mastered:w.is_mastered}))})()`))
  assert.deepEqual(frequentSaved, [{ term: firstFrequent, mastered: true }])
  const frequentContent = JSON.parse(await browser('eval', `(async()=>{
    const r=await fetch('/api/vocab/study/items',{method:'POST',headers:{Authorization:'Bearer '+localStorage.getItem('token'),'X-Exam-Slug':'current','Content-Type':'application/json'},body:JSON.stringify({scope:'frequent',bank_id:1,refs:[{term:${JSON.stringify(firstFrequent)}}]})});return(await r.json()).results[0].content;
  })()`))
  assert.equal(frequentContent.term_zh, `刷新后的 ${firstFrequent} 中文`)
  assert.equal(frequentContent.definition, `A refreshed English definition for ${firstFrequent}.`)
  assert.equal(frequentContent.definition_zh, `刷新后的 ${firstFrequent} 中文释义。`)
  await browser('find', 'role', 'link', 'click', '--name', '退出学习')
  await browser('wait', '--text', '选择词汇来源')
  await browser('find', 'role', 'button', 'click', '--name', 'Current', '--exact')
  await browser('find', 'role', 'menuitem', 'click', '--name', 'Other Other', '--exact')
  await browser('wait', '--url', '**/other/vocab')
  await browser('find', 'role', 'button', 'click', '--name', '学习我的单词本')
  await browser('wait', '--text', '继续上轮')
  await browser('find', 'role', 'button', 'click', '--name', '继续上轮')
  await browser('wait', '--text', second)
  assert.match(await browser('get', 'text', '.study-header'), /第 2 \/ 3 个词/)
})
