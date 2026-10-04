<template>
  <div class="rounded-xl bg-white dark:bg-slate-800 shadow-card p-4 md:p-6">
    <template v-if="question">
    <!-- 题目信息：位置与辅助工具，弱化装饰 -->
    <div class="mb-5 flex items-center justify-between gap-2">
      <div class="min-w-0 text-sm text-gray-500 dark:text-gray-400">
        第 {{ currentIndex + 1 }} / {{ total }} 题
      </div>
      <div class="flex items-center gap-2">
        <span v-if="question.question_type === 'multiple'" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">多选</span>
        <span v-else-if="question.question_type === 'truefalse'" class="rounded-full bg-sky-100 dark:bg-sky-900/30 px-2.5 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400">判断</span>
        <span v-if="answerCount > 0" class="text-xs text-gray-400 dark:text-gray-500">已答 {{ answerCount }} 次</span>
        <button type="button" aria-label="复制题目" @click="copyQuestion"
          class="inline-flex h-7 w-7 items-center justify-center rounded-button text-slate-500
                 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700 transition-colors">
          <ClipboardDocumentIcon class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- 题干：常规字重、保留原始换行、限制阅读列宽 -->
    <div class="mb-6">
      <p class="max-w-[72ch] whitespace-pre-line text-lg font-normal leading-relaxed text-gray-900 dark:text-white">{{ question.content }}</p>
      <!-- 翻译入口紧邻题干；显隐为会话级偏好（由父组件持有） -->
      <div class="mt-2.5">
        <TranslateButton :key="question.id" :question-id="question.id" :has-translation="hasFullTranslation" :show="showTranslation"
          @translated="onTranslated"
          @toggle="$emit('update:showTranslation', !showTranslation)" />
      </div>
      <p v-if="showTranslation && question.content_zh" class="mt-2 max-w-[72ch] whitespace-pre-line text-base leading-relaxed text-gray-600 dark:text-gray-400">{{ question.content_zh }}</p>
    </div>

    <!-- 选项：控件/标号/正文三列，标号窄列悬挂对齐；input 为唯一激活入口 -->
    <fieldset class="min-w-0">
      <legend class="sr-only">题目选项</legend>
      <div class="space-y-2.5">
        <component :is="interactive ? 'label' : 'div'" v-for="option in question.options" :key="option.key"
          class="question-option"
          :class="optionClass(option.key)">
          <input v-if="question.question_type === 'multiple'"
            type="checkbox" :name="inputGroupName" :checked="isOptionChecked(option.key)"
            :class="inputClass(option.key)"
            @change="onOptionChange(option.key)" />
          <input v-else
            type="radio" :name="inputGroupName" :checked="isOptionChecked(option.key)"
            :class="inputClass(option.key)"
            @change="onOptionChange(option.key)" />
          <span class="w-7 shrink-0 pt-0.5 text-right font-medium text-gray-900 dark:text-white">{{ option.key }}.</span>
          <span class="min-w-0 flex-1 text-gray-700 dark:text-gray-300">
            <span class="break-words" :class="{ 'font-medium text-gray-900 dark:text-white': isResultKey(option.key) }">{{ option.text }}</span>
            <span v-if="resultBadge(option.key)"
              class="ml-2 inline-flex items-center rounded-full px-2 py-0.5 align-middle text-xs font-medium"
              :class="resultBadge(option.key).tone">{{ resultBadge(option.key).text }}</span>
            <span v-if="showTranslation && option.text_zh" class="mt-1 block text-sm leading-relaxed text-gray-500 dark:text-gray-400">{{ option.text_zh }}</span>
          </span>
        </component>
      </div>
    </fieldset>

    <!-- 答题反馈：对/错 + 你的答案与正确答案对照（aria 播报） -->
    <div v-if="result && !examMode" role="status" aria-live="polite" class="mt-4 rounded-xl p-4 border"
      :class="result.is_correct
        ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
        : 'bg-rose-50 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800'">
      <div class="flex items-center gap-2">
        <CheckCircleIcon v-if="result.is_correct" class="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
        <XCircleIcon v-else class="h-5 w-5 text-rose-600 dark:text-rose-400" />
        <p class="font-medium" :class="result.is_correct ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'">
          {{ result.is_correct ? '回答正确' : '回答错误' }}
        </p>
      </div>
      <p class="mt-1.5 text-sm text-gray-700 dark:text-gray-300">
        你的答案 <span class="font-medium text-gray-900 dark:text-white">{{ submittedDisplay }}</span>
        <template v-if="!result.is_correct">
          <span class="mx-1 text-gray-400">→</span>
          正确答案 <span class="font-medium text-emerald-700 dark:text-emerald-400">{{ result.correct_answer }}</span>
        </template>
      </p>
      <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <template v-if="editing">
          <span class="text-xs text-amber-600 dark:text-amber-400">重新作答中，提交后更新结果</span>
          <button type="button" @click="$emit('cancel-editing')"
            class="text-sm font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
            取消重做
          </button>
        </template>
        <template v-else-if="!correctionMode">
          <button type="button" @click="$emit('start-editing')"
            class="text-sm font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300">
            重新作答
          </button>
          <button type="button" @click="enterCorrectionMode"
            class="text-sm font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
            更正答案
          </button>
        </template>
        <template v-else>
          <span class="text-xs text-gray-500 dark:text-gray-400">点击选项选择新的正确答案</span>
          <BaseButton size="sm" variant="primary" @click="askConfirmCorrection"
            :disabled="pendingCorrectKeys.length === 0 || correcting">确认更正</BaseButton>
          <BaseButton size="sm" variant="secondary" @click="cancelCorrection" :disabled="correcting">取消</BaseButton>
        </template>
      </div>
    </div>

    <!-- AI 解析：可折叠，默认收起 -->
    <div v-if="explanationShown && !examMode"
      class="mt-3 rounded-card border border-sky-200 bg-sky-50 p-4 text-sm
             dark:border-sky-800 dark:bg-sky-900/20">
      <div class="flex items-center justify-between gap-2">
        <p class="font-medium text-sky-800 dark:text-sky-300">AI 解析</p>
        <button type="button" @click="explainOpen = false"
          class="text-xs font-medium text-sky-700 hover:text-sky-800 dark:text-sky-400 dark:hover:text-sky-300">
          收起
        </button>
      </div>
      <p class="mt-2 whitespace-pre-wrap text-gray-600 dark:text-gray-400">{{ displayedExplanation }}</p>
    </div>

    <!-- 辅助工具行：解析获取/更新与生词，保持次级权重 -->
    <div class="mt-5 flex flex-wrap items-center gap-2">
      <ExplainButton
        v-if="!examMode"
        :key="question.id"
        :question-id="question.id"
        :initial-explanation="initialExplanation"
        :displayed="explanationShown"
        @explained="onExplained"
      />
      <AddVocabButton :initial-term="question.content" />
    </div>
    </template>

  <ConfirmDialog
    :open="confirmCorrectOpen"
    title="更正答案"
    :message="confirmCorrectMessage"
    confirmText="确认更正"
    @confirm="submitCorrectAnswer"
    @cancel="confirmCorrectOpen = false"
  />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { CheckCircleIcon, ClipboardDocumentIcon, XCircleIcon } from '@heroicons/vue/24/outline'
