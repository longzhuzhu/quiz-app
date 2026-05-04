<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">导入任务</h1>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="jobs.length === 0" class="py-16 text-center">
      <ArrowUpTrayIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-400 dark:text-gray-500">暂无导入任务</p>
    </div>

    <!-- 导入任务列表 -->
    <div v-else class="space-y-4">
      <div v-for="job in jobs" :key="job.id"
        class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-5">
        <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div class="min-w-0">
            <router-link :to="`/import-jobs/${job.id}`"
              class="font-semibold text-primary-600 dark:text-primary-400 hover:underline">
              {{ job.file_name }}
            </router-link>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              <span :class="statusClass(job.status)">{{ statusLabel(job.status) }}</span>
              <span class="mx-1">|</span>
              题库 #{{ job.bank_id }}
              <span class="mx-1">|</span>
              {{ job.file_type?.toUpperCase() }}
            </p>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
              解析 {{ job.parsed_questions || 0 }} 题 / 入库 {{ job.imported_questions || 0 }} 题 / 待复核 {{ job.review_questions || 0 }} 题
              <span v-if="job.failed_chunks"> / 失败 {{ job.failed_chunks }} chunk</span>
            </p>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">{{ job.created_at }}</p>
          </div>
          <div class="flex gap-2 flex-wrap flex-shrink-0">
            <BaseButton v-if="job.review_questions > 0"
              variant="secondary" size="sm"
              @click="$router.push(`/import-jobs/${job.id}/review`)">
              <ExclamationCircleIcon class="h-4 w-4" />
              复核 ({{ job.review_questions }})
            </BaseButton>
            <BaseButton variant="ghost" size="sm"
              @click="$router.push(`/import-jobs/${job.id}`)">
              <EyeIcon class="h-4 w-4" />
              详情
            </BaseButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { ArrowUpTrayIcon, ExclamationCircleIcon, EyeIcon } from '@heroicons/vue/24/outline'

const jobs = ref([])
const loading = ref(false)
let pollTimer = null

const STATUS_MAP = {
  pending: '待处理',
  extracting: '抽取中',
  chunking: '切片中',
  parsing: '解析中',
  validating: '校验中',
  importing: '导入中',
  imported: '已入库',
  review_required: '待复核',
  partial_imported: '部分入库',
  failed: '失败',
  cancelled: '已取消',
}

function statusLabel(status) {
  return STATUS_MAP[status] || status
}

function statusClass(status) {
  const activeStatuses = ['pending', 'extracting', 'chunking', 'parsing', 'validating', 'importing']
  const doneStatuses = ['imported']
  const warnStatuses = ['review_required', 'partial_imported']
  const errorStatuses = ['failed']

  if (activeStatuses.includes(status)) return 'text-sky-600 dark:text-sky-400'
  if (doneStatuses.includes(status)) return 'text-emerald-600 dark:text-emerald-400'
  if (warnStatuses.includes(status)) return 'text-amber-600 dark:text-amber-400'
  if (errorStatuses.includes(status)) return 'text-rose-600 dark:text-rose-400'
  return 'text-gray-500 dark:text-gray-400'
}

async function fetchJobs() {
  try {
    const res = await client.get('/import-jobs')
    jobs.value = res.data.jobs || []
  } catch {
    // 静默处理
  }
}

function hasActiveJobs() {
  const activeStatuses = ['pending', 'extracting', 'chunking', 'parsing', 'validating', 'importing']
  return jobs.value.some(j => activeStatuses.includes(j.status))
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    await fetchJobs()
    if (!hasActiveJobs()) stopPolling()
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(async () => {
  loading.value = true
  await fetchJobs()
  loading.value = false
  if (hasActiveJobs()) startPolling()
})

onUnmounted(stopPolling)
</script>
