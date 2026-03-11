<template>
  <div class="fixed top-4 right-4 z-50 flex flex-col gap-2">
    <TransitionGroup
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="translate-x-full opacity-0"
      enter-to-class="translate-x-0 opacity-100"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="translate-x-full opacity-0"
    >
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :class="[
          'rounded-lg border p-4 shadow-lg min-w-[280px] sm:min-w-[320px] max-w-[calc(100vw-2rem)] flex items-start gap-3',
          'dark:bg-slate-800 dark:border-slate-700 dark:text-gray-100',
          typeClasses[toast.type]
        ]"
      >
        <component
          :is="typeIcons[toast.type]"
          class="h-5 w-5 shrink-0 mt-0.5"
        />
        <span class="flex-1 text-sm">{{ toast.message }}</span>
        <button
          @click="remove(toast.id)"
          class="shrink-0 rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10"
        >
          <XMarkIcon class="h-4 w-4" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { useToast } from '../composables/useToast'
import { CheckCircleIcon, XCircleIcon, InformationCircleIcon } from '@heroicons/vue/24/outline'
import { XMarkIcon } from '@heroicons/vue/20/solid'

const { toasts, remove } = useToast()

const typeClasses = {
  success: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  error: 'bg-rose-50 text-rose-800 border-rose-200',
  info: 'bg-sky-50 text-sky-800 border-sky-200'
}

const typeIcons = {
  success: CheckCircleIcon,
  error: XCircleIcon,
  info: InformationCircleIcon
}
</script>
