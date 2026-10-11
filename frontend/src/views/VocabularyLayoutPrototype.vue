<!-- PROTOTYPE：同一 /exams/:examSlug/vocab 路由的 A/B/C 布局，只用于讨论，不合并产品。 -->
<template>
  <div v-if="prototypeEnabled" class="vocab-prototype" :class="[`variant-${variant}`, { immersion: immersive }]">
    <section v-if="screen === 'overview'" class="overview">
      <div class="overview-heading">
        <div><h1>单词本</h1><p class="muted">选择一个词库，开始这一轮学习</p></div>
        <button class="plain-button" @click="navigate({ screen: 'manage', source: 'personal' })">管理词汇</button>
      </div>
      <div class="source-grid">
        <article v-for="source in sources" :key="source.key" class="source-card">
          <button :data-source="source.key" class="source-entry" @click="start(source.key)">
            <span class="source-top"><component :is="source.icon" class="icon" /><ArrowUpRightIcon class="icon muted" /></span>
            <span class="source-name">{{ source.name }}</span>
            <span class="source-count">{{ source.count }}<span class="muted"> 个词</span></span>
            <span class="source-description muted">{{ source.description }}</span>
            <span class="source-start">开始学习 <ArrowRightIcon class="icon" /></span>
          </button>
          <label v-if="source.key === 'frequent'" class="bank-choice">题库
            <select v-model="bankId" aria-label="高频词题库"><option v-for="bank in banks" :key="bank.id" :value="bank.id">{{ bank.name }}</option></select>
          </label>
        </article>
      </div>
      <p class="prototype-note">布局原型 · 内容和数量均为演示，不会写入单词本</p>
    </section>

    <section v-else-if="screen === 'manage'" class="management">
      <header class="manage-heading"><button class="plain-button" @click="navigate({ screen: 'overview' })"><ArrowLeftIcon class="icon" />来源概览</button><h1>管理词汇</h1></header>
      <div class="manage-tabs"><button v-for="source in sources" :key="source.key" class="plain-button" :class="{ selected: sourceKey === source.key }" @click="navigate({ source: source.key })">{{ source.name }}</button></div>
      <label class="search-label">查找单词<input v-model="search" placeholder="输入英文或中文" /></label>
      <div class="manage-heading"><p class="muted">{{ sourceName }} · {{ filteredWords.length }} 个演示词</p><button class="plain-button" @click="notice = '这里只验证添加入口，不执行真实添加。'">添加单词</button></div>
      <div v-for="word in filteredWords" :key="word.id || word.term" class="manage-row"><div><strong>{{ word.term }}</strong><p class="muted">{{ word.term_zh || '暂无中文翻译' }}</p></div><button class="plain-button" @click="notice = '这里只验证删除入口，不执行真实删除。'">删除</button></div>
      <p v-if="notice" role="status">{{ notice }}</p>
      <button class="primary-button" @click="start(sourceKey)">学习这个词库</button>
      <p class="prototype-note">管理入口布局示意；添加、删除、搜索规则仍沿用已有能力。</p>
    </section>

    <section v-else class="study-shell" :class="{ 'reading-layout': variant === 'C' }">
      <header class="study-header">
        <button aria-label="退出学习，返回来源概览" class="icon-button" @click="navigate({ screen: 'overview' })"><XMarkIcon class="icon" /></button>
        <div class="study-title"><p>{{ sourceName }}</p><p class="muted subtitle">{{ sourceKey === 'frequent' ? bankName : '单词卡学习' }}</p></div>
        <span class="position" aria-label="卡片位置" aria-live="polite">{{ screen === 'result' ? deck.length : index + 1 }} / {{ deck.length }}</span>
      </header>

      <template v-if="screen === 'study' && currentWord">
        <div class="position-track" aria-hidden="true"><span :style="{ width: `${((index + 1) / deck.length) * 100}%` }" /></div>
        <div class="study-content">
          <aside v-if="variant === 'B'" class="study-rail"><p class="rail-heading">本轮标记</p><p class="rail-item"><span>未记住</span><strong>{{ unremembered }}</strong></p><p class="rail-item"><span>已记住</span><strong>{{ remembered }}</strong></p><p class="rail-note muted">滑动只切词</p></aside>
          <div class="card-stage">
            <div v-if="variant === 'C'" class="reading-heading"><span class="muted">当前单词</span><strong>{{ currentWord.term }}</strong></div>
            <div class="flashcard" :class="{ flipped }">
              <div class="card-meta"><span>{{ flipped ? '中文释义' : '英文单词' }}</span><span v-if="currentWord.frequency">出现 {{ currentWord.frequency }} 次</span><span v-else-if="currentMark !== undefined">{{ currentMark ? '已记住' : '未记住' }}</span></div>
              <button ref="faceRef" class="card-face" :class="{ 'long-face': flipped && isLong }" :aria-label="flipped ? '查看英文单词' : '翻面，查看中文释义'"
                @click="flip" @pointerdown="pointerStart" @pointerup="pointerEnd" @pointercancel="pointer = null">
                <template v-if="!flipped"><span class="term">{{ currentWord.term }}</span></template>
                <template v-else>
                  <span v-if="variant === 'B'" class="back-term">{{ currentWord.term }}</span>
                  <span v-if="currentWord.term_zh" class="translation">{{ currentWord.term_zh }}</span>
                  <span v-if="currentWord.definition_zh" class="definition">{{ currentWord.definition_zh }}</span>
                  <template v-if="!currentWord.term_zh && !currentWord.definition_zh"><span class="translation">暂无中文内容</span><span class="definition muted">{{ currentWord.definition || '此词尚未提供中文翻译。' }}</span></template>
                </template>
              </button>
              <div class="card-hint"><ArrowPathIcon class="small-icon" /><span>{{ flipped ? '点击返回英文 · 纵向滚动阅读' : '点击卡片，查看中文' }}</span></div>
            </div>
          </div>
        </div>
        <footer class="study-actions">
          <div class="mark-actions"><button data-action="unremembered" class="mark-button unremembered" @click="mark(false)"><XMarkIcon class="icon" />未记住</button><button data-action="remembered" class="mark-button remembered" @click="mark(true)"><CheckIcon class="icon" />已记住</button></div>
          <div class="navigation-actions"><button class="plain-button" :disabled="index === 0" @click="move(-1)"><ChevronLeftIcon class="icon" />上一张</button><span class="muted navigation-hint">左右滑动只切词</span><button class="plain-button" :disabled="index === deck.length - 1" @click="move(1)">下一张<ChevronRightIcon class="icon" /></button></div>
        </footer>
      </template>

      <div v-else-if="screen === 'result'" class="result-content">
        <CheckCircleIcon class="result-icon" /><h1>这一轮结束了</h1><p class="muted">{{ sourceName }}</p>
        <div class="result-counts"><p><strong>{{ remembered }}</strong><span>已记住</span></p><p><strong>{{ unremembered }}</strong><span>未记住</span></p></div>
        <button class="primary-button" :disabled="unremembered === 0" @click="retry">再练未记住的词</button><button class="plain-button" @click="navigate({ screen: 'overview' })">返回来源概览</button>
        <p class="prototype-note">结束页布局示意；统计和再练队列规则在后续决策票确认。</p>
      </div>
    </section>

    <div class="prototype-switcher" :class="{ 'over-navigation': !immersive }" aria-label="布局原型切换">
      <button class="switch-button" aria-label="上一个布局方案" @click="switchVariant(-1)"><ChevronLeftIcon class="icon" /></button>
      <span class="variant-label">原型 {{ variant }} · {{ variantNames[variant] }}</span>
      <button class="switch-button" aria-label="下一个布局方案" @click="switchVariant(1)"><ChevronRightIcon class="icon" /></button>
      <details class="scenario-menu"><summary>场景</summary><div class="scenario-panel">
        <label>预览场景<select :value="scenario" @change="changeScenario($event.target.value)"><option value="normal">正常卡片</option><option value="long">长释义</option><option value="missing">缺中文</option><option value="result">结束页</option><option value="overview">来源入口</option><option value="manage">管理入口</option></select></label>
        <button class="plain-button" @click="toggleTheme">切换明暗主题</button>
        <p class="prototype-note">{{ screen }} · {{ sourceKey }} · {{ index + 1 }}/{{ deck.length }} · {{ flipped ? '背面' : '正面' }} · 标记 {{ Object.keys(marks).length }} 张</p>
        <p class="prototype-note">仅布局演示，轮次／恢复规则尚未定案。</p>
      </div></details>
    </div>
  </div>
  <p v-else>此原型仅在 npm run prototype:vocab 开发模式下可用。</p>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '../api/client'
