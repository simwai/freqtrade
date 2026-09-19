<template>
  <section class="flex flex-col gap-4 min-w-0">
    <div class="section-head flex items-baseline justify-between gap-3 flex-wrap">
      <h2 class="text-lg font-semibold text-lavender">Lab</h2>
    </div>

    <div class="card p-4.5">
      <div class="section-head flex items-baseline justify-between gap-3 flex-wrap mb-4">
        <h3 class="text-base font-semibold">Benchmark</h3>
      </div>
      <div class="form-row flex gap-3 flex-wrap items-end">
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Strategies <input v-model="benchStrategies" placeholder="strategies, comma separated (empty = all)" class="input-field" /></label>
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Timerange <input v-model="timerange" class="input-field" /></label>
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Timeframe <input v-model="timeframe" class="input-field" /></label>
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Mode
          <select v-model="benchMode" class="input-field">
            <option>backtest</option>
            <option>hyperopt</option>
            <option>walkforward</option>
          </select>
        </label>
        <template v-if="benchMode !== 'backtest'">
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Number of optimization epochs. More epochs explore more parameter combinations but take longer."><span class="tip">Epochs</span></UTooltip> <input v-model="benchEpochs" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Loss function scoring each epoch. Lower loss wins; profit-based losses prefer raw return, Sharpe-style losses prefer risk-adjusted return."><span class="tip">Loss</span></UTooltip>
            <select v-model="benchLoss" class="input-field">
              <option v-for="l in lossOptions" :key="l" :value="l">{{ l }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Parameter spaces to optimize, space separated: buy sell roi stoploss trailing."><span class="tip">Spaces</span></UTooltip> <input v-model="benchSpaces" placeholder="buy sell roi stoploss trailing" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Parallel workers. -1 uses all cores; lower it if the machine runs out of memory."><span class="tip">Jobs</span></UTooltip> <input v-model="benchJobs" placeholder="-1" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Random seed for reproducible runs. Empty means random."><span class="tip">Seed</span></UTooltip> <input v-model="benchSeed" placeholder="auto" class="input-field" /></label>
        </template>
        <template v-if="benchMode === 'walkforward'">
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Training window length in days for each walk-forward step."><span class="tip">Train d</span></UTooltip> <input v-model="benchTrain" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Out-of-sample test window length in days for each step."><span class="tip">Test d</span></UTooltip> <input v-model="benchTest" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Step size in days between consecutive windows."><span class="tip">Step d</span></UTooltip> <input v-model="benchStep" type="number" class="input-field" /></label>
        </template>
        <UButton color="primary" @click="startBench" class="btn-primary">Run benchmark</UButton>
      </div>
      <div v-if="benchMsg" class="message text-lavender text-sm mt-2" role="status">{{ benchMsg }}</div>
      <InlineStatus v-if="benchStatus" :type="benchStatus.type" :title="benchStatus.title" :message="benchStatus.message" duration="5000" />
    </div>

    <div class="card p-4.5">
      <div class="section-head flex items-baseline justify-between gap-3 flex-wrap mb-4">
        <h3 class="text-base font-semibold">Single run</h3>
      </div>
      <div class="form-row flex gap-3 flex-wrap items-end">
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Strategy
          <select v-model="strategy" class="input-field">
            <option value="">(choose…)</option>
            <option v-for="s in strategyOptions" :key="s.name" :value="s.name">{{ s.name }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Mode
          <select v-model="mode" class="input-field">
            <option>backtest</option>
            <option>hyperopt</option>
            <option>walkforward</option>
          </select>
        </label>
        <label class="flex flex-col gap-1.5 text-text-dim text-sm">Config
          <select v-model="runConfig" class="input-field">
            <option value="">auto (optional)</option>
            <option v-for="c in configOptions" :key="c.path" :value="c.path">{{ c.name }}{{ c.hint ? ' (' + c.hint + ')' : '' }}</option>
          </select>
        </label>
        <div class="hint text-text-faint text-sm">{{ configHint }}</div>
        <template v-if="mode !== 'backtest'">
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Number of optimization epochs. More epochs explore more parameter combinations but take longer."><span class="tip">Epochs</span></UTooltip> <input v-model="epochs" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Loss function scoring each epoch. Lower loss wins."><span class="tip">Loss</span></UTooltip>
            <select v-model="loss" class="input-field">
              <option v-for="l in lossOptions" :key="l" :value="l">{{ l }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Parameter spaces to optimize, space separated: buy sell roi stoploss trailing."><span class="tip">Spaces</span></UTooltip> <input v-model="spaces" placeholder="buy sell roi stoploss trailing" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Parallel workers. Empty means auto."><span class="tip">Jobs</span></UTooltip> <input v-model="runJobs" placeholder="auto" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Random seed for reproducible runs. Empty means random."><span class="tip">Seed</span></UTooltip> <input v-model="randomState" placeholder="random" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Skip epochs with fewer trades than this. Filters out noise from tiny samples."><span class="tip">Min trades</span></UTooltip> <input v-model="minTrades" placeholder="0" class="input-field" /></label>
          <label class="check flex items-center gap-1.5 text-text-dim text-sm"><input v-model="analyzePerEpoch" type="checkbox" /> <UTooltip text="Analyze every epoch, not just the best one. Slower but shows the full search distribution."><span class="tip">analyze per epoch</span></UTooltip></label>
        </template>
        <template v-if="mode === 'walkforward'">
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Training window length in days for each walk-forward step."><span class="tip">Train days</span></UTooltip> <input v-model="trainDays" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Out-of-sample test window length in days for each step."><span class="tip">Test days</span></UTooltip> <input v-model="testDays" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Step size in days between consecutive windows."><span class="tip">Step days</span></UTooltip> <input v-model="stepDays" type="number" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Minimum out-of-sample trades per window, otherwise the window is discarded."><span class="tip">WF min trades</span></UTooltip> <input v-model="wfMinTrades" placeholder="0" class="input-field" /></label>
          <label class="flex flex-col gap-1.5 text-text-dim text-sm"><UTooltip text="Maximum out-of-sample drawdown as a fraction, e.g. 0.2 for 20%."><span class="tip">WF max DD</span></UTooltip> <input v-model="wfMaxDD" placeholder="0.2" class="input-field" /></label>
        </template>
        <template v-if="mode === 'hyperopt'">
          <label class="check flex items-center gap-1.5 text-text-dim text-sm"><input v-model="disableExport" type="checkbox" /> <UTooltip text="Do not write the best parameters back to the strategy directory."><span class="tip">disable param export</span></UTooltip></label>
          <label class="check flex items-center gap-1.5 text-text-dim text-sm"><input v-model="printAll" type="checkbox" /> <UTooltip text="Print every epoch result instead of only improvements."><span class="tip">print all</span></UTooltip></label>
        </template>
        <label class="check flex items-center gap-1.5 text-text-dim text-sm"><input v-model="verbose" type="checkbox" /> <UTooltip text="Verbose backend logging for this run."><span class="tip">verbose</span></UTooltip></label>
        <UButton color="primary" @click="startRun" class="btn-primary">Run</UButton>
      </div>
      <div v-if="formError" class="edit-msg text-bad text-sm mt-2" role="alert">{{ formError }}</div>
      <pre v-if="configPreview" class="code-block">{{ configPreview }}</pre>
      <InlineStatus v-if="runStatus" :type="runStatus.type" :title="runStatus.title" :message="runStatus.message" duration="5000" />
    </div>

<div class="card p-4.5">
      <div class="section-head flex items-baseline justify-between gap-3 flex-wrap mb-4">
        <h3 class="text-base font-semibold">Run meta</h3>
      </div>
      <UButton variant="outline" @click="loadRunMeta" :disabled="runMetaLoading" class="btn-secondary">
        <span v-if="runMetaLoading" class="animate-spin mr-2">⟳</span>
        {{ runMetaLoading ? 'Loading...' : 'Load run meta' }}
      </UButton>
      <pre v-if="runMetaText" class="code-block">{{ runMetaText }}</pre>
      <p v-else-if="!runMetaLoading" class="hint text-text-faint text-sm">Click "Load run meta" to fetch run metadata</p>
    </div>

    <div v-if="message" class="message text-lavender text-sm my-2">{{ message }}</div>

    <div class="card p-4.5">
      <div class="section-head flex items-baseline justify-between gap-3 flex-wrap mb-4">
        <h3 class="text-base font-semibold">Jobs</h3>
        <div class="controls flex gap-2 flex-wrap items-center">
          <UButton variant="ghost" size="sm" @click="loadJobs">
            <template #leading>
              <UIcon name="i-lucide-refresh-cw" size="14" />
            </template>
            Refresh jobs
          </UButton>
          <ColumnToggle :columns="jobsColumns" :visibility="columnVisibility" @update:visibility="columnVisibility = $event" />
        </div>
      </div>
      <UTable
        :data="jobRows"
        :columns="jobsColumns"
        :loading="false"
        :column-visibility="columnVisibility"
        @update:column-visibility="columnVisibility = $event"
        class="w-full"
        empty="No jobs yet — start a benchmark or single run above."
      >
        <template #status-cell="{ row }">
          <span :class="statusClass((row.original as any).status)">{{ (row.original as any).status }}</span>
        </template>
        <template #actions-cell="{ row }">
          <div class="flex gap-1 flex-wrap">
            <UButton v-if="(row.original as any).status === 'running'" size="xs" variant="ghost" @click="jobAction((row.original as any).id, 'pause')">Pause</UButton>
            <UButton v-if="(row.original as any).status === 'paused'" size="xs" variant="ghost" @click="jobAction((row.original as any).id, 'resume')">Resume</UButton>
            <UButton v-if="(row.original as any).status === 'running' || (row.original as any).status === 'paused' || (row.original as any).status === 'queued'" size="xs" variant="ghost" color="error" @click="stopJob((row.original as any).id)">Stop</UButton>
            <UButton size="xs" variant="ghost" @click="viewLog((row.original as any).id)">Log</UButton>
            <router-link :to="'/lab/jobs/' + (row.original as any).id"><UButton size="xs" variant="ghost">Detail</UButton></router-link>
          </div>
        </template>
      </UTable>

      <div v-if="logJob" class="log-panel card p-4 mt-4">
        <div class="log-header flex justify-between items-center mb-2">
          <h4 class="text-sm m-0">Log {{ logJob }}
            <span v-if="isStreaming" class="status active ml-2 text-xs">LIVE</span>
            <span v-else-if="jobStatus" class="status ml-2 text-xs" :class="jobStatus === 'done' ? 'active' : 'retired'">{{ jobStatus.toUpperCase() }}</span>
          </h4>
          <div class="flex gap-2 items-center">
            <UButton size="xs" variant="ghost" @click="closeLog">Close</UButton>
            <UButton v-if="isStreaming" size="xs" variant="outline" @click="stopJobStream">Disconnect</UButton>
            <UButton v-if="!isStreaming && jobStatus === 'running'" size="xs" variant="ghost" @click="startJobStream(logJob)">Reconnect</UButton>
          </div>
        </div>
        <div v-if="Object.keys(progressTasks).length" class="progress-tasks mb-2">
          <div v-for="(task, taskId) in progressTasks" :key="taskId" class="progress-task text-xs">
            <span class="font-mono">{{ task.description }}</span>
            <span v-if="task.total > 0">: {{ task.progress }} / {{ task.total }}</span>
          </div>
        </div>
        <pre class="code-block">{{ getLogText(6000) }}</pre>
      </div>
    </div>

    <div class="card p-4.5">
      <div class="section-head flex items-baseline justify-between gap-3 flex-wrap mb-4">
        <h3 class="text-base font-semibold">Benchmark log</h3>
        <UButton variant="ghost" size="sm" @click="loadBenchLog" :disabled="benchLogLoading">
          {{ benchLogLoading ? 'Loading...' : 'Load latest bench log' }}
        </UButton>
      </div>
      <pre v-if="benchLogText" class="code-block">{{ benchLogText }}</pre>
      <p v-else-if="!benchLogLoading" class="hint text-text-faint text-sm">Click "Load latest bench log" to fetch benchmark job log</p>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import * as z from 'zod'
import { sortableHeader } from '../utils/table'
import { api } from '../api/client'
import { useDashboardStore } from '../stores/dashboard'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { useJobLogStream } from '../composables/useEventSource'
import InlineStatus from '../components/InlineStatus.vue'

const store = useDashboardStore()

const timerangeSchema = z.string().regex(/^\d{8}-\d{8}$/, 'Use a full timerange like 20220101-20240101.')
const benchSchema = z.object({
  timerange: timerangeSchema,
  timeframe: z.string().min(1, 'Timeframe is required.'),
  epochs: z.number().int().min(1, 'Epochs must be at least 1.').optional(),
  train_days: z.number().int().min(1, 'Train days must be at least 1.').optional(),
  test_days: z.number().int().min(1, 'Test days must be at least 1.').optional(),
  step_days: z.number().int().min(1, 'Step days must be at least 1.').optional()
}).passthrough()

const runSchema = z.object({
  strategy: z.string().min(1, 'Pick a strategy first.'),
  timerange: timerangeSchema,
  timeframe: z.string().min(1, 'Timeframe is required.'),
  epochs: z.number().int().min(1, 'Epochs must be at least 1.').optional(),
  train_days: z.number().int().min(1, 'Train days must be at least 1.').optional(),
  test_days: z.number().int().min(1, 'Test days must be at least 1.').optional(),
  step_days: z.number().int().min(1, 'Step days must be at least 1.').optional()
}).passthrough()

const { confirm } = useConfirmDialog()

// Inline status state (replaces toast)
const benchStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)
const runStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showBenchStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  benchStatus.value = { type, title, message }
  setTimeout(() => { benchStatus.value = null }, 5000)
}

function showRunStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  runStatus.value = { type, title, message }
  setTimeout(() => { runStatus.value = null }, 5000)
}

