<template>
  <div>
    <div class="mb-6 flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900">题库管理</h1>
      <button @click="showCreate = true"
        class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">
        创建题库
      </button>
    </div>

    <!-- Create modal -->
    <div v-if="showCreate" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h2 class="mb-4 text-lg font-semibold">创建题库</h2>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">名称</label>
            <input v-model="newBank.name" type="text"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">描述</label>
            <textarea v-model="newBank.description" rows="3"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"></textarea>
          </div>
        </div>
        <div class="mt-4 flex justify-end gap-2">
          <button @click="showCreate = false"
            class="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">取消</button>
          <button @click="createBank"
            class="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">创建</button>
        </div>
      </div>
    </div>

    <!-- Bank list -->
    <div class="space-y-4">
      <div v-for="bank in banks" :key="bank.id"
        class="rounded-lg bg-white p-5 shadow">
        <div class="flex items-center justify-between">
          <div>
            <router-link :to="`/admin/banks/${bank.id}`" class="font-semibold text-indigo-600 hover:underline">
              {{ bank.name }}
            </router-link>
            <p class="text-sm text-gray-500">{{ bank.question_count }} 道题目</p>
          </div>
          <div class="flex gap-2">
            <button @click="startEdit(bank)"
              class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
              编辑
            </button>
            <button @click="selectedBankId = bank.id; showImport = true"
              class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
              导入题目
            </button>
            <button @click="deleteBank(bank.id)"
              class="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Import modal -->
    <div v-if="showImport" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg">
        <h2 class="mb-4 text-lg font-semibold">导入题目</h2>
        <FileUpload :bank-id="selectedBankId" @imported="handleImported" />
        <div class="mt-4 flex justify-end">
          <button @click="showImport = false"
            class="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">关闭</button>
        </div>
      </div>
    </div>

    <!-- Edit modal -->
    <div v-if="showEdit" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h2 class="mb-4 text-lg font-semibold">编辑题库</h2>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">名称</label>
            <input v-model="editBank.name" type="text"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">描述</label>
            <textarea v-model="editBank.description" rows="3"
              class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"></textarea>
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
import { ref, onMounted } from 'vue'
import { useBankStore } from '../stores/bank'
import client from '../api/client'
import FileUpload from '../components/FileUpload.vue'

const bankStore = useBankStore()
const banks = ref([])
const showCreate = ref(false)
const showImport = ref(false)
const selectedBankId = ref(null)
const newBank = ref({ name: '', description: '' })
const showEdit = ref(false)
const editBank = ref({ id: null, name: '', description: '' })

async function fetchBanks() {
  await bankStore.fetchBanks()
  banks.value = bankStore.banks
}

async function createBank() {
  await client.post('/banks/', newBank.value)
  newBank.value = { name: '', description: '' }
  showCreate.value = false
  fetchBanks()
}

async function deleteBank(id) {
  if (!confirm('确定删除该题库？')) return
  await client.delete(`/banks/${id}`)
  fetchBanks()
}

function handleImported() {
  showImport.value = false
  fetchBanks()
}

function startEdit(bank) {
  editBank.value = { id: bank.id, name: bank.name, description: bank.description || '' }
  showEdit.value = true
}

async function saveEdit() {
  await client.put(`/banks/${editBank.value.id}`, {
    name: editBank.value.name,
    description: editBank.value.description,
  })
  showEdit.value = false
  fetchBanks()
}

onMounted(fetchBanks)
</script>
