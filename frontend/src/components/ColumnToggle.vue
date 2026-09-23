<template>
  <details ref="root" class="col-toggle">
    <summary class="col-toggle-btn" aria-label="Toggle column visibility">
      <UIcon name="i-lucide-columns-3" size="14" />
      <span>Columns</span>
    </summary>
    <div class="col-toggle-panel card">
      <UCheckbox
        v-for="c in toggleable"
        :key="c.accessorKey"
        :label="toggleLabel(c)"
        :model-value="visibility[c.accessorKey] !== false"
        @update:model-value="set(c.accessorKey, $event === true)"
      />
      <UButton size="xs" variant="ghost" @click="reset">Show all</UButton>
    </div>
  </details>
</template>
<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{ columns: any[]; visibility: Record<string, boolean> }>()
const emit = defineEmits<{ 'update:visibility': [v: Record<string, boolean>] }>()

const root = ref<HTMLElement | null>(null)

const toggleable = computed(() => props.columns.filter((c) => c.accessorKey !== 'actions' && c.enableHiding !== false))

function toggleLabel(c: any): string {
  if (typeof c.header === 'string') return c.header
  return c.header?.toggleLabel || c.accessorKey
}

function set(key: string, visible: boolean) {
  emit('update:visibility', { ...props.visibility, [key]: visible })
}

function reset() {
  emit('update:visibility', {})
}

function onDocClick(e: MouseEvent) {
  const el = root.value
  if (el && el.hasAttribute('open') && e.target instanceof Node && !el.contains(e.target)) el.removeAttribute('open')
}

onMounted(() => { document.addEventListener('click', onDocClick) })
onUnmounted(() => { document.removeEventListener('click', onDocClick) })
</script>

<style scoped>
.col-toggle { position: relative; }
.col-toggle-btn { display: inline-flex; align-items: center; gap: 6px; background: var(--bg-soft); border: 1px solid var(--border); color: var(--text-dim); padding: 7px 12px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; list-style: none; }
.col-toggle-btn::-webkit-details-marker { display: none; }
.col-toggle-btn:hover { color: var(--lavender); border-color: var(--lavender-ink); }
.col-toggle-panel { position: absolute; right: 0; top: calc(100% + 6px); z-index: 60; display: flex; flex-direction: column; gap: 6px; min-width: 180px; max-height: 320px; overflow-y: auto; }
</style>
