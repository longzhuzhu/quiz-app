<template>
  <div>
    <!-- 页面标题 -->
    <div class="mb-6">
      <p class="text-sm text-primary-600 dark:text-primary-400">{{ examStore.current?.short_name || '考试项目' }}</p>
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ examStore.current?.name || '项目首页' }}</h1>
    </div>

    <!-- 统计仪表盘 - 4列 -->
    <div class="mb-8 grid grid-cols-2 md:grid-cols-4 gap-4">
      <!-- 题库数量 -->
      <div class="relative overflow-hidden rounded-xl bg-white dark:bg-slate-800 shadow-card p-5">
        <div class="absolute top-0 left-0 right-0 h-1 bg-primary-500 rounded-t-xl"></div>
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-100 dark:bg-primary-900/30">
            <FolderIcon class="h-5 w-5 text-primary-600 dark:text-primary-400" />
          </div>
          <div>
            <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ banks.length }}</div>
            <div class="text-sm text-gray-500 dark:text-gray-400">题库</div>
          </div>
        </div>
      </div>

      <!-- 总题目 -->
      <div class="relative overflow-hidden rounded-xl bg-white dark:bg-slate-800 shadow-card p-5">
        <div class="absolute top-0 left-0 right-0 h-1 bg-sky-500 rounded-t-xl"></div>
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-100 dark:bg-sky-900/30">
            <DocumentTextIcon class="h-5 w-5 text-sky-600 dark:text-sky-400" />
          </div>
          <div>
            <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ totalQuestions }}</div>
            <div class="text-sm text-gray-500 dark:text-gray-400">总题目</div>
          </div>
        </div>
      </div>

      <!-- 正确率 -->
      <div class="relative overflow-hidden rounded-xl bg-white dark:bg-slate-800 shadow-card p-5">
        <div class="absolute top-0 left-0 right-0 h-1 bg-emerald-500 rounded-t-xl"></div>
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
            <CheckBadgeIcon class="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div>
            <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ recentTotal > 0 ? recentAccuracy : 0 }}%</div>
            <div class="text-sm text-gray-500 dark:text-gray-400">正确率<span v-if="recentTotal > 0" class="text-xs text-gray-400 dark:text-gray-500 ml-1">(近{{ recentTotal }}题)</span></div>
          </div>
        </div>
      </div>

      <!-- 待攻克错题 -->
      <router-link :to="currentExamPath(route, 'wrong')" class="relative overflow-hidden rounded-xl bg-white dark:bg-slate-800 shadow-card p-5 hover:shadow-card-hover transition-shadow cursor-pointer">
        <div class="absolute top-0 left-0 right-0 h-1 bg-rose-500 rounded-t-xl"></div>
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-rose-100 dark:bg-rose-900/30">
            <ExclamationTriangleIcon class="h-5 w-5 text-rose-600 dark:text-rose-400" />
          </div>
          <div>
            <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ wrongStats.unresolved || 0 }}</div>
            <div class="text-sm text-gray-500 dark:text-gray-400">待攻克</div>
          </div>
        </div>
      </router-link>
    </div>

    <PracticeHeatmap
      :days="heatmap.days"
      :today="heatmap.today"
      :current-streak="heatmap.current_streak"
    />

    <!-- 题库列表 -->
    <div v-if="lastIncompleteSession" class="mb-4 rounded-xl bg-white dark:bg-slate-800 shadow-card p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div class="min-w-0">
          <p class="text-sm font-medium text-primary-600 dark:text-primary-400">继续上次答题</p>
          <h2 class="mt-1 text-lg font-semibold text-gray-900 dark:text-white truncate">
            {{ lastIncompleteSession.bank_name || '未知题库' }}
          </h2>
          <div class="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-sm text-gray-500 dark:text-gray-400">
            <span>{{ sessionModeLabel(lastIncompleteSession) }}</span>
            <span>进度：{{ lastIncompleteSession.answered_count || 0 }}/{{ lastIncompleteSession.total_questions || 0 }}</span>
            <span>正确率：{{ sessionAccuracy(lastIncompleteSession) }}%</span>
            <span>开始：{{ formatSessionDate(lastIncompleteSession.created_at) }}</span>
          </div>
        </div>
        <BaseButton variant="primary" size="sm" class="self-start md:self-center" @click="continueLastSession">
          继续答题
        </BaseButton>
      </div>
    </div>

    <div v-if="loading" class="space-y-4">
      <SkeletonLoader type="card" :count="2" />
    </div>
    <div v-else-if="banks.length === 0" class="py-16 text-center">
      <FolderIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-400 dark:text-gray-500">暂无题库，请管理员添加</p>
    </div>
    <div v-else class="space-y-4">
      <div v-for="bank in banks" :key="bank.id"
        class="rounded-xl bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-6">
        <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
          <div class="min-w-0">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ bank.name }}</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ bank.description || '暂无描述' }}</p>
            <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">
              {{ bank.question_count }} 道题目<template v-if="incompleteSessionByBankId[bank.id]"> ｜ 已答 {{ incompleteSessionByBankId[bank.id].answered_count || 0 }}/{{ incompleteSessionByBankId[bank.id].total_questions || 0 }} ｜ {{ sessionModeLabel(incompleteSessionByBankId[bank.id]) }}</template>
            </p>
          </div>
          <div class="flex gap-2 flex-wrap flex-shrink-0">
            <BaseButton v-if="incompleteSessionByBankId[bank.id]" variant="primary" size="sm" @click="continueSession(incompleteSessionByBankId[bank.id])">
              ▶ 继续答题
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="startQuiz(bank, 'sequential')" :disabled="bank.question_count === 0">
              ▶ 顺序练习
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="startQuiz(bank, 'random')" :disabled="bank.question_count === 0">
              🔀 随机练习
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="openTopicModal(bank)" :disabled="bank.question_count === 0">
              🎯 专项练习
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="openExamModal(bank)" :disabled="bank.question_count === 0">
              📝 模拟考试
            </BaseButton>
          </div>
        </div>
      </div>
    </div>

    <!-- 专项练习考点选择弹窗 -->
    <BaseModal :open="showTopicModal" title="选择专项考点" @close="showTopicModal = false">
      <div v-if="topicsLoading" class="py-6">
        <SkeletonLoader type="text" :count="3" />
      </div>
      <p v-else-if="topicOptions.length === 0" class="py-6 text-center text-sm text-gray-500 dark:text-gray-400">
        该题库所在的考试项目还没有考点，请管理员先灌入考点大纲。
      </p>
      <div v-else class="space-y-2">
        <button
          v-for="option in topicOptions"
          :key="option.key"
          type="button"
          :disabled="option.question_count === 0"
          class="w-full rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 enabled:hover:border-primary-500 enabled:hover:bg-primary-50 dark:enabled:hover:bg-primary-900/20"
          :class="option.key === selectedTopicKey
            ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
            : 'border-gray-200 dark:border-slate-600'"
          @click="selectedTopicKey = option.key"
        >
          <div class="font-medium text-gray-900 dark:text-white">{{ option.label }}</div>
          <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            <span v-if="option.blueprint_max">考试占 {{ option.blueprint_min }}–{{ option.blueprint_max }} 题 · </span>
            本库 {{ option.question_count }} 题
          </div>
        </button>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showTopicModal = false">取消</BaseButton>
        <BaseButton variant="primary" :disabled="!selectedTopicOption" @click="startTopicQuiz">
          开始练习
        </BaseButton>
      </template>
    </BaseModal>

    <!-- 模拟考试设置弹窗 -->
    <BaseModal :open="showExamModal" title="模拟考试设置" @close="showExamModal = false">
      <div class="space-y-4">
        <label class="block">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">
            题目数量（该题库共 {{ examBank?.question_count }} 题）
          </span>
          <input type="number" v-model.number="examQuestionCount"
            :min="1" :max="examBank?.question_count"
            class="mt-1 block w-full rounded-lg border-gray-300 dark:border-slate-600 dark:bg-slate-700 dark:text-white shadow-sm focus:border-primary-500 focus:ring-primary-500" />
        </label>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showExamModal = false">取消</BaseButton>
        <BaseButton variant="primary" @click="startExam"
          :disabled="!examQuestionCount || examQuestionCount < 1 || examQuestionCount > (examBank?.question_count || 0)">
          开始考试
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useBankStore } from '../stores/bank'
import { useQuizStore } from '../stores/quiz'
import { useExamStore } from '../stores/exam'
import { currentExamPath } from '../utils/examRoutes'
import { sessionModeLabel } from '../utils/quizMode'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import { formatLocalDate } from '../utils/localDate'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import PracticeHeatmap from '../components/PracticeHeatmap.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { FolderIcon, DocumentTextIcon, CheckBadgeIcon, ExclamationTriangleIcon } from '@heroicons/vue/24/outline'

