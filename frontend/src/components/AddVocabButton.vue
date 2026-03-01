<template>
  <div class="relative">
    <button @click="open = !open"
      class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
      收藏单词
    </button>

    <!-- 弹出表单 -->
    <div v-if="open" class="absolute left-0 top-full z-10 mt-1 w-72 rounded-lg bg-white p-4 shadow-lg border border-gray-200">
      <div class="mb-3 text-sm font-medium text-gray-700">添加到我的单词本</div>
      <input v-model="term" ref="inputRef" placeholder="输入英文单词或短语"
        class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
        @keyup.enter="submit" />
      <div class="mt-3 flex items-center justify-between">
        <span class="text-xs text-gray-400">自动翻译为中文</span>
        <div class="flex gap-2">
          <button @click="open = false" class="rounded-md px-3 py-1 text-sm text-gray-500 hover:bg-gray-100">取消</button>
          <button @click="submit" :disabled="!term.trim() || saving"
            class="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
      <div v-if="message" class="mt-2 text-xs" :class="messageOk ? 'text-green-600' : 'text-red-500'">{{ message }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import client from '../api/client'

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
    term.value = ''
    setTimeout(() => { open.value = false; message.value = '' }, 1500)
  } catch (e) {
    messageOk.value = false
    message.value = e.response?.data?.error || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>
