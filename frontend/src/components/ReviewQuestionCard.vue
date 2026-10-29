<template>
  <div class="rounded-xl bg-white dark:bg-slate-800 shadow-card p-4 md:p-6" data-testid="review-question"
    :data-index="question.index" :data-status="statusKind">
    <!-- 题目信息 -->
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <span class="text-sm text-gray-500 dark:text-gray-400">
        第 {{ question.index }} 题
      </span>
      <div class="flex flex-wrap items-center gap-2">
        <span v-if="question.question_type === 'multiple'" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">多选</span>
        <span v-else-if="question.question_type === 'truefalse'" class="rounded-full bg-sky-100 dark:bg-sky-900/30 px-2.5 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400">判断</span>
        <span data-testid="review-status" class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium" :class="statusBadgeClass">
          <component :is="statusIcon" class="h-3.5 w-3.5" />
          {{ statusText }}
        </span>
      </div>
    </div>

    <!-- 题目内容：完整展示，不截断 -->
    <div class="mb-6">
      <p v-if="question.content" class="text-lg font-medium text-gray-900 dark:text-white leading-relaxed whitespace-pre-wrap break-words">{{ question.content }}</p>
      <p v-else class="text-lg font-medium text-gray-500 dark:text-gray-400 leading-relaxed">题目内容不可用</p>
      <p v-if="showTranslation && question.content_zh" class="mt-2 text-base text-gray-600 dark:text-gray-400 leading-relaxed">{{ question.content_zh }}</p>
    </div>

    <!-- 选项：只读展示，不绑定点击 -->
    <div v-if="options.length" class="space-y-3">
      <div v-for="option in options" :key="option.key" data-testid="review-option"
        class="flex items-start gap-3 rounded-xl border-2 p-4" :class="optionClass(option.key)">
        <div class="min-w-0 flex-1">
          <span class="font-medium text-gray-900 dark:text-white">{{ option.key }}.</span>
          <span class="text-gray-700 dark:text-gray-300 break-words"> {{ option.text }}</span>
          <span v-if="showTranslation && option.text_zh" class="block text-sm text-gray-500 dark:text-gray-400 mt-1">{{ option.text_zh }}</span>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 flex-shrink-0">
          <span v-if="isCorrectKey(option.key)" data-testid="badge-correct-answer"
            class="rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            当场正确答案
          </span>
          <span v-if="isUserKey(option.key)" data-testid="badge-user-answer"
            class="rounded-full px-2 py-0.5 text-xs font-medium" :class="userBadgeClass">
            你的答案
          </span>
        </div>
      </div>
    </div>

    <!-- AI 按钮区：与答题卡保持一致，紧跟在选项下方 -->
    <div class="mt-4 flex flex-wrap items-center gap-2">
      <TranslateButton :key="question.id" :question-id="question.id" :has-translation="hasFullTranslation" :show="showTranslation"
        @translated="onTranslated" @toggle="showTranslation = !showTranslation" />
      <AddVocabButton :initial-term="question.content || ''" />
    </div>

    <!-- 作答证据：不推断未保存的状态 -->
    <div class="mt-4 rounded-xl p-4 border" :class="verdictClass">
      <p class="font-medium" :class="verdictTextClass">{{ statusText }}</p>
      <p v-if="statusKind === 'unknown'" class="mt-1 text-sm text-gray-600 dark:text-gray-300">记录不完整，无法核实本题的作答与判定</p>
      <p v-if="statusKind !== 'unanswered' && question.user_answer" class="mt-2 text-sm text-gray-600 dark:text-gray-300">
        你的答案: {{ question.user_answer }}
      </p>
      <p v-if="question.correct_answer" class="mt-2 text-sm text-gray-600 dark:text-gray-300">
        当场正确答案: {{ question.correct_answer }}
      </p>
    </div>

    <QuestionExplanation :key="question.id" :question="question" auto-reveal />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CheckCircleIcon, MinusCircleIcon, QuestionMarkCircleIcon, XCircleIcon } from '@heroicons/vue/24/outline'
import TranslateButton from './TranslateButton.vue'
import QuestionExplanation from './QuestionExplanation.vue'
import AddVocabButton from './AddVocabButton.vue'
import { reviewStatusLabel, reviewStatusOf } from '../utils/quizReview'

const props = defineProps({
  question: { type: Object, required: true },
})

const showTranslation = ref(false)

const options = computed(() => Array.isArray(props.question.options) ? props.question.options : [])
const statusKind = computed(() => reviewStatusOf(props.question))
const statusText = computed(() => reviewStatusLabel(props.question))
const hasFullTranslation = computed(() =>
  Boolean(props.question.content_zh) && options.value.every(option => option.text_zh))

function parseKeys(raw) {
  if (!raw) return []
  return String(raw).split(',').map(part => part.trim()).filter(Boolean)
}

// 未答题不显示用户选择；不可核实时保留服务端已保存的选择，但不据此推断对错
const userKeys = computed(() => statusKind.value === 'unanswered' ? [] : parseKeys(props.question.user_answer))
const correctKeys = computed(() => parseKeys(props.question.correct_answer))

const isUserKey = key => userKeys.value.includes(key)
const isCorrectKey = key => correctKeys.value.includes(key)

const statusBadgeClass = computed(() => ({
  correct: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  wrong: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400',
  unanswered: 'bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-gray-400',
  unknown: 'bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-gray-400',
}[statusKind.value]))

const statusIcon = computed(() => ({
  correct: CheckCircleIcon,
  wrong: XCircleIcon,
  unanswered: MinusCircleIcon,
  unknown: QuestionMarkCircleIcon,
}[statusKind.value]))

const userBadgeClass = computed(() =>
  statusKind.value === 'wrong'
    ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400'
    : 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-300')

function optionClass(key) {
  const base = 'flex items-start gap-3 rounded-xl border-2 p-4'
  if (isCorrectKey(key)) return `${base} border-emerald-400 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/20`
  if (isUserKey(key) && statusKind.value === 'wrong') return `${base} border-rose-400 bg-rose-50 dark:border-rose-600 dark:bg-rose-900/20`
  if (isUserKey(key)) return `${base} border-gray-400 bg-gray-50 dark:border-slate-500 dark:bg-slate-700/50`
  return `${base} border-gray-200 dark:border-slate-700`
}

const verdictClass = computed(() => ({
  correct: 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800',
  wrong: 'bg-rose-50 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800',
  unanswered: 'bg-gray-50 dark:bg-slate-700/40 border-gray-200 dark:border-slate-600',
  unknown: 'bg-gray-50 dark:bg-slate-700/40 border-gray-200 dark:border-slate-600',
}[statusKind.value]))

const verdictTextClass = computed(() => ({
  correct: 'text-emerald-700 dark:text-emerald-400',
  wrong: 'text-rose-700 dark:text-rose-400',
  unanswered: 'text-gray-600 dark:text-gray-300',
  unknown: 'text-gray-600 dark:text-gray-300',
}[statusKind.value]))

function onTranslated(data) {
  if (data.content_zh) props.question.content_zh = data.content_zh
  if (data.options_zh) {
    for (const option of options.value) {
      const translated = data.options_zh.find(item => item.key === option.key)
      if (translated) option.text_zh = translated.text_zh
    }
  }
  showTranslation.value = true
}
</script>
