<template>
  <div class="rounded-lg bg-white p-6 shadow">
    <!-- Progress -->
    <div v-if="!hideProgress" class="mb-4 flex items-center justify-between text-sm text-gray-500">
      <span>第 {{ currentIndex + 1 }} / {{ total }} 题</span>
      <span v-if="question.question_type === 'multiple'" class="rounded bg-amber-100 px-2 py-0.5 text-amber-700">多选</span>
      <span v-else-if="question.question_type === 'truefalse'" class="rounded bg-blue-100 px-2 py-0.5 text-blue-700">判断</span>
    </div>

    <!-- Progress bar -->
    <div v-if="!hideProgress" class="mb-6 h-1.5 w-full rounded-full bg-gray-200">
      <div class="h-1.5 rounded-full bg-indigo-600 transition-all"
        :style="{ width: `${((currentIndex + 1) / total) * 100}%` }"></div>
    </div>

    <!-- Question type badge (when progress is hidden) -->
    <div v-if="hideProgress" class="mb-4 flex items-center justify-between">
      <span class="text-sm text-gray-500">第 {{ currentIndex + 1 }} 题</span>
      <span v-if="question.question_type === 'multiple'" class="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-700">多选</span>
      <span v-else-if="question.question_type === 'truefalse'" class="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">判断</span>
    </div>

    <!-- Question content -->
    <div class="mb-6">
      <p class="text-lg font-medium text-gray-900 leading-relaxed">{{ question.content }}</p>
      <p v-if="showTranslation && question.content_zh" class="mt-2 text-base text-gray-600 leading-relaxed">{{ question.content_zh }}</p>
    </div>

    <!-- Options -->
    <div class="space-y-3">
      <label v-for="option in question.options" :key="option.key"
        class="flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors"
        :class="optionClass(option.key)"
        @click="!answered && toggleOption(option.key)">
        <input v-if="question.question_type === 'multiple'"
          type="checkbox" :checked="selectedAnswers.includes(option.key)"
          :disabled="answered" class="mt-0.5 h-4 w-4 rounded text-indigo-600" />
        <input v-else
          type="radio" :checked="selectedAnswers.includes(option.key)"
          :disabled="answered" class="mt-0.5 h-4 w-4 text-indigo-600" />
        <div>
          <span class="font-medium">{{ option.key }}.</span> {{ option.text }}
          <span v-if="showTranslation && option.text_zh" class="block text-sm text-gray-500 mt-1">{{ option.text_zh }}</span>
        </div>
      </label>
    </div>

    <!-- AI buttons row -->
    <div class="mt-4 flex gap-2">
      <TranslateButton :question-id="question.id" :has-translation="!!question.content_zh" :show="showTranslation"
        @translated="(e) => { $emit('translated', e); showTranslation = true }"
        @toggle="showTranslation = !showTranslation" />
      <ExplainButton v-if="answered" :question-id="question.id" />
      <AddVocabButton />
    </div>

    <!-- Answer result -->
    <div v-if="answered" class="mt-4 rounded-lg p-4" :class="result.is_correct ? 'bg-green-50' : 'bg-red-50'">
      <p class="font-medium" :class="result.is_correct ? 'text-green-700' : 'text-red-700'">
        {{ result.is_correct ? '回答正确' : '回答错误' }}
      </p>
      <p class="mt-1 text-sm text-gray-600">正确答案: {{ result.correct_answer }}</p>
      <div v-if="result.explanation" class="mt-2 text-sm text-gray-700">
        <p class="font-medium">解析:</p>
        <p class="whitespace-pre-wrap">{{ result.explanation }}</p>
      </div>
      <div v-if="result.explanation_zh" class="mt-2 text-sm text-gray-600">
        <p class="font-medium">中文解析:</p>
        <p class="whitespace-pre-wrap">{{ result.explanation_zh }}</p>
      </div>
    </div>

    <!-- Actions -->
    <div class="mt-6 flex justify-between">
      <button @click="$emit('prev')" :disabled="currentIndex === 0"
        class="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-30">
        上一题
      </button>
      <button v-if="!answered" @click="handleSubmit"
        :disabled="selectedAnswers.length === 0"
        class="rounded-md bg-indigo-600 px-6 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
        提交答案
      </button>
      <button v-else-if="currentIndex < total - 1" @click="$emit('next')"
        class="rounded-md bg-indigo-600 px-6 py-2 text-sm text-white hover:bg-indigo-700">
        下一题
      </button>
      <button v-else @click="$emit('finish')"
        class="rounded-md bg-emerald-600 px-6 py-2 text-sm text-white hover:bg-emerald-700">
        完成答题
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import TranslateButton from './TranslateButton.vue'
import ExplainButton from './ExplainButton.vue'
import AddVocabButton from './AddVocabButton.vue'

const props = defineProps({
  question: Object,
  currentIndex: Number,
  total: Number,
  hideProgress: { type: Boolean, default: false },
})

const emit = defineEmits(['submit', 'next', 'prev', 'finish', 'translated'])

const selectedAnswers = ref([])
const answered = ref(false)
const result = ref(null)
const showTranslation = ref(false)

watch(() => props.currentIndex, () => {
  selectedAnswers.value = []
  answered.value = false
  result.value = null
  showTranslation.value = false
})

function toggleOption(key) {
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
  if (!answered.value) {
    return selectedAnswers.value.includes(key) ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200 hover:border-gray-300'
  }
  const correct = result.value.correct_answer.split(',').map(s => s.trim())
  const isCorrect = correct.includes(key)
  const isSelected = selectedAnswers.value.includes(key)
  if (isCorrect) return 'border-green-500 bg-green-50'
  if (isSelected && !isCorrect) return 'border-red-500 bg-red-50'
  return 'border-gray-200 opacity-60'
}

async function handleSubmit() {
  const answer = selectedAnswers.value.sort().join(',')
  emit('submit', answer, (res) => {
    result.value = res
    answered.value = true
  })
}
</script>
