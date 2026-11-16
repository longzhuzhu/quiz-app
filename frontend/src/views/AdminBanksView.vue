<template>
  <div>
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">题库管理</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          当前项目「{{ examStore.current?.short_name || examStore.current?.name || route.params.examSlug }}」的题库与个人副本
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <BaseButton variant="secondary" @click="showDirectory = true">
          <BookOpenIcon class="h-4 w-4" />
          平台题库
        </BaseButton>
        <BaseButton @click="showCreate = true">
          <PlusIcon class="h-4 w-4" />
          创建题库
        </BaseButton>
      </div>
    </div>

    <!-- 题库列表 -->
    <div v-if="banks.length === 0" class="py-16 text-center">
      <FolderIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-500 dark:text-gray-400">当前项目还没有题库</p>
      <p class="mt-1 text-sm text-gray-400 dark:text-gray-500">
        可以从平台目录选用题库，或自行创建并导入题目。
      </p>
      <BaseButton class="mt-4" variant="secondary" @click="showDirectory = true">
        <BookOpenIcon class="h-4 w-4" />
        浏览平台题库
      </BaseButton>
    </div>
    <div v-else class="space-y-4">
      <div v-for="bank in banks" :key="bank.id"
        class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-5">
        <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <router-link :to="currentExamPath(route, 'banks') + `/${bank.id}`"
                class="font-semibold text-primary-600 dark:text-primary-400 hover:underline">
                {{ bank.name }}
              </router-link>
              <span
                v-if="bank.is_platform_copy"
                class="inline-flex rounded-full bg-sky-100 dark:bg-sky-900/30 px-2 py-0.5 text-xs font-medium text-sky-700 dark:text-sky-400"
              >平台副本</span>
            </div>
            <p v-if="bank.description" class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ bank.description }}</p>
            <p class="mt-1 text-sm text-gray-400 dark:text-gray-500">{{ bank.question_count }} 道题目</p>
          </div>
          <div class="flex gap-2 flex-wrap flex-shrink-0">
            <template v-if="bank.is_platform_copy">
              <BaseButton
                v-if="incompleteSessionByBankId[bank.id]"
                variant="primary"
                size="sm"
                @click="continueSession(incompleteSessionByBankId[bank.id])"
              >继续练习</BaseButton>
              <BaseButton
                v-else
                variant="primary"
                size="sm"
                :disabled="bank.question_count === 0"
                :loading="startingPracticeBankId === bank.id"
                @click="startPractice(bank)"
              >开始练习</BaseButton>
            </template>
            <BaseButton variant="secondary" size="sm" @click="startEdit(bank)">
              <PencilSquareIcon class="h-4 w-4" />
              编辑
            </BaseButton>
            <BaseButton v-if="!bank.is_platform_copy" variant="secondary" size="sm" @click="openImportModal(bank.id)">
              <ArrowUpTrayIcon class="h-4 w-4" />
              导入题目
            </BaseButton>
            <BaseButton variant="danger" size="sm" @click="confirmDeleteBank(bank)">
              <TrashIcon class="h-4 w-4" />
              删除
            </BaseButton>
          </div>
        </div>
        <p v-if="bank.is_platform_copy" class="mt-3 text-xs text-gray-400 dark:text-gray-500">
          来源平台题库（{{ shortId(bank.source_platform_bank_id, 8) }}）只读；可修改名称/简介、更正正确答案与开始练习。
        </p>
      </div>
    </div>

    <!-- 平台题库目录 -->
    <BaseModal :open="showDirectory" title="平台题库" maxWidth="lg" @close="closeDirectory">
      <PlatformBankDirectory :exam-slug="route.params.examSlug" @adopted="handleAdopted" />
    </BaseModal>

    <!-- 创建题库 Modal -->
    <BaseModal :open="showCreate" title="创建题库" @close="showCreate = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">名称</label>
          <input v-model="newBank.name" type="text"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">描述</label>
          <textarea v-model="newBank.description" rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showCreate = false">取消</BaseButton>
        <BaseButton @click="createBank">创建</BaseButton>
      </template>
    </BaseModal>

    <!-- 编辑题库 Modal -->
    <BaseModal :open="showEdit" title="编辑题库" @close="showEdit = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">名称</label>
          <input v-model="editBank.name" type="text"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">描述</label>
          <textarea v-model="editBank.description" rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
        <p v-if="editBank.is_platform_copy" class="text-xs text-gray-500 dark:text-gray-400">
          平台副本只允许修改名称与简介；来源和发布版本保持只读。
        </p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showEdit = false">取消</BaseButton>
        <BaseButton @click="saveEdit">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- 导入题目 Modal -->
    <BaseModal :open="showImport" title="导入题目" maxWidth="lg" @close="closeImportModal">
      <FileUpload :bank-id="selectedBankId" @imported="handleImported" />
      <template #actions>
        <BaseButton variant="secondary" @click="closeImportModal">关闭</BaseButton>
      </template>
    </BaseModal>

    <!-- 删除确认对话框 -->
    <ConfirmDialog
      :open="showDeleteConfirm"
      title="确认删除题库"
      :message="deleteConfirmMessage"
      confirmText="删除"
      :danger="true"
      @confirm="deleteBank"
      @cancel="showDeleteConfirm = false"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useBankStore } from '../stores/bank'