const benchStrategies = ref('')
const timerange = ref('20230101-20240101')
const timeframe = ref('5m')
const benchMode = ref('backtest')
const benchEpochs = ref(100)
const benchLoss = ref('SharpeHyperOptLossDaily')
const benchSpaces = ref('buy sell roi stoploss trailing')
const benchJobs = ref('')
const benchSeed = ref('')
const benchTrain = ref(90)
const benchTest = ref(7)
const benchStep = ref(7)
const benchMsg = ref('')
const strategy = ref('')
const mode = ref('backtest')
const runConfig = ref('')
const epochs = ref(100)
const loss = ref('SharpeHyperOptLossDaily')
const spaces = ref('')
const runJobs = ref('')
const randomState = ref('')
const minTrades = ref('')
const trainDays = ref(90)
const testDays = ref(7)
const stepDays = ref(7)
const wfMinTrades = ref('')
const wfMaxDD = ref('')
const disableExport = ref(false)
const printAll = ref(false)
const analyzePerEpoch = ref(false)
const verbose = ref(false)
const configPreview = ref('')
const formError = ref('')
const strategyOptions = ref([] as any[])
const configOptions = ref([] as any[])
const lossOptions = ref(['SharpeHyperOptLossDaily'])
const configHint = ref('')
const message = ref('')
const jobs = ref<Record<string, any>>({})
const logJob = ref('')

