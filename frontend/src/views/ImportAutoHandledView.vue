<template>
  <div>
    <div class="mb-4">
      <router-link :to="currentExamPath(route, 'importJobDetail', { jobId })"
        class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">
        <ArrowLeftIcon class="h-4 w-4" />
        返回导入任务详情
      </router-link>
    </div>

    <div class="mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">自动处理记录</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">共 {{ items.length }} 条记录</p>
    </div>

    <div v-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <div v-else-if="items.length === 0" class="py-16 text-center">
      <ClipboardDocumentListIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-400 dark:text-gray-500">暂无自动处理记录</p>
    </div>

    <div v-else class="space-y-3">
      <div v-for="item in items" :key="item.id"
        class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="mb-2 flex flex-wrap items-center gap-2">
              <span class="text-xs rounded-full px-2 py-0.5" :class="resultClass(item.result)">
                {{ resultLabel(item.result) }}
              </span>
              <span class="text-sm font-medium text-gray-900 dark:text-white">{{ item.reason }}</span>
              <span v-if="item.source_question_no" class="text-xs text-gray-400 dark:text-gray-500">
                Q{{ item.source_question_no }}
              </span>
            </div>

            <p class="line-clamp-2 text-sm text-gray-700 dark:text-gray-300">
              {{ displayContent(item) }}
            </p>

            <div v-if="item.quality_tips?.length" class="mt-2 flex flex-wrap gap-1">
              <span v-for="tip in item.quality_tips" :key="tip"
                class="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                {{ tip }}
              </span>
            </div>

            <div class="mt-2 flex flex-wrap gap-2 text-xs text-gray-400 dark:text-gray-500">
              <span>答案: {{ (item.correct_answer || []).join(', ') || '无' }}</span>
              <span>处理时间: {{ formatDate(item.handled_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import client from '../api/client'
import { currentExamPath } from '../utils/examRoutes'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { ArrowLeftIcon, ClipboardDocumentListIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const jobId = route.params.jobId
const items = ref([])
const loading = ref(true)

function resultLabel(result) {
  return result === 'auto_skipped' ? '自动跳过' : '自动入库'
}

function resultClass(result) {
  if (result === 'auto_skipped') return 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'
  return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
}

function displayContent(item) {
  const scenario = (item.scenario_text || '').trim()
  const content = (item.content || '').trim()
  if (scenario && content && !content.startsWith(scenario)) return `${scenario} ${content}`
  return content || scenario || '无题干'
}

function formatDate(value) {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN')
}

async function fetchItems() {
  try {
    const res = await client.get(`/import-jobs/${jobId}/auto-handled`)
    items.value = res.data.items || []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchItems)
</script>
