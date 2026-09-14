<template>
  <div>
    <h2>Benchmark</h2>
    <div v-if="store.loading">Loading...</div>
    <div v-else>
      <table>
        <thead><tr><th>Strategy</th><th>Source</th><th>Profit</th><th>Trades</th><th>Sortino</th></tr></thead>
        <tbody>
          <tr v-for="b in store.benchmarks" :key="b.strategy + b.source">
            <td>{{ b.strategy }}</td>
            <td>{{ b.source }}</td>
            <td>{{ b.profit_total }}</td>
            <td>{{ b.total_trades }}</td>
            <td>{{ b.sortino }}</td>
          </tr>
        </tbody>
      </table>
      <VChart :option="benchOption" autoresize />
    </div>
  </div>
</template>
<script setup lang='ts'>
import { computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { useDashboardStore } from '../stores/dashboard'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
const store = useDashboardStore()
const benchOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: store.benchmarks.map((b: any) => b.strategy) },
  yAxis: { type: 'value' },
  series: [{ type: 'line', data: store.benchmarks.map((b: any) => b.profit_total || 0) }]
}))
onMounted(() => { store.fetchAll() })
</script>
