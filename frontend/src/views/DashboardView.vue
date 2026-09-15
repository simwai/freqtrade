<template>
  <div>
    <h2>Dashboard</h2>
    <div v-if="store.loading">Loading...</div>
    <div v-else-if="store.error">{{ store.error }}</div>
    <div v-else>
      <GradeTuner v-model:min-profit="minProfit" v-model:min-trades="minTrades" />
      <table v-sortable>
        <thead><tr><th>Strategy</th><th>Grade</th><th>Profit</th><th>Trades</th><th>WinRate</th></tr></thead>
        <tbody>
          <tr v-for="s in filtered" :key="s.strategy" v-on:click="openStrategy(s.strategy)">
            <td>{{ s.strategy }}</td>
            <td>{{ s.score.grade }}</td>
            <td>{{ s.profit_total }}</td>
            <td>{{ s.total_trades }}</td>
            <td>{{ s.winrate }}</td>
          </tr>
        </tbody>
      </table>
      <VChart :option="profitOption" autoresize  style="height:400px" />
      <select v-model="metric2">
        <option value="profit_total">profit</option>
        <option value="total_trades">trades</option>
        <option value="winrate">winrate</option>
      </select>
      <VChart :option="metric2Option" autoresize style="height:400px" />
      <h3>Top 5</h3>
      <table v-sortable><tbody><tr v-for="s in topRows" :key="s.strategy"><td>{{ s.strategy }}</td><td>{{ s.profit_total }}</td></tr></tbody></table>
      <h3>Bottom 5</h3>
      <table v-sortable><tbody><tr v-for="s in flopRows" :key="s.strategy"><td>{{ s.strategy }}</td><td>{{ s.profit_total }}</td></tr></tbody></table>
      <StrategyDrawer v-if="selected" :name="selected" v-on:close="selected = ''" />
    </div>
  </div>
</template>
<script setup lang='ts'>
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { useDashboardStore } from '../stores/dashboard'
import GradeTuner from '../components/GradeTuner.vue'
import StrategyDrawer from '../components/StrategyDrawer.vue'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
const store = useDashboardStore()
const minProfit = ref(0)
const minTrades = ref(0)
const selected = ref('')
const filtered = computed(() => store.canonical.filter((s: any) => (s.profit_total || 0) >= minProfit.value).filter((s: any) => (s.total_trades || 0) >= minTrades.value))
const profitOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: filtered.value.map((s: any) => s.strategy) },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: filtered.value.map((s: any) => s.profit_total || 0) }]
}))
const metric2 = ref('total_trades')
const metric2Option = computed((): ECOption => ({
  xAxis: { type: 'category', data: filtered.value.map((s: any) => s.strategy) },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: filtered.value.map((s: any) => s[metric2.value] || 0) }]
}))
const topRows = computed(() => [...store.canonical].sort((a: any, b: any) => (b.profit_total || 0) - (a.profit_total || 0)).slice(0, 5))
const flopRows = computed(() => [...store.canonical].sort((a: any, b: any) => (a.profit_total || 0) - (b.profit_total || 0)).slice(0, 5))
function openStrategy(name: string) {
  selected.value = name
}
onMounted(() => { store.fetchAll() })
</script>
