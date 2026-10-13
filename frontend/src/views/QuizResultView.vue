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
    <div class="rounded-2xl bg-white dark:bg-slate-800 shadow-card p-8 text-center">
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
          <span data-testid="result-accuracy" class="text-3xl font-bold" :class="scoreColor">{{ session.accuracy }}%</span>
        </div>
      </div>

      <!-- 三列统计：正确 / 错误 / 未答，数值与分母口径均由后端给出 -->
      <div class="mb-8 grid grid-cols-3 gap-4">
        <div class="rounded-xl bg-emerald-50 dark:bg-emerald-900/20 p-4">
          <div data-testid="result-correct" class="text-2xl font-bold text-emerald-600 dark:text-emerald-400">{{ session.correct_count }}</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">正确</div>
        </div>
        <div class="rounded-xl bg-rose-50 dark:bg-rose-900/20 p-4">
          <div data-testid="result-wrong" class="text-2xl font-bold text-rose-600 dark:text-rose-400">{{ session.wrong_count }}</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">错误</div>
        </div>
        <div class="rounded-xl bg-gray-50 dark:bg-slate-700/50 p-4">
          <div data-testid="result-unanswered" class="text-2xl font-bold text-gray-500 dark:text-gray-400">{{ session.unanswered_count }}</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">未答</div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="flex justify-center gap-3 flex-wrap">
        <BaseButton variant="secondary" @click="router.push(currentExamPath(route, 'dashboard'))">返回首页</BaseButton>
        <BaseButton variant="secondary" data-testid="result-review" @click="goReview()">查看详情</BaseButton>
        <BaseButton variant="secondary" data-testid="result-review-wrong" @click="goReview('wrong')">本次错题</BaseButton>
        <BaseButton variant="primary" data-testid="result-retry" :disabled="retrying" @click="retryQuiz">再来一次</BaseButton>
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
import { XCircleIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const router = useRouter()
const quizStore = useQuizStore()
const toast = useToast()
const session = ref(null)
const retrying = ref(false)

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

onMounted(async () => {
  try {
    const res = await client.get(`/quiz/session/${route.params.sessionId}`)
    if (res.data.session?.is_completed !== true) {
      // 完成页只服务已完成会话：错误／未答数与正确率分母只在完成态由后端给出，
      // 进行中的会话必须继续回答题页，不能借结果页提前查看答案或成绩。
      router.replace(currentExamPath(route, 'quiz', { sessionId: route.params.sessionId }))
      return
    }
    session.value = res.data.session
  } catch {
    session.value = { error: true }
  }
})

function goReview(filter = null) {
  router.push(currentExamPath(route, 'quizReview', {
    sessionId: route.params.sessionId,
    ...(filter ? { filter } : {}),
  }))
}

async function retryQuiz() {
  if (retrying.value) return
  retrying.value = true
  try {
    await quizStore.retryQuiz(route.params.sessionId)
    router.push(currentExamPath(route, 'quiz', { sessionId: quizStore.session.id }))
  } catch (e) {
    // 原题不可用时后端在 detail 里列出题目 ID；失败留在本页，不清空已有结果
    toast.error(e.response?.data?.detail || '重新开始失败')
  } finally {
    retrying.value = false
  }
}
</script>
