<template>
  <div>
    <!-- 导航 -->
    <div class="mb-4">
      <router-link :to="currentExamPath(route, 'importJobDetail', { jobId })"
        class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">
        <ArrowLeftIcon class="h-4 w-4" />
        返回任务详情
      </router-link>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="2" />
    </div>

    <div v-else>
      <div class="mb-6 flex items-center justify-between">
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">人工复核</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          待复核 {{ pendingCount }} / 共 {{ items.length }} 项
        </p>
      </div>

      <!-- 空状态 -->
      <div v-if="items.length === 0" class="py-16 text-center">
        <CheckCircleIcon class="mx-auto h-12 w-12 text-emerald-400 dark:text-emerald-500" />
        <p class="mt-4 text-gray-400 dark:text-gray-500">没有待复核项</p>
      </div>

      <!-- 复核项列表 -->
      <div v-else class="space-y-4">
        <div v-for="item in items" :key="item.id"
          class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-5"
          :class="{ 'opacity-60': item.status !== 'pending' }">

          <!-- 标题行 -->
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-gray-900 dark:text-white">
                Review #{{ item.id }}
              </span>
              <span class="text-xs rounded-full px-2 py-0.5"
                :class="severityClass(item.severity)">{{ item.severity || 'N/A' }}</span>
              <span class="text-xs rounded-full px-2 py-0.5"
                :class="reviewStatusClass(item.status)">{{ reviewStatusLabel(item.status) }}</span>
            </div>
            <div v-if="item.status === 'pending'" class="flex gap-2">
              <BaseButton variant="primary" size="sm" @click="acceptItem(item)" :loading="actionLoading === item.id">
                <CheckIcon class="h-4 w-4" />
                接受入库
              </BaseButton>
              <BaseButton variant="secondary" size="sm" @click="skipItem(item)" :loading="actionLoading === item.id">
                <XMarkIcon class="h-4 w-4" />
                跳过
              </BaseButton>
              <BaseButton variant="ghost" size="sm" @click="reparseItem(item)" :loading="actionLoading === item.id">
                <ArrowPathIcon class="h-4 w-4" />
                重新解析
              </BaseButton>
            </div>
          </div>

          <!-- 复核原因 -->
          <div class="mb-3 text-xs text-amber-600 dark:text-amber-400">
            复核类型: {{ item.review_type || '未知' }}
          </div>

          <!-- 解析结果 -->
          <div v-if="item.parsed_question" class="mb-4">
            <h4 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase mb-2">LLM 解析结果</h4>
            <div class="rounded-card bg-gray-50 dark:bg-slate-900 p-3">
              <p class="text-sm text-gray-900 dark:text-white">
                <span v-if="item.parsed_question.source_question_no" class="text-gray-400 mr-1">Q{{ item.parsed_question.source_question_no }}</span>
                {{ item.parsed_question.content }}
              </p>
              <div v-if="item.parsed_question.options" class="mt-2 flex flex-wrap gap-1">
                <span v-for="opt in item.parsed_question.options" :key="opt.key"
                  class="text-xs rounded-md px-2 py-0.5"
                  :class="(item.parsed_question.correct_answer || []).includes(opt.key)
                    ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                    : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'">
                  {{ opt.key }}. {{ opt.text }}
                </span>
              </div>
              <div class="mt-2 flex flex-wrap gap-2 text-xs text-gray-400 dark:text-gray-500">
                <span>类型: {{ questionTypeLabel(item.parsed_question.question_type) }}</span>
                <span>答案: {{ (item.parsed_question.correct_answer || []).join(', ') || '无' }}</span>
                <span v-if="item.parsed_question.final_confidence != null">
                  置信度: {{ (item.parsed_question.final_confidence * 100).toFixed(1) }}%
                </span>
              </div>
              <div v-if="item.parsed_question.issues" class="mt-1 flex flex-wrap gap-1">
                <span v-for="issue in (item.parsed_question.issues.details || [])" :key="issue.code"
                  class="text-xs rounded px-1.5 py-0.5"
                  :class="issue.severity === 'HIGH' ? 'bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400' : 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'">
                  {{ issue.code }}: {{ issue.detail }}
                </span>
              </div>
              <p v-if="item.parsed_question.explanation" class="mt-2 text-xs text-gray-500 dark:text-gray-400">
                解析: {{ item.parsed_question.explanation }}
              </p>
            </div>
          </div>

          <!-- 原始 Chunk 文本 -->
          <div v-if="item.chunk_text">
            <h4 class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase mb-2">原始 Chunk 文本</h4>
            <pre class="max-h-48 overflow-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-slate-900 rounded-card p-3">{{ item.chunk_text }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import { currentExamPath } from '../utils/examRoutes'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { ArrowLeftIcon, CheckIcon, XMarkIcon, ArrowPathIcon, CheckCircleIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const toast = useToast()
const jobId = route.params.jobId
const items = ref([])
const loading = ref(true)
const actionLoading = ref(null)
let pollTimer = null

const pendingCount = computed(() => items.value.filter(i => i.status === 'pending').length)

function severityClass(severity) {
  if (severity === 'HIGH') return 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400'
  if (severity === 'MEDIUM') return 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
  return 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'
}

function reviewStatusClass(status) {
  if (status === 'accepted') return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
  if (status === 'skipped') return 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'
  return 'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400'
}

function reviewStatusLabel(status) {
  const map = { pending: '待处理', accepted: '已接受', skipped: '已跳过' }
  return map[status] || status
}

function questionTypeLabel(type) {
  const map = { single: '单选', multiple: '多选', truefalse: '判断', unknown: '未知' }
  return map[type] || type || '未知'
}

async function fetchItems() {
  try {
    const res = await client.get(`/import-jobs/${jobId}/review-items`)
    items.value = res.data.items || []
  } catch {
    // 静默处理
  }
}

function hasPending() {
  return items.value.some(i => i.status === 'pending')
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    await fetchItems()
    if (!hasPending()) stopPolling()
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function acceptItem(item) {
  actionLoading.value = item.id
  try {
    await client.post(`/import-jobs/${jobId}/review-items/${item.id}/accept`)
    toast.success('题目已入库')
    await fetchItems()
  } catch (e) {
    toast.error(e.response?.data?.detail || '接受失败')
  } finally {
    actionLoading.value = null
  }
}

async function skipItem(item) {
  actionLoading.value = item.id
  try {
    await client.post(`/import-jobs/${jobId}/review-items/${item.id}/skip`)
    toast.success('题目已跳过')
    await fetchItems()
  } catch (e) {
    toast.error(e.response?.data?.detail || '跳过失败')
  } finally {
    actionLoading.value = null
  }
}

async function reparseItem(item) {
  actionLoading.value = item.id
  try {
    const res = await client.post(`/import-jobs/${jobId}/review-items/${item.id}/reparse`)
    toast.success(res.data.message || '重新解析任务已创建')
    await fetchItems()
    startPolling()
  } catch (e) {
    toast.error(e.response?.data?.detail || '重新解析失败')
  } finally {
    actionLoading.value = null
  }
}

onMounted(async () => {
  loading.value = true
  await fetchItems()
  loading.value = false
  if (hasPending()) startPolling()
})

onUnmounted(stopPolling)
</script>
