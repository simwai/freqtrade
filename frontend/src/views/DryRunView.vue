<template>
  <section>
    <div class="section-head">
      <h2>Dry Run</h2>
    </div>

    <InlineStatus v-if="dryrunStatus" :type="dryrunStatus.type" :title="dryrunStatus.title" :message="dryrunStatus.message" :duration="5000" />

    <div v-if="loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading dry-run status...</span>
      </div>
    </div>
    <div v-else-if="loadError" class="card" style="color: var(--bad);">
      <div class="flex items-center gap-3">
        <UIcon name="i-lucide-alert-circle" class="text-error" size="20" />
        <div>
          <p class="font-medium">{{ loadError }}</p>
          <UButton size="sm" variant="outline" @click="reload">Retry</UButton>
        </div>
      </div>
    </div>
    <div v-else>
      <div class="card">
        <h3>Status</h3>
        <div v-if="dryrun.active" class="status active">Active: {{ dryrun.dryrun.strategy }} (started {{ dryrun.dryrun.started_at }})</div>
        <div v-else-if="dryrun.dryrun" class="status experimental">Last: {{ dryrun.dryrun.strategy }} ({{ dryrun.dryrun.status }})</div>
        <div v-else class="status">No dry run yet.</div>
      </div>

      <div class="card">
        <div class="section-head">
          <h3>Log</h3>
          <UButton variant="ghost" size="sm" @click="loadLog">Refresh log</UButton>
        </div>
        <pre class="code-block">{{ logText }}</pre>
      </div>

      <div class="card">
        <h3>Start new</h3>
        <UForm :schema="dryrunSchema" :state="formState" @submit="startDryrun" @error="onDryrunError">
          <div class="form-row">
            <UFormField name="strategy" label="Strategy" required>
              <USelect v-model="formState.strategy" :options="strategySelectOptions" placeholder="(choose…)" />
            </UFormField>
            <UFormField name="timerange" label="Timerange">
              <UInput v-model="formState.timerange" placeholder="20220101-20240101" />
            </UFormField>
            <UFormField name="timeframe" label="Timeframe">
              <UInput v-model="formState.timeframe" placeholder="5m" />
            </UFormField>
            <UFormField name="dryrunConfig" label="Config">
              <USelect v-model="formState.dryrunConfig" :options="configSelectOptions" placeholder="auto (optional)" />
            </UFormField>
            <UButton type="submit">Start dry run</UButton>
            <UButton type="button" variant="outline" color="error" @click="stopDryrun">Stop dry run</UButton>
          </div>
        </UForm>
      </div>

      <div class="card">
        <div class="section-head">
          <h3>Gate</h3>
          <UTooltip text="Pre-dry-run validation gate. Runs hyperopt baseline check (if needed) and walk-forward validation. The dry-run will only start if the gate passes — i.e., out-of-sample metrics beat the current baseline. If the gate fails, the dry-run is aborted.">
            <UIcon name="i-lucide-info" class="text-dim" size="16" />
          </UTooltip>
        </div>
        <UButton @click="openGate">Open gate</UButton>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted } from 'vue'
import * as z from 'zod'
import { api } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import InlineStatus from '../components/InlineStatus.vue'

const { confirm } = useConfirmDialog()

// Inline status state (replaces toast)
const dryrunStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showDryrunStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  dryrunStatus.value = { type, title, message }
  setTimeout(() => { dryrunStatus.value = null }, 5000)
}
const loading = ref(true)
const loadError = ref('')
const dryrun = ref<any>({ active: false, dryrun: null, all: [] })
const logText = ref('')
const dryrunSchema = z.object({
  strategy: z.string().min(1, 'Pick a strategy first.'),
  timerange: z.string().regex(/^\d{8}-\d{8}$/, 'Use a full timerange like 20220101-20240101.'),
  timeframe: z.string().min(1, 'Timeframe is required.'),
  dryrunConfig: z.string().optional().default('')
})

type DryrunForm = z.output<typeof dryrunSchema>

