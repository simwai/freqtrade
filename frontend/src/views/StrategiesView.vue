<template>
  <div>
    <h2>Strategies</h2>
    <div v-if="store.loading">Loading...</div>
    <div v-else>
      <table>
        <thead><tr><th>Name</th><th>Status</th><th>Grade</th><th>Backtests</th><th>Trades</th></tr></thead>
        <tbody>
          <tr v-for="s in rows" :key="s.strategy" v-on:click="openStrategy(s.strategy)">
            <td>{{ s.strategy }}</td>
            <td>{{ s.status }}</td>
            <td>{{ s.score.grade }}</td>
            <td>{{ s.n_backtests }}</td>
            <td>{{ s.n_trades }}</td>
          </tr>
        </tbody>
      </table>
      <StrategyDrawer v-if="selected" :name="selected" v-on:close="selected = ''" />
    </div>
  </div>
</template>
<script setup lang='ts'>
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import StrategyDrawer from '../components/StrategyDrawer.vue'
const store = useDashboardStore()
const selected = ref('')
const rows = computed(() => store.canonical.map((c: any) => {
  const reg = store.strategies.find((r: any) => r.name === c.strategy)
  let nb = 0
  let nt = 0
  if (reg) {
    nb = reg.n_backtests || 0
    nt = reg.n_trades || 0
  }
  return { strategy: c.strategy, status: c.status || 'active', score: c.score, n_backtests: nb, n_trades: nt }
}))
function openStrategy(name: string) {
  selected.value = name
}
onMounted(() => { store.fetchAll() })
</script>
