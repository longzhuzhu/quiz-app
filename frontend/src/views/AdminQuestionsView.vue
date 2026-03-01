<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <div>
        <router-link to="/admin/banks" class="text-sm text-indigo-600 hover:underline">&larr; 返回题库列表</router-link>
        <h1 class="mt-1 text-2xl font-bold text-gray-900">{{ bankName }} - 题目管理</h1>
      </div>
      <div class="flex gap-2">
        <button @click="batchTranslate" :disabled="translating"
          class="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
          {{ translating ? '翻译中...' : '批量翻译' }}
        </button>
        <button @click="showAdd = true"
          class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">
          添加题目
        </button>
      </div>
    </div>

    <div v-if="loading" class="text-center text-gray-500">加载中...</div>
    <div v-else-if="questions.length === 0" class="py-12 text-center text-gray-400">暂无题目</div>
    <div v-else class="space-y-3">
      <div v-for="(q, i) in questions" :key="q.id"
        class="rounded-lg bg-white p-4 shadow">
        <div class="flex items-start justify-between">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-900">{{ i + 1 }}. {{ q.content }}</p>
            <p v-if="q.content_zh" class="mt-1 text-sm text-gray-500">{{ q.content_zh }}</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <span v-for="opt in q.options" :key="opt.key"
                class="text-xs rounded px-2 py-0.5"
                :class="q.correct_answer.includes(opt.key) ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'">
                {{ opt.key }}. {{ opt.text }}
              </span>
            </div>
            <p class="mt-1 text-xs text-gray-400">
              类型: {{ q.question_type === 'single' ? '单选' : q.question_type === 'multiple' ? '多选' : '判断' }}
              · 答案: {{ q.correct_answer }}
            </p>
          </div>
          <div class="ml-4 flex-shrink-0 flex gap-2">
            <button @click="startEdit(q)"
              class="text-sm text-indigo-500 hover:text-indigo-700">编辑</button>
            <button @click="deleteQuestion(q.id)"
              class="text-sm text-red-500 hover:text-red-700">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="mt-6 flex justify-center gap-2">
      <button v-for="p in totalPages" :key="p" @click="page = p"
        class="rounded px-3 py-1 text-sm"
        :class="p === page ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-100'">
        {{ p }}
      </button>
    </div>

    <!-- Add question modal -->
    <div v-if="showAdd" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg max-h-[80vh] overflow-y-auto">
        <h2 class="mb-4 text-lg font-semibold">添加题目</h2>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">题目内容</label>
            <textarea v-model="newQ.content" rows="3"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"></textarea>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">题型</label>
            <select v-model="newQ.question_type"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none">
              <option value="single">单选</option>
              <option value="multiple">多选</option>
              <option value="truefalse">判断</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">选项（每行一个，格式: A. 选项文本）</label>
            <textarea v-model="optionsText" rows="4" placeholder="A. Option one&#10;B. Option two&#10;C. Option three&#10;D. Option four"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none"></textarea>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">正确答案（多选用逗号分隔）</label>
            <input v-model="newQ.correct_answer" type="text" placeholder="A 或 A,C"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          </div>
        </div>
        <div class="mt-4 flex justify-end gap-2">
          <button @click="showAdd = false"
            class="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">取消</button>
          <button @click="addQuestion"
            class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">添加</button>
        </div>
      </div>
    </div>

    <!-- Edit question modal -->
    <div v-if="showEdit" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg max-h-[80vh] overflow-y-auto">
        <h2 class="mb-4 text-lg font-semibold">编辑题目</h2>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">题目内容</label>
            <textarea v-model="editQ.content" rows="3"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"></textarea>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">题型</label>
            <select v-model="editQ.question_type"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none">
              <option value="single">单选</option>
              <option value="multiple">多选</option>
              <option value="truefalse">判断</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">选项（每行一个，格式: A. 选项文本）</label>
            <textarea v-model="editOptionsText" rows="4"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:border-indigo-500 focus:outline-none"></textarea>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">正确答案（多选用逗号分隔）</label>
            <input v-model="editQ.correct_answer" type="text"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          </div>
        </div>
        <div class="mt-4 flex justify-end gap-2">
          <button @click="showEdit = false"
            class="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">取消</button>
          <button @click="saveEdit"
            class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import client from '../api/client'

const route = useRoute()
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

async function deleteQuestion(id) {
  if (!confirm('确定删除该题目？')) return
  await client.delete(`/questions/${id}`)
  fetchQuestions()
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
  if (!options.length) return alert('请输入有效选项')
  await client.post('/questions/', {
    bank_id: parseInt(bankId),
    ...newQ.value,
    options,
  })
  showAdd.value = false
  newQ.value = { content: '', question_type: 'single', correct_answer: '' }
  optionsText.value = ''
  fetchQuestions()
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
  if (!options.length) return alert('请输入有效选项')
  await client.put(`/questions/${editQ.value.id}`, {
    content: editQ.value.content,
    question_type: editQ.value.question_type,
    correct_answer: editQ.value.correct_answer,
    options,
  })
  showEdit.value = false
  fetchQuestions()
}

async function batchTranslate() {
  translating.value = true
  try {
    const res = await client.post('/ai/translate/batch', { bank_id: parseInt(bankId) })
    alert(`翻译完成: 成功 ${res.data.success} 题，失败 ${res.data.errors} 题`)
    fetchQuestions()
  } catch (e) {
    alert(e.response?.data?.error || '批量翻译失败')
  } finally {
    translating.value = false
  }
}

onMounted(async () => {
  const banks = await client.get('/banks/')
  const bank = banks.data.find(b => b.id === parseInt(bankId))
  bankName.value = bank?.name || `题库 #${bankId}`
  fetchQuestions()
})

watch(page, fetchQuestions)
</script>
