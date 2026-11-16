<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">平台题库</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          独立于个人考试项目的内容来源：导入草稿、核对后发布，登录用户可在各自项目中选用副本。
        </p>
      </div>
      <BaseButton :disabled="creating" @click="openCreate">新建平台题库</BaseButton>
    </div>

    <div
      v-if="loadError"
      class="rounded-card-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300"
    >
      <p>{{ loadError }}</p>
      <BaseButton class="mt-3" size="sm" variant="secondary" @click="fetchBanks">重试</BaseButton>
    </div>

    <div v-else-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <div v-else-if="banks.length === 0" class="py-16 text-center">
      <FolderIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-500 dark:text-gray-400">还没有平台题库</p>
      <p class="mt-1 text-sm text-gray-400 dark:text-gray-500">
        新建来源后上传导入文件，草稿核对完成即可发布。
      </p>
    </div>

    <div v-else class="space-y-4">
      <div
        v-for="bank in banks"
        :key="bank.id"
        class="rounded-card-lg bg-white p-5 shadow-card transition-all hover:shadow-card-hover dark:bg-slate-800"
      >
        <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <router-link
                :to="{ name: 'AdminPlatformBankDetail', params: { sourceId: bank.id } }"
                class="font-semibold text-primary-600 hover:underline dark:text-primary-400"
              >{{ bank.name }}</router-link>
              <span
                class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                :class="bank.is_listed
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                  : 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-300'"
              >{{ bank.is_listed ? '已上架' : '未上架' }}</span>
              <span
                v-if="bank.has_active_import"
                class="inline-flex rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
              >导入进行中</span>
            </div>
            <p v-if="bank.description" class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ bank.description }}
            </p>
            <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">
              草稿 {{ bank.draft_question_count }} 题
              <template v-if="bank.latest_release">
                ｜ 已发布 v{{ bank.latest_release.version_number }}（{{ bank.latest_release.question_count }} 题）
                <template v-if="bank.latest_release.name !== bank.name">
                  ｜ 发布名：{{ bank.latest_release.name }}
                </template>
              </template>
              <template v-else>｜ 尚未发布</template>
            </p>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
              创建于 {{ formatDateTime(bank.created_at) }}
            </p>
          </div>
          <div class="flex flex-shrink-0 flex-wrap gap-2">
            <BaseButton
              variant="secondary"
              size="sm"
              @click="router.push({ name: 'AdminPlatformBankDetail', params: { sourceId: bank.id } })"
            >
              <EyeIcon class="h-4 w-4" />
              草稿与发布
            </BaseButton>
            <BaseButton variant="secondary" size="sm" @click="openEdit(bank)">
              <PencilSquareIcon class="h-4 w-4" />
              编辑草稿信息
            </BaseButton>
          </div>
        </div>
      </div>
    </div>

    <BaseModal :open="showCreate" title="新建平台题库" @close="showCreate = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">名称</label>
          <input
            v-model="createForm.name"
            type="text"
            maxlength="200"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">简介</label>
          <textarea
            v-model="createForm.description"
            rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          ></textarea>
        </div>
        <p v-if="createError" class="text-sm text-rose-600 dark:text-rose-400">{{ createError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showCreate = false">取消</BaseButton>
        <BaseButton :loading="creating" :disabled="creating" @click="createBank">创建</BaseButton>
      </template>
    </BaseModal>

    <BaseModal :open="showEdit" title="编辑草稿信息" @close="showEdit = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">名称</label>
          <input
            v-model="editForm.name"
            type="text"
            maxlength="200"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">简介</label>
          <textarea
            v-model="editForm.description"
            rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          ></textarea>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          这里只修改草稿元数据。已发布版本的名称与简介保持不变，重新发布后才生效。
        </p>
        <p v-if="editError" class="text-sm text-rose-600 dark:text-rose-400">{{ editError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showEdit = false">取消</BaseButton>
        <BaseButton :loading="savingEdit" :disabled="savingEdit" @click="saveEdit">保存</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '../api/client'
import { useToast } from '../composables/useToast'
import { errorMessage, formatDateTime } from '../utils/platformBanks'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { EyeIcon, FolderIcon, PencilSquareIcon } from '@heroicons/vue/24/outline'

const router = useRouter()
const toast = useToast()
const banks = ref([])
const loading = ref(true)
const loadError = ref('')
const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = ref({ name: '', description: '' })
const showEdit = ref(false)
const savingEdit = ref(false)
const editError = ref('')
const editForm = ref({ id: null, name: '', description: '' })

// 本次页面生命周期的请求序号；卸载或新请求发出后丢弃旧响应。
let requestGeneration = 0
let unmounted = false

async function fetchBanks() {
  const generation = ++requestGeneration
  loading.value = true
  loadError.value = ''
  try {
    const res = await client.get('/admin/platform-banks')
    if (unmounted || generation !== requestGeneration) return
    banks.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    if (unmounted || generation !== requestGeneration) return
    loadError.value = errorMessage(e, '加载平台题库失败')
  } finally {
    if (!unmounted && generation === requestGeneration) loading.value = false
  }
}

function openCreate() {
  createForm.value = { name: '', description: '' }
  createError.value = ''
  showCreate.value = true
}

async function createBank() {
  if (creating.value) return
  const name = createForm.value.name.trim()
  if (!name) {
    createError.value = '请填写名称'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const res = await client.post('/admin/platform-banks', {
      name,
      description: createForm.value.description.trim() || null,
    })
    if (unmounted) return
    showCreate.value = false
    toast.success('平台题库已创建')
    router.push({ name: 'AdminPlatformBankDetail', params: { sourceId: res.data.id } })
  } catch (e) {
    if (!unmounted) createError.value = errorMessage(e, '创建平台题库失败')
  } finally {
    if (!unmounted) creating.value = false
  }
}

function openEdit(bank) {
  editForm.value = {
    id: bank.id,
    name: bank.name,
    description: bank.description || '',
  }
  editError.value = ''
  showEdit.value = true
}

async function saveEdit() {
  if (savingEdit.value) return
  const name = editForm.value.name.trim()
  if (!name) {
    editError.value = '请填写名称'
    return
  }
  savingEdit.value = true
  editError.value = ''
  try {
    await client.put(`/admin/platform-banks/${editForm.value.id}`, {
      name,
      description: editForm.value.description.trim() || null,
    })
    if (unmounted) return
    showEdit.value = false
    toast.success('草稿信息已更新')
    await fetchBanks()
  } catch (e) {
    if (!unmounted) editError.value = errorMessage(e, '更新草稿信息失败')
  } finally {
    if (!unmounted) savingEdit.value = false
  }
}

onMounted(fetchBanks)
onUnmounted(() => { unmounted = true })
</script>
