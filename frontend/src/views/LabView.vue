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
        <label>Strategies <input v-model="benchStrategies" placeholder="strategies, comma separated" /></label>
        <label>Timerange <input v-model="timerange" /></label>
        <label>Timeframe <input v-model="timeframe" /></label>
        <button class="btn-primary" v-on:click="startBench">Run benchmark</button>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>Single run</h3>
      </div>
      <div class="form-row">
        <label>Strategy <input v-model="strategy" /></label>
        <label>Mode
          <select v-model="mode">
            <option>backtest</option>
            <option>hyperopt</option>
            <option>walkforward</option>
          </select>
        </label>
        <label>Epochs <input v-model="epochs" type="number" /></label>
        <label>Loss <input v-model="loss" /></label>
        <label>Spaces <input v-model="spaces" placeholder="buy sellroi trailing" /></label>
        <label>Jobs <input v-model="runJobs" placeholder="auto" /></label>
        <label>Seed <input v-model="randomState" placeholder="random" /></label>
        <label>Min trades <input v-model="minTrades" placeholder="0" /></label>
        <label>Train days <input v-model="trainDays" type="number" /></label>
        <label>Test days <input v-model="testDays" type="number" /></label>
        <label>Step days <input v-model="stepDays" type="number" /></label>
        <label class="check"><input v-model="analyzePerEpoch" type="checkbox" /> analyze per epoch</label>
        <label class="check"><input v-model="verbose" type="checkbox" /> verbose</label>
        <button class="btn-primary" v-on:click="startRun">Run</button>
        <button class="btn-secondary" v-on:click="previewConfig">Preview config</button>
      </div>
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
      </div>
      <div class="form-row">
        <button class="btn-secondary" v-on:click="loadJobs">Refresh jobs</button>
      </div>
      <div class="table-wrap table-stack">
        <div class="thead-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" >ID</th>
                <th scope="col" >Name</th>
                <th scope="col" >Status</th>
                <th scope="col" >Actions</th>
              </tr>
            </thead>
          </table>
        </div>
        <div class="table-wrap" ref="jobsTableWrap">
          <table>
            <tbody>
              <tr v-for="(j, id) in jobs" :key="id">
                <td>{{ id }}</td>
                <td>{{ j.name }}</td>
                <td><span :class="statusClass(j.status)">{{ j.status }}</span></td>
                <td>
                  <button v-if="j.status === 'running'" class="btn-secondary btn-sm" v-on:click="jobAction(id, 'pause')">Pause</button>
                  <button v-if="j.status === 'paused'" class="btn-secondary btn-sm" v-on:click="jobAction(id, 'resume')">Resume</button>
                  <button v-if="j.status === 'running' || j.status === 'paused' || j.status === 'queued'" class="btn-secondary btn-sm" v-on:click="jobAction(id, 'stop')">Stop</button>
                  <button class="btn-secondary btn-sm" v-on:click="viewLog(id)">Log</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="logJob" class="log-panel card">
        <div class="log-header">
          <h4>Log {{ logJob }}</h4>
          <button class="btn-secondary btn-sm" v-on:click="closeLog">Close</button>
        </div>
        <pre class="code-block">{{ logText }}</pre>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>Benchmark log</h3>
      </div>
      <button class="btn-secondary" v-on:click="loadBenchLog">Load latest bench log</button>
      <pre class="code-block">{{ benchLogText }}</pre>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { api } from '../api/client'

const benchStrategies = ref('')
const timerange = ref('20230101-20240101')
const timeframe = ref('5m')
const strategy = ref('')
const mode = ref('backtest')
const epochs = ref(100)
const loss = ref('SharpeHyperOptLossDaily')
const spaces = ref('')
const runJobs = ref('')
const randomState = ref('')
const minTrades = ref('')
const trainDays = ref(90)
const testDays = ref(7)
const stepDays = ref(7)
const analyzePerEpoch = ref(false)
const verbose = ref(false)
const configPreview = ref('')
const message = ref('')
const jobs = ref<Record<string, any>>({})
const logJob = ref('')
const logText = ref('')
const runMetaText = ref('')
const benchLogText = ref('')
const jobsTableWrap = ref<HTMLElement | null>(null)

async function startBench() {
  const list = benchStrategies.value.split(',').map((s: string) => s.trim())
  const body = { strategies: list, timerange: timerange.value, timeframe: timeframe.value, mode: 'backtest' }
  const { data } = await api.post('/api/bench', body)
  message.value = 'job ' + data.job_id
  await loadJobs()
}
async function startRun() {
  const { data } = await api.post('/api/run', buildRunBody())
  message.value = 'job ' + data.job_id
  await loadJobs()
}
function buildRunBody() {
  const body: any = { strategy: strategy.value, mode: mode.value, timerange: timerange.value, timeframe: timeframe.value, rebuild: true }
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
  }
  if (verbose.value) body.verbosity = 3
  return body
}
function previewConfig() {
  configPreview.value = JSON.stringify(buildRunBody(), null, 2)
}
async function loadJobs() {
  const { data } = await api.get('/api/jobs')
  jobs.value = data
  await nextTick()
  if (jobsTableWrap.value) {
    syncScroll()
  }
}
async function jobAction(id: string, action: string) {
  message.value = ''
  await api.post('/api/jobs/' + id + '/' + action, {})
  await loadJobs()
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
function syncScroll() {
  if (!jobsTableWrap.value) return
  const tw = jobsTableWrap.value
  tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
  tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
}
onMounted(() => {
  loadJobs()
  if (jobsTableWrap.value) {
    jobsTableWrap.value.addEventListener('scroll', syncScroll)
  }
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
.message { color: var(--lavender); font-size: 13px; margin: 8px 0; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.log-panel { margin-top: 16px; }
.log-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.log-header h4 { margin: 0; font-size: 13px; }
</style>