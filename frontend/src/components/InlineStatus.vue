<template>
  <div v-if="visible" class="inline-status" :class="typeClass" role="alert" aria-live="polite">
    <div class="status-content">
      <svg v-if="type === 'success'" class="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
        <polyline points="22 4 12 14.01 9 11.01"></polyline>
      </svg>
      <svg v-else-if="type === 'error'" class="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="15" y1="9" x2="9" y2="15"></line>
        <line x1="9" y1="9" x2="15" y2="15"></line>
      </svg>
      <svg v-else-if="type === 'warning'" class="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
        <line x1="12" y1="9" x2="12" y2="13"></line>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
      </svg>
      <svg v-else class="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="16" x2="12" y2="12"></line>
        <line x1="12" y1="8" x2="12.01" y2="8"></line>
      </svg>
      <div class="status-text">
        <strong v-if="title">{{ title }}</strong>
        <span v-if="message">{{ message }}</span>
      </div>
    </div>
    <button class="status-dismiss" @click="dismiss" aria-label="Dismiss">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="6" x2="6" y2="18"></line>
        <line x1="6" y1="6" x2="18" y2="18"></line>
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message?: string
  duration?: number // 0 = persistent
}>()

const emit = defineEmits<{ (e: 'dismiss'): void }>()

const visible = ref(true)

const typeClass = computed(() => `inline-status-${props.type}`)

function dismiss() {
  visible.value = false
  emit('dismiss')
}

if (props.duration !== 0) {
  const duration = props.duration ?? 5000
  setTimeout(dismiss, duration)
}
</script>

<style scoped>
.inline-status {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  border: 1px solid;
  animation: slideIn 0.2s ease-out;
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.status-content {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.status-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}

.status-text {
  font-size: var(--text-sm);
  line-height: 1.5;
}

.status-text strong { display: block; margin-bottom: 2px; }
.status-text span { color: inherit; opacity: 0.9; }

.status-dismiss {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: inherit;
  opacity: 0.6;
  cursor: pointer;
  transition: opacity var(--transition-fast), background var(--transition-fast);
  flex-shrink: 0;
}

.status-dismiss:hover { opacity: 1; background: rgba(255,255,255,0.1); }

/* Type variants */
.inline-status-success { background: var(--color-pnl-positive-bg); color: var(--color-pnl-positive); border-color: var(--color-pnl-positive-border); }
.inline-status-error { background: var(--color-pnl-negative-bg); color: var(--color-pnl-negative); border-color: var(--color-pnl-negative-border); }
.inline-status-warning { background: var(--color-warning-bg); color: var(--color-warning); border-color: var(--color-warning); }
.inline-status-info { background: var(--color-info-bg); color: var(--color-info); border-color: var(--color-info); }
</style>
