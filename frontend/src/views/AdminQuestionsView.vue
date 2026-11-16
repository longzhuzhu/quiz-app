<template>
  <div>
    <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <router-link :to="currentExamPath(route, 'banks')"
          class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">
          <ArrowLeftIcon class="h-4 w-4" />
          返回题库列表
        </router-link>
        <div class="mt-1 flex flex-wrap items-center gap-2">
          <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ bankName }} - 题目管理</h1>
          <span
            v-if="isPlatformCopy"
            class="inline-flex rounded-full bg-sky-100 dark:bg-sky-900/30 px-2 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400"
          >平台副本</span>
        </div>
        <p v-if="isPlatformCopy" class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          正式内容只读：来源 {{ shortId(sourcePlatformBankId, 8) }}
          <template v-if="sourcePlatformReleaseId">，版本 {{ shortId(sourcePlatformReleaseId, 8) }}</template>
          ；可更正正确答案，翻译与 AI 解析照常可用。
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <BaseButton variant="secondary" @click="batchTranslate" :loading="translating" :disabled="translating">
          <LanguageIcon class="h-4 w-4" />
          {{ translating ? '翻译中...' : '批量翻译' }}
        </BaseButton>
        <BaseButton v-if="!isPlatformCopy" variant="secondary" @click="batchTagTopics" :loading="tagging" :disabled="tagging">
          <TagIcon class="h-4 w-4" />
          {{ tagging ? tagProgressText : '批量打标' }}
        </BaseButton>
        <BaseButton v-if="!isPlatformCopy" @click="showAdd = true">
          <PlusIcon class="h-4 w-4" />
          添加题目
        </BaseButton>
      </div>
    </div>

    <div
      v-if="isPlatformCopy"
      class="mb-4 rounded-card-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800 dark:border-sky-800 dark:bg-sky-900/20 dark:text-sky-200"
    >
      平台副本的题干、选项与题型来自所选发布版本，不能编辑、增删或再导入；如需修正判分答案，请使用每题的「更正答案」。
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="questions.length === 0" class="py-16 text-center">
      <DocumentTextIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-400 dark:text-gray-500">
        {{ isPlatformCopy ? '该平台副本没有题目' : '暂无题目，点击上方按钮添加' }}
      </p>
    </div>

    <!-- 题目列表 -->
    <div v-else class="space-y-3">
      <div v-for="(q, i) in questions" :key="q.id"
        class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-4">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-900 dark:text-white">{{ (page - 1) * perPage + i + 1 }}. {{ q.content }}</p>
            <p v-if="q.content_zh && (!isPlatformCopy || isTranslationVisible(q.id))" class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ q.content_zh }}</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <span v-for="opt in q.options" :key="opt.key"
                class="text-xs rounded-md px-2 py-0.5"
                :class="q.correct_answer.includes(opt.key)
                  ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                  : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'">
                {{ opt.key }}. {{ opt.text }}
                <template v-if="opt.text_zh && (!isPlatformCopy || isTranslationVisible(q.id))">
                  <span class="text-gray-400 dark:text-gray-500">/ {{ opt.text_zh }}</span>
                </template>
              </span>
            </div>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
              类型: {{ q.question_type === 'single' ? '单选' : q.question_type === 'multiple' ? '多选' : '判断' }}
              · 答案: {{ q.correct_answer }}
            </p>
            <!-- 个人考点（仅自建/普通库） -->
            <div v-if="!isPlatformCopy" class="mt-1 flex flex-wrap items-center gap-1">
              <span v-for="t in q.topics" :key="t.id"
                class="rounded-md bg-sky-100 dark:bg-sky-900/30 px-2 py-0.5 text-xs text-sky-700 dark:text-sky-400">
                {{ t.number || t.code }} {{ t.short_name_zh }}
              </span>
              <span v-if="!q.topics || q.topics.length === 0" class="text-xs text-gray-400 dark:text-gray-500">
                考点未分类
              </span>
            </div>
            <!-- 平台来源考点：只读描述，不参与项目专项练习 -->
            <div v-if="isPlatformCopy" class="mt-1 flex flex-wrap items-center gap-1">
              <span class="text-xs text-gray-400 dark:text-gray-500">来源考点：</span>
              <span v-for="(topic, topicIndex) in sourceTopics(q)" :key="topicIndex"
                class="rounded-md bg-violet-100 dark:bg-violet-900/30 px-2 py-0.5 text-xs text-violet-700 dark:text-violet-300">
                {{ topic }}
              </span>
              <span v-if="sourceTopics(q).length === 0" class="text-xs text-gray-400 dark:text-gray-500">未标注</span>
            </div>
          </div>
          <div class="ml-2 flex flex-shrink-0 flex-wrap justify-end gap-2">
            <BaseButton v-if="isPlatformCopy" variant="ghost" size="sm" @click="openCorrectAnswer(q)">
              <CheckBadgeIcon class="h-4 w-4" />
              更正答案
            </BaseButton>
            <template v-if="!isPlatformCopy">
              <BaseButton variant="ghost" size="sm" @click="startEdit(q)">
                <PencilSquareIcon class="h-4 w-4" />
                编辑
              </BaseButton>
              <BaseButton variant="ghost" size="sm" class="!text-rose-500 hover:!text-rose-700 dark:!text-rose-400" @click="confirmDeleteQuestion(q.id)">
                <TrashIcon class="h-4 w-4" />
                删除
              </BaseButton>
            </template>
          </div>
        </div>
        <!-- 辅助学习：平台副本保留翻译与 AI 解析 -->
        <div v-if="isPlatformCopy" class="mt-2 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-2 dark:border-slate-700">
          <TranslateButton
            :question-id="q.id"
            :has-translation="Boolean(q.content_zh)"
            :show="translationShown[q.id]"
            @translated="applyTranslation(q.id, $event)"
            @toggle="toggleTranslation(q.id)"
          />
          <BaseButton
            v-if="!explanationOpen[q.id]"
            variant="ghost"
            size="sm"
            @click="toggleExplanation(q.id)"
          >
            <LightBulbIcon class="h-4 w-4" />
            AI 解析
          </BaseButton>
          <QuestionExplanation v-else :question="q" :show-summary="false" />
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="totalPages > 1" class="mt-6 flex justify-center gap-2">
      <button v-for="p in totalPages" :key="p" @click="page = p"
        class="rounded-card px-3 py-1 text-sm transition-colors"
        :class="p === page
          ? 'bg-primary-600 text-white'
          : 'bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700 shadow-card'">
        {{ p }}
      </button>
    </div>

    <!-- 更正正确答案 Modal（所有库可用，平台副本推荐入口） -->
    <BaseModal :open="showCorrectAnswer" title="更正正确答案" @close="showCorrectAnswer = false">
      <div class="space-y-3">
        <p class="text-sm text-gray-600 dark:text-gray-300">{{ correctAnswerTarget?.content }}</p>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
            正确答案（多选用逗号分隔，如 A,C）
          </label>
          <input v-model="correctAnswerValue" type="text"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          更正只影响当前项目中的这份题库，不改变平台来源；已有解析会失效并可按需重新生成。
        </p>
        <p v-if="correctAnswerError" class="text-sm text-rose-600 dark:text-rose-400">{{ correctAnswerError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showCorrectAnswer = false">取消</BaseButton>
        <BaseButton :loading="correctAnswerSaving" :disabled="correctAnswerSaving" @click="saveCorrectAnswer">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- 添加题目 Modal -->
    <BaseModal :open="showAdd" title="添加题目" maxWidth="lg" @close="showAdd = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">题目内容</label>
          <textarea v-model="newQ.content" rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">题型</label>
          <select v-model="newQ.question_type"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none">
            <option value="single">单选</option>
            <option value="multiple">多选</option>
            <option value="truefalse">判断</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">选项（每行一个，格式: A. 选项文本）</label>
          <textarea v-model="optionsText" rows="4" placeholder="A. Option one&#10;B. Option two&#10;C. Option three&#10;D. Option four"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 font-mono text-sm text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">正确答案（多选用逗号分隔）</label>
          <input v-model="newQ.correct_answer" type="text" placeholder="A 或 A,C"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showAdd = false">取消</BaseButton>
        <BaseButton @click="addQuestion">添加</BaseButton>
      </template>
    </BaseModal>

    <!-- 编辑题目 Modal -->
    <BaseModal :open="showEdit" title="编辑题目" maxWidth="lg" @close="showEdit = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">题目内容</label>
          <textarea v-model="editQ.content" rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">题型</label>
          <select v-model="editQ.question_type"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none">
            <option value="single">单选</option>
            <option value="multiple">多选</option>
            <option value="truefalse">判断</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">选项（每行一个，格式: A. 选项文本）</label>
          <textarea v-model="editOptionsText" rows="4"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 font-mono text-sm text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">正确答案（多选用逗号分隔）</label>
          <input v-model="editQ.correct_answer" type="text"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div v-if="competencies.length">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
            考点（可多选，保存后不会被批量打标覆盖）
          </label>
          <div class="mt-1 max-h-48 space-y-1 overflow-y-auto rounded-card border border-gray-300 dark:border-slate-600 p-2">
            <label v-for="c in competencies" :key="c.id"
              class="flex items-start gap-2 rounded px-1 py-0.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700">
              <input type="checkbox" :value="c.id" v-model="editTopicIds" class="mt-1" />
              <span>{{ c.number || c.code }} {{ c.short_name_zh }}</span>
            </label>
          </div>
        </div>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showEdit = false">取消</BaseButton>
        <BaseButton @click="saveEdit">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- 删除确认对话框 -->
    <ConfirmDialog
      :open="showDeleteConfirm"
      title="确认删除"
      message="删除后无法恢复，确定要删除该题目吗？"
      confirmText="删除"
      :danger="true"
      @confirm="deleteQuestion"
      @cancel="showDeleteConfirm = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from '../composables/useToast'
import { useBackgroundJob } from '../composables/useBackgroundJob'
import client from '../api/client'
import { currentExamPath } from '../utils/examRoutes'
import { errorMessage, formatSourceTopic, shortId } from '../utils/platformBanks'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import TranslateButton from '../components/TranslateButton.vue'
import QuestionExplanation from '../components/QuestionExplanation.vue'
import {
  PlusIcon,
  PencilSquareIcon,
  TrashIcon,
  ArrowLeftIcon,
  LanguageIcon,
  DocumentTextIcon,
  TagIcon,
  CheckBadgeIcon,
  LightBulbIcon,
} from '@heroicons/vue/24/outline'

const route = useRoute()
const toast = useToast()
// 同一路由记录下切换题库时组件会复用，必须随之更新。
let bankId = route.params.bankId
const perPage = 50
const bankName = ref('')
const isPlatformCopy = ref(false)
const sourcePlatformBankId = ref(null)
const sourcePlatformReleaseId = ref(null)
const questions = ref([])
const loading = ref(false)
const page = ref(1)
const totalPages = ref(1)
const showAdd = ref(false)
const translating = ref(false)
const newQ = ref({ content: '', question_type: 'single', correct_answer: '' })
const optionsText = ref('')
const showEdit = ref(false)
const editQ = ref({ id: null, content: '', question_type: 'single', correct_answer: '' })
const editOptionsText = ref('')
const editTopicIds = ref([])
const competencies = ref([])
const showDeleteConfirm = ref(false)
const deleteQuestionId = ref(null)
const showCorrectAnswer = ref(false)
const correctAnswerTarget = ref(null)
const correctAnswerValue = ref('')
const correctAnswerSaving = ref(false)
const correctAnswerError = ref('')
const translationShown = ref({})
const explanationOpen = ref({})
const topicTagJob = useBackgroundJob()

// 项目/题库切换与卸载时丢弃旧响应，避免跨库数据串页。
let requestGeneration = 0
let unmounted = false

const tagging = computed(() => topicTagJob.polling.value)
const tagProgressText = computed(() => {
  const job = topicTagJob.job.value
  if (!job || !job.progress_total) return '打标中...'
  return `打标中 ${job.progress_done}/${job.progress_total}`
})

function sourceTopics(question) {
  return (question.source_topics || []).map(formatSourceTopic).filter(Boolean)
}

// 平台副本默认收起缓存翻译，避免标题列表同时显示两种语言；用户主动点开后展示。
function isTranslationVisible(questionId) {
  return Boolean(translationShown.value[questionId])
}

function isCurrent(generation) {
  return !unmounted && generation === requestGeneration
}

async function fetchBankMeta(generation) {
  const res = await client.get('/banks')
  if (!isCurrent(generation)) return
  const bank = (res.data || []).find((b) => b.id === parseInt(bankId))
  bankName.value = bank?.name || `题库 #${bankId}`
  isPlatformCopy.value = Boolean(bank?.is_platform_copy)
  sourcePlatformBankId.value = bank?.source_platform_bank_id || null
  sourcePlatformReleaseId.value = bank?.source_platform_release_id || null
}

async function fetchQuestions() {
  const generation = requestGeneration
  loading.value = true
  try {
    const res = await client.get(`/questions/banks/${bankId}/questions`, { params: { page: page.value } })
    if (!isCurrent(generation)) return
    questions.value = res.data.questions
    totalPages.value = res.data.pages
  } catch (e) {
    if (isCurrent(generation)) toast.error(errorMessage(e, '加载题目失败'))
  } finally {
    if (isCurrent(generation)) loading.value = false
  }
}

function confirmDeleteQuestion(id) {
  deleteQuestionId.value = id
  showDeleteConfirm.value = true
}

async function deleteQuestion() {
  showDeleteConfirm.value = false
  const targetId = deleteQuestionId.value
  deleteQuestionId.value = null
  try {
    await client.delete(`/questions/${targetId}`)
    toast.success('题目已删除')
    fetchQuestions()
  } catch (e) {
    toast.error(errorMessage(e, '删除题目失败'))
  }
}

function parseOptions(text) {
  return text.split('\n')
    .map(line => line.trim())
    .filter(line => /^[A-E][.)]\s*/.test(line))
    .map(line => {
      const match = line.match(/^([A-E])[.)]\s*(.+)/)
      return match ? { key: match[1], text: match[2] } : null
    })
    .filter(Boolean)
}

