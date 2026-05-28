<template>
  <div>
    <!-- 标题栏 -->
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">答题历史</h1>
      <BaseButton v-if="sessions.length > 0" variant="danger" size="sm" @click="showConfirmClear = true">
        清空历史
      </BaseButton>
    </div>

    <!-- 加载骨架屏 -->
    <SkeletonLoader v-if="loading" type="list" :count="3" />

    <!-- 空状态 -->
    <div v-else-if="sessions.length === 0" class="flex flex-col items-center justify-center py-20 text-gray-400 dark:text-gray-500">
      <ClockIcon class="h-16 w-16 mb-4" />
      <p class="text-lg font-medium">暂无答题记录</p>
      <p class="mt-1 text-sm">完成一次练习后，记录将显示在这里</p>
    </div>

    <!-- 历史记录列表 -->
    <template v-else>
      <div class="space-y-3">
        <router-link
          v-for="s in sessions"
          :key="s.id"
          :to="currentExamPath(route, 'quizResult', { sessionId: s.id })"
          class="flex items-center gap-4 rounded-xl bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-5"
        >
          <!-- 正确率圆环 -->
          <svg class="h-10 w-10 flex-shrink-0 -rotate-90" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="15" fill="none" stroke-width="3" class="stroke-gray-200 dark:stroke-slate-700" />
            <circle cx="18" cy="18" r="15" fill="none" stroke-width="3" stroke-linecap="round"
              :class="s.accuracy >= 60 ? 'stroke-emerald-500' : 'stroke-rose-500'"
              :stroke-dasharray="94.248"
              :stroke-dashoffset="94.248 * (1 - s.accuracy / 100)" />
          </svg>

          <!-- 信息区 -->
          <div class="flex-1 min-w-0">
            <p class="font-medium text-gray-900 dark:text-white truncate">{{ s.bank_name }}</p>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ s.mode === 'sequential' ? '顺序' : s.mode === 'random' ? '随机' : '错题' }}练习
              · {{ new Date(s.created_at).toLocaleDateString('zh-CN') }}
            </p>
          </div>

          <!-- 正确率数值 -->
          <div class="text-right flex-shrink-0">
            <div class="text-lg font-bold" :class="s.accuracy >= 60 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400'">
              {{ s.accuracy }}%
            </div>
            <p class="text-xs text-gray-400 dark:text-gray-500">{{ s.correct_count }}/{{ s.answered_count }}</p>
          </div>
        </router-link>
      </div>

      <!-- 分页 -->
      <div v-if="totalPages > 1" class="mt-6 flex items-center justify-center gap-2">
        <BaseButton variant="secondary" size="sm" :disabled="page <= 1" @click="goPage(page - 1)">
          上一页
        </BaseButton>
        <template v-for="p in pageList" :key="p">
          <span v-if="p === '...'" class="px-2 text-sm text-gray-400 dark:text-gray-500">...</span>
          <BaseButton v-else size="sm"
            :variant="p === page ? 'primary' : 'secondary'"
            @click="goPage(p)">
            {{ p }}
          </BaseButton>
        </template>
        <BaseButton variant="secondary" size="sm" :disabled="page >= totalPages" @click="goPage(page + 1)">
          下一页
        </BaseButton>
      </div>
    </template>

    <!-- 清空确认弹窗 -->
    <ConfirmDialog
      :open="showConfirmClear"
      danger
      title="清空历史"
      message="确定要清空所有答题历史吗？此操作不可撤销。"
      confirm-text="清空"
      @confirm="doClear"
      @cancel="showConfirmClear = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import client from '../api/client'
import { currentExamPath } from '../utils/examRoutes'
import BaseButton from '../components/BaseButton.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { useToast } from '../composables/useToast'
import { ClockIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const toast = useToast()

const sessions = ref([])
const loading = ref(false)
const page = ref(1)
const totalPages = ref(1)
const showConfirmClear = ref(false)

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

async function doClear() {
  showConfirmClear.value = false
  try {
    await client.delete('/quiz/history')
    sessions.value = []
    page.value = 1
    totalPages.value = 1
    toast.success('历史已清空')
  } catch (e) {
    toast.error(e.response?.data?.error || '清空失败')
  }
}

onMounted(fetchHistory)
</script>