import { useExamStore } from '../stores/exam'
import { currentExamPath } from '../utils/examRoutes'
import { errorMessage, shortId } from '../utils/platformBanks'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import FileUpload from '../components/FileUpload.vue'
import PlatformBankDirectory from '../components/PlatformBankDirectory.vue'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import {
  PlusIcon,
  PencilSquareIcon,
  ArrowUpTrayIcon,
  TrashIcon,
  FolderIcon,
  BookOpenIcon,
} from '@heroicons/vue/24/outline'

const route = useRoute()
const router = useRouter()
const bankStore = useBankStore()
const examStore = useExamStore()
const toast = useToast()
const banks = ref([])
const showCreate = ref(false)
const showImport = ref(false)
const showDirectory = ref(false)
const selectedBankId = ref(null)
const newBank = ref({ name: '', description: '' })
const showEdit = ref(false)
const editBank = ref({ id: null, name: '', description: '', is_platform_copy: false })
const showDeleteConfirm = ref(false)
const deleteTarget = ref(null)
const incompleteSessionByBankId = ref({})
const IMPORT_MODAL_BANK_STORAGE_KEY = 'admin-banks:import-bank-id'

// 项目切换/卸载时丢弃旧项目的题库与会话响应。
let requestGeneration = 0
let unmounted = false

const deleteConfirmMessage = computed(() => {
  if (deleteTarget.value?.is_platform_copy) {
    return '删除该平台副本后，本地的答案更正、该库练习记录与错题统计会一并清理；'
      + '来源已下架时无法重新获取。来源仍上架时可再次选用最新发布版本。'
  }
  return '删除后无法恢复，确定要删除该题库吗？'
})

async function fetchBanks() {
  const generation = ++requestGeneration
  await bankStore.fetchBanks()
  if (unmounted || generation !== requestGeneration) return
  banks.value = bankStore.banks
  await fetchIncompleteSessions(generation)
}

async function fetchIncompleteSessions(generation) {
  try {
    const res = await client.get('/quiz/history', { params: { page: 1, per_page: 100 } })
    if (unmounted || generation !== requestGeneration) return
    const items = Array.isArray(res.data?.items) ? res.data.items : []
    const sessionsByBankId = {}
    for (const session of items) {
      if (session.is_completed !== false || session.mode === 'wrong_practice') continue
      if (session.bank_id == null || sessionsByBankId[session.bank_id]) continue
      sessionsByBankId[session.bank_id] = session
    }
    incompleteSessionByBankId.value = sessionsByBankId
  } catch {
    if (!unmounted && generation === requestGeneration) incompleteSessionByBankId.value = {}
  }
}

async function createBank() {
  try {
    await client.post('/banks', newBank.value)
    newBank.value = { name: '', description: '' }
    showCreate.value = false
    toast.success('题库创建成功')
    fetchBanks()
  } catch (e) {
    toast.error(errorMessage(e, '创建题库失败'))
  }
}

