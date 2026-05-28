<template>
  <div>
  <div v-if="!quizStore.session" class="text-center py-12 text-gray-500 dark:text-gray-400">加载中...</div>
  <div v-else>
    <!-- 顶部信息栏 -->
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0">
        <h1 class="text-base md:text-lg font-bold text-gray-900 dark:text-white truncate">
          {{ quizStore.session.bank_name || '答题' }}
        </h1>
        <span class="rounded-full bg-primary-100 dark:bg-primary-900/30 px-2 py-0.5 text-xs font-medium text-primary-700 dark:text-primary-400 flex-shrink-0">
          {{ quizStore.currentIndex + 1 }} / {{ quizStore.questions.length }}
        </span>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <span v-if="isExamMode" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">模拟考试</span>
        <label class="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 cursor-pointer select-none">
          <input type="checkbox" v-model="autoNext"
            class="h-3.5 w-3.5 rounded border-gray-300 dark:border-slate-600 text-primary-600 dark:text-primary-500" />
          自动下一题
        </label>
      </div>
    </div>

    <!-- 进度条 -->
    <div class="mb-4 h-1 w-full rounded-full bg-gray-200 dark:bg-slate-700">
      <div class="h-1 rounded-full bg-gradient-to-r from-primary-500 to-sky-400 transition-all duration-300"
        :style="{ width: `${((quizStore.currentIndex + 1) / quizStore.questions.length) * 100}%` }"></div>
    </div>

    <div class="flex gap-4 items-start">
      <!-- 左侧题目导航 -->
      <div class="hidden md:block w-48 flex-shrink-0">
        <div class="sticky top-20 rounded-xl bg-white dark:bg-slate-800 shadow-card overflow-hidden flex flex-col max-h-[calc(100vh-7rem)]">
          <div class="px-4 py-2.5 bg-gray-50 dark:bg-slate-700/50 border-b border-gray-100 dark:border-slate-700 flex items-center justify-between flex-shrink-0">
            <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">题目导航</span>
            <span class="text-[10px] text-gray-400 dark:text-gray-500">
              {{ totalAnsweredCount }} / {{ quizStore.questions.length }}
            </span>
          </div>
          <div class="flex-1 overflow-y-auto">
            <div class="py-1">
              <button v-for="(q, i) in quizStore.questions" :key="q.id"
                @click="jumpTo(i)"
                class="flex w-full items-center gap-2 px-4 py-2 text-sm transition-colors"
                :class="i === quizStore.currentIndex
                  ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 font-medium border-l-[3px] border-primary-600'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-slate-700/50 border-l-[3px] border-transparent'">
                <span class="w-6 text-xs text-right flex-shrink-0"
                  :class="i === quizStore.currentIndex ? 'text-primary-600 dark:text-primary-400 font-semibold' : 'text-gray-400 dark:text-gray-500'">
                  {{ i + 1 }}
                </span>
                <span class="flex-1 truncate text-left text-xs"
                  :class="i === quizStore.currentIndex ? 'text-primary-700 dark:text-primary-400' : 'text-gray-500 dark:text-gray-400'">
                  第 {{ i + 1 }} 题
                </span>
                <span v-if="i in answerResults" class="flex-shrink-0">
                  <span v-if="isExamMode" class="inline-flex items-center rounded-full bg-sky-100 dark:bg-sky-900/30 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:text-sky-400">已答</span>
                  <span v-else-if="answerResults[i]" class="inline-flex items-center rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400">正确</span>
                  <span v-else class="inline-flex items-center rounded-full bg-rose-100 dark:bg-rose-900/30 px-1.5 py-0.5 text-[10px] font-medium text-rose-700 dark:text-rose-400">错误</span>
                </span>
                <span v-else class="flex-shrink-0 inline-flex items-center rounded-full bg-gray-100 dark:bg-slate-700 px-1.5 py-0.5 text-[10px] text-gray-400 dark:text-gray-500">未答</span>
              </button>
            </div>
          </div>
          <!-- 底部统计 -->
          <div class="px-4 py-2 bg-gray-50 dark:bg-slate-700/50 border-t border-gray-100 dark:border-slate-700 flex justify-between text-[10px] text-gray-400 dark:text-gray-500 flex-shrink-0">
            <template v-if="isExamMode">
              <span class="flex items-center gap-1">
                <span class="inline-block w-2 h-2 rounded-full bg-sky-400"></span>
                已答 {{ totalAnsweredCount }}
              </span>
              <span class="flex items-center gap-1">
                <span class="inline-block w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600"></span>
                未答 {{ unansweredCount }}
              </span>
            </template>
            <template v-else>
              <span class="flex items-center gap-1">
                <span class="inline-block w-2 h-2 rounded-full bg-emerald-400"></span>
                正确 {{ correctCount }}
              </span>
              <span class="flex items-center gap-1">
                <span class="inline-block w-2 h-2 rounded-full bg-rose-400"></span>
                错误 {{ wrongCount }}
              </span>
              <span class="flex items-center gap-1">
                <span class="inline-block w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600"></span>
                未答 {{ unansweredCount }}
              </span>
            </template>
          </div>
        </div>
      </div>

      <!-- 移动端底部导航 -->
      <div class="md:hidden fixed bottom-14 left-0 right-0 z-20 bg-white/95 dark:bg-slate-800/95 backdrop-blur border-t border-gray-200 dark:border-slate-700 px-3 py-2 safe-area-bottom">
        <div class="flex gap-1 overflow-x-auto scrollbar-hide">
          <button v-for="(q, i) in quizStore.questions" :key="q.id"
            @click="jumpTo(i)"
            class="flex-shrink-0 w-8 h-8 rounded text-xs font-medium transition-all"
            :class="navBtnClass(i)">
            {{ i + 1 }}
          </button>
        </div>
      </div>

      <!-- 右侧答题区 -->
      <div class="flex-1 min-w-0 pb-28 md:pb-0">
        <QuestionCard
          :question="currentQuestion"
          :current-index="quizStore.currentIndex"
          :total="quizStore.questions.length"
          :hide-progress="true"
          :initial-answer="currentInitialAnswer"
          :initial-result="currentInitialResult"
          :answer-count="currentQuestion?.user_answer_count ?? 0"
          :exam-mode="isExamMode"
          @submit="handleSubmit"
          @next="quizStore.nextQuestion()"
          @prev="quizStore.prevQuestion()"
          @finish="handleFinish"
          @translated="handleTranslated"
        />
      </div>
    </div>
  </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuizStore } from '../stores/quiz'
