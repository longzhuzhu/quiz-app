<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900">答题历史</h1>
      <button v-if="sessions.length > 0" @click="confirmClear"
        class="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50">
        清空历史
      </button>
    </div>

    <div v-if="loading" class="text-center text-gray-500">加载中...</div>
    <div v-else-if="sessions.length === 0" class="py-12 text-center text-gray-400">暂无答题记录</div>
    <template v-else>
      <div class="space-y-3">
        <router-link v-for="s in sessions" :key="s.id" :to="`/quiz/${s.id}/result`"
          class="block rounded-lg bg-white p-5 shadow hover:shadow-md transition-shadow">
          <div class="flex items-center justify-between">
            <div>
              <p class="font-medium text-gray-900">{{ s.bank_name }}</p>
              <p class="mt-1 text-sm text-gray-500">
                {{ s.mode === 'sequential' ? '顺序' : s.mode === 'random' ? '随机' : '错题' }}练习
                · {{ new Date(s.created_at).toLocaleDateString('zh-CN') }}
              </p>
            </div>
            <div class="text-right">
              <div class="text-lg font-bold" :class="s.accuracy >= 60 ? 'text-green-600' : 'text-red-500'">
                {{ s.accuracy }}%
              </div>
              <p class="text-xs text-gray-400">{{ s.correct_count }}/{{ s.answered_count }}</p>
            </div>
          </div>
        </router-link>
      </div>

      <!-- 分页 -->
      <div v-if="totalPages > 1" class="mt-6 flex items-center justify-center gap-2">
        <button @click="goPage(page - 1)" :disabled="page <= 1"
          class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-30">
          上一页
        </button>
        <template v-for="p in pageList" :key="p">
          <span v-if="p === '...'" class="px-2 text-sm text-gray-400">...</span>
          <button v-else @click="goPage(p)"
            class="rounded-md px-3 py-1.5 text-sm"
            :class="p === page ? 'bg-indigo-600 text-white' : 'border border-gray-300 text-gray-600 hover:bg-gray-50'">
            {{ p }}
          </button>
        </template>
        <button @click="goPage(page + 1)" :disabled="page >= totalPages"
          class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-30">
          下一页
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import client from '../api/client'

const sessions = ref([])
const loading = ref(false)
const page = ref(1)
const totalPages = ref(1)

const pageList = computed(() => {
  const pages = []
  const total = totalPages.value
  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
    return pages
  }
  pages.push(1)
  if (page.value > 3) pages.push('...')
  for (let i = Math.max(2, page.value - 1); i <= Math.min(total - 1, page.value + 1); i++) {
    pages.push(i)
  }
  if (page.value < total - 2) pages.push('...')
  pages.push(total)
  return pages
})

async function fetchHistory() {
  loading.value = true
  try {
    const res = await client.get('/quiz/history', { params: { page: page.value, per_page: 10 } })
    sessions.value = res.data.items
    totalPages.value = res.data.pages
  } finally {
    loading.value = false
  }
}

function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  fetchHistory()
}

async function confirmClear() {
  if (!confirm('确定要清空所有答题历史吗？此操作不可撤销。')) return
  try {
    await client.delete('/quiz/history')
    sessions.value = []
    page.value = 1
    totalPages.value = 1
  } catch (e) {
    alert(e.response?.data?.error || '清空失败')
  }
}

onMounted(fetchHistory)
</script>
