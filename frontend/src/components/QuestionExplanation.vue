<template>
  <section ref="root" class="mt-4 min-w-0" aria-label="AI 解析">
    <ExplainButton :displayed="opened && (models.some(m => m.result) || legacyAvailable)" :loading="busy" :disabled="stale" @explain="act" />
    <ExplanationSummary v-if="showSummary && opened && !stale" :models="models" @select="selectModel" />
    <p v-if="error" role="alert" class="mt-2 text-sm text-rose-700 dark:text-rose-300">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="refresh()">重新读取</button>
    </p>
    <template v-if="opened && !stale">
      <div v-if="isMobile && models.length" role="tablist" aria-label="解析模型" class="mt-4 flex gap-2 overflow-x-auto pb-2">
        <button v-for="(model, index) in models" :key="model.model_id" type="button" role="tab"
          :id="tabId(index)" :aria-controls="panelId(index)" :aria-selected="model.model_id === activeModel"
          :tabindex="model.model_id === activeModel ? 0 : -1"
          :title="model.model_id" class="max-w-60 shrink-0 truncate rounded-lg border px-3 py-2 text-sm"
          :class="model.model_id === activeModel ? 'border-primary-500 bg-primary-50 text-primary-800 dark:bg-primary-900/30 dark:text-primary-200' : 'border-gray-300 text-gray-700 dark:border-slate-600 dark:text-gray-300'"
          @click="selectModel(model.model_id)" @keydown="tabKey($event, index)">{{ model.model_id }}</button>
      </div>
      <div class="explanation-grid mt-3">
        <article v-for="model in visibleModels" :key="model.model_id" :data-model-id="model.model_id"
          :id="panelId(models.findIndex(m => m.model_id === model.model_id))" :role="isMobile ? 'tabpanel' : undefined"
          :aria-labelledby="isMobile ? tabId(models.findIndex(m => m.model_id === model.model_id)) : undefined"
          class="min-w-0 rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm dark:border-sky-800 dark:bg-sky-900/20">
          <h3 class="break-all font-semibold text-sky-900 dark:text-sky-200">{{ model.model_id }}</h3>
          <p v-if="model.result" class="mt-2 text-gray-700 dark:text-gray-300">
            模型认定答案：<strong>{{ model.result.judged_answer }}</strong>
            <span v-if="model.result.is_conflict" class="ml-1 text-amber-700 dark:text-amber-300">与题库答案不同</span>
          </p>
          <p v-if="model.result" class="mt-1 text-xs text-gray-500 dark:text-gray-400">生成于 {{ formatTime(model.result.generated_at) }}</p>
          <p v-if="explanationStatus(model)" :role="model.generation?.status === 'failed' ? 'alert' : 'status'"
            class="mt-2 text-gray-700 dark:text-gray-300">{{ explanationStatus(model) }}</p>
          <p v-if="model.generation?.error" class="mt-1 text-rose-700 dark:text-rose-300">{{ model.generation.error }}</p>
          <div v-if="bodies.get(model.model_id)" :data-reader="model.model_id" class="explanation-body mt-3 whitespace-pre-wrap leading-relaxed text-gray-700 dark:text-gray-300"
            @scroll="positions.set(model.model_id, $event.target.scrollTop)">{{ bodies.get(model.model_id).explanation_zh }}</div>
          <p v-else-if="model.result" class="mt-3 text-gray-500">正在加载正文…</p>
          <button type="button" :disabled="isGenerating(model) || dispatching || reading"
            :aria-label="(model.generation?.status === 'failed' ? '重试 ' : model.result ? '更新 ' : '生成 ') + model.model_id"
            class="mt-4 rounded-lg border border-sky-300 px-3 py-2 font-medium text-sky-800 hover:bg-sky-100 disabled:opacity-50 dark:border-sky-700 dark:text-sky-200 dark:hover:bg-sky-900/50"
            @click="updateModel(model.model_id)">{{ model.generation?.status === 'failed' ? '重试' : model.result ? '更新解析' : '生成解析' }}</button>
        </article>
      </div>
      <details v-if="legacyAvailable && (question.explanation_zh || question.explanation)" class="mt-4 rounded-lg border border-gray-200 p-3 text-sm dark:border-slate-700">
        <summary class="cursor-pointer text-gray-600 dark:text-gray-400">历史解析（模型来源未知）</summary>
        <p class="mt-2 whitespace-pre-wrap text-gray-700 dark:text-gray-300">{{ question.explanation_zh || question.explanation }}</p>
      </details>
    </template>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import ExplainButton from './ExplainButton.vue'
import ExplanationSummary from './ExplanationSummary.vue'
import { useQuestionExplanations } from '../composables/useQuestionExplanations'
import { explanationStatus, isGenerating } from '../utils/explanationPresentation'

const props = defineProps({
  question: { type: Object, required: true },
  autoReveal: { type: Boolean, default: false },
  showSummary: { type: Boolean, default: true },
})
const emit = defineEmits(['summary'])
const { models, bodies, opened, busy, dispatching, reading, error, stale, legacyAvailable, act, updateModel, refresh } =
  useQuestionExplanations(() => props.question, () => props.autoReveal)
const activeModel = ref('')
const positions = new Map()
const root = ref(null)
const uid = useId()
const mobileQuery = window.matchMedia('(max-width: 767px)')
const isMobile = ref(mobileQuery.matches)
const changedViewport = event => { isMobile.value = event.matches }
mobileQuery.addEventListener('change', changedViewport)
onBeforeUnmount(() => mobileQuery.removeEventListener('change', changedViewport))
const tabId = index => uid + '-tab-' + index
const panelId = index => uid + '-panel-' + index
const visibleModels = computed(() => isMobile.value ? models.value.filter(m => m.model_id === activeModel.value) : models.value)
const formatTime = time => new Date(time).toLocaleString('zh-CN', { hour12: false })

watch(models, value => {
  if (!value.some(m => m.model_id === activeModel.value)) activeModel.value = value[0]?.model_id || ''
  emit('summary', value)
}, { deep: true })
watch(() => props.question.id, () => { activeModel.value = models.value[0]?.model_id || ''; positions.clear() })

async function selectModel(id) {
  activeModel.value = id
  if (!opened.value) { opened.value = true; await refresh() }
  await nextTick()
  const reader = Array.from(root.value?.querySelectorAll('[data-reader]') || []).find(element => element.dataset.reader === id)
  if (reader) reader.scrollTop = positions.get(id) || 0
  const panel = document.getElementById(panelId(models.value.findIndex(m => m.model_id === id)))
  if (!isMobile.value) panel?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}

function tabKey(event, index) {
  let next
  if (event.key === 'ArrowRight') next = (index + 1) % models.value.length
  if (event.key === 'ArrowLeft') next = (index + models.value.length - 1) % models.value.length
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = models.value.length - 1
  if (next === undefined) return
  event.preventDefault()
  selectModel(models.value[next].model_id)
  nextTick(() => document.getElementById(tabId(next))?.focus())
}
defineExpose({ refresh, selectModel })
</script>
<style scoped>
.explanation-grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); max-width: 1120px; }
.explanation-body { max-height: min(65vh, 42rem); overflow-y: auto; overscroll-behavior: contain; overflow-wrap: anywhere; }
</style>