import { currentExamPath } from '../utils/examRoutes'
import { useToast } from '../composables/useToast'
import QuestionCard from '../components/QuestionCard.vue'
import client from '../api/client'

const route = useRoute()
const router = useRouter()
const quizStore = useQuizStore()
const toast = useToast()

const currentQuestion = computed(() => quizStore.questions[quizStore.currentIndex])

// 记录每题的答题结果：{ [index]: true/false }
const answerResults = reactive({})
// 会话恢复映射：questionId -> user_answer
const questionAnswerMap = reactive({})
// 会话恢复映射：questionId -> { is_correct, correct_answer, explanation, explanation_zh }
const questionResultMap = reactive({})
const autoNext = ref(false)
const prewarmKeys = new Set()

const isExamMode = computed(() => quizStore.session?.mode === 'exam')
const totalAnsweredCount = computed(() => Object.keys(answerResults).length)
const correctCount = computed(() => Object.values(answerResults).filter(v => v === true).length)
const wrongCount = computed(() => Object.values(answerResults).filter(v => v === false).length)
const unansweredCount = computed(() => quizStore.questions.length - totalAnsweredCount.value)

const currentInitialAnswer = computed(() => {
  const questionId = currentQuestion.value?.id
  if (!questionId) return null
  return questionAnswerMap[questionId] ?? null
})

const currentInitialResult = computed(() => {
  const questionId = currentQuestion.value?.id
  if (!questionId) return null
  return questionResultMap[questionId] ?? null
})

function clearReactiveMap(map) {
  Object.keys(map).forEach((k) => delete map[k])
}

function triggerAiPrewarm() {
  const sessionId = quizStore.session?.id
  if (!sessionId || !currentQuestion.value?.id) return

  const ids = [currentQuestion.value.id]
  const nextQuestion = quizStore.questions[quizStore.currentIndex + 1]
  if (nextQuestion?.id) ids.push(nextQuestion.id)

  const key = `${sessionId}:${ids.join(',')}`
  if (prewarmKeys.has(key)) return
  prewarmKeys.add(key)

  client.post('/ai/prewarm', { session_id: sessionId, question_ids: ids }).catch(() => {})
}

