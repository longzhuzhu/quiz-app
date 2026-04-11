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
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { LightBulbIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

const props = defineProps({
  questionId: Number,
  initialExplanation: { type: Object, default: null },
})
const emit = defineEmits(['explained'])
const loading = ref(false)
const explanation = ref(null)

function hasExplanation(payload) {
  return !!(payload && (payload.explanation || payload.explanation_zh))
}

async function handleExplain() {
  const existing = explanation.value ?? props.initialExplanation
  if (hasExplanation(existing)) {
    emit('explained', existing)
    return
  }
  loading.value = true
  try {
    const res = await client.post('/ai/explain', { question_id: props.questionId })
    explanation.value = res.data
    emit('explained', res.data)
  } catch (e) {
    toast.error(e.response?.data?.error || '解析失败')
  } finally {
    loading.value = false
  }
}
</script>
