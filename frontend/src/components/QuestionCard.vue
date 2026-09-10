<template>
  <div class="rounded-xl bg-white dark:bg-slate-800 shadow-card p-4 md:p-6">
    <template v-if="question">
    <!-- 题目信息 -->
    <div class="mb-4 flex items-center justify-between gap-2">
      <div class="min-w-0">
        <span class="text-sm text-gray-500 dark:text-gray-400 block truncate">
          第 {{ currentIndex + 1 }}{{ !hideProgress ? ` / ${total}` : '' }} 题
        </span>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="question.question_type === 'multiple'" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">多选</span>
        <span v-else-if="question.question_type === 'truefalse'" class="rounded-full bg-sky-100 dark:bg-sky-900/30 px-2.5 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400">判断</span>
        <span class="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">
          已答 {{ answerCount }} 次
        </span>
        <button type="button" aria-label="复制题目" @click="copyQuestion"
          class="inline-flex h-7 w-7 items-center justify-center rounded-button text-slate-600
                 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-600 transition-colors">
          <ClipboardDocumentIcon class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- 进度条（仅 !hideProgress） -->
    <div v-if="!hideProgress" class="mb-6 h-1.5 w-full rounded-full bg-gray-200 dark:bg-slate-700">
      <div class="h-1.5 rounded-full bg-gradient-to-r from-primary-500 to-sky-400 transition-all duration-300"
        :style="{ width: `${((currentIndex + 1) / total) * 100}%` }"></div>
    </div>

    <!-- 题目内容 -->
    <div class="mb-6">
      <p class="text-lg font-medium text-gray-900 dark:text-white leading-relaxed">{{ question.content }}</p>
      <p v-if="showTranslation && question.content_zh" class="mt-2 text-base text-gray-600 dark:text-gray-400 leading-relaxed">{{ question.content_zh }}</p>
    </div>

    <!-- 选项 -->
    <div class="space-y-3">
      <label v-for="option in question.options" :key="option.key"
        :class="optionClass(option.key)"
        @click="toggleOption(option.key)">
        <input v-if="question.question_type === 'multiple'"
          type="checkbox" :checked="isOptionChecked(option.key)"
           class="mt-0.5 h-4 w-4 rounded text-primary-600 dark:text-primary-500" />
        <input v-else
          type="radio" :checked="isOptionChecked(option.key)"
           class="mt-0.5 h-4 w-4 text-primary-600 dark:text-primary-500" />
        <div>
          <span class="font-medium text-gray-900 dark:text-white">{{ option.key }}.</span>
          <span class="text-gray-700 dark:text-gray-300">{{ option.text }}</span>
          <span v-if="showTranslation && option.text_zh" class="block text-sm text-gray-500 dark:text-gray-400 mt-1">{{ option.text_zh }}</span>
        </div>
      </label>
    </div>

    <!-- AI 按钮区 -->
    <div class="mt-4 flex flex-wrap items-center gap-2">
      <TranslateButton :key="question.id" :question-id="question.id" :has-translation="hasFullTranslation" :show="showTranslation"
        @translated="(e) => { $emit('translated', e); showTranslation = true }"
        @toggle="showTranslation = !showTranslation" />
      <ExplainButton
        v-if="!examMode"
        :key="question.id"
        :question-id="question.id"
        :initial-explanation="initialExplanation"
        :displayed="!!displayedExplanation"
        @explained="onExplained"
      />
      <AddVocabButton :initial-term="question.content" />
    </div>

    <!-- 答题反馈 -->
    <div v-if="answered && !examMode" class="mt-4 rounded-xl p-4 border"
      :class="result.is_correct
        ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
        : 'bg-rose-50 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800'">
      <div class="flex items-center gap-2">
        <CheckCircleIcon v-if="result.is_correct" class="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
        <XCircleIcon v-else class="h-5 w-5 text-rose-600 dark:text-rose-400" />
        <p class="font-medium" :class="result.is_correct ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'">
          {{ result.is_correct ? '回答正确！' : '回答错误' }}
        </p>
      </div>
      <p class="mt-2 text-sm text-gray-600 dark:text-gray-300">正确答案: {{ result.correct_answer }}</p>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <button v-if="!correctionMode" type="button" @click="enterCorrectionMode"
          class="text-sm font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400">
          更正答案
        </button>
        <template v-else>
          <span class="text-xs text-gray-500 dark:text-gray-400">点击选项选择新的正确答案</span>
          <BaseButton size="sm" variant="primary" @click="askConfirmCorrection"
            :disabled="pendingCorrectKeys.length === 0 || correcting">确认更正</BaseButton>
          <BaseButton size="sm" variant="secondary" @click="cancelCorrection" :disabled="correcting">取消</BaseButton>
        </template>
      </div>
    </div>

    <!-- AI 解析内容（独立于按钮行） -->
    <div v-if="displayedExplanation && !examMode"
      class="mt-3 rounded-card border border-sky-200 bg-sky-50 p-4 text-sm
             dark:border-sky-800 dark:bg-sky-900/20">
      <p class="font-medium text-sky-800 dark:text-sky-300">AI 解析</p>
      <p class="mt-2 whitespace-pre-wrap text-gray-600 dark:text-gray-400">{{ displayedExplanation }}</p>
    </div>

    <!-- 操作栏 -->
    <div class="mt-6 flex flex-wrap justify-between items-center gap-2">
      <BaseButton variant="secondary" size="sm" @click="$emit('prev')" :disabled="currentIndex === 0">上一题</BaseButton>
      <div class="flex items-center gap-2">
        <BaseButton variant="primary" size="sm" @click="handleSubmit" :disabled="selectedAnswers.length === 0 || submitting || correctionMode" :loading="submitting">提交答案</BaseButton>
        <BaseButton v-if="answered && currentIndex < total - 1" variant="primary" size="sm" @click="$emit('next')">下一题</BaseButton>
        <BaseButton v-else-if="answered" variant="primary" size="sm" @click="$emit('finish')" class="!bg-emerald-600 hover:!bg-emerald-700">完成答题</BaseButton>
      </div>
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
  hideProgress: { type: Boolean, default: false },
  initialAnswer: { type: String, default: '' },
  initialResult: { type: Object, default: null },
  examMode: { type: Boolean, default: false },
  answerCount: { type: Number, default: 0 },
  sessionId: { type: Number, default: null },
})

