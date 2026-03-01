<template>
  <div class="mx-auto max-w-3xl">
    <!-- 顶部区域：标题 + 统计摘要 -->
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">错题本</h1>

      <!-- 掌握率统计 -->
      <div class="mt-4 rounded-xl bg-white dark:bg-slate-800 shadow-card p-5">
        <div class="flex items-center justify-between text-sm text-gray-600 dark:text-gray-400">
          <span>
            已掌握
            <span class="font-semibold text-emerald-600 dark:text-emerald-400">{{ wrongStats.resolved }}</span>
            / 总
            <span class="font-semibold text-gray-900 dark:text-white">{{ wrongStats.total }}</span>
          </span>
          <span class="font-semibold text-emerald-600 dark:text-emerald-400">
            掌握率 {{ masteryRate }}%
          </span>
        </div>
        <div class="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-slate-700">
          <div
            class="h-full rounded-full bg-emerald-500 transition-all duration-500 ease-out"
            :style="{ width: masteryRate + '%' }"
          ></div>
        </div>
      </div>

      <!-- 筛选 + 练习按钮 -->
      <div class="mt-4 flex items-center gap-3">
        <select
          v-model="selectedBankId"
          class="flex-1 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        >
          <option :value="null">全部题库</option>
          <option v-for="bank in banks" :key="bank.id" :value="bank.id">{{ bank.name }}</option>
        </select>
        <BaseButton @click="practiceWrong" :disabled="wrongs.length === 0">
          错题练习
        </BaseButton>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-4">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="wrongs.length === 0" class="py-16 text-center">
      <FaceSmileIcon class="mx-auto h-16 w-16 text-emerald-400 dark:text-emerald-500" />
      <p class="mt-4 text-lg font-medium text-gray-700 dark:text-gray-300">暂无错题</p>
      <p class="mt-1 text-sm text-gray-400 dark:text-gray-500">继续保持，你做得很棒！</p>
    </div>

    <!-- 错题列表 -->
    <div v-else class="space-y-4">
      <div
        v-for="w in wrongs"
        :key="w.id"
        class="rounded-xl bg-white dark:bg-slate-800 shadow-card overflow-hidden"
      >
        <!-- 摘要行（可点击展开） -->
        <div
          class="flex items-start justify-between p-5 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-750 transition-colors"
          @click="toggle(w.id)"
        >
          <div class="flex-1 min-w-0">
            <p class="font-medium text-gray-900 dark:text-white leading-relaxed">{{ w.question.content }}</p>
            <div class="mt-2 flex flex-wrap gap-3 text-xs text-gray-400 dark:text-gray-500">
              <span class="inline-flex items-center gap-1">
                <span class="inline-block h-1.5 w-1.5 rounded-full bg-rose-400"></span>
                错误 {{ w.wrong_count }} 次
              </span>
              <span>正确答案: <span class="text-emerald-600 dark:text-emerald-400 font-medium">{{ w.question.correct_answer }}</span></span>
              <span v-if="w.question.question_type === 'multiple'" class="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-amber-600 dark:text-amber-400">多选</span>
              <span v-else-if="w.question.question_type === 'truefalse'" class="rounded-full bg-blue-100 dark:bg-blue-900/30 px-2 py-0.5 text-blue-600 dark:text-blue-400">判断</span>
            </div>
          </div>
          <div class="ml-4 flex items-center gap-2 flex-shrink-0">
            <BaseButton variant="secondary" size="sm" @click.stop="resolveWrong(w.id)">
              标记掌握
            </BaseButton>
            <ChevronDownIcon
              class="h-5 w-5 text-gray-400 dark:text-gray-500 transition-transform duration-200"
              :class="{ 'rotate-180': expandedId === w.id }"
            />
          </div>
        </div>

        <!-- 展开详情 -->
        <Transition
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="max-h-0 opacity-0"
          enter-to-class="max-h-[2000px] opacity-100"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="max-h-[2000px] opacity-100"
          leave-to-class="max-h-0 opacity-0"
        >
          <div v-if="expandedId === w.id" class="overflow-hidden">
            <div class="border-t border-gray-100 dark:border-slate-700 px-5 pb-5">
              <!-- 中文翻译 -->
              <p v-if="w.question.content_zh" class="mt-4 text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                {{ w.question.content_zh }}
              </p>

              <!-- 选项列表 -->
              <div class="mt-4 space-y-2">
                <div
                  v-for="opt in w.question.options"
                  :key="opt.key"
                  class="flex items-start gap-3 rounded-lg border p-3 transition-colors"
                  :class="isCorrectOption(w.question, opt.key)
                    ? 'border-emerald-400 bg-emerald-50 dark:border-emerald-600 dark:bg-emerald-900/20'
                    : 'border-gray-200 dark:border-slate-600 bg-white dark:bg-slate-800'"
                >
                  <div class="flex-1">
                    <span class="font-medium text-gray-900 dark:text-white">{{ opt.key }}.</span>
                    <span class="text-gray-700 dark:text-gray-300"> {{ opt.text }}</span>
                    <span v-if="opt.text_zh" class="block text-sm text-gray-500 dark:text-gray-400 mt-0.5">{{ opt.text_zh }}</span>
                  </div>
                  <span
                    v-if="isCorrectOption(w.question, opt.key)"
                    class="ml-auto text-xs font-medium text-emerald-600 dark:text-emerald-400 flex-shrink-0"
                  >正确</span>
                </div>
              </div>

              <!-- 解析区域 -->
              <div v-if="w.question.explanation" class="mt-4 rounded-lg bg-gray-50 dark:bg-slate-700/50 p-4 text-sm">
                <p class="font-medium text-gray-700 dark:text-gray-300">解析:</p>
                <p class="mt-1 whitespace-pre-wrap text-gray-600 dark:text-gray-400">{{ w.question.explanation }}</p>
              </div>
              <div v-if="w.question.explanation_zh" class="mt-2 rounded-lg bg-gray-50 dark:bg-slate-700/50 p-4 text-sm">
                <p class="font-medium text-gray-700 dark:text-gray-300">中文解析:</p>
                <p class="mt-1 whitespace-pre-wrap text-gray-600 dark:text-gray-400">{{ w.question.explanation_zh }}</p>
              </div>

              <!-- AI 按钮 -->
              <div class="mt-4 flex gap-2">
                <TranslateButton
                  :question-id="w.question.id"
                  :has-translation="!!w.question.content_zh"
                  :show="translationVisible[w.id] ?? false"
                  @translated="onTranslated(w, $event)"
                  @toggle="translationVisible[w.id] = !translationVisible[w.id]"
                />
                <ExplainButton :question-id="w.question.id" />
                <AddVocabButton />
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBankStore } from '../stores/bank'
import { useQuizStore } from '../stores/quiz'
import client from '../api/client'
import TranslateButton from '../components/TranslateButton.vue'
import ExplainButton from '../components/ExplainButton.vue'
import AddVocabButton from '../components/AddVocabButton.vue'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { useToast } from '../composables/useToast'
import { ChevronDownIcon, FaceSmileIcon } from '@heroicons/vue/24/outline'

