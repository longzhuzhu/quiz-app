<template>
  <div>
    <div class="mb-6">
      <router-link to="/admin/banks"
        class="inline-flex items-center gap-1 text-sm text-primary-600 dark:text-primary-400 hover:underline">
        <ArrowLeftIcon class="h-4 w-4" />
        返回题库管理
      </router-link>
      <h1 class="mt-1 text-2xl font-bold text-gray-900 dark:text-white">系统设置</h1>
    </div>

    <div class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <div class="flex items-center gap-3 mb-4">
        <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-100 dark:bg-primary-900/30">
          <CpuChipIcon class="h-5 w-5 text-primary-600 dark:text-primary-400" />
        </div>
        <div>
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white">AI API 配置</h2>
          <p class="text-sm text-gray-500 dark:text-gray-400">配置 OpenAI 兼容 API 用于题目翻译和解析功能。</p>
        </div>
      </div>

      <div v-if="loading" class="py-8">
        <SkeletonLoader type="text" />
      </div>
      <div v-else class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">API Base URL</label>
          <input v-model="form.ai_api_base_url" type="text" placeholder="https://api.openai.com"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">例如 https://api.openai.com 或第三方兼容地址</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">API Key</label>
          <input v-model="form.ai_api_key" type="password" placeholder="sk-..."
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">Anthropic API 密钥</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">模型</label>
          <input v-model="form.ai_model" type="text" placeholder="gpt-4o-mini"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">使用的模型名称</p>
        </div>
        <div class="pt-2">
          <BaseButton @click="save" :loading="saving" :disabled="saving">
            {{ saving ? '保存中...' : '保存设置' }}
          </BaseButton>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { ArrowLeftIcon, CpuChipIcon } from '@heroicons/vue/24/outline'

const toast = useToast()
const loading = ref(true)
const saving = ref(false)
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
    toast.error('加载设置失败')
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  try {
    await client.put('/settings/ai', form.value)
    toast.success('设置已保存')
  } catch (e) {
    toast.error(e.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>
