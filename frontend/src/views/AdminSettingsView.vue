<template>
  <div>
    <div class="mb-6">
      <router-link to="/exams"
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
            <input v-model="form.ai_api_key" :type="showApiKey ? 'text' : 'password'"
              :placeholder="hasStoredKey ? '已保存，留空则保持不变' : 'sk-...'"
              class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 pr-10 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
            <button type="button" @click="toggleApiKey"
              class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              <EyeSlashIcon v-if="showApiKey" class="h-5 w-5" />
              <EyeIcon v-else class="h-5 w-5" />
            </button>
          </div>
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
            {{ hasStoredKey ? `当前已保存：${storedKeyMask || '已配置'}；留空则保持不变` : 'OpenAI 兼容 API 密钥' }}
          </p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">模型</label>
          <input v-model="form.ai_model" type="text" placeholder="gpt-4o-mini"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">系统统一默认模型；当未配置翻译模型或解析模型时，默认使用该模型</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">翻译模型</label>
          <input v-model="form.ai_translate_model" type="text" placeholder="gpt-5-nano"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">用于题目翻译、词汇翻译等场景；留空时默认使用“默认模型”</p>
        </div>
        <section aria-label="AI 解析模型配置">
          <div class="flex items-center justify-between gap-2">
            <h3 class="text-sm font-medium text-gray-700 dark:text-gray-300">AI 解析模型</h3>
            <button type="button" :disabled="form.ai_explain_models.length >= 5" @click="addModel"
              class="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:opacity-40 dark:border-slate-600 dark:text-gray-300">添加模型</button>
          </div>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">配置 1～5 个不重复模型，共用上方接入地址和密钥；展示顺序与列表一致。</p>
          <div v-for="(model, index) in form.ai_explain_models" :key="index" :data-model-row="index"
            class="mt-3 rounded-lg border border-gray-200 p-3 dark:border-slate-600">
            <label :for="'explain-model-' + index" class="text-sm text-gray-700 dark:text-gray-300">模型 {{ index + 1 }} ID</label>
            <input :id="'explain-model-' + index" v-model="model.model_id" type="text" maxlength="255" placeholder="填写网关支持的模型 ID"
              class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 dark:border-slate-600 dark:bg-slate-700 dark:text-white" />
            <div class="mt-2 flex gap-3 text-sm">
              <button type="button" :disabled="index === 0" :aria-label="'上移模型 ' + (index + 1)" @click="moveModel(index, -1)" class="text-primary-700 disabled:opacity-40 dark:text-primary-300">上移</button>
              <button type="button" :disabled="index === form.ai_explain_models.length - 1" :aria-label="'下移模型 ' + (index + 1)" @click="moveModel(index, 1)" class="text-primary-700 disabled:opacity-40 dark:text-primary-300">下移</button>
              <button type="button" :disabled="form.ai_explain_models.length <= 1" :aria-label="'移除模型 ' + (index + 1)" @click="form.ai_explain_models.splice(index, 1)" class="text-rose-700 disabled:opacity-40 dark:text-rose-300">移除</button>
            </div>
            <details class="mt-3 text-sm text-gray-600 dark:text-gray-400">
              <summary class="cursor-pointer">高级推理设置</summary>
              <label class="mt-2 flex items-center gap-2">
                <input type="checkbox" :checked="model.reasoning_effort === null"
                  @change="model.reasoning_effort = $event.target.checked ? null : 'xhigh'" />
                不发送 reasoning_effort
              </label>
              <label :for="'explain-effort-' + index" class="mt-2 block">推理强度（默认 xhigh）</label>
              <input :id="'explain-effort-' + index" v-model="model.reasoning_effort" :disabled="model.reasoning_effort === null"
                type="text" maxlength="32" placeholder="xhigh"
                class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-700 dark:text-white" />
              <p class="mt-1 text-xs">填写该模型支持的强度；不支持时调用会失败，不自动降级。修改不会重算已有解析。</p>
            </details>
          </div>
        </section>
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

    <div class="mt-6 rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6">
      <div class="flex items-center gap-3 mb-4">
        <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-100 dark:bg-sky-900/30">
          <CpuChipIcon class="h-5 w-5 text-sky-600 dark:text-sky-400" />
        </div>
        <div>
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white">答题设置</h2>
          <p class="text-sm text-gray-500 dark:text-gray-400">配置答题过程中的体验优化能力。</p>
        </div>
      </div>

      <div v-if="loading" class="py-8">
        <SkeletonLoader type="text" />
      </div>
      <div v-else class="space-y-4">
        <label class="flex items-start gap-3 rounded-card border border-gray-200 dark:border-slate-700 p-4 cursor-pointer">
          <input v-model="form.quiz_ai_prewarm_enabled" type="checkbox"
            class="mt-1 h-4 w-4 rounded border-gray-300 dark:border-slate-600 text-primary-600 dark:text-primary-500" />
          <span>
            <span class="block text-sm font-medium text-gray-700 dark:text-gray-300">是否启用答题预热</span>
            <span class="mt-1 block text-xs text-gray-400 dark:text-gray-500">
              开启后，答题时会静默预先生成当前题和下一题的翻译与 AI 解析，以提升点击响应速度，全部已配置解析模型都参与预热，可能增加 AI 调用成本。
            </span>
          </span>
        </label>

        <label class="block rounded-card border border-gray-200 dark:border-slate-700 p-4">
          <span class="block text-sm font-medium text-gray-700 dark:text-gray-300">错题掌握连对阈值</span>
          <span class="mt-1 block text-xs text-gray-400 dark:text-gray-500">
            一道错题连续答对达到该次数即自动标记为掌握、退出错题本，可在 1 到 9 之间调整。任何一次答错都会清零连对。
          </span>
          <input v-if="form.wrong_mastery_correct_streak !== null" v-model.number="form.wrong_mastery_correct_streak"
            type="number" min="1" max="9" step="1"
            class="mt-3 w-24 rounded-lg border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-gray-700 dark:text-gray-200" />
          <span v-else class="mt-3 block text-xs text-rose-500 dark:text-rose-400">
            当前值未加载成功，保存时不会改动此项；请重新加载页面后再调整。
          </span>
          <span class="mt-2 block text-xs text-amber-600 dark:text-amber-400">
            修改后从下一次作答起生效，不会重新计算已有错题的掌握状态：已掌握的不会被取消，未掌握的也不会被立即标记为掌握。
          </span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useToast } from '../composables/useToast'
