<template>
  <div v-for="i in count" :key="i">
    <!-- type="text": 3 行不同宽度的灰色圆角条 -->
    <div v-if="type === 'text'" class="space-y-3">
      <div class="h-4 w-3/4 rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
      <div class="h-4 w-full rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
      <div class="h-4 w-1/2 rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
    </div>

    <!-- type="card": 带标题行 + 两行内容 + 按钮区的卡片骨架 -->
    <div v-else-if="type === 'card'" class="rounded-xl bg-white dark:bg-slate-800 p-6 shadow-sm space-y-4">
      <div class="h-5 w-1/3 rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
      <div class="h-4 w-full rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
      <div class="h-4 w-2/3 rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
      <div class="flex gap-2">
        <div class="h-9 w-24 rounded-lg bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
        <div class="h-9 w-24 rounded-lg bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
      </div>
    </div>

    <!-- type="list": 多行条目 -->
    <div v-else-if="type === 'list'" class="space-y-3">
      <div class="flex items-center gap-3 rounded-xl bg-white dark:bg-slate-800 p-4 shadow-sm">
        <div class="h-10 w-10 rounded-full bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
        <div class="flex-1 space-y-2">
          <div class="h-4 w-1/2 rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
          <div class="h-3 w-1/3 rounded bg-gray-200 dark:bg-slate-700 animate-pulse"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  type: {
    type: String,
    default: 'text',
    validator: (value) => ['text', 'card', 'list'].includes(value),
  },
  count: {
    type: Number,
    default: 1,
  },
})
</script>