async function addQuestion() {
  const options = parseOptions(optionsText.value)
  if (!options.length) {
    toast.error('请输入有效选项')
    return
  }
  try {
    await client.post('/questions', {
      bank_id: parseInt(bankId),
      ...newQ.value,
      options,
    })
    showAdd.value = false
    newQ.value = { content: '', question_type: 'single', correct_answer: '' }
    optionsText.value = ''
    toast.success('题目添加成功')
    fetchQuestions()
  } catch (e) {
    toast.error(errorMessage(e, '添加题目失败'))
  }
}

function startEdit(q) {
  if (isPlatformCopy.value) return
  editQ.value = {
    id: q.id,
    content: q.content,
    question_type: q.question_type,
    correct_answer: q.correct_answer,
  }
  editOptionsText.value = q.options.map(o => `${o.key}. ${o.text}`).join('\n')
  editTopicIds.value = (q.topics || []).map(t => t.id)
  showEdit.value = true
}

async function saveEdit() {
  const options = parseOptions(editOptionsText.value)
  if (!options.length) {
    toast.error('请输入有效选项')
    return
  }
  try {
    await client.put(`/questions/${editQ.value.id}`, {
      content: editQ.value.content,
      question_type: editQ.value.question_type,
      correct_answer: editQ.value.correct_answer,
      options,
      topic_ids: editTopicIds.value,
    })
    showEdit.value = false
    toast.success('题目已更新')
    fetchQuestions()
  } catch (e) {
    toast.error(errorMessage(e, '更新题目失败'))
  }
}

