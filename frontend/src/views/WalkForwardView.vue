<template>
  <div>
    <h2>WalkForward</h2>
    <div v-if="store.loading">Loading...</div>
    <div v-else>
      <input v-model="q" placeholder="filter" />
      <div>{{ filtered.length }} / {{ store.walkforward.length }} runs</div>
      <table>
        <thead><tr><th>Strategy</th><th>Run</th><th>Windows</th><th>Profitable</th><th>OOS Trades</th><th>OOS Profit</th><th>Avg Sortino</th><th>Avg PF</th><th>Loss</th><th>Detail</th></tr></thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.source" v-on:click="drill(r.source)">
            <td>{{ r.strategy }}</td>
            <td>{{ r.run_id }}</td>
            <td>{{ r.n_windows }}</td>
            <td :class="ratioClass(profitableRatio(r))">{{ r.profitable_windows }}/{{ r.n_windows }}</td>
            <td>{{ r.oos_trades }}</td>
            <td>{{ r.oos_profit_abs }}</td>
            <td>{{ r.avg_oos_sortino }}</td>
            <td>{{ r.avg_oos_profit_factor }}</td>
            <td>{{ r.loss_function }}</td>
            <td><button v-on:click.stop="drill(r.source)">Windows</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="detail">
        <h3>OOS per window {{ detail.r.strategy }}</h3>
        <VChart :option="comboOption" autoresize style="height:400px" />
        <table>
          <thead><tr><th>#</th><th>Test range</th><th>Trades</th><th>Profit</th><th>WinRate</th><th>Sortino</th><th>PF</th><th>DD</th></tr></thead>
          <tbody>
            <tr v-for="(w, i) in detail.wins" :key="i">
              <td>{{ i + 1 }}</td>
              <td>{{ w.test_range }}</td>
              <td>{{ w.oos_trades }}</td>
              <td>{{ w.oos_profit_abs }}</td>
              <td>{{ w.oos_winrate }}</td>
              <td>{{ w.oos_sortino }}</td>
              <td>{{ w.oos_pf }}</td>
              <td>{{ w.oos_dd }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
<script setup lang='ts'>
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import { ratioClass } from '../utils/pills'
const store = useDashboardStore()
const q = ref('')
const selected = ref('')
const detail = ref(null as any)
function profitableRatio(r: any) {
  if (!r.n_windows) return 0
  return r.profitable_windows / r.n_windows
}
const filtered = computed(() => {
  const ql = q.value.toLowerCase()
  return store.walkforward.filter((r: any) => {
    const reg = store.canonical.find((c: any) => c.strategy === r.strategy)
    if (reg && (reg.status || 'active') === 'retired') return false
    if (!ql) return true
    return (r.strategy || '').toLowerCase().includes(ql)
  }).sort((a: any, b: any) => (b.run_time || '').localeCompare(a.run_time || '')).slice(0, 80)
})
async function drill(source: string) {
  selected.value = source
  const local = store.walkforward.find((r: any) => r.source === source)
  if (local && local.windows_json) {
    try {
      const wins = JSON.parse(local.windows_json)
      if (wins && wins.length) { detail.value = { r: local, wins: wins }; return }
    } catch (e) {}
  }
  const { data } = await api.get('/api/walkforward', { params: { source: source } })
  const wrows = data.rows || []
  if (!wrows.length) { detail.value = null; return }
  detail.value = { r: wrows[0], wins: wrows[0].windows || [] }
}
const comboOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: ((detail.value && detail.value.wins) || []).map((w: any, i: number) => 'W' + (i + 1)) },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: ((detail.value && detail.value.wins) || []).map((w: any) => w.oos_profit_abs || 0) }, { type: 'line', data: ((detail.value && detail.value.wins) || []).map((w: any) => w.oos_profit_abs || 0) }]
}))
onMounted(() => { store.fetchAll() })
</script>