function confirmDeleteBank(bank) {
  deleteTarget.value = bank
  showDeleteConfirm.value = true
}

function persistImportBankId(bankId) {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(IMPORT_MODAL_BANK_STORAGE_KEY, String(bankId))
}

function clearImportBankId() {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(IMPORT_MODAL_BANK_STORAGE_KEY)
}

function openImportModal(bankId) {
  selectedBankId.value = bankId
  showImport.value = true
  persistImportBankId(bankId)
}

function closeImportModal() {
  showImport.value = false
  selectedBankId.value = null
  clearImportBankId()
}

function restoreImportModal() {
  if (typeof window === 'undefined') return

  const rawBankId = window.sessionStorage.getItem(IMPORT_MODAL_BANK_STORAGE_KEY)
  if (!rawBankId) return

  const bankId = Number(rawBankId)
  const bank = banks.value.find((item) => item.id === bankId)
  // 平台副本不能导入；恢复时也要尊重这个限制。
  if (!Number.isInteger(bankId) || !bank || bank.is_platform_copy) {
    clearImportBankId()
    return
  }

  selectedBankId.value = bankId
  showImport.value = true
}

async function deleteBank() {
  const target = deleteTarget.value
  showDeleteConfirm.value = false
  deleteTarget.value = null
  if (!target) return
  try {
    await client.delete(`/banks/${target.id}`)
    toast.success('题库已删除')
    fetchBanks()
  } catch (e) {
    toast.error(errorMessage(e, '删除题库失败'))
  }
}

function handleImported() {
  fetchBanks()
}

function handleAdopted() {
  showDirectory.value = false
}

// 关闭目录时移除一次性查询参数，避免刷新页面再次自动弹出。
function closeDirectory() {
  showDirectory.value = false
  if (route.query.directory) {
    const { directory, ...rest } = route.query
    router.replace({ path: route.path, query: rest })
  }
}

function startEdit(bank) {
  editBank.value = {
    id: bank.id,
    name: bank.name,
    description: bank.description || '',
    is_platform_copy: Boolean(bank.is_platform_copy),
  }
  showEdit.value = true
}

async function saveEdit() {
  try {
    await client.put(`/banks/${editBank.value.id}`, {
      name: editBank.value.name,
      description: editBank.value.description,
    })
    showEdit.value = false
    toast.success('题库已更新')
    fetchBanks()
  } catch (e) {
    toast.error(errorMessage(e, '更新题库失败'))
  }
}

// 连点「开始练习」会创建多场会话；请求期间用标记挡住重复点击。
const startingPracticeBankId = ref(null)

async function startPractice(bank) {
  if (startingPracticeBankId.value !== null) return
  startingPracticeBankId.value = bank.id
  try {
    const res = await client.post('/quiz/start', {
      bank_id: bank.id,
      mode: 'sequential',
    })
    router.push(currentExamPath(route, 'quiz', { sessionId: res.data.session.id }))
  } catch (e) {
    toast.error(errorMessage(e, '开始练习失败'))
  } finally {
    // 成功时导航已发起，仍复位以便返回本页后可再次点击。
    startingPracticeBankId.value = null
  }
}

function continueSession(session) {
  const sessionId = session?.id
  if (sessionId == null) return
  router.push(currentExamPath(route, 'quiz', { sessionId }))
}

// 同一路由组件切换项目时清空旧项目状态，避免显示过期入口。
watch(() => route.params.examSlug, async (next, previous) => {
  if (next === previous) return
  banks.value = []
  incompleteSessionByBankId.value = {}
  closeImportModal()
  showDirectory.value = false
  await fetchBanks()
})

onMounted(async () => {
  await fetchBanks()
  restoreImportModal()
  // 首页空态「浏览平台题库」通过查询参数直接打开目录。
  if (route.query.directory === '1') showDirectory.value = true
})

onUnmounted(() => {
  unmounted = true
  requestGeneration += 1
})
</script>
