<template>
  <div>
    <div class="mb-6">
      <router-link to="/admin/banks" class="text-sm text-indigo-600 hover:underline">&larr; 返回题库管理</router-link>
      <h1 class="mt-1 text-2xl font-bold text-gray-900">系统设置</h1>
    </div>

    <div class="rounded-lg bg-white p-6 shadow">
      <h2 class="mb-4 text-lg font-semibold text-gray-800">AI API 配置</h2>
      <p class="mb-4 text-sm text-gray-500">配置 OpenAI 兼容 API 用于题目翻译和解析功能。</p>

      <div v-if="loading" class="text-center text-gray-500 py-8">加载中...</div>
      <div v-else class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700">API Base URL</label>
          <input v-model="form.ai_api_base_url" type="text" placeholder="https://api.openai.com"
            class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400">例如 https://api.openai.com 或第三方兼容地址</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700">API Key</label>
          <input v-model="form.ai_api_key" type="password" placeholder="sk-..."
            class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400">Anthropic API 密钥</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700">模型</label>
          <input v-model="form.ai_model" type="text" placeholder="gpt-4o-mini"
            class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 focus:border-indigo-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400">使用的模型名称</p>
        </div>
        <div class="flex items-center gap-3 pt-2">
          <button @click="save" :disabled="saving"
            class="rounded-md bg-indigo-600 px-6 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
            {{ saving ? '保存中...' : '保存设置' }}
          </button>
          <span v-if="message" class="text-sm" :class="messageError ? 'text-red-500' : 'text-green-600'">
            {{ message }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import client from '../api/client'

const loading = ref(true)
const saving = ref(false)
const message = ref('')
const messageError = ref(false)
const form = ref({
  ai_api_base_url: '',
  ai_api_key: '',
  ai_model: '',
})

onMounted(async () => {
  try {
    const res = await client.get('/settings/ai')
    form.value = res.data
  } catch {
    message.value = '加载设置失败'
    messageError.value = true
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  message.value = ''
  try {
    await client.put('/settings/ai', form.value)
    message.value = '设置已保存'
    messageError.value = false
  } catch (e) {
    message.value = e.response?.data?.error || '保存失败'
    messageError.value = true
  } finally {
    saving.value = false
  }
}
</script>
