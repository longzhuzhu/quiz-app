<template>
  <button @click="handleClick" :disabled="loading"
    class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
    {{ loading ? '翻译中...' : (show ? '隐藏翻译' : '翻译') }}
  </button>
</template>

<script setup>
import { ref } from 'vue'
import client from '../api/client'

const props = defineProps({
  questionId: Number,
  hasTranslation: Boolean,
  show: Boolean,
})
const emit = defineEmits(['translated', 'toggle'])
const loading = ref(false)

async function handleClick() {
  if (props.hasTranslation) {
    emit('toggle')
    return
  }
  loading.value = true
  try {
    const res = await client.post('/ai/translate', { question_id: props.questionId })
    emit('translated', res.data)
  } catch (e) {
    alert(e.response?.data?.error || '翻译失败')
  } finally {
    loading.value = false
  }
}
</script>