import client from '../api/client'
import { responseError } from '../utils/explanationPresentation'
import BaseButton from '../components/BaseButton.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { ArrowLeftIcon, CpuChipIcon, EyeIcon, EyeSlashIcon } from '@heroicons/vue/24/outline'

const toast = useToast()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const showApiKey = ref(false)
const storedKeyMask = ref('')
const hasStoredKey = ref(false)
const form = ref({
  ai_api_base_url: '',
  ai_api_key: '',
  ai_model: '',
  ai_translate_model: '',
  ai_explain_models: [],
  quiz_ai_prewarm_enabled: true,
  // null 表示「尚未从后端读到」：加载失败时保存不提交该字段，避免用一个猜的默认值
  // 覆盖管理员先前设定的非默认阈值（后端 is not None 语义即「不改动」）。
  wrong_mastery_correct_streak: null,
})

onMounted(async () => {
  try {
    const [aiRes, quizRes] = await Promise.all([
      client.get('/settings/ai'),
      client.get('/settings/quiz'),
    ])
    form.value = {
      ai_api_base_url: aiRes.data.ai_api_base_url || '',
      ai_api_key: '',
      ai_model: aiRes.data.ai_model || '',
      ai_translate_model: aiRes.data.ai_translate_model || '',
      ai_explain_models: aiRes.data.ai_explain_models || [{ model_id: aiRes.data.ai_explain_model || aiRes.data.ai_model || '', reasoning_effort: 'xhigh' }],
      quiz_ai_prewarm_enabled: quizRes.data.quiz_ai_prewarm_enabled !== false,
      wrong_mastery_correct_streak: quizRes.data.wrong_mastery_correct_streak ?? null,
    }
    storedKeyMask.value = aiRes.data.ai_api_key || ''
    hasStoredKey.value = !!aiRes.data.ai_api_key_configured
  } catch {
    toast.error('加载设置失败')
  } finally {
    loading.value = false
  }
})

function addModel() {
  if (form.value.ai_explain_models.length < 5) form.value.ai_explain_models.push({ model_id: '', reasoning_effort: 'xhigh' })
}

function moveModel(index, direction) {
  const target = index + direction
  if (target < 0 || target >= form.value.ai_explain_models.length) return
  const models = form.value.ai_explain_models
  ;[models[index], models[target]] = [models[target], models[index]]
}

async function save() {
  // null 表示设置没加载成功（见 onMounted 的 catch）。此时不提交该字段，让后端保持原值——
  // 否则会用一个猜的默认值把管理员先前设定的阈值悄悄改回去。
  let streak = null
  if (form.value.wrong_mastery_correct_streak !== null) {
    // 数字输入框可手打小数或非法内容；取整后若越界就先提示，不让它变成 NaN →
    // 后端按「未提供」处理，否则用户会以为改了而实际没改（静默失败）。
    streak = Math.trunc(Number(form.value.wrong_mastery_correct_streak))
    if (!Number.isInteger(streak) || streak < 1 || streak > 9) {
      toast.error('错题掌握连对阈值必须是 1 到 9 之间的整数')
      return
    }
  }
  saving.value = true
  try {
    await client.put('/settings/ai', {
      ai_api_base_url: form.value.ai_api_base_url,
      ai_api_key: form.value.ai_api_key,
      ai_model: form.value.ai_model,
      ai_translate_model: form.value.ai_translate_model,
      ai_explain_models: form.value.ai_explain_models,
    })
    await client.put('/settings/quiz', {
      quiz_ai_prewarm_enabled: form.value.quiz_ai_prewarm_enabled,
      wrong_mastery_correct_streak: streak,
    })
    if (form.value.ai_api_key.trim()) {
      storedKeyMask.value = ''
      hasStoredKey.value = true
      form.value.ai_api_key = ''
      showApiKey.value = false
      const res = await client.get('/settings/ai')
      storedKeyMask.value = res.data.ai_api_key || ''
      hasStoredKey.value = !!res.data.ai_api_key_configured
    }
    toast.success('设置已保存')
  } catch (e) {
    toast.error(responseError(e, '保存失败，请检查模型列表'))
  } finally {
    saving.value = false
  }
}

function toggleApiKey() {
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