// SSE-based job log streaming
const { logLines, isStreaming, jobStatus, progressTasks, start: startJobStream, stop: stopJobStream, getLogText } = useJobLogStream(logJob)

const runMetaText = ref('')
const runMetaLoading = ref(false)
const benchLogText = ref('')
const benchLogLoading = ref(false)

const jobRows = computed(() => Object.entries(jobs.value || {}).map(([id, j]: [string, any]) => ({ id: id, name: j?.name || '', status: j?.status || '' })))

const columnVisibility = ref<Record<string, boolean>>({})

const jobsColumns = [
  { accessorKey: 'id', header: sortableHeader('ID') },
  { accessorKey: 'name', header: sortableHeader('Name') },
  { accessorKey: 'status', header: sortableHeader('Status') },
  { accessorKey: 'actions', header: 'Actions', enableSorting: false, enableGlobalFilter: false },
]

async function startBench() {
  const list = benchStrategies.value.split(',').map((s: string) => s.trim()).filter(Boolean)
  const body: any = { strategies: list, timerange: timerange.value, timeframe: timeframe.value, mode: benchMode.value }
  if (benchMode.value !== 'backtest') {
    body.epochs = Number(benchEpochs.value) || 100
    body.loss = (benchLoss.value || '').trim() || 'SharpeHyperOptLossDaily'
    const sp = (benchSpaces.value || '').split(/\s+/).map((s: string) => s.trim()).filter(Boolean)
    if (sp.length) body.spaces = sp
    if ((benchJobs.value || '').trim() !== '') body.jobs = Number(benchJobs.value)
    if ((benchSeed.value || '').trim() !== '') body.random_state = Number(benchSeed.value)
  }
  if (benchMode.value === 'walkforward') {
    body.train_days = Number(benchTrain.value) || 90
    body.test_days = Number(benchTest.value) || 7
    body.step_days = Number(benchStep.value) || 7
  }
  const checked = benchSchema.safeParse(body)
  if (!checked.success) {
    benchMsg.value = checked.error.issues[0]?.message || 'Invalid benchmark configuration.'
    return
  }
  try {
    const { data } = await api.post('/api/bench', body)
    benchMsg.value = 'job ' + data.job_id
    message.value = ''
    showBenchStatus('success', 'Benchmark started', 'job ' + data.job_id)
    await loadJobs()
  } catch (e) {
    benchMsg.value = 'Could not start the benchmark.'
  }
}
function validateRun(): string {
  if (!strategy.value) return 'Pick a strategy first.'
  if (mode.value === 'walkforward') {
    const m = /^(\d{8})-(\d{8})$/.exec(timerange.value || '')
    if (!m) return 'Walk-forward needs a full timerange like 20220101-20240101.'
    const day = (s: string) => Date.UTC(Number(s.slice(0, 4)), Number(s.slice(4, 6)) - 1, Number(s.slice(6, 8))) / 86400000
    const span = day(m[2]) - day(m[1])
    if (span < Number(trainDays.value) + Number(testDays.value)) {
      return 'Timerange covers ' + span + ' days but train (' + trainDays.value + ') + test (' + testDays.value + ') needs more.'
    }
  }
  return ''
}
async function startRun() {
  const checked = runSchema.safeParse(buildRunBody())
  formError.value = !checked.success
    ? (checked.error.issues[0]?.message || 'Invalid run configuration.')
    : validateRun()
  if (formError.value) return
  const { data } = await api.post('/api/run', buildRunBody())
  message.value = 'job ' + data.job_id
  await loadJobs()
}
function buildRunBody() {
  const body: any = { strategy: strategy.value, mode: mode.value, timerange: timerange.value, timeframe: timeframe.value, rebuild: true }
  if ((runConfig.value || '').trim() !== '') body.config = runConfig.value.trim()
  if (mode.value === 'hyperopt' || mode.value === 'walkforward') {
    body.epochs = Number(epochs.value) || 100
    body.loss = (loss.value || '').trim() || 'SharpeHyperOptLossDaily'
    const sp = (spaces.value || '').split(/\s+/).map((s: string) => s.trim()).filter(Boolean)
    if (sp.length) body.spaces = sp
    if ((runJobs.value || '').trim() !== '') body.jobs = Number(runJobs.value)
    if ((randomState.value || '').trim() !== '') body.random_state = Number(randomState.value)
    if ((minTrades.value || '').trim() !== '') body.min_trades = Number(minTrades.value)
    if (analyzePerEpoch.value) body.analyze_per_epoch = true
  }
  if (mode.value === 'walkforward') {
    body.train_days = Number(trainDays.value) || 90
    body.test_days = Number(testDays.value) || 7
    body.step_days = Number(stepDays.value) || 7
    if ((wfMinTrades.value || '').trim() !== '') body.wf_min_trades = Number(wfMinTrades.value)
    if ((wfMaxDD.value || '').trim() !== '') body.wf_max_drawdown = Number(wfMaxDD.value)
  }
  if (mode.value === 'hyperopt') {
    if (disableExport.value) body.disable_param_export = true
    if (printAll.value) body.print_all = true
  }
  if (verbose.value) body.verbosity = 3
  return body
}
function previewConfig() {
  configPreview.value = JSON.stringify(buildRunBody(), null, 2)
}
watch([strategy, mode, timerange, timeframe, runConfig, epochs, loss, spaces, runJobs, randomState, minTrades, trainDays, testDays, stepDays, analyzePerEpoch, verbose], () => {
  if (strategy.value) previewConfig()
})
async function loadDropdowns() {
  try {
    const { data } = await api.get('/api/strategies')
    strategyOptions.value = Array.isArray(data) ? data : []
  } catch (e) { strategyOptions.value = [] }
  try {
    const { data } = await api.get('/api/configs')
    configOptions.value = (data && data.configs) || []
    configHint.value = configOptions.value.length
      ? 'Auto: user_data/config_<strategy>.json or config_benchmark.json, or pick one from the dropdown.'
      : 'No configs found — check user_data/config*.json'
  } catch (e) {
    configHint.value = 'Auto config: user_data/config_<strategy>.json if it exists, else config_benchmark.json. Config dropdown needs the lab server.'
  }
  try {
    const { data } = await api.get('/api/losses')
    const live = (data && data.losses) || []
    const seen = new Set(lossOptions.value)
    live.forEach((l: string) => { if (l && !seen.has(l)) { seen.add(l); lossOptions.value.push(l) } })
    if (!lossOptions.value.includes(loss.value)) loss.value = lossOptions.value[0]
    if (!lossOptions.value.includes(benchLoss.value)) benchLoss.value = lossOptions.value[0]
  } catch (e) {}
}
async function loadJobs() {
  try {
    const { data } = await api.get('/api/jobs')
    jobs.value = data
  } catch (e) {
    // error suppressed
  }
}
async function jobAction(id: string, action: string) {
  message.value = ''
  try {
    await api.post('/api/jobs/' + id + '/' + action, {})
    await loadJobs()
  } catch (e) {
    // error suppressed
  }
}
async function stopJob(id: string) {
  const confirmed = await confirm({
    title: 'Stop job',
    description: 'Stop job ' + id + '? A running backtest or optimization will be terminated.',
    confirmLabel: 'Stop job',
    color: 'error'
  })
  if (!confirmed) return
  await jobAction(id, 'stop')
}
async function viewLog(id: string) {
  if (logJob.value === id && isStreaming.value) {
    // Already viewing this job, close it
    closeLog()
    return
  }
  logJob.value = id
  startJobStream(id)
}

