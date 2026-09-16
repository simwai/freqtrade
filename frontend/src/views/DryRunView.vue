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
          <label>Strategy <input v-model="strategy" placeholder="strategy name" /></label>
          <label>Timerange <input v-model="timerange" placeholder="20220101-20240101" /></label>
          <label>Timeframe <input v-model="timeframe" placeholder="5m" /></label>
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
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

const loading = ref(true)
const dryrun = ref<any>({ active: false, dryrun: null, all: [] })
const logText = ref('')
const strategy = ref('')
const timerange = ref('20220101-20240101')
const timeframe = ref('5m')

async function loadStatus() {
  const { data } = await api.get('/api/dryrun')
  dryrun.value = data
  loading.value = false
}

async function loadLog() {
  logText.value = 'Loading...'
  const { data } = await api.get('/api/dryrun/log')
  logText.value = data || ''
}

async function startDryrun() {
  if (!strategy.value) return
  await api.post('/api/dryrun', { strategy: strategy.value, timerange: timerange.value, timeframe: timeframe.value })
  await loadStatus()
}

async function stopDryrun() {
  await api.post('/api/dryrun/stop', { strategy: strategy.value })
  await loadStatus()
}

async function openGate() {
  if (!strategy.value) return
  await api.post('/api/dryrun/gate', { strategy: strategy.value, timerange: timerange.value, timeframe: timeframe.value })
}

onMounted(loadStatus)
</script>