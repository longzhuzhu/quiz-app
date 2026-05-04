<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <div>
        <router-link to="/admin/banks"
          class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">
          <ArrowLeftIcon class="h-4 w-4" />
          返回题库列表
        </router-link>
        <h1 class="mt-1 text-2xl font-bold text-gray-900 dark:text-white">{{ bankName }} - 题目管理</h1>
      </div>
      <div class="flex gap-2">
        <BaseButton variant="secondary" @click="batchTranslate" :loading="translating" :disabled="translating">
          <LanguageIcon class="h-4 w-4" />
          {{ translating ? '翻译中...' : '批量翻译' }}
        </BaseButton>
        <BaseButton @click="showAdd = true">
          <PlusIcon class="h-4 w-4" />
          添加题目
        </BaseButton>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <!-- 空状态 -->
    <div v-else-if="questions.length === 0" class="py-16 text-center">
      <DocumentTextIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-400 dark:text-gray-500">暂无题目，点击上方按钮添加</p>
    </div>

    <!-- 题目列表 -->
    <div v-else class="space-y-3">
      <div v-for="(q, i) in questions" :key="q.id"
        class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-4">
        <div class="flex items-start justify-between">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-900 dark:text-white">{{ i + 1 }}. {{ q.content }}</p>
            <p v-if="q.content_zh" class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ q.content_zh }}</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <span v-for="opt in q.options" :key="opt.key"
                class="text-xs rounded-md px-2 py-0.5"
                :class="q.correct_answer.includes(opt.key)
                  ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                  : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-400'">
                {{ opt.key }}. {{ opt.text }}
              </span>
            </div>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
              类型: {{ q.question_type === 'single' ? '单选' : q.question_type === 'multiple' ? '多选' : '判断' }}
              · 答案: {{ q.correct_answer }}
            </p>
          </div>
          <div class="ml-4 flex-shrink-0 flex gap-2">
            <BaseButton variant="ghost" size="sm" @click="startEdit(q)">
              <PencilSquareIcon class="h-4 w-4" />
              编辑
            </BaseButton>
            <BaseButton variant="ghost" size="sm" class="!text-rose-500 hover:!text-rose-700 dark:!text-rose-400" @click="confirmDeleteQuestion(q.id)">
              <TrashIcon class="h-4 w-4" />
              删除
            </BaseButton>
          </div>
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
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { PlusIcon, PencilSquareIcon, TrashIcon, ArrowLeftIcon, LanguageIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'

const route = useRoute()
const toast = useToast()
const bankId = route.params.bankId
const bankName = ref('')
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
const showDeleteConfirm = ref(false)
const deleteQuestionId = ref(null)

async function fetchQuestions() {
  loading.value = true
  try {
    const res = await client.get(`/questions/banks/${bankId}/questions`, { params: { page: page.value } })
    questions.value = res.data.questions
    totalPages.value = res.data.pages
  } finally {
    loading.value = false
  }
}

function confirmDeleteQuestion(id) {
  deleteQuestionId.value = id
  showDeleteConfirm.value = true
}

async function deleteQuestion() {
  showDeleteConfirm.value = false
  try {
    await client.delete(`/questions/${deleteQuestionId.value}`)
    toast.success('题目已删除')
    fetchQuestions()
  } catch (e) {
    toast.error(e.response?.data?.error || '删除题目失败')
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
    toast.error(e.response?.data?.error || '添加题目失败')
  }
}

function startEdit(q) {
  editQ.value = {
    id: q.id,
    content: q.content,
    question_type: q.question_type,
    correct_answer: q.correct_answer,
  }
  editOptionsText.value = q.options.map(o => `${o.key}. ${o.text}`).join('\n')
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
    })
    showEdit.value = false
    toast.success('题目已更新')
    fetchQuestions()
  } catch (e) {
    toast.error(e.response?.data?.error || '更新题目失败')
  }
}

async function batchTranslate() {
  translating.value = true
  try {
    const res = await client.post('/ai/translate/batch', { bank_id: parseInt(bankId) })
    toast.success(`翻译完成: 成功 ${res.data.success} 题，失败 ${res.data.errors} 题`)
    fetchQuestions()
  } catch (e) {
    toast.error(e.response?.data?.error || '批量翻译失败')
  } finally {
    translating.value = false
  }
}

onMounted(async () => {
  const banks = await client.get('/banks')
  const bank = banks.data.find(b => b.id === parseInt(bankId))
  bankName.value = bank?.name || `题库 #${bankId}`
  fetchQuestions()
})

watch(page, fetchQuestions)
</script>