function openCorrectAnswer(q) {
  correctAnswerTarget.value = q
  correctAnswerValue.value = q.correct_answer || ''
  correctAnswerError.value = ''
  showCorrectAnswer.value = true
}

async function saveCorrectAnswer() {
  const value = correctAnswerValue.value.trim()
  if (!value) {
    correctAnswerError.value = '请填写正确答案'
    return
  }
  const target = correctAnswerTarget.value
  if (!target) return
  correctAnswerSaving.value = true
  correctAnswerError.value = ''
  try {
    const res = await client.put(`/questions/${target.id}/correct-answer`, {
      correct_answer: value,
    })
    showCorrectAnswer.value = false
    toast.success('正确答案已更正')
    // 只更新本地对应题目，避免整表刷新造成的滚动跳动。
    questions.value = questions.value.map((q) => (
      q.id === target.id
        ? { ...q, correct_answer: res.data.correct_answer, explanation: res.data.explanation, explanation_zh: res.data.explanation_zh }
        : q
    ))
  } catch (e) {
    correctAnswerError.value = errorMessage(e, '更正答案失败')
  } finally {
    correctAnswerSaving.value = false
  }
}

function applyTranslation(questionId, payload) {
  questions.value = questions.value.map((q) => {
    if (q.id !== questionId) return q
    const optionsZh = new Map((payload?.options_zh || []).map((opt) => [opt.key, opt.text_zh]))
    return {
      ...q,
      content_zh: payload?.content_zh || q.content_zh,
      options: (q.options || []).map((opt) => (
        optionsZh.has(opt.key) ? { ...opt, text_zh: optionsZh.get(opt.key) } : opt
      )),
    }
  })
  translationShown.value = { ...translationShown.value, [questionId]: true }
}