import TranslateButton from './TranslateButton.vue'
import ExplainButton from './ExplainButton.vue'
import AddVocabButton from './AddVocabButton.vue'
import BaseButton from './BaseButton.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import client from '../api/client'
import { useToast } from '../composables/useToast'
import { formatLocalDate } from '../utils/localDate'

const props = defineProps({
  question: Object,
  currentIndex: Number,
  total: Number,
  examMode: { type: Boolean, default: false },
  answerCount: { type: Number, default: 0 },
  sessionId: { type: Number, default: null },
  // 受控状态：未提交草稿与已提交答案分离（N1/E2）
  selectedAnswers: { type: Array, default: () => [] },
  submittedAnswer: { type: String, default: '' },
  result: { type: Object, default: null },
  editing: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
  showTranslation: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:selectedAnswers',
  'update:showTranslation',
  'submit',
  'start-editing',
  'cancel-editing',
  'translated',
  'answer-corrected',
])
const toast = useToast()

const explainOpen = ref(false)
const explainData = ref(null)
const correctionMode = ref(false)
const pendingCorrectKeys = ref([])
const confirmCorrectOpen = ref(false)
const correcting = ref(false)
let correctionGeneration = 0

const isAnswered = computed(() => !!props.result && !props.editing)
const interactive = computed(() => !isAnswered.value || props.editing || correctionMode.value)
const submittedKeys = computed(() => parseAnswerKeys(props.submittedAnswer))
const inputGroupName = computed(() => `quiz-options-${props.question?.id ?? 'x'}`)

const submittedDisplay = computed(() => {
  if (submittedKeys.value.length) return submittedKeys.value.join(', ')
  return props.submittedAnswer || '—'
})

