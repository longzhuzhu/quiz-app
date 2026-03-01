<template>
  <button @click="handleClick" :disabled="loading"
    class="inline-flex items-center gap-1.5 rounded-button px-3 py-1.5 text-sm font-medium
           bg-gray-100 text-gray-700 hover:bg-gray-200
           dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600
           disabled:opacity-50 transition-colors">
    <LanguageIcon class="h-4 w-4" />
    {{ loading ? '翻译中...' : (show ? '隐藏翻译' : '翻译') }}
  </button>
</template>

<script setup>
import { ref } from 'vue'
import { LanguageIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

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
    toast.error(e.response?.data?.error || '翻译失败')
  } finally {
    loading.value = false
  }
}
</script>
