<template>
  <div class="rounded-card-lg border-2 border-dashed border-gray-300 p-8 text-center
              dark:border-slate-600 dark:bg-slate-800/50"
    @dragover.prevent="dragging = true" @dragleave="dragging = false"
    @drop.prevent="handleDrop"
    :class="{ 'border-primary-500 bg-primary-50 dark:bg-primary-900/20': dragging }">
    <div class="text-gray-500 dark:text-gray-400">
      <ArrowUpTrayIcon class="mx-auto h-10 w-10 text-gray-400 dark:text-gray-500" />
      <p class="mb-2 mt-3 text-lg dark:text-gray-300">拖拽文件到这里上传</p>
      <p class="text-sm dark:text-gray-400">支持 PDF、XLSX、DOCX 格式</p>
      <label class="mt-4 inline-flex cursor-pointer items-center gap-1.5 rounded-button
                     bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700
                     transition-colors">
        <ArrowUpTrayIcon class="h-4 w-4" />
        选择文件
        <input type="file" accept=".pdf,.xlsx,.docx" @change="handleFileSelect" class="hidden" />
      </label>
    </div>
    <div v-if="uploading" class="mt-4 text-sm text-primary-600 dark:text-primary-400">上传中...</div>
    <div v-if="result" class="mt-4 text-sm"
      :class="result.error ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400'">
      {{ result.message || result.error }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ArrowUpTrayIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

const props = defineProps({ bankId: Number })
const emit = defineEmits(['imported'])
const dragging = ref(false)
const uploading = ref(false)
const result = ref(null)

async function uploadFile(file) {
  uploading.value = true
  result.value = null
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await client.post(`/banks/${props.bankId}/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    result.value = res.data
    toast.success(res.data.message || '上传成功')
    emit('imported', res.data)
  } catch (e) {
    result.value = { error: e.response?.data?.error || '上传失败' }
    toast.error(result.value.error)
  } finally {
    uploading.value = false
  }
}

function handleDrop(e) {
  dragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) uploadFile(file)
}

function handleFileSelect(e) {
  const file = e.target.files[0]
  if (file) uploadFile(file)
}
</script>
