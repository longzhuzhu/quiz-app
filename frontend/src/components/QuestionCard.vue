<template>
  <div class="rounded-xl bg-white dark:bg-slate-800 shadow-card p-6">
    <template v-if="question">
    <!-- 题目信息 -->
    <div class="mb-4 flex items-center justify-between">
      <span class="text-sm text-gray-500 dark:text-gray-400">
        第 {{ currentIndex + 1 }}{{ !hideProgress ? ` / ${total}` : '' }} 题
      </span>
      <span v-if="question.question_type === 'multiple'" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">多选</span>
      <span v-else-if="question.question_type === 'truefalse'" class="rounded-full bg-sky-100 dark:bg-sky-900/30 px-2.5 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400">判断</span>
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
          type="checkbox" :checked="selectedAnswers.includes(option.key)"
           class="mt-0.5 h-4 w-4 rounded text-primary-600 dark:text-primary-500" />
        <input v-else
          type="radio" :checked="selectedAnswers.includes(option.key)"
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
      <TranslateButton :question-id="question.id" :has-translation="!!question.content_zh" :show="showTranslation"
        @translated="(e) => { $emit('translated', e); showTranslation = true }"
        @toggle="showTranslation = !showTranslation" />
      <ExplainButton v-if="answered" :question-id="question.id" @explained="(e) => explainData = e" />
      <AddVocabButton />
    </div>

    <!-- AI 解析内容（独立于按钮行） -->
    <div v-if="explainData"
      class="mt-3 rounded-card border border-sky-200 bg-sky-50 p-4 text-sm
             dark:border-sky-800 dark:bg-sky-900/20">
      <p class="font-medium text-sky-800 dark:text-sky-300">AI 解析</p>
      <p class="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-300">{{ explainData.explanation }}</p>
      <p v-if="explainData.explanation_zh"
        class="mt-2 whitespace-pre-wrap text-gray-600 dark:text-gray-400">{{ explainData.explanation_zh }}</p>
    </div>

    <!-- 答题反馈 -->
    <div v-if="answered" class="mt-4 rounded-xl p-4 border"
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
      <div v-if="result.explanation" class="mt-2 text-sm text-gray-700 dark:text-gray-300">
        <p class="font-medium">解析:</p>
        <p class="whitespace-pre-wrap">{{ result.explanation }}</p>
      </div>
      <div v-if="result.explanation_zh" class="mt-2 text-sm text-gray-600 dark:text-gray-400">
        <p class="font-medium">中文解析:</p>
        <p class="whitespace-pre-wrap">{{ result.explanation_zh }}</p>
      </div>
    </div>

    <!-- 操作栏 -->
    <div class="mt-6 flex justify-between items-center gap-2">
      <BaseButton variant="secondary" @click="$emit('prev')" :disabled="currentIndex === 0">上一题</BaseButton>
      <div class="flex items-center gap-2">
        <BaseButton variant="primary" @click="handleSubmit" :disabled="selectedAnswers.length === 0">提交答案</BaseButton>
        <BaseButton v-if="answered && currentIndex < total - 1" variant="primary" @click="$emit('next')">下一题</BaseButton>
        <BaseButton v-else-if="answered" variant="primary" @click="$emit('finish')" class="!bg-emerald-600 hover:!bg-emerald-700">完成答题</BaseButton>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { CheckCircleIcon, XCircleIcon } from '@heroicons/vue/24/outline'
import TranslateButton from './TranslateButton.vue'
import ExplainButton from './ExplainButton.vue'
import AddVocabButton from './AddVocabButton.vue'
import BaseButton from './BaseButton.vue'

const props = defineProps({
  question: Object,
  currentIndex: Number,
  total: Number,
  hideProgress: { type: Boolean, default: false },
  initialAnswer: { type: String, default: '' },
  initialResult: { type: Object, default: null },
})

const emit = defineEmits(['submit', 'next', 'prev', 'finish', 'translated'])

const selectedAnswers = ref([])
const answered = ref(false)
const result = ref(null)
const showTranslation = ref(false)
const explainData = ref(null)

watch(
  [() => props.currentIndex, () => props.initialAnswer, () => props.initialResult],
  () => {
    selectedAnswers.value = props.initialAnswer
      ? props.initialAnswer.split(',').map(s => s.trim()).filter(Boolean)
      : []
    answered.value = !!props.initialResult
    result.value = props.initialResult
    showTranslation.value = false
    explainData.value = null
  },
  { immediate: true }
)

function toggleOption(key) {
  if (!props.question) return

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

function optionClass(key) {
  const base = 'flex cursor-pointer items-start gap-3 rounded-xl border-2 p-4 transition-all duration-200'
  if (!answered.value) {
    if (selectedAnswers.value.includes(key)) {
      return `${base} border-primary-500 bg-primary-50 dark:bg-primary-900/20 ring-2 ring-primary-500/20`
    }
    return `${base} border-gray-200 dark:border-slate-600 hover:border-gray-300 dark:hover:border-slate-500 hover:bg-gray-50 dark:hover:bg-slate-700/50`
  }
  const correct = (result.value?.correct_answer || '').split(',').map(s => s.trim()).filter(Boolean)
  const isCorrect = correct.includes(key)
  const isSelected = selectedAnswers.value.includes(key)
  if (isCorrect) return `${base} border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20`
  if (isSelected && !isCorrect) return `${base} border-rose-500 bg-rose-50 dark:bg-rose-900/20 animate-shake`
  return `${base} border-gray-200 dark:border-slate-700 opacity-50`
}

async function handleSubmit() {
  const answer = selectedAnswers.value.sort().join(',')
  emit('submit', answer, (res) => {
    result.value = res
    answered.value = true
  })
}
</script>
