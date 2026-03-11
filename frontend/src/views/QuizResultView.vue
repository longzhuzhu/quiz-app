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
    <router-link to="/" class="mt-4 inline-block text-primary-600 hover:text-primary-500 dark:text-primary-400 dark:hover:text-primary-300">返回首页</router-link>
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
          <span class="text-3xl font-bold" :class="scoreColor">{{ session.accuracy }}%</span>
        </div>
      </div>

      <!-- 三列统计 -->
      <div class="mb-8 grid grid-cols-3 gap-4">
        <div class="rounded-xl bg-gray-50 dark:bg-slate-700/50 p-4">
          <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ session.total_questions }}</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">总题数</div>
        </div>
        <div class="rounded-xl bg-emerald-50 dark:bg-emerald-900/20 p-4">
          <div class="text-2xl font-bold text-emerald-600 dark:text-emerald-400">{{ session.correct_count }}</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">正确</div>
        </div>
        <div class="rounded-xl bg-rose-50 dark:bg-rose-900/20 p-4">
          <div class="text-2xl font-bold text-rose-600 dark:text-rose-400">{{ session.answered_count - session.correct_count }}</div>
          <div class="text-sm text-gray-500 dark:text-gray-400">错误</div>
        </div>
      </div>

      <!-- 答题详情 -->
      <div v-if="answers.length" class="mb-6 text-left">
        <h2 class="mb-3 font-semibold text-gray-700 dark:text-gray-300">答题详情</h2>
        <div class="space-y-2 max-h-64 overflow-y-auto">
          <div v-for="(a, i) in answers" :key="i"
            class="flex items-start gap-2 rounded-lg p-3 text-sm"
            :class="a.is_correct ? 'bg-emerald-50 dark:bg-emerald-900/10' : 'bg-rose-50 dark:bg-rose-900/10'">
            <CheckCircleIcon v-if="a.is_correct" class="h-5 w-5 flex-shrink-0 text-emerald-500" />
            <XCircleIcon v-else class="h-5 w-5 flex-shrink-0 text-rose-500" />
            <div class="min-w-0">
              <p class="truncate text-gray-800 dark:text-gray-200">{{ i + 1 }}. {{ a.question_content }}</p>
              <p class="text-xs text-gray-500 dark:text-gray-400">
                你的答案: {{ a.user_answer }} | 正确答案: {{ a.correct_answer }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="flex justify-center gap-3 flex-wrap">
        <BaseButton variant="secondary" @click="$router.push('/')">返回首页</BaseButton>
        <BaseButton variant="primary" @click="$router.push('/wrong')">查看错题</BaseButton>
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
import { useToast } from '../composables/useToast'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { CheckCircleIcon, XCircleIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const router = useRouter()
const quizStore = useQuizStore()
const toast = useToast()
const session = ref(null)
const answers = ref([])

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
    session.value = res.data.session
    answers.value = res.data.answers
  } catch {
    session.value = { error: true }
  }
})

async function retryQuiz() {
  if (!session.value?.bank_id) {
    router.push('/')
    return
  }
  try {
    await quizStore.startQuiz(session.value.bank_id, session.value.mode || 'random')
    router.push(`/quiz/${quizStore.session.id}`)
  } catch (e) {
    toast.error(e.response?.data?.error || '开始答题失败')
  }
}
</script>
