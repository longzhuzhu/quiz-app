<template>
  <div>
    <!-- 页面标题 -->
    <h1 class="mb-6 text-2xl font-bold text-gray-900 dark:text-white">题库列表</h1>

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
      <router-link to="/wrong" class="relative overflow-hidden rounded-xl bg-white dark:bg-slate-800 shadow-card p-5 hover:shadow-card-hover transition-shadow cursor-pointer">
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

    <!-- 题库列表 -->
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
            <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">{{ bank.question_count }} 道题目</p>
          </div>
          <div class="flex gap-2 flex-wrap flex-shrink-0">
            <BaseButton variant="primary" size="sm" @click="startQuiz(bank, 'sequential')" :disabled="bank.question_count === 0">
              ▶ 顺序练习
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="startQuiz(bank, 'random')" :disabled="bank.question_count === 0">
              🔀 随机练习
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="openExamModal(bank)" :disabled="bank.question_count === 0">
              📝 模拟考试
            </BaseButton>
          </div>
        </div>
      </div>
    </div>

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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBankStore } from '../stores/bank'
import { useQuizStore } from '../stores/quiz'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { FolderIcon, DocumentTextIcon, CheckBadgeIcon, ExclamationTriangleIcon } from '@heroicons/vue/24/outline'

const bankStore = useBankStore()
const quizStore = useQuizStore()
const router = useRouter()
const toast = useToast()
const wrongStats = ref({})
const recentAccuracy = ref(0)
const recentTotal = ref(0)
const showExamModal = ref(false)
const examBank = ref(null)
const examQuestionCount = ref(90)

const banks = computed(() => bankStore.banks)
const loading = computed(() => bankStore.loading)
const totalQuestions = computed(() => banks.value.reduce((s, b) => s + b.question_count, 0))

onMounted(async () => {
  bankStore.fetchBanks()
  const wrongP = client.get('/wrong/stats').then(r => { wrongStats.value = r.data }).catch(() => {})
  const accP = client.get('/quiz/recent-accuracy').then(r => {
    recentAccuracy.value = r.data.accuracy
    recentTotal.value = r.data.total
  }).catch(() => {})
  await Promise.allSettled([wrongP, accP])
})

async function startQuiz(bank, mode) {
  try {
    await quizStore.startQuiz(bank.id, mode)
    router.push(`/quiz/${quizStore.session.id}`)
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
    router.push(`/quiz/${quizStore.session.id}`)
  } catch (e) {
    toast.error(e.response?.data?.error || '开始考试失败')
  }
}
</script>