const initialExplanation = computed(() => {
  if (!props.question?.explanation_zh) return null
  return {
    explanation: props.question.explanation,
    explanation_zh: props.question.explanation_zh,
  }
})

const displayedExplanation = computed(() => {
  if (!props.result && !explainData.value) return null
  if (explainData.value?.explanation_zh) return explainData.value.explanation_zh
  if (isAnswered.value) {
    return props.result?.explanation_zh || props.question?.explanation_zh || null
  }
  return null
})

const explanationShown = computed(() => explainOpen.value && !!displayedExplanation.value)

const hasFullTranslation = computed(() => {
  if (!props.question?.content_zh) return false
  return (props.question.options || []).every(opt => opt.text_zh)
})

const confirmCorrectMessage = computed(() => {
  const oldAnswer = props.result?.correct_answer || ''
  const newAnswer = formatAnswerKeys(pendingCorrectKeys.value)
  return `将正确答案从 ${oldAnswer} 改为 ${newAnswer}？`
})

// 切题时重置瞬态状态；解析缓存保留（对应同一题目数据）
watch(
  () => props.question?.id,
  () => {
    explainOpen.value = false
    correctionMode.value = false
    pendingCorrectKeys.value = []
    confirmCorrectOpen.value = false
    correcting.value = false
  },
)

function formatAnswerKeys(keys) {
  return [...keys].map((key) => String(key).trim()).filter(Boolean).sort().join(',')
}

function parseAnswerKeys(raw) {
  if (!raw) return []
  return String(raw).split(',').map((part) => part.trim()).filter(Boolean)
}

function parseJudgedAnswerFromExplanation(text) {
  if (!text || !text.includes('【答案冲突】')) return []
  const match = String(text).match(/AI 认定：([^\n]+)/)
  if (!match) return []
  return parseAnswerKeys(match[1])
}

function isOptionChecked(key) {
  if (correctionMode.value) return pendingCorrectKeys.value.includes(key)
  if (isAnswered.value) return submittedKeys.value.includes(key)
  return props.selectedAnswers.includes(key)
}

function onExplained(payload) {
  explainData.value = payload
  explainOpen.value = true
  if (props.result) {
    props.result.explanation = payload.explanation
    props.result.explanation_zh = payload.explanation_zh
  }
  if (props.question) {
    props.question.explanation = payload.explanation
    props.question.explanation_zh = payload.explanation_zh
  }
}

function onTranslated(data) {
  emit('translated', data)
  emit('update:showTranslation', true)
}

function enterCorrectionMode() {
  correctionMode.value = true
  const judged = parseJudgedAnswerFromExplanation(displayedExplanation.value)
  if (judged.length) {
    pendingCorrectKeys.value = [...judged]
  } else {
    pendingCorrectKeys.value = parseAnswerKeys(props.result?.correct_answer)
  }
}

function cancelCorrection() {
  correctionMode.value = false
  pendingCorrectKeys.value = []
  confirmCorrectOpen.value = false
}

function askConfirmCorrection() {
  if (!pendingCorrectKeys.value.length) return
  confirmCorrectOpen.value = true
}

async function submitCorrectAnswer() {
  if (!props.question || pendingCorrectKeys.value.length === 0) return
  const requestGeneration = ++correctionGeneration
  correcting.value = true
  try {
    const res = await client.put(`/questions/${props.question.id}/correct-answer`, {
      correct_answer: formatAnswerKeys(pendingCorrectKeys.value),
      session_id: props.sessionId,
      local_date: formatLocalDate(),
    })
    if (requestGeneration !== correctionGeneration) return
    const data = res.data || {}
    if (props.result) {
      if (data.is_correct != null) props.result.is_correct = data.is_correct
      props.result.correct_answer = data.correct_answer
      props.result.explanation = data.explanation
      props.result.explanation_zh = data.explanation_zh
    }
    if (props.question) {
      props.question.correct_answer = data.correct_answer
      props.question.explanation = data.explanation
      props.question.explanation_zh = data.explanation_zh
    }
    explainData.value = null
    correctionMode.value = false
    pendingCorrectKeys.value = []
    confirmCorrectOpen.value = false
    toast.success('答案已更正')
    emit('answer-corrected', {
      questionId: props.question.id,
      correct_answer: data.correct_answer,
      is_correct: data.is_correct,
      explanation: data.explanation,
      explanation_zh: data.explanation_zh,
    })
  } catch (e) {
    if (requestGeneration !== correctionGeneration) return
    toast.error(e.response?.data?.detail || '更正答案失败')
    confirmCorrectOpen.value = false
  } finally {
    if (requestGeneration === correctionGeneration) {
      correcting.value = false
    }
  }
}

