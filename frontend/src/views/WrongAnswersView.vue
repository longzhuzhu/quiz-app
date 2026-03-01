<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900">错题本</h1>
      <div class="flex gap-2">
        <select v-model="selectedBankId"
          class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none">
          <option :value="null">全部题库</option>
          <option v-for="bank in banks" :key="bank.id" :value="bank.id">{{ bank.name }}</option>
        </select>
        <button @click="practiceWrong" :disabled="wrongs.length === 0"
          class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
          错题练习
        </button>
      </div>
    </div>

    <div v-if="loading" class="text-center text-gray-500">加载中...</div>
    <div v-else-if="wrongs.length === 0" class="py-12 text-center text-gray-400">没有错题，继续保持！</div>
    <div v-else class="space-y-3">
      <div v-for="w in wrongs" :key="w.id" class="rounded-lg bg-white shadow">
        <!-- 摘要行（可点击展开） -->
        <div class="flex items-start justify-between p-5 cursor-pointer" @click="toggle(w.id)">
          <div class="flex-1 min-w-0">
            <p class="font-medium text-gray-900">{{ w.question.content }}</p>
            <div class="mt-2 flex gap-4 text-xs text-gray-400">
              <span>错误 {{ w.wrong_count }} 次</span>
              <span>正确答案: {{ w.question.correct_answer }}</span>
              <span v-if="w.question.question_type === 'multiple'" class="text-amber-500">多选</span>
              <span v-else-if="w.question.question_type === 'truefalse'" class="text-blue-500">判断</span>
            </div>
          </div>
          <div class="ml-4 flex items-center gap-2 flex-shrink-0">
            <button @click.stop="resolveWrong(w.id)"
              class="rounded-md border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50">
              标记掌握
            </button>
            <svg class="h-4 w-4 text-gray-400 transition-transform" :class="{ 'rotate-180': expandedId === w.id }"
              fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>

        <!-- 展开详情 -->
        <div v-if="expandedId === w.id" class="border-t border-gray-100 px-5 pb-5">
          <!-- 中文翻译 -->
          <p v-if="w.question.content_zh" class="mt-3 text-sm text-gray-600 leading-relaxed">{{ w.question.content_zh }}</p>

          <!-- 选项列表 -->
          <div class="mt-4 space-y-2">
            <div v-for="opt in w.question.options" :key="opt.key"
              class="flex items-start gap-3 rounded-lg border p-3"
              :class="isCorrectOption(w.question, opt.key) ? 'border-green-500 bg-green-50' : 'border-gray-200'">
              <div>
                <span class="font-medium">{{ opt.key }}.</span> {{ opt.text }}
                <span v-if="opt.text_zh" class="block text-sm text-gray-500 mt-0.5">{{ opt.text_zh }}</span>
              </div>
              <span v-if="isCorrectOption(w.question, opt.key)" class="ml-auto text-xs text-green-600 flex-shrink-0">正确</span>
            </div>
          </div>

          <!-- 解析区域 -->
          <div v-if="w.question.explanation" class="mt-4 rounded-lg bg-gray-50 p-4 text-sm">
            <p class="font-medium text-gray-700">解析:</p>
            <p class="mt-1 whitespace-pre-wrap text-gray-600">{{ w.question.explanation }}</p>
          </div>
          <div v-if="w.question.explanation_zh" class="mt-2 rounded-lg bg-gray-50 p-4 text-sm">
            <p class="font-medium text-gray-700">中文解析:</p>
            <p class="mt-1 whitespace-pre-wrap text-gray-600">{{ w.question.explanation_zh }}</p>
          </div>

          <!-- AI 按钮 -->
          <div class="mt-4 flex gap-2">
            <TranslateButton :question-id="w.question.id"
              :has-translation="!!w.question.content_zh"
              :show="translationVisible[w.id] ?? false"
              @translated="onTranslated(w, $event)"
              @toggle="translationVisible[w.id] = !translationVisible[w.id]" />
            <ExplainButton :question-id="w.question.id" />
            <AddVocabButton />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBankStore } from '../stores/bank'
import { useQuizStore } from '../stores/quiz'
import client from '../api/client'
import TranslateButton from '../components/TranslateButton.vue'
import ExplainButton from '../components/ExplainButton.vue'
import AddVocabButton from '../components/AddVocabButton.vue'

const bankStore = useBankStore()
const quizStore = useQuizStore()
const router = useRouter()

const wrongs = ref([])
const loading = ref(false)
const selectedBankId = ref(null)
const banks = ref([])
const expandedId = ref(null)
const translationVisible = reactive({})

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

async function resolveWrong(id) {
  await client.put(`/wrong/${id}/resolve`)
  wrongs.value = wrongs.value.filter(w => w.id !== id)
}

async function practiceWrong() {
  try {
    const res = await client.post('/wrong/practice', { bank_id: selectedBankId.value })
    quizStore.session = res.data.session
    quizStore.questions = res.data.questions
    quizStore.currentIndex = 0
    router.push(`/quiz/${res.data.session.id}`)
  } catch (e) {
    alert(e.response?.data?.error || '开始错题练习失败')
  }
}

onMounted(async () => {
  await bankStore.fetchBanks()
  banks.value = bankStore.banks
  fetchWrongs()
})

watch(selectedBankId, fetchWrongs)
</script>
