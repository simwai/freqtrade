<template>
  <div>
    <h2>Trades</h2>
    <div v-if="store.loading">Loading...</div>
    <table v-else>
      <thead><tr><th>Strategy</th><th>Source</th><th>Trades</th><th>File</th></tr></thead>
      <tbody>
        <tr v-for="r in store.trade_runs" :key="r.key">
          <td>{{ r.strategy }}</td>
          <td>{{ r.source }}</td>
          <td>{{ r.n_trades }}</td>
          <td><a :href="'/trades/' + r.key + '.json'">JSON</a></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<script setup lang='ts'>
import { onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
const store = useDashboardStore()
onMounted(() => { store.fetchAll() })
</script>
