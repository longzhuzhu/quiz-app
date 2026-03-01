<template>
  <div v-if="!quizStore.session" class="text-center py-12 text-gray-500 dark:text-gray-400">加载中...</div>
  <div v-else>
    <!-- 顶部信息栏 -->
    <div class="mb-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <h1 class="text-lg font-bold text-gray-900 dark:text-white">
          {{ quizStore.session.bank_name || '答题' }}
        </h1>
        <span class="rounded-full bg-primary-100 dark:bg-primary-900/30 px-2.5 py-0.5 text-xs font-medium text-primary-700 dark:text-primary-400">
          {{ quizStore.currentIndex + 1 }} / {{ quizStore.questions.length }}
        </span>
      </div>
      <label class="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 cursor-pointer select-none">
        <input type="checkbox" v-model="autoNext"
          class="h-3.5 w-3.5 rounded border-gray-300 dark:border-slate-600 text-primary-600 dark:text-primary-500" />
        自动下一题
      </label>
    </div>

    <!-- 进度条 -->
    <div class="mb-4 h-1 w-full rounded-full bg-gray-200 dark:bg-slate-700">
      <div class="h-1 rounded-full bg-gradient-to-r from-primary-500 to-sky-400 transition-all duration-300"
        :style="{ width: `${((quizStore.currentIndex + 1) / quizStore.questions.length) * 100}%` }"></div>
    </div>

    <div class="flex gap-4 items-start">
      <!-- 左侧题目导航 -->
      <div class="hidden md:block w-48 flex-shrink-0">
        <div class="sticky top-20 rounded-xl bg-white dark:bg-slate-800 shadow-card overflow-hidden">
          <div class="px-4 py-2.5 bg-gray-50 dark:bg-slate-700/50 border-b border-gray-100 dark:border-slate-700 flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">题目导航</span>
            <span class="text-[10px] text-gray-400 dark:text-gray-500">
              {{ correctCount + wrongCount }} / {{ quizStore.questions.length }}
            </span>
          </div>
          <div class="max-h-[calc(100vh-12rem)] overflow-y-auto">
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
                  <span v-if="answerResults[i]" class="inline-flex items-center rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400">正确</span>
                  <span v-else class="inline-flex items-center rounded-full bg-rose-100 dark:bg-rose-900/30 px-1.5 py-0.5 text-[10px] font-medium text-rose-700 dark:text-rose-400">错误</span>
                </span>
                <span v-else class="flex-shrink-0 inline-flex items-center rounded-full bg-gray-100 dark:bg-slate-700 px-1.5 py-0.5 text-[10px] text-gray-400 dark:text-gray-500">未答</span>
              </button>
            </div>
          </div>
          <!-- 底部统计 -->
          <div class="px-4 py-2 bg-gray-50 dark:bg-slate-700/50 border-t border-gray-100 dark:border-slate-700 flex justify-between text-[10px] text-gray-400 dark:text-gray-500">
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
          </div>
        </div>
      </div>

      <!-- 移动端底部导航 -->
      <div class="md:hidden fixed bottom-0 left-0 right-0 z-20 bg-white/95 dark:bg-slate-800/95 backdrop-blur border-t border-gray-200 dark:border-slate-700 px-3 py-2 safe-area-bottom">
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
      <div class="flex-1 min-w-0 pb-16 md:pb-0">
        <QuestionCard
          :question="currentQuestion"
          :current-index="quizStore.currentIndex"
          :total="quizStore.questions.length"
          :hide-progress="true"
          @submit="handleSubmit"
          @next="quizStore.nextQuestion()"
          @prev="quizStore.prevQuestion()"
          @finish="handleFinish"
          @translated="handleTranslated"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuizStore } from '../stores/quiz'
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
const autoNext = ref(true)

const correctCount = computed(() => Object.values(answerResults).filter(v => v === true).length)
const wrongCount = computed(() => Object.values(answerResults).filter(v => v === false).length)
const unansweredCount = computed(() => quizStore.questions.length - correctCount.value - wrongCount.value)

onMounted(async () => {
  if (!quizStore.session || String(quizStore.session.id) !== route.params.sessionId) {
    try {
      const res = await client.get(`/quiz/session/${route.params.sessionId}`)
      if (res.data.session.is_completed) {
        router.replace(`/quiz/${route.params.sessionId}/result`)
        return
      }
      if (res.data.questions) {
        quizStore.session = res.data.session
        quizStore.questions = res.data.questions
        // 恢复已答题的状态
        res.data.questions.forEach((q, i) => {
          if (q.answered) answerResults[i] = q.is_correct
        })
        const firstUnanswered = res.data.questions.findIndex(q => !q.answered)
        quizStore.currentIndex = firstUnanswered >= 0 ? firstUnanswered : 0
      } else {
        router.replace('/')
      }
    } catch {
      router.replace('/')
    }
  }
})

function jumpTo(index) {
  quizStore.currentIndex = index
}

function navBtnClass(index) {
  if (index === quizStore.currentIndex) {
    return 'bg-primary-600 text-white shadow-sm ring-2 ring-primary-300 dark:ring-primary-700'
  }
  if (index in answerResults) {
    return answerResults[index]
      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-200 dark:hover:bg-emerald-900/50'
      : 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400 hover:bg-rose-200 dark:hover:bg-rose-900/50'
  }
  return 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-slate-600'
}

async function handleSubmit(answer, callback) {
  try {
    const res = await quizStore.submitAnswer(currentQuestion.value.id, answer)
    answerResults[quizStore.currentIndex] = res.is_correct
    callback(res)
    if (autoNext.value && quizStore.currentIndex < quizStore.questions.length - 1) {
      setTimeout(() => quizStore.nextQuestion(), 1500)
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '提交失败')
  }
}

async function handleFinish() {
  try {
    await quizStore.finishQuiz()
    router.push(`/quiz/${quizStore.session.id}/result`)
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
