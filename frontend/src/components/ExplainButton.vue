<template>
  <div>
    <button @click="handleExplain" :disabled="loading"
      class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
      {{ loading ? '解析中...' : 'AI 解析' }}
    </button>
    <div v-if="explanation" class="mt-3 rounded-lg bg-blue-50 p-4 text-sm">
      <p class="font-medium text-blue-800">AI 解析</p>
      <p class="mt-1 whitespace-pre-wrap text-gray-700">{{ explanation.explanation }}</p>
      <p v-if="explanation.explanation_zh" class="mt-2 whitespace-pre-wrap text-gray-600">{{ explanation.explanation_zh }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import client from '../api/client'

const props = defineProps({ questionId: Number })
const loading = ref(false)
const explanation = ref(null)

async function handleExplain() {
  if (explanation.value) return
  loading.value = true
  try {
    const res = await client.post('/ai/explain', { question_id: props.questionId })
    explanation.value = res.data
  } catch (e) {
    alert(e.response?.data?.error || '解析失败')
  } finally {
    loading.value = false
  }
}
</script>
