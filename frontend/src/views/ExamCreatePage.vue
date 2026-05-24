<template>
  <div class="mx-auto max-w-2xl">
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">新建考试项目</h1>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">创建后会自动切换到该项目。</p>
    </div>

    <form class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-6 space-y-5" @submit.prevent="submit">
      <div class="grid gap-4 md:grid-cols-2">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">项目简称</label>
          <input v-model="form.short_name" required maxlength="30" placeholder="例如 PMP"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">URL 标识</label>
          <input v-model="form.slug" required maxlength="50" placeholder="例如 pmp"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">项目名称</label>
        <input v-model="form.name" required maxlength="100" placeholder="例如 PMP 项目管理专业人士"
          class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">描述</label>
        <textarea v-model="form.description" rows="3"
          class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
      </div>

      <div class="grid gap-4 md:grid-cols-3">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">图标</label>
          <input v-model="form.icon" placeholder="BookOpen"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">语言</label>
          <input v-model="form.locale" placeholder="en-US"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">排序</label>
          <input v-model.number="form.sort_order" type="number"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
      </div>

      <div class="rounded-lg bg-gray-50 dark:bg-slate-700/50 p-3 text-sm text-gray-500 dark:text-gray-400">
        AI Profile 暂使用平台默认配置，后续可在项目管理中扩展编辑。
      </div>

      <div class="flex justify-end gap-3">
        <BaseButton type="button" variant="secondary" @click="router.push('/exams')">取消</BaseButton>
        <BaseButton type="submit" :loading="loading" :disabled="loading">创建项目</BaseButton>
      </div>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import BaseButton from '../components/BaseButton.vue'
import { useExamStore } from '../stores/exam'
import { examPath } from '../utils/examRoutes'
import { useToast } from '../composables/useToast'

const router = useRouter()
const examStore = useExamStore()
const toast = useToast()
const loading = ref(false)
const form = reactive({
  slug: '',
  name: '',
  short_name: '',
  description: '',
  icon: '',
  locale: 'en-US',
  sort_order: 0,
})

watch(() => form.short_name, (value) => {
  if (form.slug) return
  form.slug = value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
})

async function submit() {
  loading.value = true
  try {
    const exam = await examStore.createExam({ ...form })
    toast.success('考试项目已创建')
    router.push(examPath(exam.slug, 'dashboard'))
  } catch (e) {
    toast.error(e.response?.data?.error || '创建考试项目失败')
  } finally {
    loading.value = false
  }
}
</script>
