<template>
  <section>
    <div class="section-head">
      <h2>Lookahead Analysis</h2>
    </div>

    <InlineStatus v-if="lookaheadStatus" :type="lookaheadStatus.type" :title="lookaheadStatus.title" :message="lookaheadStatus.message" :duration="5000" />

    <div v-if="loadingStrategies" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading strategies...</span>
      </div>
    </div>

    <div class="card">
      <h3>Run Lookahead Analysis</h3>
      <UForm :schema="formSchema" :state="formState" @submit="runAnalysis" @error="onFormError">
        <div class="form-row">
          <UFormField name="strategy" label="Strategy" required>
            <USelect v-model="formState.strategy" :options="strategyOptions" placeholder="(choose…)" />
          </UFormField>
          <UFormField name="timeframe" label="Timeframe">
            <UInput v-model="formState.timeframe" placeholder="5m" />
          </UFormField>
          <UFormField name="timeframe_detail" label="Detail Timeframe">
            <UInput v-model="formState.timeframe_detail" placeholder="1m" />
          </UFormField>
          <UFormField name="timerange" label="Timerange">
            <UInput v-model="formState.timerange" placeholder="20230101-20240101" />
          </UFormField>
          <UFormField name="lookahead_window" label="Lookahead Window (candles)">
            <UInput type="number" v-model.number="formState.lookahead_window" placeholder="1" />
          </UFormField>
          <UButton type="submit" :disabled="runningJob">{{ runningJob ? 'Running...' : 'Start Analysis' }}</UButton>
        </div>
      </UForm>
      <div v-if="formError" class="edit-msg" role="alert">{{ formError }}</div>
      <div v-if="jobId" class="job-status">
        <p>Job ID: <code>{{ jobId }}</code></p>
        <UButton size="sm" variant="ghost" @click="navigateToJob">View Job Detail</UButton>
      </div>
    </div>

    <div v-if="result" class="card mt-4">
      <h3>Analysis Result</h3>
      <div class="result-summary">
        <div class="summary-card" :class="result.has_bias ? 'bias' : 'clean'">
          <span class="label">Lookahead Bias</span>
          <span class="value">{{ result.has_bias ? 'DETECTED ⚠' : 'NONE ✓' }}</span>
        </div>
        <div class="summary-card">
          <span class="label">Total Signals</span>
          <span class="value">{{ fmtNum(result.total_signals) }}</span>
        </div>
        <div class="summary-card">
          <span class="label">Biased Entry Signals</span>
          <span class="value">{{ fmtNum(result.biased_entry_signals) }}</span>
        </div>
        <div class="summary-card">
          <span class="label">Biased Exit Signals</span>
          <span class="value">{{ fmtNum(result.biased_exit_signals) }}</span>
        </div>
      </div>

      <div v-if="result.biased_indicators?.length" class="card mt-4">
        <h4>Biased Indicators</h4>
        <UTable
          :data="biasedIndicators"
          :columns="biasColumns"
          :loading="false"
          :sticky="true"
          class="w-full"
        >
          <template #indicator-cell="{ row }">
            <span class="font-mono">{{ (row.original as any).indicator }}</span>
          </template>
        </UTable>
      </div>
      <p v-else class="hint mt-4">No biased indicators detected.</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import * as z from 'zod'
import { api } from '../api/client'
import { rpcApi } from '../api/rpcClient'
import { sortableHeader } from '../utils/table'
import type { LookaheadAnalysisResult, LookaheadAnalysisResponse } from '../api/schemas'
import InlineStatus from '../components/InlineStatus.vue'

const router = useRouter()

// Inline status state (replaces toast)
const lookaheadStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showLookaheadStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  lookaheadStatus.value = { type, title, message }
  setTimeout(() => { lookaheadStatus.value = null }, 5000)
}

const loadingStrategies = ref(true)
const strategyOptions = ref<{ label: string; value: string }[]>([])
const formError = ref('')
const runningJob = ref(false)
const jobId = ref('')
const result = ref<LookaheadAnalysisResult | null>(null)

