<template>
  <div class="relative">
    <button @click="open = !open"
      class="inline-flex items-center gap-1.5 rounded-button px-3 py-1.5 text-sm font-medium
             bg-gray-100 text-gray-700 hover:bg-gray-200
             dark:bg-slate-700 dark:text-gray-300 dark:hover:bg-slate-600
             transition-colors">
      <BookmarkIcon class="h-4 w-4" />
      收藏单词
    </button>

    <!-- 弹出表单 -->
    <div v-if="open"
      class="absolute left-0 top-full z-10 mt-1 w-72 rounded-card border border-gray-200 bg-white p-4 shadow-lg
             dark:border-slate-600 dark:bg-slate-800">
      <div class="mb-3 text-sm font-medium text-gray-700 dark:text-white">添加到我的单词本</div>
      <input v-model="term" ref="inputRef" placeholder="输入英文单词或短语"
        class="w-full rounded-button border border-gray-300 px-3 py-2 text-sm
               focus:border-primary-500 focus:outline-none
               dark:border-slate-600 dark:bg-slate-700 dark:text-white dark:placeholder-gray-400"
        @keyup.enter="submit" />
      <div class="mt-3 flex items-center justify-between">
        <span class="text-xs text-gray-400 dark:text-gray-500">自动翻译为中文</span>
        <div class="flex gap-2">
          <button @click="open = false"
            class="rounded-button px-3 py-1 text-sm text-gray-500 hover:bg-gray-100
                   dark:text-gray-400 dark:hover:bg-slate-700">取消</button>
          <button @click="submit" :disabled="!term.trim() || saving"
            class="rounded-button bg-primary-600 px-3 py-1 text-sm text-white hover:bg-primary-700
                   disabled:opacity-50">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
      <div v-if="message" class="mt-2 text-xs" :class="messageOk ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'">{{ message }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import { BookmarkIcon } from '@heroicons/vue/24/outline'
import client from '../api/client'
import { useToast } from '../composables/useToast'

const toast = useToast()

const open = ref(false)
const term = ref('')
const saving = ref(false)
const message = ref('')
const messageOk = ref(false)
const inputRef = ref(null)

watch(open, (val) => {
  if (val) {
    term.value = ''
    message.value = ''
    nextTick(() => inputRef.value?.focus())
  }
})

async function submit() {
  if (!term.value.trim() || saving.value) return
  saving.value = true
  message.value = ''
  try {
    const res = await client.post('/vocab/personal', {
      term: term.value.trim(),
      auto_translate: true,
    })
    const w = res.data
    messageOk.value = true
    message.value = w.term_zh ? `已保存: ${w.term_zh}` : '已保存'
    toast.success(message.value)
    term.value = ''
    setTimeout(() => { open.value = false; message.value = '' }, 1500)
  } catch (e) {
    messageOk.value = false
    message.value = e.response?.data?.error || '保存失败'
    toast.error(message.value)
  } finally {
    saving.value = false
  }
}
</script>
