<template>
  <BaseModal :open="open" :title="title" @close="$emit('cancel')">
    <p class="text-sm text-gray-600 dark:text-gray-300">{{ message }}</p>
    <template #actions>
      <BaseButton variant="secondary" @click="$emit('cancel')">取消</BaseButton>
      <BaseButton :variant="danger ? 'danger' : 'primary'" @click="$emit('confirm')">
        {{ confirmText }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<script setup>
import BaseModal from './BaseModal.vue'
import BaseButton from './BaseButton.vue'

defineProps({
  open: {
    type: Boolean,
    required: true,
  },
  title: {
    type: String,
    default: '确认',
  },
  message: {
    type: String,
    default: '',
  },
  confirmText: {
    type: String,
    default: '确定',
  },
  danger: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['confirm', 'cancel'])
</script>
