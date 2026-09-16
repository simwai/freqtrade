<template>
  <section>
    <div class="section-head">
      <h2>Dashboard</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else-if="store.error" class="card" style="color: var(--bad);">{{ store.error }}</div>
    <div v-else>
      <GradeTuner v-model:min-profit="minProfit" v-model:min-trades="minTrades" />

      <div class="table-wrap table-stack">
        <div class="thead-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" v-on:click="sortBy('strategy')">Strategy <span class="arrow" v-if="sortKey==='strategy'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('score.grade')">Grade <span class="arrow" v-if="sortKey==='score.grade'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('profit_total')">Profit% <span class="arrow" v-if="sortKey==='profit_total'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('sortino')">Sortino <span class="arrow" v-if="sortKey==='sortino'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('calmar')">Calmar <span class="arrow" v-if="sortKey==='calmar'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('profit_factor')">PF <span class="arrow" v-if="sortKey==='profit_factor'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('max_drawdown_account')">MaxDD <span class="arrow" v-if="sortKey==='max_drawdown_account'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('propPass')">Prop <span class="arrow" v-if="sortKey==='propPass'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('winrate')">Win% <span class="arrow" v-if="sortKey==='winrate'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('total_trades')">Trades <span class="arrow" v-if="sortKey==='total_trades'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('basis')">Basis <span class="arrow" v-if="sortKey==='basis'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('timerange')">Range <span class="arrow" v-if="sortKey==='timerange'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('run_time')">Run <span class="arrow" v-if="sortKey==='run_time'">{{ sortAsc ? '▲' : '▼' }}</span></th>
              </tr>
            </thead>
          </table>
        </div>
        <div class="table-wrap" ref="tableWrap">
          <table>
            <tbody>
              <tr v-for="s in sortedFiltered" :key="s.strategy" v-on:click="openStrategy(s.strategy)" v-on:keydown.enter="openStrategy(s.strategy)" tabindex="0" role="button" :aria-label="'Open ' + s.strategy">
                <td>{{ s.strategy }} <span :class="statusClass(s.status)">{{ s.status }}</span></td>
                <td><span :class="gradePill(s.score.grade)">{{ s.score.grade }}</span></td>
                <td class="num" :class="profitClass(s.profit_total)">{{ fmtProfitPct(s.profit_total) }}</td>
                <td class="num">{{ fmt3(s.sortino) }}</td>
                <td class="num">{{ fmt3(s.calmar) }}</td>
                <td class="num">{{ fmt3(s.profit_factor) }}</td>
                <td class="num">{{ fmtPct(s.max_drawdown_account) }}</td>
                <td class="num"><span :class="propClass(s)" :title="propTitle(s)">{{ propText(s) }}</span></td>
                <td class="num">{{ fmtPct(s.winrate) }}</td>
                <td class="num">{{ s.total_trades }}</td>
                <td :title="basisTooltip(s)">{{ basisLabel(s) }}</td>
                <td style="font-size:12px;color:var(--text-dim)">{{ fmtRange(s.timerange) }}</td>
                <td>{{ (s.run_time || '').slice(0, 10) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="charts">
        <div class="chart-box">
          <VChart :option="profitOption" autoresize class="chart" style="height: 300px" />
        </div>
        <div class="chart-box">
          <select v-model="metric2" class="metric-select">
            <option value="profit_total">profit</option>
            <option value="total_trades">trades</option>
            <option value="winrate">winrate</option>
          </select>
          <VChart :option="metric2Option" autoresize class="chart" style="height: 300px" />
        </div>
      </div>

      <div class="stats-row">
        <div class="card">
          <h3>What to improve next</h3>
          <div v-for="s in improveNext" :key="s.strategy" class="metric-card" v-on:click="openStrategy(s.strategy)">
            <div class="mk">{{ s.strategy }} — {{ s.score.grade }}</div>
            <div class="mv">{{ s.focus || '—' }}</div>
          </div>
        </div>
        <div class="card">
          <h3>Top 5</h3>
          <table class="mini-table">
            <tbody>
              <tr v-for="s in topRows" :key="s.strategy" v-on:click="openStrategy(s.strategy)" v-on:keydown.enter="openStrategy(s.strategy)" tabindex="0" role="button" :aria-label="'Open ' + s.strategy">
                <td>{{ s.strategy }}</td>
                <td class="num">{{ fmtNum(s.profit_total) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="card">
          <h3>Bottom 5</h3>
          <table class="mini-table">
            <tbody>
              <tr v-for="s in flopRows" :key="s.strategy" v-on:click="openStrategy(s.strategy)" v-on:keydown.enter="openStrategy(s.strategy)" tabindex="0" role="button" :aria-label="'Open ' + s.strategy">
                <td>{{ s.strategy }}</td>
                <td class="num">{{ fmtNum(s.profit_total) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <StrategyDrawer v-if="selected" :name="selected" v-on:close="selected = ''" />
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])
import { useDashboardStore } from '../stores/dashboard'
import GradeTuner from '../components/GradeTuner.vue'
import StrategyDrawer from '../components/StrategyDrawer.vue'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'

const store = useDashboardStore()
const minProfit = ref(0)
const minTrades = ref(0)
const selected = ref('')
const metric2 = ref('total_trades')
const sortKey = ref('profit_total')
const sortAsc = ref(false)
const tableWrap = ref<HTMLElement | null>(null)

const filtered = computed(() => store.canonical.filter((s: any) => (s.profit_total || 0) >= minProfit.value).filter((s: any) => (s.total_trades || 0) >= minTrades.value))

const sortedFiltered = computed(() => {
  const arr = [...filtered.value]
  arr.sort((a: any, b: any) => {
    let av = sortKey.value === 'propPass' ? propPassCount(a) : sortKey.value.split('.').reduce((o: any, k: string) => o?.[k], a)
    let bv = sortKey.value === 'propPass' ? propPassCount(b) : sortKey.value.split('.').reduce((o: any, k: string) => o?.[k], b)
    if (av === undefined && bv === undefined) return 0
    if (av === '' || av === undefined || av === null) return sortAsc.value ? 1 : -1
    if (bv === '' || bv === undefined || bv === null) return sortAsc.value ? -1 : 1
    const an = Number(av), bn = Number(bv)
    const useNum = !isNaN(an) && !isNaN(bn)
    const r = useNum ? an - bn : String(av).localeCompare(String(bv))
    return sortAsc.value ? r : -r
  })
  return arr
})

const profitOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: filtered.value.map((s: any) => s.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'bar', data: filtered.value.map((s: any) => (s.profit_total || 0) * 100), itemStyle: { color: '#a78bfa' } }]
}))

