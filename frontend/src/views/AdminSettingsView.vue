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
          <div class="relative mt-1">
            <input v-model="form.ai_api_key" :type="showApiKey ? 'text' : 'password'" placeholder="sk-..."
              class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 pr-10 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
            <button type="button" @click="toggleApiKey"
              class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              <EyeSlashIcon v-if="showApiKey" class="h-5 w-5" />
              <EyeIcon v-else class="h-5 w-5" />
            </button>
          </div>
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">OpenAI 兼容 API 密钥</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">模型</label>
          <input v-model="form.ai_model" type="text" placeholder="gpt-4o-mini"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">使用的模型名称</p>
        </div>
        <div class="flex gap-3 pt-2">
          <BaseButton @click="save" :loading="saving" :disabled="saving">
            {{ saving ? '保存中...' : '保存设置' }}
          </BaseButton>
          <BaseButton @click="testConnection" :loading="testing" :disabled="testing" variant="secondary">
            {{ testing ? '测试中...' : '测试连接' }}
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
import { ArrowLeftIcon, CpuChipIcon, EyeIcon, EyeSlashIcon } from '@heroicons/vue/24/outline'

const toast = useToast()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const showApiKey = ref(false)
const maskedKey = ref('')
const realKeyFetched = ref(false)
const form = ref({
  ai_api_base_url: '',
  ai_api_key: '',
  ai_model: '',
})

onMounted(async () => {
  try {
    const res = await client.get('/settings/ai')
    form.value = res.data
    maskedKey.value = res.data.ai_api_key
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

async function toggleApiKey() {
  if (!showApiKey.value && form.value.ai_api_key === maskedKey.value && !realKeyFetched.value) {
    // 当前显示的是遮罩值，需要从后端拉取真实 key
    try {
      const res = await client.get('/settings/ai/key')
      form.value.ai_api_key = res.data.ai_api_key
      realKeyFetched.value = true
    } catch {
      toast.error('获取 API Key 失败')
      return
    }
  }
  showApiKey.value = !showApiKey.value
}

async function testConnection() {
  testing.value = true
  try {
    const res = await client.post('/settings/ai/test', form.value)
    if (res.data.success) {
      toast.success(res.data.message)
    } else {
      toast.error(res.data.error || '测试失败')
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '测试请求失败')
  } finally {
    testing.value = false
  }
}
</script>
