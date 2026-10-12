<template>
  <section class="study-screen" aria-labelledby="study-title">
    <header class="study-header">
      <router-link :to="overviewPath" aria-label="退出学习" class="study-touch inline-flex items-center justify-center rounded-button text-gray-600 dark:text-gray-300"><ArrowLeftIcon class="h-6 w-6" aria-hidden="true" /></router-link>
      <div class="min-w-0 flex-1"><h1 id="study-title" class="break-words text-lg font-semibold text-gray-900 dark:text-white">{{ sourceLabel }}</h1><p class="text-xs text-gray-500 dark:text-gray-400">{{ scopeLabel }}<span v-if="params?.context.scope === 'frequent'"> · 题库 {{ params.context.bank_id }}</span></p></div>
      <router-link :to="manageLink" aria-label="管理词汇" class="study-touch inline-flex items-center justify-center rounded-button px-2 text-sm text-gray-500 dark:text-gray-400"><span class="sm:hidden">管理</span><span class="hidden sm:inline">管理词汇</span></router-link>
      <div v-if="state?.manifest" class="col-span-3 flex flex-wrap justify-between gap-x-3 gap-y-1 text-sm tabular-nums text-gray-500 dark:text-gray-400">
        <span aria-live="polite">{{ state.phase === 'studying' && wordProgress ? `第 ${wordProgress} / ${state.counts.available} 个词` : `本轮 · ${state.counts.available} 个词` }}</span><span>{{ state.counts.available ? Math.round(wordProgress / state.counts.available * 100) : 0 }}%</span>
        <progress class="study-progress w-full" :value="wordProgress" :max="state.counts.available || 1" aria-label="本轮单词位置进度" :aria-valuetext="`第 ${wordProgress} 个，共 ${state.counts.available} 个词`" />
      </div>
    </header>
    <div v-if="parameterError || state?.warning || state?.error || state?.refreshError || state?.verificationError || state?.uncertain || state?.counts.unavailable || state?.contextChanging" class="study-notices">
      <p v-if="state?.contextChanging" role="status">正在切换考试项目，已暂停学习操作。</p>
      <p v-if="parameterError" role="alert">{{ parameterError }}</p>
      <p v-if="state?.warning" role="status">{{ state.warning }}</p>
      <p v-if="state?.counts.unavailable" role="status">原卡组 {{ state.counts.original }} 词，其中 {{ state.counts.unavailable }} 词已删除、排除或不再可见，已从本轮排除。</p>
      <p v-if="state?.uncertain" role="status">上次保存结果未确认，未计为新的成功判断。{{ state.uncertain.mastered === null ? '请核验服务器状态后重新判断。' : `服务器当前为${state.uncertain.mastered ? '已掌握' : '未掌握'}，请重新确认。` }}</p>
      <BaseButton v-if="state?.uncertain" variant="secondary" class="study-touch mt-2" :disabled="state.busy || state.loading" @click="study.returnToPending()">返回待确认词</BaseButton>
      <p v-if="state?.error || state?.verificationError" role="alert">{{ state.error || state.verificationError }}</p>
      <p v-if="state?.refreshError" role="alert">{{ state.refreshError }}</p>
      <BaseButton v-if="state && (state.error || state.verificationError || state.uncertain?.mastered === null) && !['invalid','blocked','handed-off','error'].includes(state.phase)" variant="secondary" class="study-touch mt-2" :disabled="state.busy || state.loading" @click="study.retry()">核验／重试</BaseButton>
    </div>
    <template v-if="state?.phase === 'studying'">
      <VocabularyStudyCard :item="state.current" :identity="state.currentKey" :position="state.position" :flipped="state.flipped" :loading="state.loading" :disabled="state.busy" @flip="study.flip()" @navigate="study.navigate" @transition="cardTransitioning = $event" />
      <footer class="study-actions">
        <div class="flex items-center justify-between gap-2">
          <BaseButton variant="ghost" class="study-touch" :disabled="state.busy || !state.canPrevious" @click="study.navigate(-1)"><ChevronLeftIcon class="h-5 w-5" aria-hidden="true" />上一张</BaseButton>
          <BaseButton variant="ghost" class="study-touch" title="AI 刷新中文翻译及中英文释义" :aria-busy="state.refreshing" :disabled="!state.canRefresh || cardTransitioning" @click="study.refresh()"><ArrowPathIcon class="h-5 w-5" aria-hidden="true" />刷新</BaseButton>
          <BaseButton variant="ghost" class="study-touch" :disabled="state.busy" @click="study.navigate(1)">{{ state.position === state.counts.available ? '查看小结' : '下一张' }}<ChevronRightIcon class="h-5 w-5" aria-hidden="true" /></BaseButton>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <BaseButton variant="secondary" class="study-judge" :disabled="!state.canJudge || cardTransitioning" @click="study.judge(false)"><XMarkIcon class="h-5 w-5" aria-hidden="true" />未记住</BaseButton>
          <BaseButton class="study-judge" :disabled="!state.canJudge || cardTransitioning" @click="study.judge(true)"><CheckIcon class="h-5 w-5" aria-hidden="true" />已记住</BaseButton>
        </div>
        <p v-if="state.saving" role="status" class="text-center text-xs text-gray-500 dark:text-gray-400">正在保存，成功后进入下一词…</p>
        <p v-if="state.refreshPending || state.refreshMessage" role="status" class="text-center text-xs text-gray-500 dark:text-gray-400">{{ state.refreshPending ? (state.refreshing ? '正在用 AI 刷新翻译与中英文释义…' : '其他词条正在刷新，可继续学习。') : state.refreshMessage }}</p>
      </footer>
    </template>
    <div v-else class="study-message rounded-card-lg border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
      <template v-if="state?.phase === 'resume'">
        <h2 class="mb-3 text-xl font-semibold text-gray-900 dark:text-white">有一轮尚未结束</h2><p class="mb-6 text-gray-500 dark:text-gray-400">上轮 {{ state.resumeInfo.total }} 词 · {{ ROUND_LABELS[state.resumeInfo.kind] || MASTERY_LABELS[state.resumeInfo.mastery] }}。继续保留原卡组与已确认结果；重新开始按当前范围选词，不清空长期掌握。</p>
        <BaseButton class="study-touch mr-2" @click="study.continueRound()">继续上轮</BaseButton><BaseButton variant="secondary" class="study-touch" @click="study.restart()">重新开始</BaseButton>
      </template>
      <template v-else-if="state?.phase === 'summary'">
        <h2 ref="summaryTitle" tabindex="-1" class="mb-3 text-2xl font-bold text-gray-900 dark:text-white">{{ state.complete ? '本轮完成' : '本轮小结' }}</h2>
        <p class="mb-6 text-sm text-gray-500 dark:text-gray-400">{{ state.counts.available === 0 ? (state.counts.unavailable ? '本轮词条已全部不可用，不计为完成。' : '当前范围没有词，本轮不计为完成。') : state.complete ? '每个词都已成功判断，完成不等于全部掌握。' : '仍有未标记词，浏览到末张不代表学习完成。' }}</p>
        <dl class="mb-6 grid grid-cols-3 gap-2">
          <div v-for="entry in [['remembered','已记住'],['forgotten','未记住'],['unmarked','未标记']]" :key="entry[0]" class="rounded-card bg-slate-50 p-3 dark:bg-slate-900"><dt class="text-sm text-gray-500 dark:text-gray-400">{{ entry[1] }}</dt><dd class="mt-2 text-3xl font-bold tabular-nums text-gray-900 dark:text-white">{{ state.counts[entry[0]] }}</dd></div>
        </dl>
        <div class="flex flex-col gap-3">
          <BaseButton v-if="state.counts.forgotten" class="study-touch" @click="study.repeat('forgotten')">再练未记住的词</BaseButton>
          <BaseButton v-if="state.counts.unmarked" variant="secondary" class="study-touch" @click="study.repeat('unmarked')">补学未标记的词</BaseButton>
          <router-link :to="overviewPath" class="study-touch inline-flex items-center justify-center text-primary-600 dark:text-primary-400">结束并返回来源选择</router-link>
        </div>
      </template>
      <template v-else-if="state?.phase === 'empty'">
        <h2 class="mb-3 text-xl font-semibold text-gray-900 dark:text-white">{{ state.counts.unavailable ? '本轮词条已全部不可用' : '当前范围没有可学词' }}</h2><p class="mb-5 text-gray-500 dark:text-gray-400">不会自动改成另一组词。可切换范围重新开始，或返回管理词汇。</p>
        <div class="flex flex-wrap gap-2"><BaseButton v-for="(label, value) in MASTERY_LABELS" :key="value" variant="secondary" class="study-touch" @click="study.restart(value)">{{ label }}</BaseButton></div>
      </template>
      <template v-else-if="state?.phase === 'blocked'">
        <h2 class="mb-4 text-xl font-semibold text-gray-900 dark:text-white">此轮正在另一标签页学习</h2><BaseButton class="study-touch mr-2" @click="study.takeOver()">请求接管</BaseButton><BaseButton variant="secondary" class="study-touch" @click="study.retry()">原页已关闭，重试</BaseButton>
      </template>
      <template v-else-if="state?.phase === 'handed-off'">
        <h2 class="mb-4 text-xl font-semibold text-gray-900 dark:text-white">学习已交接到另一标签页</h2><p class="text-gray-500 dark:text-gray-400">此页已停止交互，不会覆盖另一页的进度。</p>
      </template>
      <template v-else-if="state?.phase === 'verifying'">
        <h2 class="mb-4 text-xl font-semibold text-gray-900 dark:text-white">{{ state.error ? '小结核验未完成' : '正在核验本轮词条…' }}</h2><p class="text-gray-500 dark:text-gray-400">所有核验成功后才展示小结；不会把部分结果当成全部完成。</p>
      </template>
      <template v-else-if="state?.phase === 'error'">
        <h2 class="mb-4 text-xl font-semibold text-gray-900 dark:text-white">学习暂不可用</h2><BaseButton class="study-touch" @click="study.restart()">重新开始／重试</BaseButton>
      </template>
      <p v-else-if="!parameterError && state?.phase !== 'invalid'" role="status" class="text-gray-500 dark:text-gray-400">正在准备本轮卡组…</p>
      <router-link v-if="parameterError || state?.phase === 'invalid'" :to="overviewPath" class="study-touch inline-flex items-center text-primary-600 dark:text-primary-400">返回来源选择</router-link>
      <router-link v-if="state?.phase === 'invalid'" to="/exams" class="study-touch ml-4 inline-flex items-center text-primary-600 dark:text-primary-400">选择有效考试项目</router-link>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ArrowLeftIcon, ArrowPathIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import BaseButton from '../components/BaseButton.vue'