const emit = defineEmits(['submit', 'next', 'prev', 'finish', 'translated', 'answer-corrected'])
const toast = useToast()

const selectedAnswers = ref([])
const answered = ref(false)
const result = ref(null)
const showTranslation = ref(false)
const explainData = ref(null)
const submitting = ref(false)
const correctionMode = ref(false)
const pendingCorrectKeys = ref([])
const confirmCorrectOpen = ref(false)
const correcting = ref(false)
let correctionGeneration = 0

const initialExplanation = computed(() => {
  if (!props.question?.explanation_zh) return null
  return {
    explanation: props.question.explanation,
    explanation_zh: props.question.explanation_zh,
  }
})

const displayedExplanation = computed(() => {
  if (explainData.value?.explanation_zh) return explainData.value.explanation_zh
  if (answered.value) {
    return result.value?.explanation_zh || props.question?.explanation_zh || null
  }
  return null
})

const hasFullTranslation = computed(() => {
  if (!props.question?.content_zh) return false
  return (props.question.options || []).every(opt => opt.text_zh)
})

const confirmCorrectMessage = computed(() => {
  const oldAnswer = result.value?.correct_answer || ''
  const newAnswer = formatAnswerKeys(pendingCorrectKeys.value)
  return `将正确答案从 ${oldAnswer} 改为 ${newAnswer}？`
})