import { useDarkMode } from '../composables/useDarkMode'
import { BookOpenIcon, BookmarkIcon, ChartBarIcon, ArrowUpRightIcon, ArrowRightIcon, ArrowLeftIcon, XMarkIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, ArrowPathIcon, CheckCircleIcon } from '@heroicons/vue/24/outline'

const prototypeEnabled = import.meta.env.DEV && import.meta.env.VITE_VOCAB_PROTOTYPE === '1'
const route = useRoute()
const router = useRouter()
const theme = useDarkMode()
const variantNames = { A: '大卡片', B: '学习侧栏', C: '阅读优先' }
const variant = computed(() => variantNames[route.query.variant] ? route.query.variant : 'A')
const screen = computed(() => ['study', 'result', 'manage'].includes(route.query.screen) ? route.query.screen : 'overview')
const immersive = computed(() => ['study', 'result'].includes(screen.value))
const sourceKey = computed(() => ['personal', 'frequent'].includes(route.query.source) ? route.query.source : 'exam_personal')
const words = ref({ exam_personal: [], personal: [], frequent: [] })
const banks = ref([])
const bankId = ref(7)
const index = ref(0)
const flipped = ref(false)
const marks = ref({})
const retryWords = ref(null)
const search = ref('')
const notice = ref('')
const faceRef = ref(null)
let pointer = null
let suppressFlip = false
const sources = computed(() => [
  { key: 'exam_personal', name: '项目词汇', count: words.value.exam_personal.length, description: '当前考试项目的核心术语', icon: BookOpenIcon },
  { key: 'personal', name: '我的单词本', count: words.value.personal.length, description: '手动添加与答题收藏的单词', icon: BookmarkIcon },
  { key: 'frequent', name: '高频词汇', count: words.value.frequent.length, description: '所选题库中经常出现的词', icon: ChartBarIcon },
])
const sourceName = computed(() => sources.value.find(source => source.key === sourceKey.value)?.name)
const bankName = computed(() => banks.value.find(bank => bank.id === Number(bankId.value))?.name)
const deck = computed(() => retryWords.value || words.value[sourceKey.value])
const currentWord = computed(() => deck.value[index.value])
const currentMark = computed(() => marks.value[index.value])
const remembered = computed(() => Object.values(marks.value).filter(value => value === true).length)
const unremembered = computed(() => Object.values(marks.value).filter(value => value === false).length)
const isLong = computed(() => (currentWord.value?.definition_zh?.length || 0) > 300)
const filteredWords = computed(() => deck.value.filter(word => `${word.term} ${word.term_zh || ''}`.toLowerCase().includes(search.value.toLowerCase())))
const scenario = computed(() => screen.value === 'study' ? route.query.sample || 'normal' : screen.value)

