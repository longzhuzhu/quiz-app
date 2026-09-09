<template>
  <div>
    <button @click="handleExplain" :disabled="loading"
      class="inline-flex items-center gap-1.5 rounded-button px-3 py-1.5 text-sm font-medium
             bg-gray-100 text-gray-700 hover:bg-gray-200
             dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600
             disabled:opacity-50 transition-colors">
      <LightBulbIcon class="h-4 w-4" />
      {{ buttonLabel }}
    </button>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { LightBulbIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

const props = defineProps({
  questionId: Number,
  initialExplanation: { type: Object, default: null },
  displayed: { type: Boolean, default: false },
})
const emit = defineEmits(['explained'])
const loading = ref(false)
const explanation = ref(null)
let generation = 0

const buttonLabel = computed(() => {
  if (props.displayed) {
    return loading.value ? '更新中...' : '更新AI解析'
  }
  return loading.value ? '解析中...' : 'AI 解析'
})

watch(() => props.questionId, () => {
  generation += 1
  loading.value = false
  explanation.value = null
})

function hasChineseExplanation(payload) {
  return !!(payload && payload.explanation_zh)
}

async function handleExplain() {
  const requestGeneration = ++generation
  if (!props.displayed) {
    const existing = explanation.value ?? props.initialExplanation
    if (hasChineseExplanation(existing)) {
      emit('explained', existing)
      return
    }
  }
  loading.value = true
  try {
    const res = await client.post('/ai/explain', {
      question_id: props.questionId,
      force: !!props.displayed,
    })
    if (requestGeneration !== generation) return
    explanation.value = res.data
    emit('explained', res.data)
  } catch (e) {
    if (requestGeneration !== generation) return
    if (props.displayed) {
      toast.error('更新失败，已保留原解析')
    } else {
      toast.error(e.response?.data?.detail || '解析失败')
    }
  } finally {
    if (requestGeneration === generation) {
      loading.value = false
    }
  }
}
</script>