function toggleTranslation(questionId) {
  translationShown.value = { ...translationShown.value, [questionId]: !translationShown.value[questionId] }
}

function toggleExplanation(questionId) {
  explanationOpen.value = { ...explanationOpen.value, [questionId]: !explanationOpen.value[questionId] }
}

async function batchTranslate() {
  translating.value = true
  try {
    const res = await client.post('/ai/translate/batch', { bank_id: parseInt(bankId) })
    toast.success(`翻译完成: 成功 ${res.data.success} 题，失败 ${res.data.errors} 题`)
    fetchQuestions()
  } catch (e) {
    toast.error(errorMessage(e, '批量翻译失败'))
  } finally {
    translating.value = false
  }
}

async function batchTagTopics() {
  if (isPlatformCopy.value) return
  try {
    const res = await topicTagJob.createJob(
      { job_type: 'question_topic_tag', bank_id: parseInt(bankId) },
      { onFinished: onTaggingFinished },
    )
    if (res?.result === 'no_work') {
      toast.success('所有题目都已有考点，无需打标')
    } else if (res?.result === 'existing') {
      toast.success('该题库已有打标任务在执行')
    } else {
      toast.success('已开始批量打标，可留在本页查看进度')
    }
  } catch (e) {
    toast.error(e.response?.data?.detail || '发起批量打标失败')
  }
}

