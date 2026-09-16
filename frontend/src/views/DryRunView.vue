<template>
  <section>
    <div class="section-head">
      <h2>Dry Run</h2>
    </div>

    <div v-if="loading" class="card">Loading...</div>
    <div v-else>
      <div class="card">
        <h3>Status</h3>
        <div v-if="dryrun.active" class="status active">Active: {{ dryrun.dryrun.strategy }} (started {{ dryrun.dryrun.started_at }})</div>
        <div v-else-if="dryrun.dryrun" class="status experimental">Last: {{ dryrun.dryrun.strategy }} ({{ dryrun.dryrun.status }})</div>
        <div v-else class="status">No dry run yet.</div>
      </div>

      <div class="card">
        <h3>Log</h3>
        <button class="btn-secondary" v-on:click="loadLog">Refresh log</button>
        <pre class="code-block">{{ logText }}</pre>
      </div>

      <div class="card">
        <h3>Start new</h3>
        <div class="form-row">
          <label>Strategy
            <select v-model="strategy">
              <option value="">(choose…)</option>
              <option v-for="s in strategyOptions" :key="s.name" :value="s.name">{{ s.name }}</option>
            </select>
          </label>
          <label>Timerange <input v-model="timerange" placeholder="20220101-20240101" /></label>
          <label>Timeframe <input v-model="timeframe" placeholder="5m" /></label>
          <label>Config
            <select v-model="dryrunConfig">
              <option value="">auto (optional)</option>
              <option v-for="c in configOptions" :key="c.path" :value="c.path">{{ c.name }}</option>
            </select>
          </label>
          <button class="btn-primary" v-on:click="startDryrun">Start dry run</button>
          <button class="btn-secondary" v-on:click="stopDryrun">Stop dry run</button>
        </div>
      </div>

      <div class="card">
        <h3>Gate</h3>
        <button class="btn-primary" v-on:click="openGate">Open gate</button>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'

const loading = ref(true)
const dryrun = ref<any>({ active: false, dryrun: null, all: [] })
const logText = ref('')
const strategy = ref('')
const timerange = ref('20220101-20240101')
const timeframe = ref('5m')
const dryrunConfig = ref('')
const strategyOptions = ref([] as any[])
const configOptions = ref([] as any[])
let pollTimer: any = null

async function loadStatus() {
  const { data } = await api.get('/api/dryrun')
  dryrun.value = data
  loading.value = false
  armPolling()
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
  const { data } = await api.get('/api/dryrun/log')
  logText.value = data || ''
}

async function startDryrun() {
  if (!strategy.value) return
  const body: any = { strategy: strategy.value, timerange: timerange.value, timeframe: timeframe.value }
  if (dryrunConfig.value) body.config = dryrunConfig.value
  await api.post('/api/dryrun', body)
  await loadStatus()
}

async function stopDryrun() {
  await api.post('/api/dryrun/stop', { strategy: strategy.value })
  await loadStatus()
}

async function openGate() {
  if (!strategy.value) return
  const body: any = { strategy: strategy.value, timerange: timerange.value, timeframe: timeframe.value }
  if (dryrunConfig.value) body.config = dryrunConfig.value
  await api.post('/api/dryrun/gate', body)
}

onMounted(() => { loadStatus(); loadDropdowns() })
onUnmounted(() => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } })
</script>