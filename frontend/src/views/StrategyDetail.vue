<template>
  <section>
    <div class="section-head">
      <router-link to="/strategies" class="back-link">← Back to Strategies</router-link>
      <h2>{{ name }}</h2>
      <span :class="gradePill(strategy?.score?.grade)">{{ strategy?.score?.grade || '?' }}</span>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else-if="!strategy.strategy" class="card">Unknown strategy {{ name }}</div>
    <div v-else>
      <div class="card">
        <h3>Grades</h3>
        <table class="drawer-table">
          <tbody>
            <tr v-for="(g, k) in strategy.score?.grades" :key="k">
              <td>{{ k }}</td>
              <td>{{ g }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>Recent runs</h3>
        <ul class="runs-list">
          <li v-for="r in runs" :key="r.source">
            <span>{{ r.source }}</span>
            <span class="num" :class="profitClass(r.profit_total)">{{ fmtNum(r.profit_total) }}</span>
          </li>
        </ul>
      </div>

      <div class="card">
        <h3>Equity</h3>
        <VChart :option="equityOption" autoresize class="chart" style="height: 280px" />
      </div>

      <div class="card">
        <h3>Profit histogram</h3>
        <VChart :option="histOption" autoresize class="chart" style="height: 260px" />
      </div>

      <div class="card">
        <h3>Config</h3>
        <table class="drawer-table">
          <tbody>
            <tr v-for="row in configRows" :key="row.k">
              <td>{{ row.k }}</td>
              <td>{{ row.v }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>Code</h3>
        <div class="code-header">
          <button v-on:click="loadCode" class="btn-secondary">Load code</button>
        </div>
        <pre class="code-block">{{ codeText || 'Click Load code to fetch strategy source' }}</pre>
      </div>

      <div class="card">
        <h3>Trades {{ trades.length }}</h3>
        <div class="table-wrap">
          <table>
            <tbody>
              <tr v-for="t in trades.slice(0, 50)" :key="t.o + t.c + t.p">
                <td>{{ t.p }}</td>
                <td class="num">{{ fmtNum(t.pr) }}</td>
                <td class="num">{{ fmtNum(t.pa) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, TitleComponent, TooltipComponent, GridComponent])
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import type { CompactTrade } from '../utils/trades'

const route = useRoute()
const store = useDashboardStore()
const name = route.params.name as string
const codeText = ref('')
const trades = ref([] as CompactTrade[])

const strategy = computed(() => store.canonical.find((s: any) => s.strategy === name) || { strategy: name, score: { grade: '?', grades: {} } })
const runs = computed(() => store.backtests.filter((b: any) => b.strategy === name).slice(0, 10))

const configRows = computed(() => {
  const raw = (strategy.value as any).config_json
  if (!raw) return []
  let cfg: any = {}
  try { cfg = JSON.parse(raw) } catch (e) { return [] }
  const keys = ['stake_currency', 'stake_amount', 'max_open_trades', 'timeframe', 'trading_mode', 'stoploss', 'exchange', 'timeframe']
  return keys.filter((k) => cfg[k] !== undefined).map((k) => ({ k: k, v: typeof cfg[k] === 'object' ? JSON.stringify(cfg[k]) : String(cfg[k]) }))
})

const equityOption = computed((): ECOption => {
  const chrono = [...trades.value].filter((t) => t && t.c).sort((a, b) => String(a.c).localeCompare(String(b.c)))
  let cum = 0
  const points = chrono.map((t) => { cum += (t.pa || 0); return [t.c, Math.round(cum * 100) / 100] })
  return {
    grid: { left: 70, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', axisLabel: { color: '#a89fc4' } },
    yAxis: { type: 'value', axisLabel: { color: '#a89fc4' } },
    series: [{ name: 'Cumulative profit', type: 'line', showSymbol: false, data: points, lineStyle: { color: '#a78bfa' } }]
  }
})

const histOption = computed((): ECOption => {
  const profits = trades.value.map((t) => t.pr).filter((v) => v !== null && v !== undefined)
  if (!profits.length) return { series: [] }
  const min = Math.min(...profits)
  const max = Math.max(...profits)
  const bins = 30
  const width = (max - min) || 1
  const counts = new Array(bins).fill(0)
  profits.forEach((v) => { let i = Math.floor((v - min) / width * bins); if (i === bins) i = bins - 1; counts[i]++ })
  return {
    grid: { left: 50, right: 16, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: counts.map((_, i) => 'b' + (i + 1)) },
    yAxis: { type: 'value' },
    series: [{ name: 'Trades', type: 'bar', data: counts, itemStyle: { color: '#a78bfa' } }]
  }
})

async function loadCode() {
  const h = (strategy.value as any).code_hash
  if (!h) { codeText.value = 'no snapshot hash'; return }
  const { data } = await api.get('/api/strategy/file', { params: { hash: h } })
  codeText.value = typeof data === 'string' ? data : JSON.stringify(data)
}

function gradePill(g: string) {
  if (!g || g === '—') return 'pill gna'
  if (g === 'A') return 'pill gA'
  if (g === 'B') return 'pill gB'
  if (g === 'C') return 'pill gC'
  if (g === 'D') return 'pill gD'
  if (g === 'F') return 'pill gF'
  return 'pill gna'
}

function profitClass(v: number) { if (!v) return ''; return v > 0 ? 'good' : v < 0 ? 'bad' : '' }
function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—' }

onMounted(async () => {
  await store.fetchAll()
  const first = store.trade_runs.find((r: any) => r.strategy === name)
  if (first) {
    try {
      const { data } = await api.get('/trades/' + first.key + '.json')
      trades.value = data.trades || []
    } catch (e) { trades.value = [] }
  }
})
</script>

<style scoped>
.back-link { color: var(--text-dim); font-size: 13px; text-decoration: none; }
.back-link:hover { color: var(--lavender); }
.drawer-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.drawer-table td { padding: 6px 8px; border-top: 1px solid var(--border); }
.runs-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.runs-list li { display: flex; justify-content: space-between; padding: 6px 8px; background: var(--bg-soft); border-radius: 8px; font-size: 12px; }
.code-block { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; overflow: auto; max-height: 300px; font-size: 11px; white-space: pre-wrap; }
</style>
