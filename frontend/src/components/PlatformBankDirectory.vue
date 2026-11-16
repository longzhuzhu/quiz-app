<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p class="text-sm text-gray-500 dark:text-gray-400">
        平台上架题库可一键取得当前项目的个人副本；副本独立保存，进度只属于当前项目。
      </p>
      <BaseButton variant="ghost" size="sm" :disabled="loading" @click="fetchDirectory">刷新</BaseButton>
    </div>

    <div
      v-if="loadError"
      class="rounded-card border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300"
    >
      {{ loadError }}
    </div>

    <div v-else-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="2" />
    </div>

    <p v-else-if="banks.length === 0" class="py-10 text-center text-sm text-gray-400 dark:text-gray-500">
      当前还没有可用的平台题库
    </p>

    <div v-else class="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
      <div
        v-for="entry in banks"
        :key="entry.id"
        class="rounded-card-lg border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="font-semibold text-gray-900 dark:text-white">{{ entry.name }}</h3>
              <span
                v-if="entry.adopted_bank_id"
                class="inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
              >已选用</span>
            </div>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ entry.description || '暂无简介' }}
            </p>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
              {{ entry.question_count }} 题 ｜ 发布版本 v{{ entry.published_version }}
            </p>
          </div>
          <div class="flex flex-shrink-0 flex-col items-start gap-1 sm:items-end">
            <BaseButton
              v-if="entry.adopted_bank_id"
              variant="secondary"
              size="sm"
              @click="openAdopted(entry)"
            >打开题库</BaseButton>
            <BaseButton
              v-else
              size="sm"
              :loading="pendingSourceId === entry.id"
              :disabled="pendingSourceId !== null"
              @click="adopt(entry)"
            >使用题库</BaseButton>
            <p
              v-if="errorBySource[entry.id]"
              class="max-w-56 text-xs text-rose-600 dark:text-rose-400"
            >{{ errorBySource[entry.id] }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import client from '../api/client'
import { examPath } from '../utils/examRoutes'
import { errorMessage } from '../utils/platformBanks'
import BaseButton from './BaseButton.vue'
import SkeletonLoader from './SkeletonLoader.vue'

const props = defineProps({
  // 必须由调用方传入本次路由的 examSlug；目录请求与选用都绑定它，不读 store 隐式项目。
  examSlug: { type: String, required: true },
})
const emit = defineEmits(['adopted'])

const router = useRouter()
const banks = ref([])
const loading = ref(true)
const loadError = ref('')
const pendingSourceId = ref(null)
const errorBySource = ref({})

// 请求序号 + 卸载标记：项目切换/重试/关闭时丢弃旧响应，避免假成功和错误导航。
let requestGeneration = 0
let adoptSequence = 0
let unmounted = false

function examHeaders() {
  return { headers: { 'X-Exam-Slug': props.examSlug } }
}

async function fetchDirectory() {
  const generation = ++requestGeneration
  loading.value = true
  loadError.value = ''
  try {
    const res = await client.get('/platform-banks', examHeaders())
    if (unmounted || generation !== requestGeneration) return
    banks.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    if (unmounted || generation !== requestGeneration) return
    loadError.value = errorMessage(e, '加载平台题库目录失败')
  } finally {
    if (!unmounted && generation === requestGeneration) loading.value = false
  }
}

function openAdopted(entry) {
  const bankId = entry.adopted_bank_id
  if (!bankId) return
  router.push(`${examPath(props.examSlug, 'banks')}/${bankId}`)
}

async function adopt(entry) {
  if (pendingSourceId.value !== null) return
  const examSlug = props.examSlug
  const sourceId = entry.id
  const requestId = ++adoptSequence
  pendingSourceId.value = sourceId
  errorBySource.value = { ...errorBySource.value, [sourceId]: '' }

  try {
    const res = await client.post(`/platform-banks/${sourceId}/adopt`, null, examHeaders())
    // 响应必须仍属于本次项目/来源/序号，否则只丢弃，不导航、不标已选。
    if (unmounted || requestId !== adoptSequence || examSlug !== props.examSlug) return
    if (!res.data?.bank_id) {
      errorBySource.value = { ...errorBySource.value, [sourceId]: '服务端未返回副本，请刷新后重试' }
      return
    }
    // 只有服务端确认后才标记已选并导航到当前项目的个人副本。
    banks.value = banks.value.map((item) => (
      item.id === sourceId ? { ...item, adopted_bank_id: res.data.bank_id } : item
    ))
    emit('adopted', res.data)
    router.push(`${examPath(examSlug, 'banks')}/${res.data.bank_id}`)
  } catch (e) {
    if (unmounted || requestId !== adoptSequence || examSlug !== props.examSlug) return
    errorBySource.value = {
      ...errorBySource.value,
      [sourceId]: errorMessage(e, '使用题库失败，请刷新目录后重试'),
    }
  } finally {
    if (!unmounted && requestId === adoptSequence && pendingSourceId.value === sourceId) {
      pendingSourceId.value = null
    }
  }
}

// 项目变化时立即失效旧目录与进行中的选用，重新按新项目拉取。
watch(() => props.examSlug, (next, previous) => {
  if (!next || next === previous) return
  requestGeneration += 1
  adoptSequence += 1
  pendingSourceId.value = null
  errorBySource.value = {}
  banks.value = []
  fetchDirectory()
})

onMounted(fetchDirectory)
onUnmounted(() => {
  unmounted = true
  requestGeneration += 1
  adoptSequence += 1
})

defineExpose({ fetchDirectory })
</script>