const metric2Option = computed((): ECOption => ({
  xAxis: { type: 'category', data: filtered.value.map((s: any) => s.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'bar', data: filtered.value.map((s: any) => s[metric2.value] || 0), itemStyle: { color: '#c4b5fd' } }]
}))

const topRows = computed(() => [...store.canonical].sort((a: any, b: any) => (b.profit_total || 0) - (a.profit_total || 0)).slice(0, 5))
const flopRows = computed(() => [...store.canonical].sort((a: any, b: any) => (a.profit_total || 0) - (b.profit_total || 0)).slice(0, 5))

const improveNext = computed(() => {
  const rows = filtered.value.filter((r: any) => r.basis !== 'registry' && r.score?.grade !== 'A').slice(0, 6)
  return rows.map((r: any) => {
    const grades = r.score?.grades || {}
    const labels = (store.scorecard || {}) as any
    const fails = Object.entries(grades).filter(([_kf, g]) => g === 'fail').map(([k]) => labels[k]?.label || k).join(', ')
    const warns = Object.entries(grades).filter(([_kw, g]) => g === 'warn').map(([k]) => labels[k]?.label || k).join(', ')
    let focus = fails ? fails : ''
    if (warns) focus += (focus ? ' + ' : '') + warns
    return { strategy: r.strategy, score: r.score, focus: focus }
  })
})

function sortBy(key: string) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = true }
}
function openStrategy(name: string) { selected.value = name }
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
function fmt3(v: number) { return v === null || v === undefined ? '—' : Number(v).toFixed(3) }
function fmtProfitPct(v: number) { return v === null || v === undefined ? '—' : ((v || 0) * 100).toFixed(1) + '%' }
function fmtPct(v: number) { return v ? (v * 100).toFixed(1) + '%' : '—' }
function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'active') return 'status active'
  if (sl === 'experimental') return 'status experimental'
  if (sl === 'retired') return 'status retired'
  return 'status'
}
function fmtRange(tr: string) { return tr || '' }
function basisLabel(r: any) {
  if (r.basis === 'registry') return 'no runs yet'
  return r.basis === 'benchmark' ? 'benchmark (fallback)' : 'last backtest'
}
function basisTooltip(r: any) {
  if (r.basis === 'registry') return 'registered in the strategies table; no backtest or benchmark ingested yet'
  return 'metrics from ' + (r.basis === 'benchmark' ? 'benchmark' : 'backtest') + ' run ' + (r.source || '?') + ' · ' + (r.run_time || '?')
}
function propPassCount(r: any) {
  const pf = r.prop_firms
  if (!pf) return -1
  const vals = Object.values(pf) as any[]
  if (vals.every((p: any) => p.verdict === 'na')) return -1
  return vals.filter((p: any) => p.verdict === 'pass').length
}
function propText(r: any) {
  const pf = r.prop_firms
  if (!pf) return '—'
  const keys = Object.keys(pf)
  if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return '—'
  return keys.filter((k) => (pf as any)[k].verdict === 'pass').length + '/' + keys.length
}
function propTitle(r: any) {
  const pf = r.prop_firms
  if (!pf) return ''
  const keys = Object.keys(pf)
  const failed = keys.filter((k) => (pf as any)[k].verdict === 'fail').map((k) => store.propSpec[k]?.label || k)
  return failed.length ? 'failed: ' + failed.join(', ') : 'all programs pass'
}
function propClass(r: any) {
  const pf = r.prop_firms
  if (!pf) return 'pill gna'
  const keys = Object.keys(pf)
  if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return 'pill gna'
  const passed = keys.filter((k) => (pf as any)[k].verdict === 'pass').length
  return passed === keys.length ? 'pill gA' : passed > 0 ? 'pill gC' : 'pill gF'
}

onMounted(async () => {
  await store.fetchAll()
  await nextTick()
  if (tableWrap.value) {
    tableWrap.value.addEventListener('scroll', () => {
      const tw = tableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
})
</script>

<style scoped>
.metric-select {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 12px;
  margin-bottom: 8px;
}
.stats-row { display: flex; gap: 14px; flex-wrap: wrap; }
.mini-table { width: 100%; font-size: 12px; }
.mini-table td { padding: 6px 8px; border-top: 1px solid var(--border); }
.mini-table td.num { text-align: right; }
.mini-table tbody tr:hover { background: var(--card-hover); cursor: pointer; }
.mini-table tbody tr:hover td { color: var(--accent); }
</style>