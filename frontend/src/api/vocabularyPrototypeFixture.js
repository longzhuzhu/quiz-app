// PROTOTYPE：演示内容。仅拦截独立开发端口上的请求，不接真实后端。
const exampleExam = { id: 55, slug: 'prototype', name: '隐私认证备考 · 演示', short_name: '演示项目' }
export const prototypeBanks = [
  { id: 7, name: '隐私基础 · 演示题库' },
  { id: 8, name: '数据安全 · 演示题库' },
]
const longDefinition = '这是用于验证长内容阅读的演示释义，不是考试资料。隐私影响评估需要结合具体业务场景，梳理哪些信息被收集、为什么需要这些信息、信息会在何处处理，以及谁可以访问。评估还应考虑个人可能受到的影响、需要向个人说明的事项，以及相关风险可以怎样降低。\n\n在产品设计阶段，团队可以逐项检查收集、存储、使用、共享和删除等环节，记录每一环节的目的、参与者和保护措施。遇到无法确认的问题时，应明确记录问题及负责人，而不是把未知情况当作已经安全。\n\n在后续审查中，可以进一步对照业务变化、数据流转路径、访问控制和保留安排，检查最初的假设是否仍然成立。评估结果需要让参与者能够理解，并支持对关键取舍进行追踪。\n\n本段仅为了拉长卡片背面，验证纵向滚动时操作按钮仍然可见、横向切卡不会误触，以及较小屏幕下的阅读密度。'.repeat(2)
export const prototypeVocabulary = {
  exam_personal: [
    { id: 1, term: 'Access Control', term_zh: '访问控制', definition_zh: '用于决定哪些主体可以访问资源，以及可以执行哪些操作。演示内容。' },
    { id: 2, term: 'Data Minimization', term_zh: '数据最小化', definition_zh: '仅收集和处理实现特定目的所需的信息。演示内容。' },
    { id: 3, term: 'Privacy Impact Assessment', term_zh: '隐私影响评估', definition_zh: longDefinition },
    { id: 4, term: 'Contextual Integrity', term_zh: null, definition: 'An untranslated entry for testing the missing-content layout.' },
  ],
  personal: [
    { id: 11, term: 'Accountability', term_zh: '问责', definition_zh: '对职责的履行承担责任，并能够说明如何履行职责。演示内容。' },
    { id: 12, term: 'Consent', term_zh: '同意', definition_zh: '个人对特定信息处理活动作出的意愿表达。演示内容。' },
    { id: 13, term: 'Data Retention', term_zh: '数据保留', definition_zh: '围绕明确目的决定信息保存的时间及到期后的处理。演示内容。' },
  ],
  frequent: [
    { term: 'privacy', term_zh: '隐私', frequency: 86 },
    { term: 'processing', term_zh: '处理', frequency: 42 },
    { term: 'controller', term_zh: null, frequency: 25 },
  ],
}

export function installVocabularyPrototypeFixture(client) {
  if (!import.meta.env.DEV || import.meta.env.VITE_VOCAB_PROTOTYPE !== '1') return
  const user = { id: 55, username: '原型评审', is_admin: false, active_exam: exampleExam }
  localStorage.setItem('token', 'prototype-not-a-real-token')
  localStorage.setItem('user', JSON.stringify(user))
  window.__vocabPrototypeRequests = []
  client.defaults.adapter = async config => {
    const method = (config.method || 'get').toLowerCase()
    window.__vocabPrototypeRequests.push({ method, url: config.url })
    if (method !== 'get') throw new Error('PROTOTYPE: real mutations are disabled')
    let data
    if (config.url === '/auth/me') data = user
    else if (config.url === '/exams') data = { items: [exampleExam] }
    else if (config.url === '/banks') data = prototypeBanks
    else if (config.url === '/vocab/stats') data = { exam_personal: 4, personal: 3, all: 7 }
    else if (config.url === '/vocab') data = { items: prototypeVocabulary[config.params.scope], pagination: { total_pages: 1 } }
    else if (config.url === '/vocab/frequent') data = { items: prototypeVocabulary.frequent, summary: { total_terms: 3 } }
    else throw new Error(`PROTOTYPE: unsupported request ${config.url}`)
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }
}