function restoreSessionState(sessionData) {
  clearReactiveMap(questionAnswerMap)
  clearReactiveMap(questionResultMap)
  clearReactiveMap(answerResults)

  const examMode = sessionData.session?.mode === 'exam'

  ;(sessionData.answers || []).forEach((a) => {
    questionAnswerMap[a.question_id] = a.user_answer
    if (examMode) {
      questionResultMap[a.question_id] = { submitted: true }
    } else {
      questionResultMap[a.question_id] = {
        is_correct: a.is_correct,
        correct_answer: a.correct_answer,
        explanation: a.explanation,
        explanation_zh: a.explanation_zh,
      }
    }
  })

  ;(sessionData.questions || []).forEach((q, i) => {
    if (questionResultMap[q.id]) {
      answerResults[i] = examMode ? 'submitted' : questionResultMap[q.id].is_correct
    }
  })

  const questionCount = (sessionData.questions || []).length
  const rawResumeIndex = sessionData.session?.resume_index
  const resumeIndex = typeof rawResumeIndex === 'number' ? rawResumeIndex : Number(rawResumeIndex)
  if (rawResumeIndex !== null && rawResumeIndex !== undefined && Number.isInteger(resumeIndex) && questionCount > 0) {
    quizStore.currentIndex = Math.min(Math.max(resumeIndex, 0), questionCount - 1)
    return
  }

  const firstUnanswered = (sessionData.questions || []).findIndex(q => !questionResultMap[q.id])
  quizStore.currentIndex = firstUnanswered >= 0 ? firstUnanswered : 0
}

onMounted(async () => {
  try {
    const res = await client.get(`/quiz/session/${route.params.sessionId}`)
    if (res.data.session.is_completed) {
      router.replace(currentExamPath(route, 'quizResult', { sessionId: route.params.sessionId }))
      return
    }

    if (res.data.questions) {
      quizStore.session = res.data.session
      quizStore.questions = res.data.questions
      restoreSessionState(res.data)
      triggerAiPrewarm()
    } else {
      router.replace(currentExamPath(route, 'dashboard'))
    }
  } catch {
    router.replace(currentExamPath(route, 'dashboard'))
  }
})

watch(
  () => [quizStore.session?.id, quizStore.currentIndex, currentQuestion.value?.id],
  () => triggerAiPrewarm(),
)

function jumpTo(index) {
  quizStore.currentIndex = index
}

function navBtnClass(index) {
  if (index === quizStore.currentIndex) {
    return 'bg-primary-600 text-white shadow-sm ring-2 ring-primary-300 dark:ring-primary-700'
  }
  if (index in answerResults) {
    if (isExamMode.value) {
      return 'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400 hover:bg-sky-200 dark:hover:bg-sky-900/50'
    }
    return answerResults[index]
      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-200 dark:hover:bg-emerald-900/50'
      : 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400 hover:bg-rose-200 dark:hover:bg-rose-900/50'
  }
  return 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-slate-600'
}

async function handleSubmit(answer, callback) {
  try {
    // 冻结提交上下文，避免异步期间 currentIndex 变化导致回写错位
    const submitQuestionId = currentQuestion.value.id
    const submitIndex = quizStore.currentIndex
    const canAutoNext = autoNext.value
    const hasNext = submitIndex < quizStore.questions.length - 1

    const res = await quizStore.submitAnswer(submitQuestionId, answer)

    if (typeof res.user_answer_count === 'number') {
      const targetQuestion = quizStore.questions.find(q => q.id === submitQuestionId)
      if (targetQuestion) {
        targetQuestion.user_answer_count = res.user_answer_count
      }
    }

    questionAnswerMap[submitQuestionId] = answer

    // 模拟考试模式：仅标记为已提交，不存储对错结果
    if (isExamMode.value) {
      questionResultMap[submitQuestionId] = { submitted: true }
      answerResults[submitIndex] = 'submitted'
      callback(res)

      if (canAutoNext && hasNext) {
        setTimeout(() => {
          if (quizStore.currentIndex === submitIndex) {
            quizStore.nextQuestion()
          }
        }, 300)
      }
      return
    }

    // 提交后覆盖映射，保证切回本题时展示最新答案与结果
    questionResultMap[submitQuestionId] = {
      is_correct: res.is_correct,
      correct_answer: res.correct_answer,
      explanation: res.explanation,
      explanation_zh: res.explanation_zh,
    }

    answerResults[submitIndex] = res.is_correct
    callback(res)

    if (canAutoNext && hasNext) {
      setTimeout(() => {
        if (quizStore.currentIndex === submitIndex) {
          quizStore.nextQuestion()
        }
      }, 1500)
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '提交失败')
  }
}

async function handleFinish() {
  try {
    await quizStore.finishQuiz()
    router.push(currentExamPath(route, 'quizResult', { sessionId: quizStore.session.id }))
  } catch (e) {
    toast.error(e.response?.data?.error || '结束失败')
  }
}

function handleTranslated(data) {
  const q = currentQuestion.value
  if (data.content_zh) q.content_zh = data.content_zh
  if (data.options_zh) {
    for (const opt of q.options) {
      const translated = data.options_zh.find(o => o.key === opt.key)
      if (translated) opt.text_zh = translated.text_zh
    }
  }
}
</script>