import VocabularyStudyCard from '../components/VocabularyStudyCard.vue'
import { useAuthStore } from '../stores/auth'
import { useExamStore } from '../stores/exam'
import { examPath } from '../utils/examRoutes'
import { parseStudyParams, MASTERY_LABELS, ROUND_LABELS, SOURCE_LABELS } from '../features/vocabularyStudy/identity.js'
import { createVocabularyStudy } from '../features/vocabularyStudy/study.js'
import { createStudyApi } from '../features/vocabularyStudy/api.js'
import { createBrowserResume } from '../features/vocabularyStudy/resume.js'
import { registerActiveStudy } from '../features/vocabularyStudy/lifecycle.js'

const route = useRoute(), router = useRouter(), auth = useAuthStore(), exams = useExamStore()
const state = shallowRef(null), parameterError = ref(''), summaryTitle = ref(null), params = shallowRef(null)
const cardTransitioning = ref(false)
const wordProgress = computed(() => Math.min(state.value?.position || 0, state.value?.counts.available || 0))
let study = null, unsubscribe = null, unregister = null
const overviewPath = computed(() => examPath(route.params.examSlug, 'vocab'))
const sourceLabel = computed(() => SOURCE_LABELS[params.value?.context.scope] || '单词卡学习')
const scopeLabel = computed(() => ['error','loading'].includes(state.value?.phase)
  ? MASTERY_LABELS[state.value?.requestedMastery] || ''
  : ROUND_LABELS[state.value?.manifest?.kind] || MASTERY_LABELS[state.value?.manifest?.mastery || params.value?.mastery] || '')
