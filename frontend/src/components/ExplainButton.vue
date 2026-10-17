<template>
  <button type="button" @click="$emit('explain')" :disabled="loading || disabled"
    class="inline-flex items-center gap-1.5 rounded-button px-3 py-1.5 text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600 disabled:opacity-50 transition-colors">
    <LightBulbIcon class="h-4 w-4" />
    {{ loading ? (displayed ? '更新中…' : '解析中…') : (displayed ? '更新全部解析' : 'AI 解析') }}
  </button>
</template>
<script setup>
import { LightBulbIcon } from '@heroicons/vue/24/outline'
defineProps({ loading: { type: Boolean, default: false }, displayed: { type: Boolean, default: false }, disabled: { type: Boolean, default: false } })
defineEmits(['explain'])
</script>
