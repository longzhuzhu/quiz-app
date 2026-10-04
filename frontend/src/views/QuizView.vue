<template>
  <div class="pb-6 md:pb-16">
    <!-- 加载失败：内联可重试错误态，不冒充空态 -->
    <div v-if="loadError" class="py-16 text-center">
      <XCircleIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-500 dark:text-gray-400">答题会话加载失败，请重试</p>
      <BaseButton variant="primary" size="sm" class="mt-4" @click="loadSession">重新加载</BaseButton>
    </div>

    <div v-else-if="!quizStore.session" class="text-center py-12 text-gray-500 dark:text-gray-400">加载中...</div>

    <div v-else>
    <!-- 顶部信息栏 -->
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0">
        <h1 class="text-base md:text-lg font-bold text-gray-900 dark:text-white truncate">
          {{ quizStore.session.bank_name || '答题' }}
        </h1>
        <span v-if="isExamMode" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400 flex-shrink-0">模拟考试</span>
        <span
          v-else-if="isTopicMode"
          class="max-w-[12rem] truncate rounded-full bg-sky-100 dark:bg-sky-900/30 px-2 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400 flex-shrink-0"
          :title="topicModeLabel"
        >{{ topicModeLabel }}</span>
      </div>
      <label class="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 cursor-pointer select-none">
        <input type="checkbox" v-model="autoNext"
          class="h-3.5 w-3.5 rounded border-gray-300 dark:border-slate-600 text-primary-600 dark:text-primary-500" />
        自动下一题
      </label>
    </div>

    <!-- 位置与完成度分离：进度条按已提交数量计算 -->
    <div class="mb-2 flex items-center justify-between gap-3">
      <span class="text-sm font-medium text-gray-900 dark:text-white">第 {{ quizStore.currentIndex + 1 }} / {{ total }} 题</span>
      <span class="text-xs text-gray-500 dark:text-gray-400">已答 {{ totalAnsweredCount }} · 未答 {{ unansweredCount }}</span>
    </div>
    <div class="mb-5 h-1 w-full rounded-full bg-gray-200 dark:bg-slate-700">
      <div class="h-1 rounded-full bg-primary-500 transition-all duration-300"
        :style="{ width: progressPercent + '%' }"></div>
    </div>

    <div class="flex gap-4 items-start">
      <!-- 桌面题目导航 -->
      <div class="hidden md:block w-48 flex-shrink-0">
        <div class="sticky top-20 rounded-xl bg-white dark:bg-slate-800 shadow-card overflow-hidden flex flex-col max-h-[calc(100vh-7rem)]">
          <div class="px-4 py-2.5 bg-gray-50 dark:bg-slate-700/50 border-b border-gray-100 dark:border-slate-700 flex items-center justify-between flex-shrink-0">
            <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">题目导航</span>
            <span class="text-[10px] text-gray-400 dark:text-gray-500">
              {{ totalAnsweredCount }} / {{ total }}
            </span>
          </div>
          <div class="flex-1 overflow-y-auto">
            <div class="py-1">
              <button v-for="(q, i) in quizStore.questions" :key="q.id"
                @click="goTo(i)"
                class="flex w-full items-center justify-between gap-2 px-3.5 py-2 text-sm transition-colors"
                :class="i === quizStore.currentIndex
                  ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 font-medium border-l-[3px] border-primary-600'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-slate-700/50 border-l-[3px] border-transparent'">
                <span class="w-6 text-xs flex-shrink-0"
                  :class="i === quizStore.currentIndex ? 'text-primary-600 dark:text-primary-400 font-semibold' : 'text-gray-400 dark:text-gray-500'">
                  {{ i + 1 }}
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
          <!-- 底部统计 + 结束入口 -->
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
          <div class="px-3 py-2 border-t border-gray-100 dark:border-slate-700 flex-shrink-0">
            <BaseButton variant="secondary" size="sm" class="w-full" @click="requestFinish">结束答题</BaseButton>
          </div>
        </div>
      </div>

      <!-- 答题区 -->
      <div class="flex-1 min-w-0">
        <QuestionCard
          :question="currentQuestion"
          :current-index="quizStore.currentIndex"
          :total="total"
          :exam-mode="isExamMode"
          :answer-count="currentQuestion?.user_answer_count ?? 0"
          :session-id="quizStore.session?.id"
          :selected-answers="currentDraft"
          :submitted-answer="currentSubmittedAnswer"
          :result="currentResult"
          :editing="isEditingCurrent"
          :submitting="submitting"
          :show-translation="showTranslation"
          @update:selected-answers="setDraft"
          @update:show-translation="showTranslation = $event"
          @submit="submitCurrent"
          @start-editing="startEditing"
          @cancel-editing="cancelEditing"
          @translated="handleTranslated"
          @answer-corrected="handleAnswerCorrected"
        />
      </div>
    </div>
    </div>

    <!-- 底部固定操作条：主操作常驻可见 -->
    <div v-if="!loadError && quizStore.session"
      class="fixed inset-x-0 bottom-0 z-30 border-t border-gray-200 dark:border-slate-700 bg-white/95 dark:bg-slate-800/95 backdrop-blur safe-area-bottom">
      <div class="mx-auto flex max-w-6xl items-center gap-2 px-3 md:px-4 py-2.5">
        <button type="button" aria-label="题目列表" @click="showQuestionPanel = true"
          class="md:hidden inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-button text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-slate-700 transition-colors">
          <QueueListIcon class="h-5 w-5" />
        </button>
        <BaseButton variant="secondary" size="md" class="shrink-0 min-h-11" @click="goPrev" :disabled="quizStore.currentIndex === 0">上一题</BaseButton>
        <div class="min-w-0 flex-1 text-center text-xs sm:text-sm text-gray-500 dark:text-gray-400">
          <template v-if="autoNextPending">
            <span>即将进入下一题…</span>
            <button type="button" class="ml-2 font-medium text-primary-600 dark:text-primary-400" @click="cancelAutoNext">取消</button>
          </template>
          <template v-else>
            <span class="md:hidden">已答 {{ totalAnsweredCount }}/{{ total }}</span>
            <span class="hidden md:inline">已答 {{ totalAnsweredCount }} · 未答 {{ unansweredCount }}</span>
          </template>
        </div>
        <BaseButton variant="primary" size="md" class="shrink-0 min-h-11 min-w-[6.5rem]"
          :loading="submitting" :disabled="primaryAction.disabled" @click="primaryAction.handler">
          {{ primaryAction.label }}
        </BaseButton>
      </div>
    </div>

    <!-- 手机题号面板：按需展开 -->
    <div v-if="showQuestionPanel" class="fixed inset-0 z-40 md:hidden" @click.self="showQuestionPanel = false">
      <div class="absolute inset-x-0 bottom-0 max-h-[70vh] overflow-y-auto rounded-t-2xl bg-white dark:bg-slate-800 shadow-lg border-t border-gray-200 dark:border-slate-700 p-4 pb-6 safe-area-bottom">
        <div class="mb-3 flex items-center justify-between">
          <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">题目列表</span>
          <span class="text-xs text-gray-400 dark:text-gray-500">已答 {{ totalAnsweredCount }} / {{ total }}</span>
        </div>
        <div class="grid grid-cols-6 gap-2">
          <button v-for="(q, i) in quizStore.questions" :key="q.id"
            @click="panelJumpTo(i)"
            class="h-11 w-11 rounded-lg text-sm font-medium transition-colors"
            :class="navBtnClass(i)">
            {{ i + 1 }}
          </button>
        </div>
        <BaseButton variant="secondary" class="mt-4 w-full min-h-11" @click="requestFinish">
          结束答题<template v-if="unansweredCount > 0">（未答 {{ unansweredCount }} 题）</template>
        </BaseButton>
      </div>
    </div>

    <ConfirmDialog
      :open="showFinishConfirm"
      danger
      title="结束答题"
      :message="finishConfirmMessage"
      confirm-text="结束答题"
      @confirm="handleFinish"
      @cancel="showFinishConfirm = false"
    />
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuizStore } from '../stores/quiz'
import { currentExamPath } from '../utils/examRoutes'
import { sessionModeLabel } from '../utils/quizMode'
import { useToast } from '../composables/useToast'
import QuestionCard from '../components/QuestionCard.vue'
import BaseButton from '../components/BaseButton.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import client from '../api/client'
import { QueueListIcon, XCircleIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const router = useRouter()
const quizStore = useQuizStore()
const toast = useToast()

const currentQuestion = computed(() => quizStore.questions[quizStore.currentIndex])
const total = computed(() => quizStore.questions.length)

// 记录每题的提交结果：{ [index]: true/false/'submitted' }
const answerResults = reactive({})
// 已提交答案：questionId -> user_answer
const questionAnswerMap = reactive({})
// 已提交结果：questionId -> { is_correct, correct_answer, explanation, explanation_zh }（同一对象约定）
const questionResultMap = reactive({})
// 未提交草稿：questionId -> string[]（N1：切题往返保留，不计入已答）
const drafts = reactive({})
const editingQuestionId = ref(null)
const showTranslation = ref(false)
const autoNext = ref(false)
const prewarmKeys = new Set()

const loadError = ref(false)
const submitting = ref(false)
const showQuestionPanel = ref(false)
const showFinishConfirm = ref(false)
const autoNextPending = ref(false)
let autoNextTimer = null

const isExamMode = computed(() => quizStore.session?.mode === 'exam')
const isTopicMode = computed(() => quizStore.session?.mode === 'topic')
const topicModeLabel = computed(() => sessionModeLabel(quizStore.session))
const totalAnsweredCount = computed(() => Object.keys(answerResults).length)
const correctCount = computed(() => Object.values(answerResults).filter(v => v === true).length)
const wrongCount = computed(() => Object.values(answerResults).filter(v => v === false).length)
const unansweredCount = computed(() => total.value - totalAnsweredCount.value)
const progressPercent = computed(() => {
  if (total.value <= 0) return 0
  return Math.round((totalAnsweredCount.value / total.value) * 100)
})

const currentDraft = computed(() => {
  const questionId = currentQuestion.value?.id
  if (!questionId) return []
  return drafts[questionId] ?? []
})

const currentSubmittedAnswer = computed(() => {
  const questionId = currentQuestion.value?.id
  if (!questionId) return ''
  return questionAnswerMap[questionId] ?? ''
})

const currentResult = computed(() => {
  const questionId = currentQuestion.value?.id
  if (!questionId) return null
  return questionResultMap[questionId] ?? null
})

const isEditingCurrent = computed(() => editingQuestionId.value != null && editingQuestionId.value === currentQuestion.value?.id)

const finishConfirmMessage = computed(() => {
  return `还有 ${unansweredCount.value} 题未作答，未答题将记为未答。确定结束本次答题吗？`
})

const primaryAction = computed(() => {
  if (!currentQuestion.value) {
    return { label: '…', handler: () => {}, disabled: true }
  }
  const isLast = quizStore.currentIndex >= total.value - 1
  if (isEditingCurrent.value || !currentResult.value) {
    const hasDraft = currentDraft.value.length > 0
    return {
      label: '提交答案',
      handler: submitCurrent,
      disabled: !hasDraft || submitting.value,
    }
  }
  if (isLast) {
    return { label: '完成答题', handler: requestFinish, disabled: false }
  }
  return {
    label: '下一题',
    handler: () => goTo(quizStore.currentIndex + 1),
    disabled: false,
  }
})

function setDraft(keys) {
  const questionId = currentQuestion.value?.id
  if (!questionId) return
  drafts[questionId] = [...keys]
}

function startEditing() {
  const questionId = currentQuestion.value?.id
  if (!questionId) return
  // 以已提交答案初始化草稿，便于微调；旧结果保留至新提交成功
  if (!drafts[questionId]) {
    drafts[questionId] = String(questionAnswerMap[questionId] ?? '')
      .split(',').map(s => s.trim()).filter(Boolean)
  }
  editingQuestionId.value = questionId
}

function cancelEditing() {
  const questionId = currentQuestion.value?.id
  if (!questionId) return
  delete drafts[questionId]
  editingQuestionId.value = null
}

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
  clearReactiveMap(drafts)
  editingQuestionId.value = null

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

async function loadSession() {
  loadError.value = false
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
    loadError.value = true
  }
}

