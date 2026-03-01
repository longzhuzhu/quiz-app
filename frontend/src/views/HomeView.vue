<template>
  <div>
    <h1 class="mb-6 text-2xl font-bold text-gray-900">题库列表</h1>

    <!-- Stats cards -->
    <div class="mb-8 grid grid-cols-3 gap-4">
      <div class="rounded-lg bg-white p-4 shadow">
        <div class="text-sm text-gray-500">题库数量</div>
        <div class="text-2xl font-bold text-indigo-600">{{ banks.length }}</div>
      </div>
      <div class="rounded-lg bg-white p-4 shadow">
        <div class="text-sm text-gray-500">总题目数</div>
        <div class="text-2xl font-bold text-indigo-600">{{ totalQuestions }}</div>
      </div>
      <router-link to="/wrong" class="block rounded-lg bg-white p-4 shadow hover:shadow-md transition-shadow cursor-pointer">
        <div class="text-sm text-gray-500">未掌握错题</div>
        <div class="text-2xl font-bold text-red-500">{{ wrongStats.unresolved || 0 }}</div>
      </router-link>
    </div>

    <!-- Bank list -->
    <div v-if="loading" class="text-center text-gray-500">加载中...</div>
    <div v-else-if="banks.length === 0" class="text-center text-gray-400 py-12">暂无题库，请管理员添加</div>
    <div v-else class="space-y-4">
      <div v-for="bank in banks" :key="bank.id"
        class="flex items-center justify-between rounded-lg bg-white p-5 shadow hover:shadow-md transition-shadow">
        <div>
          <h3 class="font-semibold text-gray-900">{{ bank.name }}</h3>
          <p class="text-sm text-gray-500">{{ bank.description || '暂无描述' }}</p>
          <p class="mt-1 text-xs text-gray-400">{{ bank.question_count }} 道题目</p>
        </div>
        <div class="flex gap-2">
          <button @click="startQuiz(bank, 'sequential')"
            class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
            :disabled="bank.question_count === 0">
            顺序练习
          </button>
          <button @click="startQuiz(bank, 'random')"
            class="rounded-md bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-700"
            :disabled="bank.question_count === 0">
            随机练习
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBankStore } from '../stores/bank'
import { useQuizStore } from '../stores/quiz'
import client from '../api/client'

const bankStore = useBankStore()
const quizStore = useQuizStore()
const router = useRouter()
const wrongStats = ref({})

const banks = computed(() => bankStore.banks)
const loading = computed(() => bankStore.loading)
const totalQuestions = computed(() => banks.value.reduce((s, b) => s + b.question_count, 0))

onMounted(async () => {
  bankStore.fetchBanks()
  try {
    const res = await client.get('/wrong/stats')
    wrongStats.value = res.data
  } catch {}
})

async function startQuiz(bank, mode) {
  try {
    await quizStore.startQuiz(bank.id, mode)
    router.push(`/quiz/${quizStore.session.id}`)
  } catch (e) {
    alert(e.response?.data?.error || '开始答题失败')
  }
}
</script>
