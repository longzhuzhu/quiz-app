<template>
  <div>
    <!-- 加载中 -->
    <SkeletonLoader v-if="!session && !loadFailed" type="card" :count="2" />

    <!-- 加载失败 -->
    <div v-else-if="loadFailed" class="py-16 text-center">
      <XCircleIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-500 dark:text-gray-400">加载失败，请返回重试</p>
      <router-link :to="backPath" class="mt-4 inline-block text-primary-600 hover:text-primary-500 dark:text-primary-400 dark:hover:text-primary-300">返回</router-link>
    </div>

    <div v-else>
      <!-- 顶部信息栏 -->
      <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2 min-w-0">
          <h1 class="text-base md:text-lg font-bold text-gray-900 dark:text-white truncate">
            {{ bankName }}
          </h1>
          <span data-testid="review-counter" class="rounded-full bg-primary-100 dark:bg-primary-900/30 px-2 py-0.5 text-xs font-medium text-primary-700 dark:text-primary-400 flex-shrink-0">
            {{ headerCounter }}
          </span>
        </div>
        <span v-if="modeText" class="rounded-full bg-gray-100 dark:bg-slate-700 px-2 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-300">{{ modeText }}</span>
      </div>

      <!-- 统计摘要 -->
      <div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600 dark:text-gray-400">
        <span>正确 <span class="font-semibold text-emerald-600 dark:text-emerald-400" data-testid="summary-correct">{{ correctCount }}</span></span>
        <span>错误 <span class="font-semibold text-rose-600 dark:text-rose-400" data-testid="summary-wrong">{{ wrongCount }}</span></span>
        <span>未答 <span class="font-semibold text-gray-900 dark:text-white" data-testid="summary-unanswered">{{ unansweredCount }}</span></span>
        <span>本场正确率 <span class="font-semibold text-gray-900 dark:text-white" data-testid="summary-accuracy">{{ accuracyText }}</span></span>
      </div>

      <!-- 旧会话兼容提示 -->
      <p v-if="session.has_snapshot === false" data-testid="snapshot-warning"
        class="mb-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
        历史题目未保存快照，当前内容可能已变更
      </p>

      <!-- 筛选 -->
      <div class="mb-4 flex flex-wrap gap-2" role="group" aria-label="复盘筛选">
        <button v-for="item in filterOptions" :key="item.value" type="button"
          :data-testid="`review-filter-${item.value}`"
          :aria-pressed="filter === item.value"
          class="rounded-full px-3 py-1.5 text-sm font-medium transition-colors"
          :class="filter === item.value
            ? 'bg-primary-600 text-white'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600'"
          @click="applyFilter(item.value)">
          {{ item.label }} {{ item.count }}
        </button>
      </div>

      <!-- 空状态 -->
      <div v-if="visibleQuestions.length === 0" data-testid="review-empty"
        class="rounded-xl bg-white dark:bg-slate-800 shadow-card py-16 text-center text-gray-500 dark:text-gray-400">
        <p class="text-lg font-medium">{{ emptyText }}</p>
      </div>

      <div v-else class="flex gap-4 items-start">
        <!-- 桌面题号侧栏 -->
        <div class="hidden md:block w-48 flex-shrink-0">
          <div class="sticky top-20 rounded-xl bg-white dark:bg-slate-800 shadow-card overflow-hidden flex flex-col max-h-[calc(100vh-7rem)]">
            <div class="px-4 py-2.5 bg-gray-50 dark:bg-slate-700/50 border-b border-gray-100 dark:border-slate-700 flex-shrink-0">
              <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">题目导航</span>
            </div>
            <div class="flex-1 overflow-y-auto">
              <div class="py-1">
                <button v-for="(q, i) in visibleQuestions" :key="q.id" type="button"
                  :data-testid="`review-nav-${q.index}`"
                  class="flex w-full items-center gap-2 px-4 py-2 text-sm transition-colors"
                  :class="i === currentVisibleIndex
                    ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 font-medium border-l-[3px] border-primary-600'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-slate-700/50 border-l-[3px] border-transparent'"
                  @click="currentVisibleIndex = i">
                  <span class="w-6 text-xs text-right flex-shrink-0">{{ q.index }}</span>
                  <span class="flex-1 truncate text-left text-xs">第 {{ q.index }} 题</span>
                  <span class="flex-shrink-0 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium" :class="badgeClass(q)">
                    {{ reviewStatusLabel(q) }}
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 移动端底部题号导航 -->
        <div class="md:hidden fixed bottom-14 left-0 right-0 z-20 bg-white/95 dark:bg-slate-800/95 backdrop-blur border-t border-gray-200 dark:border-slate-700 px-3 py-2 safe-area-bottom">
          <div class="flex gap-1 overflow-x-auto scrollbar-hide">
            <button v-for="(q, i) in visibleQuestions" :key="q.id" type="button"
              :data-testid="`review-nav-mobile-${q.index}`"
              class="flex-shrink-0 w-8 h-8 rounded text-xs font-medium transition-all"
              :class="navBtnClass(q, i)"
              @click="currentVisibleIndex = i">
              {{ q.index }}
            </button>
          </div>
        </div>

        <!-- 复盘内容区 -->
        <div class="flex-1 min-w-0 pb-28 md:pb-0">
          <ReviewQuestionCard v-if="currentQuestion" :key="currentQuestion.id" :question="currentQuestion" />

          <div class="mt-4 flex flex-wrap justify-between items-center gap-2">
            <BaseButton variant="secondary" size="sm" @click="goPrev" :disabled="currentVisibleIndex === 0">上一题</BaseButton>
            <BaseButton variant="secondary" size="sm" @click="goNext" :disabled="currentVisibleIndex >= visibleQuestions.length - 1">下一题</BaseButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { XCircleIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { currentExamPath } from '../utils/examRoutes'
import { sessionModeLabel } from '../utils/quizMode'
import { normalizeReviewFilter, reviewStatusLabel, reviewStatusOf, visibleReviewQuestions } from '../utils/quizReview'
import ReviewQuestionCard from '../components/ReviewQuestionCard.vue'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'

const route = useRoute()
const router = useRouter()
const session = ref(null)
const questions = ref([])
const loadFailed = ref(false)
const filter = ref(normalizeReviewFilter(route.query.filter))
const currentVisibleIndex = ref(0)
let loadGeneration = 0

const visibleQuestions = computed(() => visibleReviewQuestions(questions.value, filter.value))
const currentQuestion = computed(() => visibleQuestions.value[currentVisibleIndex.value] || null)
const backPath = computed(() => currentExamPath(route, 'quizResult', { sessionId: route.params.sessionId }))

const bankName = computed(() => session.value?.bank_name || '答题复盘')
const modeText = computed(() => session.value ? sessionModeLabel(session.value) : '')
const correctCount = computed(() => session.value?.correct_count ?? 0)
const wrongCount = computed(() => session.value?.wrong_count ?? 0)
const unansweredCount = computed(() => session.value?.unanswered_count ?? 0)
const accuracyText = computed(() => `${session.value?.accuracy ?? 0}%`)
const headerCounter = computed(() =>
  `${currentVisibleIndex.value + 1} / ${visibleQuestions.value.length}`)

const filterOptions = computed(() => [
  { value: 'all', label: '全部', count: questions.value.length },
  { value: 'correct', label: '正确', count: countOf('correct') },
  { value: 'wrong', label: '错误', count: countOf('wrong') },
  { value: 'unanswered', label: '未答', count: countOf('unanswered') },
])

const emptyText = computed(() => ({
  all: '本场没有可复盘的题目',
  correct: '本场没有答对的题目',
  wrong: '本场没有答错的题目',
  unanswered: '本场没有未答的题目',
}[filter.value]))

function countOf(kind) {
  return questions.value.filter(question => reviewStatusOf(question) === kind).length
}

// 切换筛选只改变可见集合：当前题仍在集合中则跟随，否则回到第一题；题号不重编号
function applyFilter(value) {
  const next = normalizeReviewFilter(value)
  const previous = filter.value
  const keepId = previous === next ? null : currentQuestion.value?.id
  filter.value = next
  const keptIndex = visibleQuestions.value.findIndex(question => question.id === keepId)
  currentVisibleIndex.value = keptIndex >= 0 ? keptIndex : 0
}

// 兜底：可见集合变化后索引越界时回到第一题
watch(visibleQuestions, (next) => {
  if (currentVisibleIndex.value >= next.length) currentVisibleIndex.value = 0
})

function goPrev() {
  if (currentVisibleIndex.value > 0) currentVisibleIndex.value -= 1
}

function goNext() {
  if (currentVisibleIndex.value < visibleQuestions.value.length - 1) currentVisibleIndex.value += 1
}

function badgeClass(question) {
  return {
    correct: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    wrong: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400',
    unanswered: 'bg-gray-100 text-gray-400 dark:bg-slate-700 dark:text-gray-500',
    unknown: 'bg-gray-100 text-gray-400 dark:bg-slate-700 dark:text-gray-500',
  }[reviewStatusOf(question)]
}

function navBtnClass(question, index) {
  if (index === currentVisibleIndex.value) {
    return 'bg-primary-600 text-white shadow-sm ring-2 ring-primary-300 dark:ring-primary-700'
  }
  return {
    correct: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-200 dark:hover:bg-emerald-900/50',
    wrong: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400 hover:bg-rose-200 dark:hover:bg-rose-900/50',
    unanswered: 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-slate-600',
    unknown: 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-slate-600',
  }[reviewStatusOf(question)]
}

async function loadSession() {
  const generation = ++loadGeneration
  try {
    const res = await client.get(`/quiz/session/${route.params.sessionId}`)
    if (generation !== loadGeneration) return
    if (res.data.session?.is_completed !== true) {
      // 复盘只面向已完成会话；进行中的会话回答题页，不能在复盘页提前看到答案与对错
      router.replace(currentExamPath(route, 'quiz', { sessionId: route.params.sessionId }))
      return
    }
    session.value = res.data.session
    questions.value = Array.isArray(res.data.questions) ? res.data.questions : []
    loadFailed.value = false
  } catch {
    if (generation !== loadGeneration) return
    loadFailed.value = true
  }
}

watch(() => route.params.sessionId, loadSession, { immediate: true })

// 深链与浏览器前进/后退同步同一套筛选语义（能保持当前题时保持）
watch(() => route.query.filter, value => applyFilter(value))
</script>