async function onTaggingFinished(finishedJob) {
  if (finishedJob?.status === 'failed') {
    toast.error(finishedJob.last_error || '批量打标失败')
  } else if (finishedJob?.status === 'completed') {
    toast.success(
      `批量打标完成：归类 ${finishedJob.success_count} 题，未能归类 ${finishedJob.skipped_count} 题`,
    )
  }
  await Promise.all([fetchQuestions(), fetchTopics()])
}

async function fetchTopics() {
  if (isPlatformCopy.value) return
  try {
    const res = await client.get(`/banks/${bankId}/topics`)
    competencies.value = res.data?.competencies || []
  } catch {
    competencies.value = []
  }
}

async function loadPage() {
  const generation = ++requestGeneration
  try {
    await fetchBankMeta(generation)
  } catch (e) {
    if (isCurrent(generation)) toast.error(errorMessage(e, '加载题库信息失败'))
  }
  if (!isCurrent(generation)) return
  // 只读副本不请求个人考点概览，也不恢复正式内容的打标任务。
  if (!isPlatformCopy.value) {
    fetchTopics()
    topicTagJob.restoreActiveJob(
      { job_type: 'question_topic_tag', bank_id: bankId },
      { onFinished: onTaggingFinished },
    )
  }
  await fetchQuestions()
}

onMounted(loadPage)
onUnmounted(() => {
  unmounted = true
  requestGeneration += 1
  topicTagJob.stopPolling()
})

// 题库切换（同一路由记录）时清空旧库状态并重新加载。
watch(() => route.params.bankId, (next, previous) => {
  if (!next || next === previous) return
  bankId = next
  page.value = 1
  bankName.value = ''
  isPlatformCopy.value = false
  sourcePlatformBankId.value = null
  sourcePlatformReleaseId.value = null
  questions.value = []
  competencies.value = []
  translationShown.value = {}
  explanationOpen.value = {}
  topicTagJob.stopPolling()
  loadPage()
})

watch(page, fetchQuestions)
</script>
