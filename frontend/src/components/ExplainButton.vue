<template>
  <div>
    <button @click="handleExplain" :disabled="loading"
      class="inline-flex items-center gap-1.5 rounded-button px-3 py-1.5 text-sm font-medium
             bg-gray-100 text-gray-700 hover:bg-gray-200
             dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600
             disabled:opacity-50 transition-colors">
      <LightBulbIcon class="h-4 w-4" />
      {{ loading ? '解析中...' : 'AI 解析' }}
    </button>
    <div v-if="explanation"
      class="mt-3 rounded-card border border-sky-200 bg-sky-50 p-4 text-sm
             dark:border-sky-800 dark:bg-sky-900/20">
      <p class="font-medium text-sky-800 dark:text-sky-300">AI 解析</p>
      <p class="mt-1 whitespace-pre-wrap text-gray-700 dark:text-gray-300">{{ explanation.explanation }}</p>
      <p v-if="explanation.explanation_zh"
        class="mt-2 whitespace-pre-wrap text-gray-600 dark:text-gray-400">{{ explanation.explanation_zh }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { LightBulbIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

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
    toast.error(e.response?.data?.error || '解析失败')
  } finally {
    loading.value = false
  }
}
</script>
