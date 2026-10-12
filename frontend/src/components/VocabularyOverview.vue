<template>
  <section aria-labelledby="vocab-title" :aria-busy="loading">
    <div class="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div><h1 id="vocab-title" class="text-2xl font-bold text-gray-900 dark:text-white">单词本</h1><p class="mt-2 text-gray-500 dark:text-gray-400">选择词汇来源，开始一轮回忆与自测。</p></div>
      <router-link :to="manage('exam_personal')" class="inline-flex min-h-12 items-center gap-2 rounded-button border border-gray-300 px-4 text-gray-700 dark:border-slate-600 dark:text-gray-200"><AdjustmentsHorizontalIcon class="h-5 w-5" aria-hidden="true" />管理词汇</router-link>
    </div>
    <div v-if="error" role="alert" class="mb-4 rounded-card border border-rose-300 p-4 text-rose-700 dark:text-rose-300">{{ error }} <BaseButton variant="secondary" class="min-h-12" @click="load">重试</BaseButton></div>
    <div class="mb-6 flex flex-wrap items-center gap-3">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">选择词汇来源</h2>
      <label class="ml-auto flex min-h-12 items-center gap-2 text-sm text-gray-600 dark:text-gray-300">学习范围
        <select v-model="mastery" class="min-h-12 rounded-button border border-gray-300 bg-white px-3 dark:border-slate-600 dark:bg-slate-800">
          <option v-for="(label, value) in MASTERY_LABELS" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
    </div>
    <div class="grid gap-4 md:grid-cols-3">
      <article v-for="scope in ['exam_personal', 'personal', 'frequent']" :key="scope" class="flex min-w-0 flex-col rounded-card-lg border border-gray-200 bg-white p-5 shadow-card dark:border-slate-700 dark:bg-slate-800">
        <button class="flex min-h-40 flex-col items-start text-left" :disabled="scope === 'frequent' && !bankId" :aria-label="`学习${SOURCE_LABELS[scope]}`" @click="start(scope)">
          <component :is="scope === 'personal' ? BookmarkIcon : scope === 'frequent' ? ChartBarIcon : BookOpenIcon" class="mb-4 h-7 w-7 text-primary-600 dark:text-primary-400" aria-hidden="true" />
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ SOURCE_LABELS[scope] }}</h3>
          <span class="mt-2 text-3xl font-bold tabular-nums text-primary-600 dark:text-primary-400">{{ scope === 'frequent' ? frequentTotal ?? '—' : stats?.[scope] ?? '—' }}<span class="ml-2 text-sm font-normal text-gray-500 dark:text-gray-400">词库总量</span></span>
          <span class="mt-3 text-sm leading-relaxed text-gray-500 dark:text-gray-400">{{ scope === 'personal' ? '手动添加与答题收藏，跨考试项目使用。' : scope === 'exam_personal' ? '仅属于当前考试项目的核心术语。' : '按题库独立学习，最多前 5000 个可见高频词。' }}</span>
        </button>
        <label v-if="scope === 'frequent'" class="mt-4 text-sm text-gray-600 dark:text-gray-300">题库
          <select id="vocab-bank" v-model="bankId" class="mt-2 min-h-12 w-full min-w-0 rounded-button border border-gray-300 bg-white px-3 dark:border-slate-600 dark:bg-slate-700">
            <option :value="null" disabled>请选择题库</option><option v-for="bank in banks" :key="bank.id" :value="bank.id">{{ bank.name }}</option>
          </select>
        </label>
        <div class="mt-auto flex flex-wrap items-center gap-2 pt-5">
          <BaseButton class="min-h-12" :disabled="scope === 'frequent' && !bankId" @click="start(scope)">开始学习</BaseButton>
          <router-link :to="manage(scope)" :aria-label="`管理${SOURCE_LABELS[scope]}`" class="inline-flex min-h-12 items-center px-3 text-sm text-gray-500 hover:text-primary-600 dark:text-gray-400">管理</router-link>
        </div>
      </article>
    </div>
    <p class="mt-5 text-sm leading-relaxed text-gray-500 dark:text-gray-400">默认优先学习未掌握词。本轮词数会在进入后显示；已有未结束轮次时，可继续或重新开始。滑过不算已学习。</p>
  </section>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AdjustmentsHorizontalIcon, BookmarkIcon, BookOpenIcon, ChartBarIcon } from '@heroicons/vue/24/outline'
import { createVocabularyOverviewApi } from '../features/vocabularyStudy/api.js'
import { useAuthStore } from '../stores/auth'
import BaseButton from './BaseButton.vue'
import { MASTERY_LABELS, SOURCE_LABELS } from '../features/vocabularyStudy/identity.js'
import { examPath } from '../utils/examRoutes'

const route = useRoute(), router = useRouter()
const examSlug = String(route.params.examSlug)
const auth = useAuthStore()
const api = createVocabularyOverviewApi({ examSlug, accountId: auth.user?.id, token: auth.token })
const stats = ref(null), banks = ref([]), bankId = ref(null), mastery = ref('unmastered'), frequentTotal = ref(null), loading = ref(true), error = ref('')
const controller = new AbortController()
let frequentGeneration = 0
async function load() {
  loading.value = true; error.value = ''
  try {
    const metadata = await api.metadata(controller.signal)
    stats.value = metadata.stats; banks.value = metadata.banks
  } catch { if (!controller.signal.aborted) error.value = '来源信息加载失败，请重试；仍可进入管理。' }
  finally { loading.value = false }
}
watch(bankId, async id => {
  const generation = ++frequentGeneration
  frequentTotal.value = null
  if (!id) return
  try {
    const total = await api.frequentTotal(id, controller.signal)
    if (generation === frequentGeneration) frequentTotal.value = total
  } catch { if (!controller.signal.aborted && generation === frequentGeneration) error.value = '题库词汇信息加载失败，请重试或进入管理。' }
})
function start(scope) { router.push({ name: 'ExamVocabularyStudy', params: { examSlug }, query: { scope, mastery: mastery.value, ...(scope === 'frequent' ? { bank_id: String(bankId.value) } : {}) } }) }
function manage(scope) { return { path: examPath(examSlug, 'vocab'), query: { mode: 'manage', scope, ...(scope === 'frequent' && bankId.value ? { bank_id: String(bankId.value) } : {}) } } }
onMounted(load)
onUnmounted(() => { controller.abort(); api.abortReads() })
</script>
