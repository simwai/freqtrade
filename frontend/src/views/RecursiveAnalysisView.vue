<template>
  <section>
    <div class="section-head">
      <h2>Recursive Analysis</h2>
    </div>

    <InlineStatus v-if="analysisStatus" :type="analysisStatus.type" :title="analysisStatus.title" :message="analysisStatus.message" :duration="5000" />

    <div v-if="loadingStrategies" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading strategies...</span>
      </div>
    </div>

    <div class="card">
      <h3>Run Recursive Analysis</h3>
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
          <UFormField name="startup_candles" label="Startup Candles">
            <UInput type="number" v-model.number="formState.startup_candles" placeholder="0" />
          </UFormField>
          <UFormField name="recursive_strategy_search" label="Recursive Search">
            <UCheckbox v-model="formState.recursive_strategy_search" />
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
        <div class="summary-card">
          <span class="label">Strategy</span>
          <span class="value">{{ result.strategy }}</span>
        </div>
        <div class="summary-card">
          <span class="label">Startup Candles Required</span>
          <span class="value">{{ result.startup_candles }}</span>
        </div>
        <div class="summary-card">
          <span class="label">SCC Count</span>
          <span class="value">{{ result.strategy_scc?.length || 0 }}</span>
        </div>
      </div>

      <div class="card mt-4">
        <h4>Indicator Dependency Graph (SCC)</h4>
        <SccGraph :nodes="graphNodes" :edges="graphEdges" />
      </div>

      <div class="card mt-4">
        <h4>Indicator Details</h4>
        <StartupCandleTable :indicators="indicatorDetails" />
      </div>

      <div class="card mt-4">
        <h4>Per-Indicator Diffs</h4>
        <UTable
          :data="diffRows"
          :columns="diffColumns"
          :loading="false"
          :sticky="true"
          class="w-full"
        >
          <template #diff-cell="{ row }">
            <span class="num" :class="diffClass((row.original as any).diff)">{{ fmtNum((row.original as any).diff) }}</span>
          </template>
        </UTable>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import * as z from 'zod'
import { api } from '../api/client'
import { rpcApi } from '../api/rpcClient'
import SccGraph from '../components/SccGraph.vue'
import StartupCandleTable from '../components/StartupCandleTable.vue'
import { sortableHeader } from '../utils/table'
import type { RecursiveAnalysisResult, SccGraphData } from '../api/schemas'
import InlineStatus from '../components/InlineStatus.vue'

const router = useRouter()

// Inline status state (replaces toast)
const analysisStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showAnalysisStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  analysisStatus.value = { type, title, message }
  setTimeout(() => { analysisStatus.value = null }, 5000)
}

const loadingStrategies = ref(true)
const strategyOptions = ref<{ label: string; value: string }[]>([])
const formError = ref('')
const runningJob = ref(false)
const jobId = ref('')
const result = ref<RecursiveAnalysisResult | null>(null)

const formSchema = z.object({
  strategy: z.string().min(1, 'Pick a strategy first.'),
  timeframe: z.string().optional().default('5m'),
  timeframe_detail: z.string().optional().default(''),
  timerange: z.string().regex(/^\d{8}-\d{8}$/, 'Use a full timerange like 20220101-20240101.').optional().default(''),
  startup_candles: z.number().int().min(0).optional().default(0),
  recursive_strategy_search: z.boolean().optional().default(false),
})

type FormState = z.output<typeof formSchema>

const formState = ref<FormState>({
  strategy: '',
  timeframe: '5m',
  timeframe_detail: '',
  timerange: '20230101-20240101',
  startup_candles: 0,
  recursive_strategy_search: false,
})

function onFormError(e: any) {
  formError.value = e?.message || 'Form error'
}

