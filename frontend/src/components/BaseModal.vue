<template>
  <TransitionRoot :show="open" as="template">
    <Dialog @close="$emit('close')" class="relative z-50">
      <!-- 遮罩 -->
      <TransitionChild
        as="template"
        enter="duration-300 ease-out"
        enter-from="opacity-0"
        enter-to="opacity-100"
        leave="duration-200 ease-in"
        leave-from="opacity-100"
        leave-to="opacity-0"
      >
        <div class="fixed inset-0 bg-black/40 backdrop-blur-sm" />
      </TransitionChild>

      <!-- 面板容器 -->
      <div class="fixed inset-0 flex items-center justify-center p-4">
        <TransitionChild
          as="template"
          enter="duration-300 ease-out"
          enter-from="translate-y-4 opacity-0 scale-95"
          enter-to="translate-y-0 opacity-100 scale-100"
          leave="duration-200 ease-in"
          leave-from="translate-y-0 opacity-100 scale-100"
          leave-to="translate-y-4 opacity-0 scale-95"
        >
          <DialogPanel
            :class="[maxWidthClass, 'w-full rounded-card-lg bg-white dark:bg-slate-800 shadow-xl overflow-hidden']"
          >
            <!-- 标题栏 -->
            <div
              v-if="title"
              class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-700"
            >
              <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ title }}</h3>
              <button @click="$emit('close')" class="text-gray-400 hover:text-gray-500">
                <XMarkIcon class="h-5 w-5" />
              </button>
            </div>

            <!-- 内容 -->
            <div class="px-6 py-4">
              <slot />
            </div>

            <!-- 操作区 -->
            <div
              v-if="$slots.actions"
              class="px-6 py-4 bg-gray-50 dark:bg-slate-800/50 flex justify-end gap-3"
            >
              <slot name="actions" />
            </div>
          </DialogPanel>
        </TransitionChild>
      </div>
    </Dialog>
  </TransitionRoot>
</template>

<script setup>
import { computed } from 'vue'
import {
  Dialog,
  DialogPanel,
  TransitionRoot,
  TransitionChild,
} from '@headlessui/vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'

const props = defineProps({
  open: {
    type: Boolean,
    required: true,
  },
  title: {
    type: String,
    default: '',
  },
  maxWidth: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})

defineEmits(['close'])

const maxWidthMap = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
}

const maxWidthClass = computed(() => maxWidthMap[props.maxWidth])
</script>
