<template>
  <div>
    <h2>Dry Run</h2>
    <div v-if="loading">Loading...</div>
    <div v-else>
      <h3>Status</h3>
      <div v-if="dryrun.active">Active: {{ dryrun.dryrun.strategy }} (started {{ dryrun.dryrun.started_at }})</div>
      <div v-else-if="dryrun.dryrun">Last: {{ dryrun.dryrun.strategy }} ({{ dryrun.dryrun.status }})</div>
      <div v-else>No dry run yet.</div>
      <h3>Log</h3>
      <button v-on:click="loadLog">Refresh log</button>
      <pre>{{ logText }}</pre>
      <h3>Start new</h3>
      <input v-model="strategy" placeholder="strategy name" />
      <input v-model="timerange" placeholder="20220101-20240101" />
      <input v-model="timeframe" placeholder="5m" />
      <button v-on:click="startDryrun">Start dry run</button>
      <button v-on:click="stopDryrun">Stop dry run</button>
      <h3>Gate</h3>
      <button v-on:click="openGate">Open gate</button>
    </div>
  </div>
</template>
<script setup lang='ts'>
import { ref, onMounted } from 'vue'
import { api } from '../api/client'
const loading = ref(true)
const dryrun = ref({ active: false, dryrun: null, all: [] })
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
  const { data } = await api.post('/api/dryrun', { strategy: strategy.value, timerange: timerange.value, timeframe: timeframe.value })
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
