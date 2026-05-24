<template>
  <div class="mx-auto max-w-2xl py-8">
    <div class="mb-6 text-center">
      <h1 class="text-3xl font-bold text-gray-900 dark:text-white">创建你的第一个考试项目</h1>
      <p class="mt-2 text-gray-500 dark:text-gray-400">题库、错题、历史和词汇都会按考试项目隔离。</p>
    </div>
    <ExamCreatePage />
  </div>
</template>

<script setup>
import ExamCreatePage from './ExamCreatePage.vue'
</script>
