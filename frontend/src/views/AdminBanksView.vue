<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">题库管理</h1>
      <BaseButton @click="showCreate = true">
        <PlusIcon class="h-4 w-4" />
        创建题库
      </BaseButton>
    </div>

    <!-- 题库列表 -->
    <div v-if="banks.length === 0" class="py-16 text-center">
      <FolderIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-400 dark:text-gray-500">暂无题库，点击上方按钮创建</p>
    </div>
    <div v-else class="space-y-4">
      <div v-for="bank in banks" :key="bank.id"
        class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card hover:shadow-card-hover transition-all p-5">
        <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div class="min-w-0">
            <router-link :to="`/admin/banks/${bank.id}`"
              class="font-semibold text-primary-600 dark:text-primary-400 hover:underline">
              {{ bank.name }}
            </router-link>
            <p v-if="bank.description" class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ bank.description }}</p>
            <p class="mt-1 text-sm text-gray-400 dark:text-gray-500">{{ bank.question_count }} 道题目</p>
          </div>
          <div class="flex gap-2 flex-wrap flex-shrink-0">
            <BaseButton variant="secondary" size="sm" @click="startEdit(bank)">
              <PencilSquareIcon class="h-4 w-4" />
              编辑
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="selectedBankId = bank.id; showImport = true">
              <ArrowUpTrayIcon class="h-4 w-4" />
              导入题目
            </BaseButton>
            <BaseButton variant="danger" size="sm" @click="confirmDeleteBank(bank.id)">
              <TrashIcon class="h-4 w-4" />
              删除
            </BaseButton>
          </div>
        </div>
      </div>
    </div>

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
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showEdit = false">取消</BaseButton>
        <BaseButton @click="saveEdit">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- 导入题目 Modal -->
    <BaseModal :open="showImport" title="导入题目" maxWidth="lg" @close="showImport = false">
      <FileUpload :bank-id="selectedBankId" @imported="handleImported" />
      <template #actions>
        <BaseButton variant="secondary" @click="showImport = false">关闭</BaseButton>
      </template>
    </BaseModal>

    <!-- 删除确认对话框 -->
    <ConfirmDialog
      :open="showDeleteConfirm"
      title="确认删除"
      message="删除后无法恢复，确定要删除该题库吗？"
      confirmText="删除"
      :danger="true"
      @confirm="deleteBank"
      @cancel="showDeleteConfirm = false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useBankStore } from '../stores/bank'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import FileUpload from '../components/FileUpload.vue'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import { PlusIcon, PencilSquareIcon, ArrowUpTrayIcon, TrashIcon, FolderIcon } from '@heroicons/vue/24/outline'

const bankStore = useBankStore()
const toast = useToast()
const banks = ref([])
const showCreate = ref(false)
const showImport = ref(false)
const selectedBankId = ref(null)
const newBank = ref({ name: '', description: '' })
const showEdit = ref(false)
const editBank = ref({ id: null, name: '', description: '' })
const showDeleteConfirm = ref(false)
const deleteBankId = ref(null)

async function fetchBanks() {
  await bankStore.fetchBanks()
  banks.value = bankStore.banks
}

async function createBank() {
  try {
    await client.post('/banks/', newBank.value)
    newBank.value = { name: '', description: '' }
    showCreate.value = false
    toast.success('题库创建成功')
    fetchBanks()
  } catch (e) {
    toast.error(e.response?.data?.error || '创建题库失败')
  }
}

function confirmDeleteBank(id) {
  deleteBankId.value = id
  showDeleteConfirm.value = true
}

async function deleteBank() {
  showDeleteConfirm.value = false
  try {
    await client.delete(`/banks/${deleteBankId.value}`)
    toast.success('题库已删除')
    fetchBanks()
  } catch (e) {
    toast.error(e.response?.data?.error || '删除题库失败')
  }
}

function handleImported() {
  showImport.value = false
  toast.success('题目导入成功')
  fetchBanks()
}

function startEdit(bank) {
  editBank.value = { id: bank.id, name: bank.name, description: bank.description || '' }
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
    toast.error(e.response?.data?.error || '更新题库失败')
  }
}

onMounted(fetchBanks)
</script>
