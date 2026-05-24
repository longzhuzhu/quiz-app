<template>
  <Menu as="div" class="relative">
    <MenuButton class="flex max-w-48 items-center gap-2 rounded-lg border border-gray-200 dark:border-slate-700 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-slate-800">
      <span class="truncate">{{ examStore.current?.short_name || examStore.current?.name || '我的项目' }}</span>
      <ChevronDownIcon class="h-4 w-4 flex-shrink-0" />
    </MenuButton>
    <transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="transform scale-95 opacity-0"
      enter-to-class="transform scale-100 opacity-100"
      leave-active-class="transition duration-75 ease-in"
      leave-from-class="transform scale-100 opacity-100"
      leave-to-class="transform scale-95 opacity-0"
    >
      <MenuItems class="absolute left-0 mt-2 w-64 rounded-card bg-white dark:bg-slate-800 shadow-lg ring-1 ring-black/5 focus:outline-none overflow-hidden">
        <div class="px-4 py-2 text-xs font-medium text-gray-400 dark:text-gray-500">切换考试项目</div>
        <MenuItem v-for="exam in examStore.myExams" :key="exam.id" v-slot="{ active }">
          <button
            @click="switchExam(exam.slug)"
            :class="[
              'block w-full px-4 py-2 text-left text-sm',
              active ? 'bg-gray-100 dark:bg-slate-700' : '',
              exam.slug === examStore.current?.slug ? 'text-primary-600 dark:text-primary-400' : 'text-gray-700 dark:text-gray-300'
            ]"
          >
            <span class="block font-medium truncate">{{ exam.short_name || exam.name }}</span>
            <span class="block text-xs text-gray-400 truncate">{{ exam.name }}</span>
          </button>
        </MenuItem>
        <div class="border-t border-gray-100 dark:border-slate-700">
          <MenuItem v-slot="{ active }">
            <router-link :to="{ name: 'MyExamProjects' }" :class="['block px-4 py-2 text-sm text-gray-700 dark:text-gray-300', active ? 'bg-gray-100 dark:bg-slate-700' : '']">我的项目</router-link>
          </MenuItem>
          <MenuItem v-slot="{ active }">
            <router-link :to="{ name: 'ExamCreate' }" :class="['block px-4 py-2 text-sm text-primary-600 dark:text-primary-400', active ? 'bg-gray-100 dark:bg-slate-700' : '']">新建项目</router-link>
          </MenuItem>
        </div>
      </MenuItems>
    </transition>
  </Menu>
</template>

<script setup>
import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/vue'
import { ChevronDownIcon } from '@heroicons/vue/24/outline'
import { useRoute, useRouter } from 'vue-router'
import { useExamStore } from '../stores/exam'
import { useQuizStore } from '../stores/quiz'
import { examPath, routeKind } from '../utils/examRoutes'
import { useToast } from '../composables/useToast'

const route = useRoute()
const router = useRouter()
const examStore = useExamStore()
const quizStore = useQuizStore()
const toast = useToast()

async function switchExam(slug) {
  if (!slug || slug === examStore.current?.slug) return
  try {
    await examStore.switchTo(slug)
    quizStore.reset()
    router.push(examPath(slug, routeKind(route), route.params))
  } catch (e) {
    toast.error(e.response?.data?.error || '切换项目失败')
  }
}
</script>