const bankStore = useBankStore()
const quizStore = useQuizStore()
const router = useRouter()
const toast = useToast()

const wrongs = ref([])
const loading = ref(false)
const selectedBankId = ref(null)
const banks = ref([])
const expandedId = ref(null)
const translationVisible = reactive({})
const wrongStats = ref({ unresolved: 0, resolved: 0, total: 0 })

const masteryRate = computed(() => {
  if (wrongStats.value.total === 0) return 0
  return Math.round((wrongStats.value.resolved / wrongStats.value.total) * 100)
})

function toggle(id) {
  expandedId.value = expandedId.value === id ? null : id
}

function isCorrectOption(question, key) {
  return question.correct_answer.split(',').map(s => s.trim()).includes(key)
}

function onTranslated(w, data) {
  if (data.content_zh) w.question.content_zh = data.content_zh
  if (data.options_zh) {
    for (const opt of w.question.options) {
      const translated = data.options_zh.find(o => o.key === opt.key)
      if (translated) opt.text_zh = translated.text_zh
    }
  }
  translationVisible[w.id] = true
}

async function fetchWrongs() {
  loading.value = true
  expandedId.value = null
  try {
    const params = selectedBankId.value ? { bank_id: selectedBankId.value } : {}
    const res = await client.get('/wrong/', { params })
    wrongs.value = res.data
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await client.get('/wrong/stats')
    wrongStats.value = res.data
  } catch {}
}

async function resolveWrong(id) {
  await client.put(`/wrong/${id}/resolve`)
  wrongs.value = wrongs.value.filter(w => w.id !== id)
  fetchStats()
}

async function practiceWrong() {
  try {
    const res = await client.post('/wrong/practice', { bank_id: selectedBankId.value })
    quizStore.session = res.data.session
    quizStore.questions = res.data.questions
    quizStore.currentIndex = 0
    router.push(`/quiz/${res.data.session.id}`)
  } catch (e) {
    toast.error(e.response?.data?.error || '开始错题练习失败')
  }
}

onMounted(async () => {
  await bankStore.fetchBanks()
  banks.value = bankStore.banks
  fetchWrongs()
  fetchStats()
})

watch(selectedBankId, fetchWrongs)
</script>