function closeLog() {
  logJob.value = ''
  stopJobStream()
}
async function loadRunMeta() {
  runMetaLoading.value = true
  runMetaText.value = ''
  try {
    const { data } = await api.get('/api/run/meta')
    runMetaText.value = JSON.stringify(data, null, 2)
  } catch (e) {
    runMetaText.value = 'Error loading run meta: ' + String(e)
  } finally {
    runMetaLoading.value = false
  }
}
async function loadBenchLog() {
  benchLogLoading.value = true
  benchLogText.value = 'Loading...'
  try {
    const { data } = await api.get('/api/jobs')
    const entries = Object.entries(data || {})
    // First, look for benchmark jobs by mode or name
    const benchEntries = entries.filter(([_, j]) => {
      const job = j as any
      return job.mode === 'benchmark' || (job.name || '').toLowerCase().includes('bench')
    })
    let bid: string | undefined
    if (benchEntries.length) {
      // Prefer the most recent benchmark job
      bid = benchEntries.sort((a, b) => {
        const ta = (a[1] as any).started_at || 0
        const tb = (b[1] as any).started_at || 0
        return tb - ta
      })[0][0]
    } else if (entries.length) {
      // Fallback to most recent job of any type
      bid = entries.sort((a, b) => {
        const ta = (a[1] as any).started_at || 0
        const tb = (b[1] as any).started_at || 0
        return tb - ta
      })[0][0]
    }
    if (!bid) { benchLogText.value = 'No jobs found'; return }
    const r = await api.get('/api/jobs/' + bid + '/log', { params: { tail: 6000 } })
    benchLogText.value = r.data.log || 'Log is empty'
  } catch (e) {
    benchLogText.value = 'Error loading benchmark log: ' + String(e)
  } finally {
    benchLogLoading.value = false
  }
}
function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'running') return 'status active'
  if (sl === 'done') return 'status active'
  if (sl === 'error') return 'status retired'
  if (sl === 'paused') return 'status experimental'
  if (sl === 'queued') return 'status experimental'
  if (sl === 'stopped') return 'status'
  return 'status'
}
onMounted(() => {
  loadJobs()
  loadDropdowns()
  defaultRunRange()
  document.addEventListener('keydown', onKey)
})
onUnmounted(() => { document.removeEventListener('keydown', onKey) })

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && logJob.value) closeLog()
}

