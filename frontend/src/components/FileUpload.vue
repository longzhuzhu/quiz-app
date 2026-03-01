<template>
  <div class="rounded-lg border-2 border-dashed border-gray-300 p-8 text-center"
    @dragover.prevent="dragging = true" @dragleave="dragging = false"
    @drop.prevent="handleDrop"
    :class="{ 'border-indigo-500 bg-indigo-50': dragging }">
    <div class="text-gray-500">
      <p class="mb-2 text-lg">拖拽文件到这里上传</p>
      <p class="text-sm">支持 PDF、XLSX、DOCX 格式</p>
      <label class="mt-4 inline-block cursor-pointer rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700">
        选择文件
        <input type="file" accept=".pdf,.xlsx,.docx" @change="handleFileSelect" class="hidden" />
      </label>
    </div>
    <div v-if="uploading" class="mt-4 text-sm text-indigo-600">上传中...</div>
    <div v-if="result" class="mt-4 text-sm" :class="result.error ? 'text-red-600' : 'text-green-600'">
      {{ result.message || result.error }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import client from '../api/client'

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
    emit('imported', res.data)
  } catch (e) {
    result.value = { error: e.response?.data?.error || '上传失败' }
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
