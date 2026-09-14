<template>
  <div>
    <h2>Hyperopt</h2>
    <div v-if="store.loading">Loading...</div>
    <div v-else>
      <input v-model="q" placeholder="filter" />
      <input v-model.number="minTrades" type="number" />
      <div>{{ filtered.length }} / {{ store.hyperopt.length }} runs</div>
      <table>
        <thead><tr><th>Strategy</th><th>Epochs</th><th>Best Loss</th><th>Best Profit</th><th>Best Sortino</th><th>Best PF</th><th>Trades</th><th>Loss</th><th>Run</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.source" v-on:click="drill(r.source)">
            <td>{{ r.strategy }}</td>
            <td>{{ r.epochs }}</td>
            <td>{{ r.best_loss }}</td>
            <td>{{ r.best_profit_total }}</td>
            <td>{{ r.best_sortino }}</td>
            <td>{{ r.best_profit_factor }}</td>
            <td>{{ r.best_trades }}</td>
            <td>{{ r.loss_function }}</td>
            <td>{{ r.run_time }}</td>
            <td><button v-on:click.stop="drill(r.source)">Drill</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="detail">
        <h3>Epochs {{ detail.count }}</h3>
        <div v-for="(v, k) in detail.corr" :key="k" :class="corrClass(v)">{{ k }}: {{ v }}</div>
        <pre>{{ detail.paramsText }}</pre>
        <table>
          <thead><tr><th>Epoch</th><th>Loss</th><th>Trades</th><th>Profit</th><th>Sortino</th><th>Calmar</th><th>PF</th><th>SQN</th><th>DD</th></tr></thead>
          <tbody>
            <tr v-for="r in detail.records" :key="r.epoch">
              <td>{{ r.epoch }}</td>
              <td>{{ r.loss }}</td>
              <td>{{ r.trades }}</td>
              <td>{{ r.profit_total }}</td>
              <td>{{ r.sortino }}</td>
              <td>{{ r.calmar }}</td>
              <td>{{ r.profit_factor }}</td>
              <td>{{ r.sqn }}</td>
              <td>{{ r.max_drawdown }}</td>
            </tr>
          </tbody>
        </table>
        <VChart :option="scatterOption" autoresize style="height:400px" />
      </div>
    </div>
  </div>
</template>
<script setup lang='ts'>
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import type { ECScatterOption } from '../utils/echarts'
import { corrClass } from '../utils/pills'
import '../utils/echarts'
const store = useDashboardStore()
const q = ref('')
const minTrades = ref(0)
const selected = ref('')
const detail = ref(null as any)
const files = ref([] as any[])
const filtered = computed(() => {
  const ql = q.value.toLowerCase()
  return store.hyperopt.filter((r: any) => {
    const reg = store.canonical.find((c: any) => c.strategy === r.strategy)
    if (reg && (reg.status || 'active') === 'retired') return false
    if ((r.best_trades || 0) < minTrades.value) return false
    if (!ql) return true
    return (r.strategy || '').toLowerCase().includes(ql)
  }).sort((a: any, b: any) => (b.epochs || 0) - (a.epochs || 0)).slice(0, 60)
})
async function drill(source: string) {
  selected.value = source
  const { data } = await api.get('/api/hyperopt', { params: { source, limit: 200 } })
  if (data.error) { detail.value = null; return }
  const hoRow = store.hyperopt.find((x: any) => x.source === data.source)
  let paramsText = ''
  if (hoRow) {
    if (hoRow.best_params) {
      try {
        paramsText = JSON.stringify(JSON.parse(hoRow.best_params), null, 2)
      } catch (e) {}
    }
  }
  detail.value = Object.assign({}, data, { paramsText: paramsText })
}
const scatterOption = computed((): ECScatterOption => ({
  xAxis: { type: 'value', name: 'loss' },
  yAxis: { type: 'value', name: 'sortino' },
  series: [{ type: 'scatter', data: ((detail.value && detail.value.records) || []).map((r: any) => [r.loss, r.sortino]) }]
}))
onMounted(async () => {
  await store.fetchAll()
  const { data } = await api.get('/api/hyperopt/files')
  files.value = data
})
</script>
