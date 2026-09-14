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
    <div>{{ message }}</div>
    <h3>Jobs</h3>
    <button v-on:click="loadJobs">Refresh jobs</button>
    <table>
      <thead><tr><th>ID</th><th>Name</th><th>Status</th></tr></thead>
      <tbody>
        <tr v-for="(j, id) in jobs" :key="id">
          <td>{{ id }}</td>
          <td>{{ j.name }}</td>
          <td>{{ j.status }}</td>
        </tr>
      </tbody>
    </table>
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
onMounted(loadJobs)
</script>
