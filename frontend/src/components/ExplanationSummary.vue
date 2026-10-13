<template>
  <section v-if="models.length" aria-label="AI 推荐答案" class="mt-3 text-sm" @click.stop>
    <p class="font-semibold text-gray-800 dark:text-gray-200">AI 推荐答案</p>
    <ul class="mt-2 space-y-1.5">
      <li v-for="model in models" :key="model.model_id" class="flex flex-wrap items-start gap-x-2 gap-y-0.5">
        <button type="button" class="min-w-0 break-all text-left text-primary-700 underline-offset-2 hover:underline dark:text-primary-300"
          :aria-label="'查看 ' + model.model_id + ' 解析'" @click="$emit('select', model.model_id)">{{ model.model_id }}：</button>
        <span v-if="model.result" class="font-semibold text-gray-900 dark:text-white">{{ model.result.judged_answer }}</span>
        <span v-if="model.result?.is_conflict" class="text-amber-700 dark:text-amber-300">与题库答案不同</span>
        <span v-if="explanationStatus(model)" class="text-gray-600 dark:text-gray-400">{{ explanationStatus(model) }}</span>
      </li>
    </ul>
  </section>
</template>
<script setup>
import { explanationStatus } from '../utils/explanationPresentation'
defineProps({ models: { type: Array, default: () => [] } })
defineEmits(['select'])
</script>