// 唯一激活入口：原生 input 的 change。锁定态守卫直接返回（E1）
function onOptionChange(key) {
  if (!interactive.value || !props.question) return

  if (correctionMode.value) {
    if (props.question.question_type === 'multiple') {
      const idx = pendingCorrectKeys.value.indexOf(key)
      if (idx >= 0) {
        pendingCorrectKeys.value.splice(idx, 1)
      } else {
        pendingCorrectKeys.value.push(key)
      }
    } else {
      pendingCorrectKeys.value = [key]
    }
    return
  }

  if (props.question.question_type === 'multiple') {
    const next = props.selectedAnswers.includes(key)
      ? props.selectedAnswers.filter(k => k !== key)
      : [...props.selectedAnswers, key]
    emit('update:selectedAnswers', next)
  } else {
    emit('update:selectedAnswers', [key])
  }
}

function formatQuestionText() {
  if (!props.question) return ''

  const lines = []
  if (props.question.content) lines.push(props.question.content)

  const options = Array.isArray(props.question.options) ? props.question.options : []
  if (options.length && lines.length) lines.push('')
  options.forEach((option) => {
    const key = option.key ? `${option.key}. ` : ''
    const text = option.text || ''
    if (key || text) lines.push(`${key}${text}`.trim())
  })

  return lines.join('\n')
}

async function copyQuestion() {
  const text = formatQuestionText()
  if (!text) {
    toast.error('没有可复制的题目内容')
    return
  }
  const clipboard = globalThis.navigator?.clipboard
  if (!clipboard?.writeText) {
    toast.error('当前浏览器不支持复制')
    return
  }

  try {
    await clipboard.writeText(text)
    toast.success('题目已复制')
  } catch {
    toast.error('复制失败，请手动选择文本复制')
  }
}

const OPTION_BASE = 'flex items-start gap-2.5 rounded-xl border p-3.5 transition-colors'
const OPTION_NEUTRAL = `${OPTION_BASE} border-gray-200 dark:border-slate-700`
const OPTION_HOVER = `${OPTION_NEUTRAL} hover:border-gray-300 dark:hover:border-slate-500 hover:bg-gray-50 dark:hover:bg-slate-700/40 cursor-pointer`
const OPTION_SELECTED = `${OPTION_BASE} border-primary-500 bg-primary-50 dark:bg-primary-900/20 cursor-pointer`

function optionClass(key) {
  if (correctionMode.value) {
    return pendingCorrectKeys.value.includes(key) ? OPTION_SELECTED : OPTION_HOVER
  }
  if (!isAnswered.value) {
    return props.selectedAnswers.includes(key) ? OPTION_SELECTED : OPTION_HOVER
  }
  // 已答：全部选项保持正常对比度，用边框/轻背景/标签表达结果（O2）
  const correct = submittedKeys.value.length ? isCorrectKey(key) : false
  const chosen = submittedKeys.value.includes(key)
  if (props.examMode) {
    return chosen ? `${OPTION_BASE} border-sky-400 bg-sky-50 dark:border-sky-600 dark:bg-sky-900/20` : OPTION_NEUTRAL
  }
  if (correct) return `${OPTION_BASE} border-emerald-500 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/20`
  if (chosen) return `${OPTION_BASE} border-rose-500 bg-rose-50 dark:border-rose-600 dark:bg-rose-900/20`
  return OPTION_NEUTRAL
}

function inputClass(key) {
  const disabledLike = !interactive.value ? ' pointer-events-none' : ''
  return `mt-1 h-4 w-4 shrink-0 accent-primary-600 dark:accent-primary-500${disabledLike}`
}

function isCorrectKey(key) {
  const correct = parseAnswerKeys(props.result?.correct_answer)
  return correct.includes(key)
}

function isResultKey(key) {
  if (correctionMode.value) return pendingCorrectKeys.value.includes(key)
  if (!isAnswered.value) return props.selectedAnswers.includes(key)
  return submittedKeys.value.includes(key)
}

function resultBadge(key) {
  if (correctionMode.value) return null
  if (!isAnswered.value) return null
  const chosen = submittedKeys.value.includes(key)
  if (props.examMode) {
    return chosen ? { text: '已选', tone: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-400' } : null
  }
  const correct = isCorrectKey(key)
  if (correct && chosen) return { text: '你的答案 ✓', tone: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400' }
  if (correct) return { text: '正确答案', tone: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400' }
  if (chosen) return { text: '你的选择', tone: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-400' }
  return null
}
</script>