watch(
  [() => props.currentIndex, () => props.initialAnswer, () => props.initialResult],
  () => {
    correctionGeneration += 1
    selectedAnswers.value = props.initialAnswer
      ? props.initialAnswer.split(',').map(s => s.trim()).filter(Boolean)
      : []
    answered.value = !!props.initialResult
    result.value = props.initialResult
    showTranslation.value = false
    explainData.value = null
    correctionMode.value = false
    pendingCorrectKeys.value = []
    confirmCorrectOpen.value = false
    correcting.value = false
  },
  { immediate: true }
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
  return selectedAnswers.value.includes(key)
}

function onExplained(payload) {
  explainData.value = payload
  if (result.value) {
    result.value.explanation = payload.explanation
    result.value.explanation_zh = payload.explanation_zh
  }
  if (props.question) {
    props.question.explanation = payload.explanation
    props.question.explanation_zh = payload.explanation_zh
  }
}

function enterCorrectionMode() {
  correctionMode.value = true
  const judged = parseJudgedAnswerFromExplanation(displayedExplanation.value)
  if (judged.length) {
    pendingCorrectKeys.value = [...judged]
  } else {
    pendingCorrectKeys.value = parseAnswerKeys(result.value?.correct_answer)
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
    if (result.value) {
      if (data.is_correct != null) result.value.is_correct = data.is_correct
      result.value.correct_answer = data.correct_answer
      result.value.explanation = data.explanation
      result.value.explanation_zh = data.explanation_zh
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

function toggleOption(key) {
  if (!props.question) return

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

  if (answered.value) {
    answered.value = false
    result.value = null
  }

  if (props.question.question_type === 'multiple') {
    const idx = selectedAnswers.value.indexOf(key)
    if (idx >= 0) {
      selectedAnswers.value.splice(idx, 1)
    } else {
      selectedAnswers.value.push(key)
    }
  } else {
    selectedAnswers.value = [key]
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

function optionClass(key) {
  const base = 'flex cursor-pointer items-start gap-3 rounded-xl border-2 p-4 transition-all duration-200'
  if (correctionMode.value) {
    if (pendingCorrectKeys.value.includes(key)) {
      return `${base} border-primary-500 bg-primary-50 dark:bg-primary-900/20 ring-2 ring-primary-500/20`
    }
    return `${base} border-gray-200 dark:border-slate-600 hover:border-gray-300 dark:hover:border-slate-500 hover:bg-gray-50 dark:hover:bg-slate-700/50`
  }
  if (!answered.value) {
    if (selectedAnswers.value.includes(key)) {
      return `${base} border-primary-500 bg-primary-50 dark:bg-primary-900/20 ring-2 ring-primary-500/20`
    }
    return `${base} border-gray-200 dark:border-slate-600 hover:border-gray-300 dark:hover:border-slate-500 hover:bg-gray-50 dark:hover:bg-slate-700/50`
  }
  // 模拟考试模式：已答题后仅显示「已选中」灰色状态
  if (props.examMode) {
    if (selectedAnswers.value.includes(key)) {
      return `${base} border-gray-400 dark:border-slate-500 bg-gray-100 dark:bg-slate-700`
    }
    return `${base} border-gray-200 dark:border-slate-700 opacity-50`
  }
  const correct = (result.value?.correct_answer || '').split(',').map(s => s.trim()).filter(Boolean)
  const isCorrect = correct.includes(key)
  const isSelected = selectedAnswers.value.includes(key)
  if (isCorrect) return `${base} border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20`
  if (isSelected && !isCorrect) return `${base} border-rose-500 bg-rose-50 dark:bg-rose-900/20 animate-shake`
  return `${base} border-gray-200 dark:border-slate-700 opacity-50`
}

async function handleSubmit() {
  if (submitting.value || correctionMode.value) return
  submitting.value = true
  const answer = selectedAnswers.value.sort().join(',')
  emit('submit', answer, (res) => {
    result.value = res
    answered.value = true
    submitting.value = false
  })
}
</script>