const manageLink = computed(() => ({ path: overviewPath.value, query: { mode: 'manage', scope: params.value?.context.scope || 'exam_personal', ...(params.value?.context.bank_id ? { bank_id: String(params.value.context.bank_id) } : {}) } }))
async function initialize(query = route.query, examSlug = String(route.params.examSlug)) {
  parameterError.value = ''; state.value = null
  try {
    params.value = parseStudyParams(query, exams.current?.id)
    const api = createStudyApi({ accountId: auth.user?.id, token: auth.token, examSlug, context: params.value.context })
    study = createVocabularyStudy({ api, resume: createBrowserResume(), accountId: auth.user?.id, ...params.value, isIdentityCurrent: api.isCurrent })
    unregister = registerActiveStudy(study)
    unsubscribe = study.subscribe(value => {
      const previous = state.value?.phase
      state.value = value
      if (value.manifest?.roundId && route.query.round !== value.manifest.roundId && ['studying','summary','empty','verifying'].includes(value.phase))
        router.replace({ query: { ...route.query, round: value.manifest.roundId } }).catch(() => {})
      if (value.phase === 'summary' && previous !== 'summary') nextTick(() => summaryTitle.value?.focus({ preventScroll: true }))
    })
    await study.open({ roundId: params.value.roundId })
  } catch (error) { parameterError.value = error.message }
}
function keydown(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target?.closest?.('input,textarea,select,summary,[contenteditable]:not([contenteditable="false"]),[role="menu"],[role="menuitem"],[role="listbox"],[role="option"],[role="combobox"],.global-navigation') || window.getSelection()?.toString()) return
  if (state.value?.phase === 'studying' && ['ArrowLeft','ArrowRight'].includes(event.key)) { event.preventDefault(); study.navigate(event.key === 'ArrowRight' ? 1 : -1) }
}
function visible() { if (document.visibilityState === 'visible') study?.checkCurrent() }
async function cleanup() { unsubscribe?.(); unregister?.(); await study?.dispose(); unsubscribe = null; unregister = null }
onBeforeRouteLeave(async () => { await study?.leave() })
onBeforeRouteUpdate(async to => {
  if (to.params.examSlug !== route.params.examSlug || to.query.scope !== route.query.scope || to.query.mastery !== route.query.mastery || to.query.bank_id !== route.query.bank_id) {
    await study?.leave(); await cleanup()
  }
})
onMounted(() => { initialize(); window.addEventListener('keydown', keydown); document.addEventListener('visibilitychange', visible) })
onUnmounted(() => { window.removeEventListener('keydown', keydown); document.removeEventListener('visibilitychange', visible); cleanup() })
</script>