const formSchema = z.object({
  strategy: z.string().min(1, 'Pick a strategy first.'),
  timeframe: z.string().optional().default('5m'),
  timeframe_detail: z.string().optional().default(''),
  timerange: z.string().regex(/^\d{8}-\d{8}$/, 'Use a full timerange like 20220101-20240101.').optional().default(''),
  lookahead_window: z.number().int().min(1).optional().default(1),
})

type FormState = z.output<typeof formSchema>

const formState = ref<FormState>({
  strategy: '',
  timeframe: '5m',
  timeframe_detail: '',
  timerange: '20230101-20240101',
  lookahead_window: 1,
})

function onFormError(e: any) {
  formError.value = e?.message || 'Form error'
}

const biasedIndicators = computed(() => {
  if (!result.value?.biased_indicators) return []
  return result.value.biased_indicators.map((indicator: string) => ({ indicator }))
})

const biasColumns: any[] = [
  { accessorKey: 'indicator', header: sortableHeader('Indicator') },
]

async function loadStrategies() {
  loadingStrategies.value = true
  try {
    const { data } = await api.get<any[]>('/api/strategies')
    strategyOptions.value = (Array.isArray(data) ? data : []).map((s: any) => ({ label: s.name, value: s.name }))
  } catch (e) {
    showLookaheadStatus('error', 'Failed to load strategies')
  } finally {
    loadingStrategies.value = false
  }
}

async function runAnalysis() {
  formError.value = ''
  runningJob.value = true
  jobId.value = ''
  try {
    const body = { ...formState.value }
    Object.keys(body).forEach(key => {
      if (body[key as keyof FormState] === '' || body[key as keyof FormState] === undefined) {
        delete body[key as keyof FormState]
      }
    })
    const { data } = await rpcApi.post<LookaheadAnalysisResponse>('/api/lookahead_analysis', body)
    jobId.value = data.job_id!
    showLookaheadStatus('success', 'Analysis started', 'Job ' + data.job_id!)
    await pollJob(data.job_id!)
  } catch (e: any) {
    formError.value = e.message || 'Failed to start analysis'
    showLookaheadStatus('error', 'Analysis failed')
  } finally {
    runningJob.value = false
  }
}

async function pollJob(id: string) {
  for (let i = 0; i < 300; i++) {
    await new Promise(r => setTimeout(r, 1000))
    try {
      const { data } = await rpcApi.get<LookaheadAnalysisResponse>('/api/lookahead_analysis/' + id)
      if (data.status === 'ended') {
        result.value = data.result || null
        showLookaheadStatus('success', 'Analysis complete')
        return
      }
      if (data.status === 'error') {
        formError.value = data.status_msg || 'Analysis failed'
        showLookaheadStatus('error', 'Analysis failed', data.status_msg)
        return
      }
    } catch (e) {
      // Continue polling
    }
  }
  formError.value = 'Polling timeout'
  showLookaheadStatus('error', 'Polling timeout')
}

function navigateToJob() {
  if (jobId.value) {
    router.push('/lab/jobs/' + jobId.value)
  }
}

function fmtNum(v: number) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

onMounted(async () => {
  await loadStrategies()
})
</script>

<style scoped>
.form-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
.form-row label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.form-row input, .form-row select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  min-width: 140px;
}
.job-status { margin-top: 12px; padding: 12px; background: var(--bg-soft); border: 1px solid var(--border); border-radius: 8px; }
.job-status code { font-size: 12px; }
.result-summary { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 16px; }
.summary-card { display: flex; flex-direction: column; gap: 4px; padding: 12px 16px; background: var(--bg-soft); border: 1px solid var(--border); border-radius: 8px; min-width: 180px; }
.summary-card.bias { border-color: var(--bad); background: rgba(248, 113, 113, 0.1); }
.summary-card.clean { border-color: var(--good); background: rgba(110, 231, 168, 0.1); }
.summary-card .label { font-size: 11px; color: var(--text-dim); }
.summary-card .value { font-size: 16px; font-weight: 600; }
.summary-card.bias .value { color: var(--bad); }
.summary-card.clean .value { color: var(--good); }
.edit-msg { color: var(--bad); font-size: 12px; margin-top: 8px; }
</style>