function navigate(query) { return router.replace({ query: { ...route.query, ...query } }) }
function start(source) {
  retryWords.value = null
  index.value = 0
  marks.value = {}
  flipped.value = false
  navigate({ source, screen: 'study', sample: 'normal' })
}
function retry() {
  const nextDeck = deck.value.filter((word, position) => marks.value[position] === false)
  if (!nextDeck.length) return
  retryWords.value = nextDeck
  index.value = 0
  marks.value = {}
  flipped.value = false
  navigate({ screen: 'study', sample: 'normal' })
}
function move(direction) {
  const next = index.value + direction
  if (next < 0 || next >= deck.value.length) return
  index.value = next
  flipped.value = false
  nextTick(() => faceRef.value?.scrollTo(0, 0))
}
function flip() {
  if (suppressFlip) { suppressFlip = false; return }
  flipped.value = !flipped.value
  nextTick(() => faceRef.value?.scrollTo(0, 0))
}
function mark(value) {
  marks.value[index.value] = value // 仅内存演示，绝不调用掌握 API。
  if (index.value < deck.value.length - 1) move(1)
  else navigate({ screen: 'result' })
}
function pointerStart(event) {
  suppressFlip = false
  pointer = { x: event.clientX, y: event.clientY, scroll: faceRef.value?.scrollTop || 0 }
}
function pointerEnd(event) {
  if (!pointer) return
  const dx = event.clientX - pointer.x
  const dy = event.clientY - pointer.y
  const scrolled = Math.abs((faceRef.value?.scrollTop || 0) - pointer.scroll) > 5
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5 && !scrolled) {
    suppressFlip = true
    move(dx < 0 ? 1 : -1)
  } else if (Math.abs(dy) > 15 || scrolled) suppressFlip = true
  pointer = null
}
function switchVariant(direction) {
  const keys = ['A', 'B', 'C']
  navigate({ variant: keys[(keys.indexOf(variant.value) + direction + keys.length) % keys.length] })
}
function keyboard(event) {
  if (event.target.closest('input,textarea,select,[contenteditable],button,summary')) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    switchVariant(event.key === 'ArrowLeft' ? -1 : 1)
  }
}
function toggleTheme() { theme.toggle() }
function applyScenario() {
  if (route.query.sample === 'long' || route.query.sample === 'missing') {
    const found = deck.value.findIndex(word => route.query.sample === 'long' ? (word.definition_zh?.length || 0) > 300 : !word.term_zh)
    index.value = Math.max(0, found)
    flipped.value = true
  }
}
function changeScenario(value) {
  retryWords.value = null
  if (['long', 'missing'].includes(value)) navigate({ screen: 'study', source: 'exam_personal', sample: value })
  else if (value === 'normal') { index.value = 0; flipped.value = false; navigate({ screen: 'study', sample: 'normal' }) }
  else if (value === 'result') { marks.value = { 0: true, 1: false }; navigate({ screen: 'result' }) }
  else navigate({ screen: value })
}
watch(() => [route.query.sample, route.query.source], applyScenario)
watch(bankId, async value => {
  const res = await client.get('/vocab/frequent', { params: { bank_id: value } })
  words.value.frequent = res.data.items
})
onMounted(async () => {
  if (!prototypeEnabled) return
  const [project, personal, frequent, bankResponse] = await Promise.all([
    client.get('/vocab', { params: { scope: 'exam_personal' } }),
    client.get('/vocab', { params: { scope: 'personal' } }),
    client.get('/vocab/frequent', { params: { bank_id: bankId.value } }),
    client.get('/banks'),
  ])
  words.value = { exam_personal: project.data.items, personal: personal.data.items, frequent: frequent.data.items }
  banks.value = bankResponse.data
  applyScenario()
  document.addEventListener('keydown', keyboard)
})
onUnmounted(() => document.removeEventListener('keydown', keyboard))
</script>