const formState = reactive<DryrunForm>({
  strategy: '',
  timerange: '20220101-20240101',
  timeframe: '5m',
  dryrunConfig: ''
})
const strategyOptions = ref([] as any[])
const configOptions = ref([] as any[])
let pollTimer: any = null

const strategySelectOptions = computed(() => strategyOptions.value.map((s: any) => ({ label: s.name, value: s.name })))
const configSelectOptions = computed(() => configOptions.value.map((c: any) => ({ label: c.name, value: c.path })))

async function loadStatus() {
  const { data } = await api.get('/api/dryrun')
  dryrun.value = data
  loading.value = false
  armPolling()
}

async function reload() {
  loading.value = true
  loadError.value = ''
  try {
    await loadStatus()
  } catch (e) {
    loadError.value = 'Could not load dry-run status.'
    loading.value = false
  }
}

function armPolling() {
  if (pollTimer) return
  pollTimer = setInterval(() => { if (!document.hidden && dryrun.value && dryrun.value.active) loadStatus() }, 15000)
}

async function loadDropdowns() {
  try {
    const { data } = await api.get('/api/strategies')
    strategyOptions.value = Array.isArray(data) ? data : []
  } catch (e) { strategyOptions.value = [] }
  try {
    const { data } = await api.get('/api/configs')
    configOptions.value = ((data as any) && (data as any).configs) || []
  } catch (e) { configOptions.value = [] }
}

async function loadLog() {
  logText.value = 'Loading...'
  try {
    const { data } = await api.get('/api/dryrun/log')
    logText.value = (data as string) || ''
  } catch (e: any) {
    if (e?.response?.status === 404 && e?.response?.data?.detail?.includes('no active dry run')) {
      logText.value = 'No active dry run — start one to see logs.'
    } else {
      logText.value = ''
    }
  }
}

async function startDryrun() {
  const body: any = { strategy: formState.strategy, timerange: formState.timerange, timeframe: formState.timeframe }
  if (formState.dryrunConfig) body.config = formState.dryrunConfig
  try {
    await api.post('/api/dryrun', body)
    showDryrunStatus('success', 'Dry run started', formState.strategy)
    await loadStatus()
  } catch (e) {
    showDryrunStatus('error', 'Failed to start dry run')
  }
}

function onDryrunError() {
  showDryrunStatus('warning', 'Check the form', 'Fix the highlighted fields and try again.')
}

async function stopDryrun() {
  const confirmed = await confirm({
    title: 'Stop dry run',
    description: 'Stop the active dry run? Open positions will no longer be managed.',
    confirmLabel: 'Stop dry run',
    color: 'error'
  })
  if (!confirmed) return
  const activeDryrun = dryrun.value?.dryrun
  const dryrunId = activeDryrun?.dryrun_id || activeDryrun?.id
  if (!dryrunId) {
    showDryrunStatus('warning', 'No active dry run', 'Cannot stop: no dry run ID found.')
    return
  }
  try {
    await api.post('/api/dryrun/stop', { dryrun_id: dryrunId })
    showDryrunStatus('success', 'Dry run stopped')
    await loadStatus()
  } catch (e) {
    showDryrunStatus('error', 'Failed to stop dry run')
  }
}

async function openGate() {
  if (!formState.strategy) {
    showDryrunStatus('warning', 'Pick a strategy first')
    return
  }
  const body: any = { strategy: formState.strategy, timerange: formState.timerange, timeframe: formState.timeframe }
  if (formState.dryrunConfig) body.config = formState.dryrunConfig
  try {
    await api.post('/api/dryrun/gate', body)
    showDryrunStatus('success', 'Gate opened', formState.strategy)
  } catch (e) {
    showDryrunStatus('error', 'Failed to open gate')
  }
}

onMounted(() => { reload(); loadDropdowns() })
onUnmounted(() => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } })
</script>

<style scoped>
.status {
  word-break: break-word;
  padding: 8px 12px;
}
</style>