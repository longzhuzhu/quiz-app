<template>
  <div>
    <!-- 导航 -->
    <div class="mb-4">
      <router-link to="/import-jobs"
        class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">
        <ArrowLeftIcon class="h-4 w-4" />
        返回导入任务列表
      </router-link>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="2" />
    </div>

    <div v-else-if="!job">
      <div class="py-16 text-center text-gray-400 dark:text-gray-500">导入任务不存在</div>
    </div>

    <div v-else>
      <!-- 任务概览 -->
      <div class="mb-6">
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ job.file_name }}</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          <span :class="statusClass(job.status)">{{ statusLabel(job.status) }}</span>
          <span class="mx-1">|</span>
          题库 #{{ job.bank_id }}
          <span class="mx-1">|</span>
          {{ job.file_type?.toUpperCase() }}
          <span class="mx-1">|</span>
          {{ job.created_at }}
        </p>
      </div>

      <!-- 进度统计卡片 -->
      <div class="mb-6 grid grid-cols-2 md:grid-cols-5 gap-3">
        <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4 text-center">
          <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ job.parsed_questions || 0 }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">解析题数</div>
        </div>
        <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4 text-center">
          <div class="text-2xl font-bold text-emerald-600 dark:text-emerald-400">{{ job.imported_questions || 0 }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">已入库</div>
        </div>
        <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4 text-center">
          <div class="text-2xl font-bold text-amber-600 dark:text-amber-400">{{ job.review_questions || 0 }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">待复核</div>
        </div>
        <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4 text-center">
          <div class="text-2xl font-bold text-rose-600 dark:text-rose-400">{{ job.failed_chunks || 0 }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">失败 Chunk</div>
        </div>
        <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4 text-center">
          <div class="text-2xl font-bold text-sky-600 dark:text-sky-400">{{ job.total_chunks || 0 }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">总 Chunk</div>
        </div>
      </div>

      <!-- 后台任务进度 -->
      <div v-if="job.background_job" class="mb-6 rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4">
        <h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">后台任务进度</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400">{{ job.background_job.status_message || '无状态信息' }}</p>
        <div v-if="job.background_job.progress_total > 0" class="mt-2">
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span>{{ job.background_job.progress_done || 0 }} / {{ job.background_job.progress_total }}</span>
            <span>{{ Math.round(((job.background_job.progress_done || 0) / job.background_job.progress_total) * 100) }}%</span>
          </div>
          <div class="w-full bg-gray-200 dark:bg-slate-700 rounded-full h-2">
            <div class="bg-primary-600 h-2 rounded-full transition-all"
              :style="{ width: Math.min(100, ((job.background_job.progress_done || 0) / job.background_job.progress_total) * 100) + '%' }"></div>
          </div>
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="job.error_message" class="mb-6 rounded-card-lg border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-900/20 p-4">
        <p class="text-sm text-rose-600 dark:text-rose-400">{{ job.error_message }}</p>
      </div>

      <!-- 操作按钮 -->
      <div class="mb-6 flex gap-2 flex-wrap">
        <BaseButton v-if="job.review_questions > 0"
          variant="secondary"
          @click="$router.push(`/import-jobs/${job.id}/review`)">
          <ExclamationCircleIcon class="h-4 w-4" />
          复核待审核题目 ({{ job.review_questions }})
        </BaseButton>
        <BaseButton variant="secondary"
          @click="$router.push(`/import-jobs/${job.id}/auto-handled`)">
          <ClipboardDocumentListIcon class="h-4 w-4" />
          自动处理记录 ({{ job.auto_handled_questions || 0 }})
        </BaseButton>
      </div>

      <!-- Chunk 列表 -->
      <div class="mb-6">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">Chunks</h2>
        <div v-if="chunks.length === 0" class="text-sm text-gray-400 dark:text-gray-500">暂无 Chunk 数据</div>
        <div v-else class="space-y-2">
          <div v-for="chunk in chunks" :key="chunk.id"
            class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4">
            <div class="flex items-center justify-between">
              <div>
                <span class="text-sm font-medium text-gray-900 dark:text-white">Chunk #{{ chunk.chunk_no }}</span>
                <span class="mx-2 text-xs text-gray-400">|</span>
                <span :class="chunkStatusClass(chunk.status)" class="text-xs">{{ chunk.status }}</span>
                <span v-if="chunk.start_page" class="mx-2 text-xs text-gray-400">|</span>
                <span v-if="chunk.start_page" class="text-xs text-gray-500">P.{{ chunk.start_page }}-{{ chunk.end_page }}</span>
              </div>
              <BaseButton variant="ghost" size="sm" @click="toggleChunk(chunk.id)">
                {{ expandedChunks.has(chunk.id) ? '收起' : '展开' }}
              </BaseButton>
            </div>
            <div v-if="chunk.issues" class="mt-2 text-xs text-amber-600 dark:text-amber-400">
              {{ chunk.issues.chunk_issues?.join('; ') || chunk.issues.error || JSON.stringify(chunk.issues) }}
            </div>
            <div v-if="expandedChunks.has(chunk.id)" class="mt-3">
              <pre class="max-h-60 overflow-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-slate-900 rounded-card p-3">{{ chunk.chunk_text }}</pre>
            </div>
          </div>
        </div>
      </div>

      <!-- 解析题目列表 -->
      <div>
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">解析题目</h2>
        <div v-if="questions.length === 0" class="text-sm text-gray-400 dark:text-gray-500">暂无解析题目数据</div>
        <div v-else class="space-y-3">
          <div v-for="q in questions" :key="q.id"
            class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-4">
            <div class="flex items-start justify-between gap-2">
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-gray-900 dark:text-white">
                  <span v-if="q.source_question_no" class="text-gray-400 mr-1">Q{{ q.source_question_no }}</span>
                  {{ q.content }}
                </p>
                <div v-if="q.options" class="mt-2 flex flex-wrap gap-1">
                  <span v-for="opt in q.options" :key="opt.key"
                    class="text-xs rounded-md px-2 py-0.5"
                    :class="(q.correct_answer || []).includes(opt.key)
                      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                      : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'">
                    {{ opt.key }}. {{ opt.text }}
                  </span>
                </div>
                <div class="mt-2 flex flex-wrap gap-2 text-xs text-gray-400 dark:text-gray-500">
                  <span>类型: {{ questionTypeLabel(q.question_type) }}</span>
                  <span>答案: {{ (q.correct_answer || []).join(', ') || '无' }}</span>
                  <span v-if="q.llm_confidence != null">LLM: {{ (q.llm_confidence * 100).toFixed(1) }}%</span>
                  <span v-if="q.final_confidence != null">最终: {{ (q.final_confidence * 100).toFixed(1) }}%</span>
                </div>
                <div v-if="q.issues" class="mt-1 flex flex-wrap gap-1">
                  <span v-for="issue in (q.issues.details || [])" :key="issue.code"
                    class="text-xs rounded px-1.5 py-0.5"
                    :class="issue.severity === 'HIGH' ? 'bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400' : issue.severity === 'MEDIUM' ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400' : 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-gray-400'">
                    {{ issue.code }}
                  </span>
                </div>
              </div>
              <div class="flex-shrink-0">
                <span class="text-xs rounded-full px-2 py-0.5"
                  :class="importStatusClass(q.import_status)">{{ importStatusLabel(q.import_status) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { ArrowLeftIcon, ClipboardDocumentListIcon, ExclamationCircleIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const jobId = route.params.jobId
const job = ref(null)
const chunks = ref([])
const questions = ref([])
const loading = ref(true)
const expandedChunks = ref(new Set())
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
  unimported: '未入库',
  failed: '失败',
  cancelled: '已取消',
}

const IMPORT_STATUS_MAP = {
  waiting: '等待',
  imported: '已入库',
  skipped: '已跳过',
}

function statusLabel(status) { return STATUS_MAP[status] || status }
function statusClass(status) {
  const active = ['pending', 'extracting', 'chunking', 'parsing', 'validating', 'importing']
  if (active.includes(status)) return 'text-sky-600 dark:text-sky-400'
  if (status === 'imported') return 'text-emerald-600 dark:text-emerald-400'
  if (status === 'unimported') return 'text-gray-500 dark:text-gray-400'
  if (['review_required', 'partial_imported'].includes(status)) return 'text-amber-600 dark:text-amber-400'
  if (status === 'failed') return 'text-rose-600 dark:text-rose-400'
  return 'text-gray-500 dark:text-gray-400'
}

function chunkStatusClass(status) {
  if (['parsed', 'parsed_cached'].includes(status)) return 'text-emerald-600 dark:text-emerald-400'
  if (['pending', 'parsing'].includes(status)) return 'text-sky-600 dark:text-sky-400'
  if (['failed', 'llm_failed', 'parse_failed'].includes(status)) return 'text-rose-600 dark:text-rose-400'
  return 'text-gray-500 dark:text-gray-400'
}

function importStatusLabel(status) { return IMPORT_STATUS_MAP[status] || status }
function importStatusClass(status) {
  if (status === 'imported') return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
  if (status === 'skipped') return 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'
  return 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
}

function questionTypeLabel(type) {
  const map = { single: '单选', multiple: '多选', truefalse: '判断', unknown: '未知' }
  return map[type] || type || '未知'
}

function toggleChunk(chunkId) {
  const next = new Set(expandedChunks.value)
  if (next.has(chunkId)) next.delete(chunkId)
  else next.add(chunkId)
  expandedChunks.value = next
}

function isActive() {
  const active = ['pending', 'extracting', 'chunking', 'parsing', 'validating', 'importing']
  return active.includes(job.value?.status)
}

async function fetchJob() {
  try {
    const res = await client.get(`/import-jobs/${jobId}`)
    job.value = res.data
  } catch {
    // 静默处理
  }
}

async function fetchChunks() {
  try {
    const res = await client.get(`/import-jobs/${jobId}/chunks`)
    chunks.value = res.data.chunks || []
  } catch {
    // 静默处理
  }
}

async function fetchQuestions() {
  try {
    const res = await client.get(`/import-jobs/${jobId}/parsed-questions`)
    questions.value = res.data.questions || []
  } catch {
    // 静默处理
  }
}

async function fetchAll() {
  await Promise.all([fetchJob(), fetchChunks(), fetchQuestions()])
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    await fetchAll()
    if (!isActive()) stopPolling()
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
  await fetchAll()
  loading.value = false
  if (isActive()) startPolling()
})

onUnmounted(stopPolling)
</script>