const bankStore = useBankStore()
const quizStore = useQuizStore()
const examStore = useExamStore()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const wrongStats = ref({})
const recentAccuracy = ref(0)
const recentTotal = ref(0)
const heatmap = ref({ today: formatLocalDate(), current_streak: 0, days: [] })
const lastIncompleteSession = ref(null)
const incompleteSessionByBankId = ref({})
const showExamModal = ref(false)
const examBank = ref(null)
const examQuestionCount = ref(90)
const showTopicModal = ref(false)
const topicBank = ref(null)
const topicOptions = ref([])
const topicsLoading = ref(false)
const selectedTopicKey = ref(null)

const UNCLASSIFIED_TOPIC_KEY = '__unclassified__'

const banks = computed(() => bankStore.banks)
const loading = computed(() => bankStore.loading)
const totalQuestions = computed(() => banks.value.reduce((s, b) => s + b.question_count, 0))
const selectedTopicOption = computed(
  () => topicOptions.value.find(o => o.key === selectedTopicKey.value) || null
)
const quizHistoryPerPage = 100

onMounted(fetchDashboardData)

watch(() => route.params.examSlug, fetchDashboardData)

async function fetchDashboardData() {
  lastIncompleteSession.value = null
  incompleteSessionByBankId.value = {}
  const localToday = formatLocalDate()
  heatmap.value = { today: localToday, current_streak: 0, days: [] }

  const bankP = bankStore.fetchBanks().catch((e) => {
    toast.error(e.response?.data?.error || '获取题库失败')
  })
  const wrongP = client.get('/wrong/stats').then(r => { wrongStats.value = r.data }).catch(() => {})
  const accP = client.get('/quiz/recent-accuracy').then(r => {
    recentAccuracy.value = r.data.accuracy
    recentTotal.value = r.data.total
  }).catch(() => {})
  const heatmapP = client.get('/quiz/practice-heatmap', { params: { today: localToday } }).then(r => {
    heatmap.value = {
      today: r.data?.today || localToday,
      current_streak: Number(r.data?.current_streak) || 0,
      days: Array.isArray(r.data?.days) ? r.data.days : [],
    }
  }).catch(() => {
    heatmap.value = { today: localToday, current_streak: 0, days: [] }
  })
  const lastSessionP = client.get('/quiz/history', { params: { page: 1, per_page: quizHistoryPerPage } }).then(r => {
    const items = Array.isArray(r.data?.items) ? r.data.items : []
    updateIncompleteSessions(items)
  }).catch(() => {
    lastIncompleteSession.value = null
    incompleteSessionByBankId.value = {}
  })
  await Promise.allSettled([bankP, wrongP, accP, heatmapP, lastSessionP])
}

