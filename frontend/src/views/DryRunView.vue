<template>
  <section>
    <div class="section-head">
      <h2>Dry Run</h2>
    </div>

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
        <h3>Gate</h3>
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

const toast = useToast()
const { confirm } = useConfirmDialog()
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
    configOptions.value = (data && data.configs) || []
  } catch (e) { configOptions.value = [] }
}

async function loadLog() {
  logText.value = 'Loading...'
  try {
    const { data } = await api.get('/api/dryrun/log')
    logText.value = data || ''
  } catch (e) {
    logText.value = ''
    toast.add({ title: 'Log refresh failed', description: 'Could not load the dry-run log.', color: 'error', duration: 3000 })
  }
}

async function startDryrun() {
  const body: any = { strategy: formState.strategy, timerange: formState.timerange, timeframe: formState.timeframe }
  if (formState.dryrunConfig) body.config = formState.dryrunConfig
  try {
    await api.post('/api/dryrun', body)
    toast.add({ title: 'Dry run started', description: formState.strategy, color: 'success', duration: 3000 })
    await loadStatus()
  } catch (e) {
    toast.add({ title: 'Start failed', description: 'Could not start the dry run.', color: 'error', duration: 3000 })
  }
}

function onDryrunError() {
  toast.add({ title: 'Check the form', description: 'Fix the highlighted fields and try again.', color: 'warning', duration: 3000 })
}

async function stopDryrun() {
  const confirmed = await confirm({
    title: 'Stop dry run',
    description: 'Stop the active dry run? Open positions will no longer be managed.',
    confirmLabel: 'Stop dry run',
    color: 'error'
  })
  if (!confirmed) return
  try {
    await api.post('/api/dryrun/stop', { strategy: formState.strategy })
    toast.add({ title: 'Dry run stopped', description: '', color: 'success', duration: 3000 })
    await loadStatus()
  } catch (e) {
    toast.add({ title: 'Stop failed', description: 'Could not stop the dry run.', color: 'error', duration: 3000 })
  }
}

async function openGate() {
  if (!formState.strategy) {
    toast.add({ title: 'Pick a strategy first', description: '', color: 'warning', duration: 3000 })
    return
  }
  const body: any = { strategy: formState.strategy, timerange: formState.timerange, timeframe: formState.timeframe }
  if (formState.dryrunConfig) body.config = formState.dryrunConfig
  try {
    await api.post('/api/dryrun/gate', body)
    toast.add({ title: 'Gate opened', description: formState.strategy, color: 'success', duration: 3000 })
  } catch (e) {
    toast.add({ title: 'Gate failed', description: 'Could not open the gate.', color: 'error', duration: 3000 })
  }
}

onMounted(() => { reload(); loadDropdowns() })
onUnmounted(() => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } })
</script>