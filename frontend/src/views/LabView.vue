<template>
  <section>
    <div class="section-head">
      <h2>Lab</h2>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>Benchmark</h3>
      </div>
      <div class="form-row">
        <label>Strategies <input v-model="benchStrategies" placeholder="strategies, comma separated (empty = all)" /></label>
        <label>Timerange <input v-model="timerange" /></label>
        <label>Timeframe <input v-model="timeframe" /></label>
        <label>Mode
          <select v-model="benchMode">
            <option>backtest</option>
            <option>hyperopt</option>
            <option>walkforward</option>
          </select>
        </label>
        <template v-if="benchMode !== 'backtest'">
          <label><UTooltip text="Number of optimization epochs. More epochs explore more parameter combinations but take longer."><span class="tip">Epochs</span></UTooltip> <input v-model="benchEpochs" type="number" /></label>
          <label><UTooltip text="Loss function scoring each epoch. Lower loss wins; profit-based losses prefer raw return, Sharpe-style losses prefer risk-adjusted return."><span class="tip">Loss</span></UTooltip>
            <select v-model="benchLoss">
              <option v-for="l in lossOptions" :key="l" :value="l">{{ l }}</option>
            </select>
          </label>
          <label><UTooltip text="Parameter spaces to optimize, space separated: buy sell roi stoploss trailing."><span class="tip">Spaces</span></UTooltip> <input v-model="benchSpaces" placeholder="buy sell roi stoploss trailing" /></label>
          <label><UTooltip text="Parallel workers. -1 uses all cores; lower it if the machine runs out of memory."><span class="tip">Jobs</span></UTooltip> <input v-model="benchJobs" placeholder="-1" /></label>
          <label><UTooltip text="Random seed for reproducible runs. Empty means random."><span class="tip">Seed</span></UTooltip> <input v-model="benchSeed" placeholder="auto" /></label>
        </template>
        <template v-if="benchMode === 'walkforward'">
          <label><UTooltip text="Training window length in days for each walk-forward step."><span class="tip">Train d</span></UTooltip> <input v-model="benchTrain" type="number" /></label>
          <label><UTooltip text="Out-of-sample test window length in days for each step."><span class="tip">Test d</span></UTooltip> <input v-model="benchTest" type="number" /></label>
          <label><UTooltip text="Step size in days between consecutive windows."><span class="tip">Step d</span></UTooltip> <input v-model="benchStep" type="number" /></label>
        </template>
        <button class="btn-primary" v-on:click="startBench">Run benchmark</button>
      </div>
      <div v-if="benchMsg" class="message">{{ benchMsg }}</div>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>Single run</h3>
      </div>
      <div class="form-row">
        <label>Strategy
          <select v-model="strategy">
            <option value="">(choose…)</option>
            <option v-for="s in strategyOptions" :key="s.name" :value="s.name">{{ s.name }}</option>
          </select>
        </label>
        <label>Mode
          <select v-model="mode">
            <option>backtest</option>
            <option>hyperopt</option>
            <option>walkforward</option>
          </select>
        </label>
        <label>Config
          <select v-model="runConfig">
            <option value="">auto (optional)</option>
            <option v-for="c in configOptions" :key="c.path" :value="c.path">{{ c.name }}{{ c.hint ? ' (' + c.hint + ')' : '' }}</option>
          </select>
        </label>
        <div class="hint">{{ configHint }}</div>
        <template v-if="mode !== 'backtest'">
          <label><UTooltip text="Number of optimization epochs. More epochs explore more parameter combinations but take longer."><span class="tip">Epochs</span></UTooltip> <input v-model="epochs" type="number" /></label>
          <label><UTooltip text="Loss function scoring each epoch. Lower loss wins."><span class="tip">Loss</span></UTooltip>
            <select v-model="loss">
              <option v-for="l in lossOptions" :key="l" :value="l">{{ l }}</option>
            </select>
          </label>
          <label><UTooltip text="Parameter spaces to optimize, space separated: buy sell roi stoploss trailing."><span class="tip">Spaces</span></UTooltip> <input v-model="spaces" placeholder="buy sellroi trailing" /></label>
          <label><UTooltip text="Parallel workers. Empty means auto."><span class="tip">Jobs</span></UTooltip> <input v-model="runJobs" placeholder="auto" /></label>
          <label><UTooltip text="Random seed for reproducible runs. Empty means random."><span class="tip">Seed</span></UTooltip> <input v-model="randomState" placeholder="random" /></label>
          <label><UTooltip text="Skip epochs with fewer trades than this. Filters out noise from tiny samples."><span class="tip">Min trades</span></UTooltip> <input v-model="minTrades" placeholder="0" /></label>
          <label class="check"><input v-model="analyzePerEpoch" type="checkbox" /> <UTooltip text="Analyze every epoch, not just the best one. Slower but shows the full search distribution."><span class="tip">analyze per epoch</span></UTooltip></label>
        </template>
        <template v-if="mode === 'walkforward'">
          <label><UTooltip text="Training window length in days for each walk-forward step."><span class="tip">Train days</span></UTooltip> <input v-model="trainDays" type="number" /></label>
          <label><UTooltip text="Out-of-sample test window length in days for each step."><span class="tip">Test days</span></UTooltip> <input v-model="testDays" type="number" /></label>
          <label><UTooltip text="Step size in days between consecutive windows."><span class="tip">Step days</span></UTooltip> <input v-model="stepDays" type="number" /></label>
          <label><UTooltip text="Minimum out-of-sample trades per window, otherwise the window is discarded."><span class="tip">WF min trades</span></UTooltip> <input v-model="wfMinTrades" placeholder="0" /></label>
          <label><UTooltip text="Maximum out-of-sample drawdown as a fraction, e.g. 0.2 for 20%."><span class="tip">WF max DD</span></UTooltip> <input v-model="wfMaxDD" placeholder="0.2" /></label>
        </template>
        <template v-if="mode === 'hyperopt'">
          <label class="check"><input v-model="disableExport" type="checkbox" /> <UTooltip text="Do not write the best parameters back to the strategy directory."><span class="tip">disable param export</span></UTooltip></label>
          <label class="check"><input v-model="printAll" type="checkbox" /> <UTooltip text="Print every epoch result instead of only improvements."><span class="tip">print all</span></UTooltip></label>
        </template>
        <label class="check"><input v-model="verbose" type="checkbox" /> <UTooltip text="Verbose backend logging for this run."><span class="tip">verbose</span></UTooltip></label>
        <button class="btn-primary" v-on:click="startRun">Run</button>
      </div>
      <div v-if="formError" class="edit-msg" role="alert">{{ formError }}</div>
      <pre v-if="configPreview" class="code-block">{{ configPreview }}</pre>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>Run meta</h3>
      </div>
      <button class="btn-secondary" v-on:click="loadRunMeta">Load run meta</button>
      <pre class="code-block">{{ runMetaText }}</pre>
    </div>

    <div v-if="message" class="message">{{ message }}</div>

    <div class="card">
      <div class="section-head">
        <h3>Jobs</h3>
        <UButton variant="ghost" size="sm" @click="loadJobs">
          <template #leading>
            <UIcon name="i-lucide-refresh-cw" size="14" />
          </template>
          Refresh jobs
        </UButton>
      </div>
      <UTable
        :data="jobRows"
        :columns="jobsColumns"
        :loading="false"
        class="w-full"
        empty="No jobs yet — start a benchmark or single run above."
      >
        <template #cell-status="{ row }">
          <span :class="statusClass((row.original as any).status)">{{ (row.original as any).status }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex gap-1 flex-wrap">
            <UButton v-if="(row.original as any).status === 'running'" size="xs" variant="ghost" @click="jobAction((row.original as any).id, 'pause')">Pause</UButton>
            <UButton v-if="(row.original as any).status === 'paused'" size="xs" variant="ghost" @click="jobAction((row.original as any).id, 'resume')">Resume</UButton>
            <UButton v-if="(row.original as any).status === 'running' || (row.original as any).status === 'paused' || (row.original as any).status === 'queued'" size="xs" variant="ghost" color="error" @click="stopJob((row.original as any).id)">Stop</UButton>
            <UButton size="xs" variant="ghost" @click="viewLog((row.original as any).id)">Log</UButton>
          </div>
        </template>
      </UTable>

      <div v-if="logJob" class="log-panel card">
        <div class="log-header">
          <h4>Log {{ logJob }}</h4>
          <UButton size="xs" variant="ghost" @click="closeLog">Close</UButton>
        </div>
        <pre class="code-block">{{ logText }}</pre>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>Benchmark log</h3>
        <UButton variant="ghost" size="sm" @click="loadBenchLog">Load latest bench log</UButton>
      </div>
      <pre class="code-block">{{ benchLogText }}</pre>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'
import { useDashboardStore } from '../stores/dashboard'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const store = useDashboardStore()
const toast = useToast()
const { confirm } = useConfirmDialog()

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
const logText = ref('')
const runMetaText = ref('')
const benchLogText = ref('')

const jobRows = computed(() => Object.entries(jobs.value || {}).map(([id, j]: [string, any]) => ({ id: id, name: j?.name || '', status: j?.status || '' })))

const jobsColumns = [
  { accessorKey: 'id', header: 'ID' },
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'status', header: 'Status' },
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
  const { data } = await api.post('/api/bench', body)
  benchMsg.value = 'job ' + data.job_id
  message.value = ''
  await loadJobs()
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
  formError.value = validateRun()
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
    toast.add({ title: 'Jobs refresh failed', description: 'Could not load jobs.', color: 'error', duration: 3000 })
  }
}
async function jobAction(id: string, action: string) {
  message.value = ''
  try {
    await api.post('/api/jobs/' + id + '/' + action, {})
    await loadJobs()
  } catch (e) {
    toast.add({ title: 'Job action failed', description: 'Could not ' + action + ' job ' + id + '.', color: 'error', duration: 3000 })
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
  logJob.value = id
  logText.value = 'Loading...'
  const { data } = await api.get('/api/jobs/' + id + '/log', { params: { tail: 6000 } })
  logText.value = data.log || ''
}
function closeLog() {
  logJob.value = ''
  logText.value = ''
}
async function loadRunMeta() {
  const { data } = await api.get('/api/run/meta')
  runMetaText.value = JSON.stringify(data, null, 2)
}
async function loadBenchLog() {
  benchLogText.value = 'Loading...'
  const { data } = await api.get('/api/jobs')
  const ids = Object.keys(data || {})
  const bid = ids.find((x) => (data[x] && data[x].name || '').toLowerCase().includes('bench')) || ids[0]
  if (!bid) { benchLogText.value = 'no jobs'; return }
  const r = await api.get('/api/jobs/' + bid + '/log', { params: { tail: 6000 } })
  benchLogText.value = r.data.log || ''
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
.tip { border-bottom: 1px dotted var(--text-faint); cursor: help; }
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
.message { color: var(--lavender); font-size: 13px; margin: 8px 0; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.log-panel { margin-top: 16px; }
.log-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.log-header h4 { margin: 0; font-size: 13px; }
</style>