async function openTopicModal(bank) {
  topicBank.value = bank
  topicOptions.value = []
  selectedTopicKey.value = null
  topicsLoading.value = true
  showTopicModal.value = true

  try {
    const res = await client.get(`/banks/${bank.id}/topics`)
    const domains = (res.data?.topics || []).map(topic => ({
      key: String(topic.id),
      topic_id: topic.id,
      label: `${topic.code}. ${topic.short_name_zh}`,
      blueprint_min: topic.blueprint_min,
      blueprint_max: topic.blueprint_max,
      question_count: topic.question_count,
    }))
    // 未分类始终列出：题数为 0 时显示为不可选，让用户知道全部题目都已归类
    domains.push({
      key: UNCLASSIFIED_TOPIC_KEY,
      topic_id: null,
      label: '未分类',
      blueprint_min: 0,
      blueprint_max: 0,
      question_count: res.data?.unclassified_count || 0,
    })
    topicOptions.value = domains
    selectedTopicKey.value = domains.find(o => o.question_count > 0)?.key || null
  } catch (e) {
    toast.error(e.response?.data?.detail || '获取考点失败')
    showTopicModal.value = false
  } finally {
    topicsLoading.value = false
  }
}

async function startTopicQuiz() {
  const option = selectedTopicOption.value
  if (!option) return

  showTopicModal.value = false
  try {
    await quizStore.startQuiz(topicBank.value.id, 'topic', null, option.topic_id)
    router.push(currentExamPath(route, 'quiz', { sessionId: quizStore.session.id }))
  } catch (e) {
    toast.error(e.response?.data?.detail || '开始专项练习失败')
  }
}

function sessionAccuracy(session) {
  const explicitAccuracy = Number(session?.accuracy)
  if (Number.isFinite(explicitAccuracy)) return explicitAccuracy

  const correctCount = Number(session?.correct_count || 0)
  const answeredCount = Number(session?.answered_count || 0)
  if (answeredCount <= 0) return 0
  return Math.round((correctCount / answeredCount) * 1000) / 10
}

function formatSessionDate(value) {
  if (!value) return '未知时间'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未知时间' : date.toLocaleString('zh-CN')
}

function updateIncompleteSessions(items) {
  const incompleteSessions = items.filter(item => item.is_completed === false && item.mode !== 'wrong_practice')
  const sessionsByBankId = {}

  lastIncompleteSession.value = incompleteSessions[0] || null
  for (const session of incompleteSessions) {
    if (session.bank_id == null || sessionsByBankId[session.bank_id]) continue
    sessionsByBankId[session.bank_id] = session
  }
  incompleteSessionByBankId.value = sessionsByBankId
}

function continueSession(session) {
  const sessionId = session?.id
  if (sessionId == null) return
  router.push(currentExamPath(route, 'quiz', { sessionId }))
}

function continueLastSession() {
  continueSession(lastIncompleteSession.value)
}

async function startQuiz(bank, mode) {
  try {
    await quizStore.startQuiz(bank.id, mode)
    router.push(currentExamPath(route, 'quiz', { sessionId: quizStore.session.id }))
  } catch (e) {
    toast.error(e.response?.data?.error || '开始答题失败')
  }
}

function openExamModal(bank) {
  examBank.value = bank
  examQuestionCount.value = Math.min(90, bank.question_count)
  showExamModal.value = true
}

async function startExam() {
  showExamModal.value = false
  try {
    await quizStore.startQuiz(examBank.value.id, 'exam', examQuestionCount.value)
    router.push(currentExamPath(route, 'quiz', { sessionId: quizStore.session.id }))
  } catch (e) {
    toast.error(e.response?.data?.error || '开始考试失败')
  }
}
</script>
