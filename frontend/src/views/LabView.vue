<template>
  <div>
    <h2>Lab</h2>
    <div>
      <h3>Benchmark</h3>
      <input v-model="benchStrategies" placeholder="strategies, comma separated" />
      <input v-model="timerange" />
      <input v-model="timeframe" />
      <button v-on:click="startBench">Run benchmark</button>
    </div>
    <div>
      <h3>Single run</h3>
      <input v-model="strategy" />
      <select v-model="mode">
        <option>backtest</option>
        <option>hyperopt</option>
        <option>walkforward</option>
      </select>
      <button v-on:click="startRun">Run</button>
    </div>
    <button v-on:click="loadRunMeta">Run meta</button>
    <pre>{{ runMetaText }}</pre>
    <div>{{ message }}</div>
    <h3>Jobs</h3>
    <button v-on:click="loadJobs">Refresh jobs</button>
    <table v-sortable>
      <thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>
        <tr v-for="(j, id) in jobs" :key="id">
          <td>{{ id }}</td>
          <td>{{ j.name }}</td>
          <td>{{ j.status }}</td>
            <td>
              <button v-if="j.status === 'running'" v-on:click="jobAction(id, 'pause')">Pause</button>
              <button v-if="j.status === 'paused'" v-on:click="jobAction(id, 'resume')">Resume</button>
              <button v-if="j.status === 'running' || j.status === 'paused' || j.status === 'queued'" v-on:click="jobAction(id, 'stop')">Stop</button>
              <button v-on:click="viewLog(id)">Log</button>
            </td>
        </tr>
      </tbody>
    </table>
    <div v-if="logJob">
      <h4>Log {{ logJob }} <button v-on:click="closeLog">Close</button></h4>
      <pre>{{ logText }}</pre>
    </div>
  </div>
    <div>
      <h3>Benchmark log</h3>
      <button v-on:click="loadBenchLog">Load latest bench log</button>
      <pre>{{ benchLogText }}</pre>
    </div>
</template>
<script setup lang='ts'>
import { ref, onMounted } from 'vue'
import { api } from '../api/client'
const benchStrategies = ref('')
const timerange = ref('20230101-20240101')
const timeframe = ref('5m')
const strategy = ref('')
const mode = ref('backtest')
const message = ref('')
const jobs = ref({})
async function startBench() {
  const list = benchStrategies.value.split(',').map((s: string) => s.trim())
  const body = { strategies: list, timerange: timerange.value, timeframe: timeframe.value, mode: 'backtest' }
  const { data } = await api.post('/api/bench', body)
  message.value = 'job ' + data.job_id
  await loadJobs()
}
async function startRun() {
  const body = { strategy: strategy.value, mode: mode.value, timerange: timerange.value, timeframe: timeframe.value }
  const { data } = await api.post('/api/run', body)
  message.value = 'job ' + data.job_id
  await loadJobs()
}
async function loadJobs() {
  const { data } = await api.get('/api/jobs')
  jobs.value = data
}
const logJob = ref('')
const logText = ref('')
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
const runMetaText = ref('')
const benchLogText = ref('')
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
onMounted(loadJobs)
</script>
