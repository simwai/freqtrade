<template>
  <UModal
    :title="title"
    :description="description"
    :dismissible="false"
    :ui="{ footer: 'justify-end' }"
    :open="isOpen"
    @update:open="onUpdateOpen"
  >
    <template #footer="{ close }">
      <UButton
        :label="cancelLabel || 'Cancel'"
        color="neutral"
        variant="outline"
        @click="close"
      />
      <UButton
        :label="confirmLabel || 'Confirm'"
        :color="color || 'error'"
        @click="$emit('close', true)"
      />
    </template>
  </UModal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  color?: 'error' | 'warning' | 'neutral'
  open?: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  close: [value: boolean]
}>()

const isOpen = ref(props.open ?? true)

watch(() => props.open, (v) => { isOpen.value = v })
watch(isOpen, (v) => { emit('update:open', v) })

function onUpdateOpen(v: boolean) {
  isOpen.value = v
  if (!v) emit('close', false)
}
</script>