<style scoped>
.vocab-prototype { --surface: #fff; --ink: #182335; --muted: #64748b; --border: #e2e8f0; --base: #f8fafc; --accent: var(--color-primary-600); color: var(--ink); }
:global(.dark) .vocab-prototype { --surface: #1e293b; --ink: #f1f5f9; --muted: #a9b7c9; --border: #475569; --base: #0f172a; --accent: var(--color-primary-400); }
h1 { font-size: 24px; font-weight: 700; } p { margin: 0; } button { cursor: pointer; } button:disabled { cursor: default; opacity: .35; }
button:focus-visible, summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.muted, .prototype-note { color: var(--muted); } .icon { width: 22px; height: 22px; flex-shrink: 0; } .small-icon { width: 16px; height: 16px; }
.plain-button, .icon-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 48px; padding: 0 12px; border-radius: 8px; background: transparent; font-size: 14px; }
.icon-button { min-width: 48px; padding: 0; } .plain-button:hover:not(:disabled), .icon-button:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); }
.primary-button { min-height: 52px; padding: 10px 24px; border-radius: 10px; background: var(--color-primary-600); color: #fff; font-weight: 600; }
.overview-heading, .manage-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
.overview-heading p { margin-top: 6px; font-size: 14px; } .source-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.source-card { min-width: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; }
.source-entry { width: 100%; padding: 24px; display: flex; flex-direction: column; gap: 12px; text-align: left; border-radius: 16px; }
.source-entry:hover { background: color-mix(in srgb, var(--accent) 4%, var(--surface)); } .source-top { display: flex; justify-content: space-between; color: var(--accent); }
.source-name { font-size: 18px; font-weight: 600; } .source-count { font-size: 30px; font-weight: 600; } .source-count .muted { font-size: 14px; font-weight: 400; }
.source-description { font-size: 13px; } .source-start { display: flex; align-items: center; gap: 8px; color: var(--accent); font-size: 14px; font-weight: 600; margin-top: 4px; }
.bank-choice { display: grid; gap: 4px; margin: 0 24px 16px; font-size: 12px; color: var(--muted); } select, input { min-height: 48px; min-width: 0; width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 8px; color: var(--ink); font-size: 16px; }
.prototype-note { margin-top: 24px; font-size: 12px; line-height: 1.6; } .management { max-width: 720px; margin: auto; } .manage-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
.selected { color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); } .search-label { display: grid; gap: 8px; margin-bottom: 16px; }
.manage-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 0; border-bottom: 1px solid var(--border); } .manage-row strong { overflow-wrap: anywhere; } .manage-row .muted { font-size: 14px; margin-top: 6px; }
.management .primary-button { margin-top: 24px; } .study-shell { max-width: 720px; margin: auto; display: flex; flex-direction: column; }
.study-header { display: flex; gap: 12px; align-items: center; min-height: 64px; } .study-title { flex: 1; min-width: 0; font-weight: 600; } .subtitle { font-size: 12px; font-weight: 400; margin-top: 3px; } .position { font-size: 14px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.position-track { height: 3px; background: var(--border); margin: 12px 0 24px; } .position-track span { display: block; height: 100%; background: var(--accent); }
.study-content { min-height: 0; flex: 1; display: flex; gap: 20px; } .card-stage { min-width: 0; flex: 1; max-width: 640px; margin: auto; width: 100%; }
.flashcard { min-width: 0; height: 420px; display: flex; flex-direction: column; overflow: hidden; background: var(--surface); border: 1px solid var(--border); border-radius: 20px; box-shadow: 0 4px 16px rgb(0 0 0 / .035); }
.card-meta { display: flex; justify-content: space-between; gap: 8px; padding: 20px 24px 0; font-size: 12px; color: var(--muted); }
.card-face { flex: 1; min-height: 0; padding: 28px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; overflow: auto; overflow-wrap: anywhere; white-space: pre-line; text-align: center; touch-action: pan-y; }
.term { font-size: clamp(24px, 4vw, 36px); font-weight: 600; line-height: 1.35; } .translation { display: block; font-size: 28px; font-weight: 600; line-height: 1.45; }
.definition { display: block; font-size: 17px; line-height: 1.85; text-align: left; } .long-face { justify-content: flex-start; align-items: stretch; text-align: left; } .card-hint { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 16px; font-size: 12px; color: var(--muted); }
.study-actions { max-width: 640px; width: 100%; margin: 24px auto 72px; } .mark-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.mark-button { display: flex; align-items: center; justify-content: center; min-height: 56px; gap: 8px; font-weight: 600; border-radius: 12px; }
.unremembered { color: #9a3412; background: #fff0e4; border: 1px solid #fed7aa; } .remembered { color: #fff; background: #087f65; border: 1px solid #087f65; }
:global(.dark) .unremembered { color: #ffcfad; background: #4d2716; border-color: #824a2c; } :global(.dark) .remembered { background: #0c806a; border-color: #0c806a; }
.navigation-actions { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-top: 8px; } .navigation-actions .plain-button { padding: 0 8px; } .navigation-hint { font-size: 12px; }
.study-rail { display: flex; flex-direction: column; gap: 16px; width: 132px; flex-shrink: 0; padding: 28px 12px 0 0; } .rail-heading { font-size: 13px; color: var(--muted); } .rail-item { display: grid; gap: 8px; font-size: 14px; } .rail-item strong { font-size: 28px; } .rail-note { font-size: 12px; margin-top: auto; }
.variant-B .flashcard { border-radius: 12px; } .variant-B .card-face { align-items: stretch; text-align: left; } .back-term { color: var(--muted); font-size: 16px; }
.reading-heading { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 20px; font-size: 14px; } .reading-heading strong { text-align: right; max-width: 72%; overflow-wrap: anywhere; }
.variant-C .flashcard { height: 340px; border-radius: 12px; box-shadow: none; } .variant-C .card-face { align-items: stretch; justify-content: flex-start; text-align: left; padding-top: 32px; }
.variant-C .study-content { align-items: flex-start; } .variant-C .card-stage { margin-top: 20px; } .variant-C .card-hint { justify-content: flex-start; padding-left: 28px; border-top: 1px solid var(--border); }
.result-content { min-height: 500px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; text-align: center; padding: 24px 16px 88px; }
.result-icon { height: 56px; width: 56px; color: #087f65; } .result-counts { display: flex; gap: 64px; margin: 16px 0; } .result-counts p { display: grid; gap: 8px; } .result-counts strong { font-size: 32px; } .result-counts span { font-size: 14px; color: var(--muted); }
.result-content .prototype-note { max-width: 320px; margin-top: 8px; }
.prototype-switcher { position: fixed; bottom: max(12px, env(safe-area-inset-bottom, 0px)); left: 50%; transform: translateX(-50%); display: flex; align-items: center; width: calc(100% - 24px); max-width: 360px; background: #182335; color: #fff; border-radius: 12px; padding: 4px; z-index: 100; box-shadow: 0 4px 12px rgb(0 0 0 / .15); }
.switch-button { min-width: 48px; height: 48px; display: grid; place-items: center; border-radius: 8px; } .switch-button:hover, .scenario-menu summary:hover { background: rgb(255 255 255 / .12); }
.variant-label { flex: 1; min-width: 0; font-size: 12px; text-align: center; } .scenario-menu summary { list-style: none; min-width: 48px; height: 48px; display: grid; place-items: center; cursor: pointer; font-size: 12px; border-left: 1px solid #475569; }
.scenario-panel { position: absolute; bottom: 68px; left: 0; right: 0; padding: 16px; background: var(--surface); color: var(--ink); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 6px 24px rgb(0 0 0 / .2); }
.scenario-panel label { display: grid; gap: 8px; font-size: 14px; } .scenario-panel .prototype-note { margin-top: 8px; }
@media (min-width: 768px) { .study-shell { min-height: 640px; } .variant-C .study-actions { margin-top: 16px; } }
@media (max-width: 767px) {
  .source-grid { grid-template-columns: 1fr; gap: 12px; } .source-entry { padding: 20px; gap: 8px; } .source-entry .source-top { float: right; } .source-count { font-size: 24px; } .source-description { font-size: 13px; } .source-start { margin-top: 8px; }
  .bank-choice { margin-left: 20px; margin-right: 20px; } .overview { padding-bottom: 80px; } .management { padding-bottom: 80px; }
  .prototype-switcher.over-navigation { bottom: calc(76px + env(safe-area-inset-bottom, 0px)); }
  .immersion { height: 100dvh; background: var(--base); } .study-shell { height: 100%; padding: max(8px, env(safe-area-inset-top, 0px)) max(16px, env(safe-area-inset-right, 0px)) 0 max(16px, env(safe-area-inset-left, 0px)); }
  .study-header { min-height: 60px; gap: 8px; } .study-title { font-size: 15px; } .study-header .subtitle { max-width: 190px; overflow-wrap: anywhere; }
  .position-track { margin: 8px 0 16px; } .study-content { overflow: hidden; padding: 0 2px; } .card-stage { height: 100%; display: flex; flex-direction: column; }
  .flashcard { height: 100%; min-height: 0; } .card-meta { padding: 18px 20px 0; } .card-face { padding: 24px; gap: 16px; } .translation { font-size: 25px; } .definition { font-size: 16px; }
  .card-hint { padding: 12px 8px; } .study-actions { flex-shrink: 0; margin: 16px 0 calc(76px + env(safe-area-inset-bottom, 0px)); } .mark-button { min-height: 56px; } .navigation-actions { gap: 2px; } .navigation-actions .plain-button { font-size: 13px; }
  .variant-B .study-content { flex-direction: column; gap: 12px; } .study-rail { flex-direction: row; justify-content: space-around; width: 100%; padding: 0; gap: 12px; }
  .rail-item { display: flex; align-items: baseline; gap: 8px; } .rail-item strong { font-size: 20px; } .rail-heading, .rail-note { display: none; }
  .variant-C .study-content { align-items: stretch; } .variant-C .card-stage { margin-top: 0; } .reading-heading { font-size: 13px; margin-bottom: 12px; flex-shrink: 0; } .variant-C .flashcard { height: 100%; }
  .result-content { flex: 1; min-height: 0; padding-bottom: 80px; }
}
@media (max-width: 359px) { .navigation-hint { display: none; } .term { font-size: 24px; } .card-face { padding: 20px; } .study-header .subtitle { font-size: 11px; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; animation: none !important; } }
</style>
