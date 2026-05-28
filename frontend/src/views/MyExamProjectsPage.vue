<template>
  <div>
    <div class="mb-6 flex items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">我的项目</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">选择一个考试项目进入练习空间。</p>
      </div>
      <BaseButton @click="router.push('/exams/new')">
        <PlusIcon class="h-4 w-4" />
        新建
      </BaseButton>
    </div>

    <SkeletonLoader v-if="examStore.loading" type="card" :count="2" />

    <div v-else-if="examStore.myExams.length === 0" class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card py-16 text-center">
      <AcademicCapIcon class="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
      <p class="mt-4 text-gray-500 dark:text-gray-400">还没有考试项目</p>
      <BaseButton class="mt-4" @click="router.push('/exams/new')">创建第一个项目</BaseButton>
    </div>

    <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div v-for="exam in examStore.myExams" :key="exam.id" class="rounded-card-lg bg-white dark:bg-slate-800 shadow-card p-5">
        <div class="mb-4 flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-sm text-primary-600 dark:text-primary-400">{{ exam.short_name }}</div>
            <h2 class="truncate text-lg font-semibold text-gray-900 dark:text-white">{{ exam.name }}</h2>
          </div>
          <span v-if="exam.slug === examStore.current?.slug" class="rounded-full bg-primary-50 dark:bg-primary-900/30 px-2 py-1 text-xs text-primary-600 dark:text-primary-400">当前</span>
        </div>
        <p class="mb-4 min-h-10 text-sm text-gray-500 dark:text-gray-400">{{ exam.description || '暂无描述' }}</p>
        <div class="mb-5 grid grid-cols-3 gap-2 text-center text-sm">
          <div class="rounded-lg bg-gray-50 dark:bg-slate-700/50 p-2">
            <div class="font-semibold text-gray-900 dark:text-white">{{ exam.stats?.bank_count || 0 }}</div>
            <div class="text-xs text-gray-400">题库</div>
          </div>
          <div class="rounded-lg bg-gray-50 dark:bg-slate-700/50 p-2">
            <div class="font-semibold text-gray-900 dark:text-white">{{ exam.stats?.question_count || 0 }}</div>
            <div class="text-xs text-gray-400">题目</div>
          </div>
          <div class="rounded-lg bg-gray-50 dark:bg-slate-700/50 p-2">
            <div class="font-semibold text-gray-900 dark:text-white">{{ Math.round(exam.stats?.progress || 0) }}%</div>
            <div class="text-xs text-gray-400">进度</div>
          </div>
        </div>
        <div class="flex gap-2">
          <BaseButton size="sm" class="flex-1" @click="enterExam(exam.slug)">进入</BaseButton>
          <BaseButton size="sm" variant="secondary" @click="startEdit(exam)">编辑</BaseButton>
          <BaseButton size="sm" variant="danger" @click="confirmDelete(exam)">删除</BaseButton>
        </div>
      </div>
    </div>

    <BaseModal :open="editForm.open" title="编辑考试项目" @close="editForm.open = false">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">项目简称</label>
            <input v-model="editForm.short_name" required maxlength="30"
              class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">URL 标识</label>
            <input v-model="editForm.slug" required maxlength="50"
              class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">项目名称</label>
          <input v-model="editForm.name" required maxlength="100"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">描述</label>
          <textarea v-model="editForm.description" rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none"></textarea>
        </div>
        <div class="grid gap-4 md:grid-cols-3">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">图标</label>
            <input v-model="editForm.icon"
              class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">语言</label>
            <input v-model="editForm.locale"
              class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">排序</label>
            <input v-model.number="editForm.sort_order" type="number"
              class="mt-1 w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-1 focus:ring-primary-500 focus:outline-none" />
          </div>
        </div>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="editForm.open = false">取消</BaseButton>
        <BaseButton @click="saveEdit" :loading="editSaving" :disabled="editSaving">保存</BaseButton>
      </template>
    </BaseModal>

    <ConfirmDialog
      :open="deleteTarget.open"
      danger
      title="删除考试项目"
      :message="`确定删除 ${deleteTarget.name} 吗？项目内题库、题目、错题和历史将被删除。`"
      confirm-text="删除"
      @confirm="deleteExam"
      @cancel="deleteTarget.open = false"
    />
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import client from '../api/client'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import { useExamStore } from '../stores/exam'
import { examPath } from '../utils/examRoutes'
import { useToast } from '../composables/useToast'
import { AcademicCapIcon, PlusIcon } from '@heroicons/vue/24/outline'

const router = useRouter()
const examStore = useExamStore()
const toast = useToast()
const deleteTarget = reactive({ open: false, slug: '', name: '' })
const editSaving = ref(false)
const editForm = reactive({
  open: false,
  originalSlug: '',
  slug: '',
  name: '',
  short_name: '',
  description: '',
  icon: '',
  locale: 'en-US',
  sort_order: 0,
})

onMounted(async () => {
  try {
    await examStore.fetchExams()
  } catch (e) {
    toast.error(e.response?.data?.error || '获取考试项目失败')
  }
})

async function enterExam(slug) {
  try {
    await examStore.switchTo(slug)
    router.push(examPath(slug, 'dashboard'))
  } catch (e) {
    toast.error(e.response?.data?.error || '进入项目失败')
  }
}

function startEdit(exam) {
  editForm.open = true
  editForm.originalSlug = exam.slug
  editForm.slug = exam.slug
  editForm.name = exam.name || ''
  editForm.short_name = exam.short_name || ''
  editForm.description = exam.description || ''
  editForm.icon = exam.icon || ''
  editForm.locale = exam.locale || 'en-US'
  editForm.sort_order = exam.sort_order || 0
}

async function saveEdit() {
  if (!editForm.slug.trim() || !editForm.name.trim() || !editForm.short_name.trim()) {
    toast.error('请填写项目简称、URL 标识和项目名称')
    return
  }

  editSaving.value = true
  try {
    const res = await client.patch(`/exams/${editForm.originalSlug}`, {
      slug: editForm.slug.trim(),
      name: editForm.name.trim(),
      short_name: editForm.short_name.trim(),
      description: editForm.description,
      icon: editForm.icon,
      locale: editForm.locale || 'en-US',
      sort_order: editForm.sort_order || 0,
    })
    editForm.open = false
    await examStore.fetchExams()
    if (examStore.current?.slug === editForm.originalSlug) {
      examStore.setCurrent(res.data)
      router.push(examPath(res.data.slug, 'dashboard'))
    }
    toast.success('考试项目已更新')
  } catch (e) {
    toast.error(e.response?.data?.error || '更新考试项目失败')
  } finally {
    editSaving.value = false
  }
}

function confirmDelete(exam) {
  deleteTarget.open = true
  deleteTarget.slug = exam.slug
  deleteTarget.name = exam.name
}

async function deleteExam() {
  deleteTarget.open = false
  try {
    await examStore.deleteExam(deleteTarget.slug)
    toast.success('考试项目已删除')
  } catch (e) {
    toast.error(e.response?.data?.error || '删除考试项目失败')
  }
}
</script>