onMounted(() => {
  loadSession()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  cancelAutoNext()
})

watch(
  () => [quizStore.session?.id, quizStore.currentIndex, currentQuestion.value?.id],
  () => triggerAiPrewarm(),
)

function goTo(index) {
  const clamped = Math.min(Math.max(index, 0), total.value - 1)
  if (clamped === quizStore.currentIndex) return
  quizStore.currentIndex = clamped
  // 手动切题取消等待中的自动跳转，并把题干起点带回可见区
  cancelAutoNext()
  window.scrollTo({ top: 0, behavior: 'auto' })
}

function goPrev() {
  goTo(quizStore.currentIndex - 1)
}

function panelJumpTo(index) {
  showQuestionPanel.value = false
  goTo(index)
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

function scheduleAutoNext(submitIndex) {
  cancelAutoNext()
  autoNextTimer = setTimeout(() => {
    autoNextTimer = null
    autoNextPending.value = false
    if (quizStore.currentIndex === submitIndex) {
      goTo(submitIndex + 1)
    }
  }, 1500)
  autoNextPending.value = true
}

function cancelAutoNext() {
  if (autoNextTimer) {
    clearTimeout(autoNextTimer)
    autoNextTimer = null
  }
  autoNextPending.value = false
}

async function submitCurrent() {
  const question = currentQuestion.value
  if (!question || submitting.value) return
  const draft = drafts[question.id] || []
  if (draft.length === 0) return

  submitting.value = true
  try {
    // 冻结提交上下文，避免异步期间 currentIndex 变化导致回写错位
    const submitQuestionId = question.id
    const submitIndex = quizStore.currentIndex
    const answer = [...draft].sort().join(',')

    const res = await quizStore.submitAnswer(submitQuestionId, answer)

    if (typeof res.user_answer_count === 'number') {
      const targetQuestion = quizStore.questions.find(q => q.id === submitQuestionId)
      if (targetQuestion) {
        targetQuestion.user_answer_count = res.user_answer_count
      }
    }

    questionAnswerMap[submitQuestionId] = answer

    const hasNext = submitIndex < total.value - 1

    // 模拟考试模式：仅标记为已提交，不存储对错结果
    if (isExamMode.value) {
      questionResultMap[submitQuestionId] = { submitted: true }
      answerResults[submitIndex] = 'submitted'
      delete drafts[submitQuestionId]
      if (editingQuestionId.value === submitQuestionId) editingQuestionId.value = null

      if (autoNext.value && hasNext) {
        setTimeout(() => {
          if (quizStore.currentIndex === submitIndex) {
            goTo(submitIndex + 1)
          }
        }, 300)
      }
      return
    }

    // 提交后覆盖映射，保证切回本题时展示最新答案与结果。
    // 必须把同一对象交给 QuestionCard，更新 AI 解析时才能写回这份缓存。
    const resultPayload = {
      is_correct: res.is_correct,
      correct_answer: res.correct_answer,
      explanation: res.explanation,
      explanation_zh: res.explanation_zh,
    }
    questionResultMap[submitQuestionId] = resultPayload

    answerResults[submitIndex] = res.is_correct
    delete drafts[submitQuestionId]
    if (editingQuestionId.value === submitQuestionId) editingQuestionId.value = null

    // 自动下一题仅在答对时触发；错题停留供复盘（F1）
    if (autoNext.value && res.is_correct === true && hasNext) {
      scheduleAutoNext(submitIndex)
    }
  } catch (e) {
    toast.error(e.response?.data?.error || e.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

function requestFinish() {
  showQuestionPanel.value = false
  if (unansweredCount.value > 0) {
    showFinishConfirm.value = true
    return
  }
  handleFinish()
}

async function handleFinish() {
  showFinishConfirm.value = false
  try {
    await quizStore.finishQuiz()
    router.push(currentExamPath(route, 'quizResult', { sessionId: quizStore.session.id }))
  } catch (e) {
    toast.error(e.response?.data?.error || '结束失败')
  }
}

function handleTranslated(data) {
  const q = currentQuestion.value
  if (!q) return
  if (data.content_zh) q.content_zh = data.content_zh
  if (data.options_zh) {
    for (const opt of q.options) {
      const translated = data.options_zh.find(o => o.key === opt.key)
      if (translated) opt.text_zh = translated.text_zh
    }
  }
}

function handleAnswerCorrected(payload) {
  const questionId = payload?.questionId
  if (!questionId) return

  const mapped = questionResultMap[questionId]
  if (mapped) {
    mapped.is_correct = payload.is_correct
    mapped.correct_answer = payload.correct_answer
    mapped.explanation = payload.explanation
    mapped.explanation_zh = payload.explanation_zh
  } else {
    questionResultMap[questionId] = {
      is_correct: payload.is_correct,
      correct_answer: payload.correct_answer,
      explanation: payload.explanation,
      explanation_zh: payload.explanation_zh,
    }
  }

  const question = quizStore.questions.find(q => q.id === questionId)
  if (question) {
    question.correct_answer = payload.correct_answer
    question.explanation = payload.explanation
    question.explanation_zh = payload.explanation_zh
  }

  const idx = quizStore.questions.findIndex(q => q.id === questionId)
  if (idx >= 0 && payload.is_correct != null) {
    answerResults[idx] = payload.is_correct
  }
}

// 键盘快捷键：A–Z / 数字选择选项，Enter 提交或切题（输入焦点与组合键不拦截）
function onKeydown(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const target = e.target
  if (target) {
    const tag = target.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) return
  }
  if (loadError.value || !quizStore.session || !currentQuestion.value) return
  if (showFinishConfirm.value) return

  if (e.key === 'Enter') {
    e.preventDefault()
    if (!primaryAction.value.disabled) primaryAction.value.handler()
    return
  }

  const question = currentQuestion.value
  // 已答且未进入重新作答时锁定选择
  if (currentResult.value && !isEditingCurrent.value) return

  let optionIndex = -1
  if (/^[a-zA-Z]$/.test(e.key)) {
    optionIndex = e.key.toUpperCase().charCodeAt(0) - 65
  } else if (/^[1-9]$/.test(e.key)) {
    optionIndex = Number(e.key) - 1
  }
  const options = question.options || []
  if (optionIndex < 0 || optionIndex >= options.length) return

  e.preventDefault()
  const key = options[optionIndex].key
  const current = drafts[question.id] || []
  if (question.question_type === 'multiple') {
    drafts[question.id] = current.includes(key)
      ? current.filter(k => k !== key)
      : [...current, key]
  } else {
    drafts[question.id] = [key]
  }
}
</script>