async function loadStrategies() {
  loadingStrategies.value = true
  try {
    const { data } = await api.get('/api/strategies')
    strategyOptions.value = (Array.isArray(data) ? data : []).map((s: any) => ({ label: s.name, value: s.name }))
  } catch (e) {
    showAnalysisStatus('error', 'Failed to load strategies')
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
    const { data } = await rpcApi.post('/api/recursive_analysis', body)
    jobId.value = data.job_id
    showAnalysisStatus('success', 'Analysis started', 'Job ' + data.job_id)
    await pollJob(data.job_id)
  } catch (e: any) {
    formError.value = e.message || 'Failed to start analysis'
    showAnalysisStatus('error', 'Analysis failed')
  } finally {
    runningJob.value = false
  }
}

async function pollJob(id: string) {
  for (let i = 0; i < 300; i++) {
    await new Promise(r => setTimeout(r, 1000))
    try {
      const { data } = await rpcApi.get('/api/recursive_analysis/' + id)
      if (data.status === 'ended') {
        result.value = data.result
        buildGraphData()
        buildIndicatorDetails()
        buildDiffRows()
        showAnalysisStatus('success', 'Analysis complete')
        return
      }
      if (data.status === 'error') {
        formError.value = data.status_msg || 'Analysis failed'
        showAnalysisStatus('error', 'Analysis failed', data.status_msg)
        return
      }
    } catch (e) {
    }
  }
  formError.value = 'Polling timeout'
  showAnalysisStatus('error', 'Polling timeout')
}

function navigateToJob() {
  if (jobId.value) {
    router.push('/lab/jobs/' + jobId.value)
  }
}

const graphNodes = ref<SccGraphData['nodes']>([])
const graphEdges = ref<SccGraphData['edges']>([])
const indicatorDetails = ref<any[]>([])
const diffRows = ref<any[]>([])
const diffColumns = [
  { accessorKey: 'indicator', header: sortableHeader('Indicator') },
  { accessorKey: 'startup_candles', header: sortableHeader('Startup Candles') },
  { accessorKey: 'diff', header: sortableHeader('Diff'), accessorFn: (r: any) => r.diff },
]

function buildGraphData() {
  if (!result.value?.results) return
  const indicators = Object.keys(result.value.results)
  const scc = result.value.strategy_scc || []

  // Create nodes for each indicator
  graphNodes.value = indicators.map((name, idx) => ({
    id: name,
    label: name,
    startup_candles: 0, // Will be filled from indicatorDetails
    indicators: [name],
  }))

  // Create edges based on dependencies (simplified - would need actual dependency analysis)
  graphEdges.value = []
  for (const indicator of indicators) {
    const diffs = result.value!.results[indicator]
    if (!diffs) continue
    const candles = Object.keys(diffs).map(Number).sort((a, b) => a - b)
    // Add edges to earlier candles as dependencies
    for (let i = 1; i < candles.length; i++) {
      graphEdges.value.push({
        source: indicator + '_candle_' + candles[i - 1],
        target: indicator + '_candle_' + candles[i],
        weight: diffs[candles[i]] || 0,
      })
    }
  }
}

function buildIndicatorDetails() {
  if (!result.value?.results) return
  indicatorDetails.value = Object.entries(result.value.results).map(([name, diffs]) => {
    const candles = Object.keys(diffs).map(Number).sort((a, b) => a - b)
    const maxDiff = Math.max(...Object.values(diffs).map(Math.abs))
    return {
      name,
      startup_candles: candles.length ? candles[candles.length - 1] : 0,
      num_candles: candles.length,
      max_diff: maxDiff,
      diffs: candles.map(c => ({ candle: c, diff: diffs[c] })),
    }
  })
}

function buildDiffRows() {
  if (!result.value?.results) return
  diffRows.value = Object.entries(result.value.results).flatMap(([indicator, diffs]) =>
    Object.entries(diffs).map(([candle, diff]) => ({
      indicator,
      candle: Number(candle),
      diff,
    }))
  )
}

function diffClass(v: number) {
  if (!v) return ''
  return v > 0 ? 'good' : 'bad'
}

function fmtNum(v: number) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 6 })
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
.summary-card .label { font-size: 11px; color: var(--text-dim); }
.summary-card .value { font-size: 16px; font-weight: 600; }
.edit-msg { color: var(--bad); font-size: 12px; margin-top: 8px; }
</style>