async function defaultRunRange() {
  await store.fetchAll()
  let min = '20220101'
  let max = '20240101'
  store.backtests.forEach((r: any) => {
    const m = /^(\d{8})-(\d{8})$/.exec(r.timerange || '')
    if (m) { if (m[1] < min) min = m[1]; if (m[2] > max) max = m[2] }
  })
  if (timerange.value === '20230101-20240101') timerange.value = min + '-' + max
}
</script>

<style scoped>
.tip { border-bottom: 1px dotted var(--color-text-faint); cursor: help; }
.form-row { display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: flex-end; }
.form-row label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.75rem; color: var(--color-text-dim); }
.input-field {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--color-text);
  font-size: 13px;
  min-width: 8.75rem;
}
.message { color: var(--color-lavender); font-size: 13px; margin: 0.5rem 0; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.log-panel { margin-top: 1rem; }
.log-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.log-header h4 { margin: 0; font-size: 13px; }

@media (max-width: 768px) {
  .form-row label { flex: 1 1 100%; min-width: 0; }
  .form-row input, .form-row select { min-width: 100%; }
  .controls { flex-direction: column; align-items: stretch; }
  .controls .filter-input { flex: 1 1 100%; min-width: 0; }
}
@media (max-width: 480px) {
  .btn-primary, .btn-secondary { width: 100%; }
  .log-header { flex-direction: column; gap: 0.5rem; align-items: flex-start; }
}
</style>
