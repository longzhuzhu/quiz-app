<template>
  <div>
  <!-- 加载中 -->
  <div v-if="!session" class="mx-auto max-w-lg py-12">
    <SkeletonLoader type="card" />
  </div>

  <!-- 加载错误 -->
  <div v-else-if="session.error" class="py-16 text-center">
    <XCircleIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
    <p class="mt-4 text-gray-500 dark:text-gray-400">加载失败，请返回重试</p>
    <router-link :to="currentExamPath(route, 'dashboard')" class="mt-4 inline-block text-primary-600 hover:text-primary-500 dark:text-primary-400 dark:hover:text-primary-300">返回首页</router-link>
  </div>

  <!-- 结果 -->
  <div v-else class="mx-auto max-w-lg">
    <div class="rounded-2xl bg-white dark:bg-slate-800 shadow-card p-6 md:p-8">
      <!-- 标题 -->
      <h1 class="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
        {{ session.accuracy >= 80 ? '🎉 练习完成！' : '📊 练习完成' }}
      </h1>

      <!-- CSS 圆环进度条 -->
      <div class="mx-auto mb-8 relative h-32 w-32">
        <svg class="h-32 w-32 -rotate-90" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r="54" fill="none" stroke-width="8"
            class="stroke-gray-200 dark:stroke-slate-700" />
          <circle cx="60" cy="60" r="54" fill="none" stroke-width="8"
            stroke-linecap="round"
            :class="ringColor"
            :stroke-dasharray="339.292"
            :stroke-dashoffset="339.292 * (1 - session.accuracy / 100)"
            style="transition: stroke-dashoffset 1s ease-out" />
        </svg>
        <div class="absolute inset-0 flex items-center justify-center">
          <span class="text-3xl font-bold" :class="scoreColor">{{ session.accuracy }}%</span>
        </div>
      </div>

      <!-- 四列统计：区分未答（跳答时结果完整可见） -->
      <div class="mb-6 grid grid-cols-4 gap-3">
        <div class="rounded-xl bg-gray-50 dark:bg-slate-700/50 p-3 md:p-4">
          <div class="text-xl md:text-2xl font-bold text-gray-900 dark:text-white">{{ session.total_questions }}</div>
          <div class="text-xs md:text-sm text-gray-500 dark:text-gray-400">总题数</div>
        </div>
        <div class="rounded-xl bg-emerald-50 dark:bg-emerald-900/20 p-3 md:p-4">
          <div class="text-xl md:text-2xl font-bold text-emerald-600 dark:text-emerald-400">{{ session.correct_count }}</div>
          <div class="text-xs md:text-sm text-gray-500 dark:text-gray-400">正确</div>
        </div>
        <div class="rounded-xl bg-rose-50 dark:bg-rose-900/20 p-3 md:p-4">
          <div class="text-xl md:text-2xl font-bold text-rose-600 dark:text-rose-400">{{ wrongCount }}</div>
          <div class="text-xs md:text-sm text-gray-500 dark:text-gray-400">错误</div>
        </div>
        <div class="rounded-xl bg-gray-50 dark:bg-slate-700/50 p-3 md:p-4">
          <div class="text-xl md:text-2xl font-bold text-gray-900 dark:text-white">{{ unansweredCount }}</div>
          <div class="text-xs md:text-sm text-gray-500 dark:text-gray-400">未答</div>
        </div>
      </div>

      <!-- 答题详情：可展开完整题干与选项对比，无嵌套滚动 -->
      <div v-if="answers.length" class="mb-6 text-left">
        <div class="mb-3 flex items-center justify-between gap-2">
          <h2 class="font-semibold text-gray-700 dark:text-gray-300">答题详情</h2>
          <div v-if="!isExamSession && wrongCount > 0" class="flex items-center gap-1 rounded-lg bg-gray-100 dark:bg-slate-700 p-0.5 text-xs">
            <button type="button"
              class="rounded-md px-2.5 py-1 font-medium transition-colors"
              :class="filterMode === 'all'
                ? 'bg-white dark:bg-slate-800 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 dark:text-gray-400'"
              @click="filterMode = 'all'">全部 {{ answers.length }}</button>
            <button type="button"
              class="rounded-md px-2.5 py-1 font-medium transition-colors"
              :class="filterMode === 'wrong'
                ? 'bg-white dark:bg-slate-800 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 dark:text-gray-400'"
              @click="filterMode = 'wrong'">答错 {{ wrongCount }}</button>
          </div>
        </div>

        <div class="space-y-2">
          <div v-for="(a, i) in filteredAnswers" :key="i"
            class="rounded-lg border transition-colors"
            :class="a.is_correct
              ? 'border-emerald-200 dark:border-emerald-900/60'
              : 'border-rose-200 dark:border-rose-900/60'">
            <button type="button"
              class="flex w-full items-start gap-2.5 p-3 text-left"
              :aria-expanded="expandedIndex === i"
              @click="toggleDetail(i)">
              <CheckCircleIcon v-if="a.is_correct" class="h-5 w-5 flex-shrink-0 text-emerald-500" />
              <XCircleIcon v-else class="h-5 w-5 flex-shrink-0 text-rose-500" />
              <span class="min-w-0 flex-1">
                <span class="block text-sm text-gray-800 dark:text-gray-200 line-clamp-2">{{ originalIndex(i) + 1 }}. {{ a.question_content }}</span>
                <span class="mt-0.5 block text-xs text-gray-500 dark:text-gray-400">
                  你的答案: {{ a.user_answer }}<template v-if="!isExamSession"> | 正确答案: {{ a.correct_answer }}</template>
                </span>
              </span>
              <ChevronDownIcon class="mt-0.5 h-4 w-4 flex-shrink-0 text-gray-400 transition-transform duration-200"
                :class="{ 'rotate-180': expandedIndex === i }" />
            </button>

            <div v-if="expandedIndex === i" class="border-t border-gray-100 dark:border-slate-700 p-3">
              <p class="whitespace-pre-line text-sm leading-relaxed text-gray-800 dark:text-gray-200">{{ a.question_content }}</p>
              <p v-if="a.question_content_zh" class="mt-1.5 text-sm leading-relaxed text-gray-500 dark:text-gray-400">{{ a.question_content_zh }}</p>

              <div class="mt-3 space-y-2">
                <div v-for="opt in a.options || []" :key="opt.key"
                  class="flex items-start gap-2.5 rounded-lg border p-2.5"
                  :class="resultOptionClass(a, opt.key)">
                  <span class="w-7 shrink-0 pt-0.5 text-right text-sm font-medium text-gray-900 dark:text-white">{{ opt.key }}.</span>
                  <span class="min-w-0 flex-1 text-sm text-gray-700 dark:text-gray-300">{{ opt.text }}</span>
                  <span v-if="resultBadge(a, opt.key)"
                    class="shrink-0 text-xs font-medium"
                    :class="resultBadge(a, opt.key).tone">{{ resultBadge(a, opt.key).text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="flex justify-center gap-3 flex-wrap">
        <BaseButton variant="secondary" @click="router.push(currentExamPath(route, 'dashboard'))">返回首页</BaseButton>
        <BaseButton variant="primary" @click="router.push(currentExamPath(route, 'wrong'))">查看错题本</BaseButton>
        <BaseButton variant="secondary" @click="retryQuiz">再来一次</BaseButton>
      </div>
    </div>
  </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuizStore } from '../stores/quiz'
import { currentExamPath } from '../utils/examRoutes'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { CheckCircleIcon, ChevronDownIcon, XCircleIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const router = useRouter()
const quizStore = useQuizStore()
const toast = useToast()
const session = ref(null)
const answers = ref([])
const filterMode = ref('all')
const expandedIndex = ref(null)

const isExamSession = computed(() => session.value?.mode === 'exam')
const wrongCount = computed(() => answers.value.filter(a => a.is_correct === false).length)
const unansweredCount = computed(() => {
  if (!session.value) return 0
  return Math.max(0, (session.value.total_questions || 0) - answers.value.length)
})

const filteredAnswers = computed(() => {
  if (filterMode.value !== 'wrong') return answers.value
  return answers.value.filter(a => a.is_correct === false)
})

const ringColor = computed(() => {
  if (!session.value) return 'stroke-gray-300'
  if (session.value.accuracy >= 80) return 'stroke-emerald-500'
  if (session.value.accuracy >= 60) return 'stroke-amber-500'
  return 'stroke-rose-500'
})

const scoreColor = computed(() => {
  if (!session.value) return 'text-gray-500'
  if (session.value.accuracy >= 80) return 'text-emerald-600 dark:text-emerald-400'
  if (session.value.accuracy >= 60) return 'text-amber-600 dark:text-amber-400'
  return 'text-rose-600 dark:text-rose-400'
})

function parseAnswerKeys(raw) {
  if (!raw) return []
  return String(raw).split(',').map((part) => part.trim()).filter(Boolean)
}

// filteredAnswers 重编号后，还原在原始 answers 中的序号
function originalIndex(filteredIdx) {
  if (filterMode.value !== 'wrong') return filteredIdx
  const target = filteredAnswers.value[filteredIdx]
  return answers.value.indexOf(target)
}

function toggleDetail(i) {
  expandedIndex.value = expandedIndex.value === i ? null : i
}

function isCorrectKey(a, key) {
  return parseAnswerKeys(a.correct_answer).includes(key)
}

function isChosenKey(a, key) {
  return parseAnswerKeys(a.user_answer).includes(key)
}

function resultOptionClass(a, key) {
  if (isExamSession.value) {
    return isChosenKey(a, key)
      ? 'border-sky-400 bg-sky-50 dark:border-sky-600 dark:bg-sky-900/20'
      : 'border-gray-200 dark:border-slate-700'
  }
  if (isCorrectKey(a, key)) return 'border-emerald-400 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/20'
  if (isChosenKey(a, key)) return 'border-rose-400 bg-rose-50 dark:border-rose-600 dark:bg-rose-900/20'
  return 'border-gray-200 dark:border-slate-700'
}

function resultBadge(a, key) {
  const chosen = isChosenKey(a, key)
  if (isExamSession.value) {
    return chosen ? { text: '已选', tone: 'text-sky-600 dark:text-sky-400' } : null
  }
  const correct = isCorrectKey(a, key)
  if (correct && chosen) return { text: '你的答案 ✓', tone: 'text-emerald-600 dark:text-emerald-400' }
  if (correct) return { text: '正确答案', tone: 'text-emerald-600 dark:text-emerald-400' }
  if (chosen) return { text: '你的选择', tone: 'text-rose-600 dark:text-rose-400' }
  return null
}

onMounted(async () => {
  try {
    const res = await client.get(`/quiz/session/${route.params.sessionId}`)
    session.value = res.data.session
    answers.value = res.data.answers
  } catch {
    session.value = { error: true }
  }
})

async function retryQuiz() {
  if (!session.value?.bank_id) {
    router.push(currentExamPath(route, 'dashboard'))
    return
  }
  try {
    await quizStore.startQuiz(session.value.bank_id, session.value.mode || 'random')
    router.push(currentExamPath(route, 'quiz', { sessionId: quizStore.session.id }))
  } catch (e) {
    toast.error(e.response?.data?.error || '开始答题失败')
  }
}
</script>
