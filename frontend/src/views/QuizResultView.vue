<template>
  <div v-if="session && !session.error" class="mx-auto max-w-lg">
    <div class="rounded-lg bg-white p-8 shadow text-center">
      <div class="mb-6">
        <div class="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-full"
          :class="session.accuracy >= 60 ? 'bg-green-100' : 'bg-red-100'">
          <span class="text-3xl font-bold" :class="session.accuracy >= 60 ? 'text-green-600' : 'text-red-600'">
            {{ session.accuracy }}%
          </span>
        </div>
        <h1 class="text-2xl font-bold text-gray-900">答题完成</h1>
      </div>

      <div class="mb-8 grid grid-cols-3 gap-4 text-center">
        <div>
          <div class="text-2xl font-bold text-gray-900">{{ session.total_questions }}</div>
          <div class="text-sm text-gray-500">总题数</div>
        </div>
        <div>
          <div class="text-2xl font-bold text-green-600">{{ session.correct_count }}</div>
          <div class="text-sm text-gray-500">正确</div>
        </div>
        <div>
          <div class="text-2xl font-bold text-red-500">{{ session.answered_count - session.correct_count }}</div>
          <div class="text-sm text-gray-500">错误</div>
        </div>
      </div>

      <!-- Answer details -->
      <div v-if="answers.length" class="mb-6 text-left">
        <h2 class="mb-3 font-semibold text-gray-700">答题详情</h2>
        <div v-for="(a, i) in answers" :key="i"
          class="mb-2 flex items-start gap-2 rounded p-3 text-sm"
          :class="a.is_correct ? 'bg-green-50' : 'bg-red-50'">
          <span class="mt-0.5 flex-shrink-0 text-xs" :class="a.is_correct ? 'text-green-600' : 'text-red-600'">
            {{ a.is_correct ? '✓' : '✗' }}
          </span>
          <div class="min-w-0">
            <p class="truncate text-gray-800">{{ i + 1 }}. {{ a.question_content }}</p>
            <p class="text-xs text-gray-500">
              你的答案: {{ a.user_answer }} | 正确答案: {{ a.correct_answer }}
            </p>
          </div>
        </div>
      </div>

      <div class="flex justify-center gap-4">
        <router-link to="/"
          class="rounded-md border border-gray-300 px-6 py-2 text-sm text-gray-700 hover:bg-gray-50">
          返回首页
        </router-link>
        <router-link to="/wrong"
          class="rounded-md bg-indigo-600 px-6 py-2 text-sm text-white hover:bg-indigo-700">
          查看错题
        </router-link>
      </div>
    </div>
  </div>
  <div v-else-if="session?.error" class="text-center py-12">
    <p class="text-red-500">加载失败，请返回重试</p>
    <router-link to="/" class="mt-4 inline-block text-indigo-600 hover:underline">返回首页</router-link>
  </div>
  <div v-else class="text-center py-12 text-gray-500">加载中...</div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import client from '../api/client'

const route = useRoute()
const session = ref(null)
const answers = ref([])

onMounted(async () => {
  try {
    const res = await client.get(`/quiz/session/${route.params.sessionId}`)
    session.value = res.data.session
    answers.value = res.data.answers
  } catch {
    session.value = { error: true }
  }
})
</script>
