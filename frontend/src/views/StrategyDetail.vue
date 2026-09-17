<template>
  <section>
    <div class="section-head">
      <router-link to="/strategies" class="back-link">← Back to Strategies</router-link>
      <h2>{{ name }}</h2>
      <span :class="gradePill(strategy?.score?.grade)">{{ strategy?.score?.grade || '?' }}</span>
      <span :class="statusClass(strategy.status)">{{ strategy.status }}</span>
      <span class="basis-badge" :title="basisTooltip(strategy)">grade basis: {{ basisLabel(strategy) }} · {{ (strategy.run_time || '').slice(0, 16) }}</span>
      <span :class="codeBadgeClass()" :title="codeBadgeTitle()">{{ codeBadgeText() }}</span>
    </div>
    <div v-if="strategy.notes || strategy.score" class="hint">{{ strategy.notes }}{{ strategy.notes ? ' · ' : '' }}{{ passWarnFail() }}</div>

    <div v-if="store.loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading strategy...</span>
      </div>
    </div>
    <div v-else-if="store.error" class="card" style="color: var(--bad);">
      <div class="flex items-center gap-3">
        <UIcon name="i-lucide-alert-circle" class="text-error" size="20" />
        <div>
          <p class="font-medium">{{ store.error }}</p>
          <UButton size="sm" variant="outline" @click="store.fetchAll(true)">Retry</UButton>
        </div>
      </div>
    </div>
    <div v-else-if="!strategy.strategy" class="card">Unknown strategy {{ name }}</div>
    <div v-else>
      <div class="card">
        <h3>Metrics</h3>
        <div class="metric-grid">
          <div v-for="m in metricCards" :key="m.k" class="metric-card">
            <span class="mk">{{ m.k }}</span><span class="mv" :class="m.c">{{ m.v }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>Scorecard</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col" class="num">Value</th>
                <th scope="col">Status</th>
                <th scope="col" class="num" v-if="benchEngaged">Benchmark</th>
                <th scope="col" v-if="benchEngaged">Bench status</th>
                <th scope="col" class="num">Pass ≥</th>
                <th scope="col" class="num">Warn ≥</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in scorecardRows" :key="row.k">
                <td>{{ row.label }}</td>
                <td class="num">{{ row.value }}</td>
                <td><span :class="'pill g' + row.g">{{ row.g }}</span></td>
                <td class="num" v-if="benchEngaged">{{ row.bench }}</td>
                <td v-if="benchEngaged"><span :class="'pill g' + row.bg">{{ row.bg }}</span></td>
                <td class="num">{{ row.pass }}</td>
                <td class="num">{{ row.warn }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h3>Prop firms</h3>
        <div v-if="propRows.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Program</th>
                <th scope="col" class="num" v-for="h in propChecksHead" :key="h">{{ h }}</th>
                <th scope="col" class="num">Verdict</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in propRows" :key="row.k" :title="'daily-DD basis: ' + row.basis">
                <td><b>{{ row.label }}</b> <span class="hint">{{ row.k }}</span></td>
                <td class="num" v-for="(c, i) in row.checks" :key="i"><span :class="'pill g' + checkPill(c.status)">{{ c.text }}</span></td>
                <td class="num"><span :class="'pill g' + row.verdict">{{ row.verdict }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="hint">No prop-firm evaluation (missing trades or starting balance).</p>
      </div>

      <div class="card">
        <h3>Diagnostics</h3>
        <div class="metric-grid">
          <div v-for="m in diagnostics" :key="m.k" class="metric-card">
            <span class="mk">{{ m.k }}</span><span class="mv" :class="m.c">{{ m.v }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>Recommendations</h3>
        <p v-if="!recommendations.length" class="hint">No recommendations — well balanced.</p>
        <div v-for="(r, i) in recommendations" :key="i" class="rec-row">
          <span :class="'pill g' + recClass(r.level)">{{ r.level }}</span>
          <div><b>{{ r.title }}</b><div class="hint">{{ r.detail }}</div></div>
        </div>
      </div>

      <div class="card">
        <div class="section-head">
          <h3>All runs</h3>
          <div class="controls">
            <UInput v-model="runsFilter" placeholder="Filter runs..." size="sm" class="filter-input" />
            <ColumnToggle :columns="runsColumns" :visibility="columnVisibility" @update:visibility="columnVisibility = $event" />
          </div>
        </div>
        <UTable
          :data="filteredRuns"
          :columns="runsColumns"
          :loading="false"
          :sticky="true"
          :sorting="runsSorting"
          @update:sorting="runsSorting = $event"
          :column-visibility="columnVisibility"
          @update:column-visibility="columnVisibility = $event"
          class="w-full"
          empty="No runs for this strategy yet."
        >
          <template #cell-grade="{ row }">
            <span class="num"><span :class="gradePill((row.original as any).score?.grade)">{{ (row.original as any).score?.grade }}</span></span>
          </template>
          <template #cell-profit_total="{ row }">
            <span class="num">{{ fmtPct1(((row.original as any).profit_total || 0) * 100) }}</span>
          </template>
          <template #cell-profit_factor="{ row }">
            <span class="num">{{ pfFmt((row.original as any).profit_factor) }}</span>
          </template>
          <template #cell-sortino="{ row }">
            <span class="num">{{ fmt((row.original as any).sortino) }}</span>
          </template>
          <template #cell-max_drawdown_account="{ row }">
            <span class="num">{{ fmtPct((row.original as any).max_drawdown_account) }}</span>
          </template>
          <template #cell-timerange="{ row }">
            <span style="font-size:12px;color:var(--text-dim)" :title="(row.original as any).timerange || ''">{{ fmtRange((row.original as any).timerange) }}</span>
          </template>
          <template #cell-source="{ row }">
            <span :title="(row.original as any).source || ''">{{ ((row.original as any).source || '').slice(-28) }}</span>
          </template>
          <template #cell-actions="{ row }">
            <UButton size="xs" variant="ghost" @click="openRun('backtest', (row.original as any).source)">Config &amp; code</UButton>
          </template>
        </UTable>
      </div>

      <div class="card">
        <h3>Benchmark runs</h3>
        <p v-if="!benches.length" class="hint">No benchmark runs.</p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Run</th><th scope="col" class="num">Grade</th><th scope="col" class="num">Profit%</th><th scope="col" class="num">Sortino</th><th scope="col" class="num">PF</th><th scope="col">Range</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in benches" :key="r.source">
                <td>{{ (r.run_time || '').slice(0, 10) }}</td>
                <td class="num">{{ r.score?.grade }}</td>
                <td class="num">{{ fmtPct1((r.profit_total || 0) * 100) }}</td>
                <td class="num">{{ fmt(r.sortino) }}</td>
                <td class="num">{{ pfFmt(r.profit_factor) }}</td>
                <td :title="r.timerange || ''">{{ fmtRange(r.timerange) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h3>Hyperopt runs</h3>
        <p v-if="!hos.length" class="hint">No hyperopt runs.</p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Run</th><th scope="col" class="num">Epochs</th><th scope="col" class="num">Best loss</th><th scope="col" class="num">Best profit</th><th scope="col" class="num">Best sortino</th><th scope="col">Range</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in hos.slice(0, 8)" :key="r.source">
                <td>{{ (r.run_time || '').slice(0, 10) }}</td>
                <td class="num">{{ fmt0(r.epochs) }}</td>
                <td class="num">{{ fmt(r.best_loss, 4) }}</td>
                <td class="num">{{ fmtPct1((r.best_profit_total || 0) * 100) }}</td>
                <td class="num">{{ fmt(r.best_sortino) }}</td>
                <td :title="r.timerange || ''">{{ fmtRange(r.timerange) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h3>Walk-forward runs</h3>
        <p v-if="!wfs.length" class="hint">No walk-forward runs.</p>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Run</th><th scope="col" class="num">Windows</th><th scope="col" class="num">Profitable</th><th scope="col" class="num">OOS profit</th><th scope="col" class="num">Avg sortino</th><th scope="col">Range</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in wfs" :key="r.source">
                <td>{{ (r.run_id || '').slice(0, 16) }}</td>
                <td class="num">{{ fmt0(r.n_windows) }}</td>
                <td class="num">{{ r.profitable_windows }}/{{ r.n_windows }}</td>
                <td class="num">{{ fmt(r.oos_profit_abs) }}</td>
                <td class="num">{{ fmt(r.avg_oos_sortino) }}</td>
                <td :title="r.timerange || ''">{{ fmtRange(r.timerange) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
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
        <h3>Equity</h3>
        <VChart :option="equityOption" autoresize class="chart" style="height: 280px" />
      </div>

      <div class="card">
        <h3>Profit histogram</h3>
        <VChart :option="histOption" autoresize class="chart" style="height: 260px" />
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

      <StrategyDrawer v-if="drawerOpen" :name="name" :run-kind="drawerKind" :run-source="drawerSource" v-on:close="drawerOpen = false" />
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
import StrategyDrawer from '../components/StrategyDrawer.vue'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import { useUrlState } from '../composables/useUrlState'
import type { CompactTrade } from '../utils/trades'

const route = useRoute()
const store = useDashboardStore()
const name = route.params.name as string
const codeText = ref('')
const trades = ref([] as CompactTrade[])
const drawerOpen = ref(false)
const drawerKind = ref('')
const drawerSource = ref('')

function openRun(kind: string, source: string) {
  drawerKind.value = kind
  drawerSource.value = source
  drawerOpen.value = true
}

// Auto-open drawer from query params
onMounted(() => {
  const kind = route.query.kind as string | undefined
  const source = route.query.source as string | undefined
  if (kind && source) {
    openRun(kind, source)
  }
})

const strategy = computed(() => store.canonical.find((s: any) => s.strategy === name) || { strategy: name, score: { grade: '?', grades: {} } })
const runs = computed(() => store.backtests.filter((b: any) => b.strategy === name).sort((a: any, b: any) => (b.run_time || '').localeCompare(a.run_time || '')))
const runsFilter = useUrlState({ key: 'runs', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })
const runsSorting = ref<{ id: string; desc: boolean }[]>([{ id: 'run_time', desc: true }])
const columnVisibility = ref<Record<string, boolean>>({})

const runsColumns = [
  { accessorKey: 'run_time', header: 'Run' },
  { accessorKey: 'grade', header: 'Grade' },
  { accessorKey: 'profit_total', header: 'Profit%' },
  { accessorKey: 'total_trades', header: 'Trades' },
  { accessorKey: 'profit_factor', header: 'PF' },
  { accessorKey: 'sortino', header: 'Sortino' },
  { accessorKey: 'max_drawdown_account', header: 'MaxDD' },
  { accessorKey: 'timeframe', header: 'TF' },
  { accessorKey: 'timerange', header: 'Range' },
  { accessorKey: 'source', header: 'Source' },
  { accessorKey: 'actions', header: '', enableSorting: false, enableGlobalFilter: false },
]

const filteredRuns = computed(() => {
  const f = runsFilter.value.trim().toLowerCase()
  if (!f) return runs.value
  return runs.value.filter((r: any) =>
    (r.run_time || '').toLowerCase().includes(f) ||
    (r.source || '').toLowerCase().includes(f) ||
    (r.timeframe || '').toLowerCase().includes(f) ||
    (r.timerange || '').toLowerCase().includes(f)
  )
})
const benches = computed(() => store.benchmarks.filter((b: any) => b.strategy === name))
const hos = computed(() => store.hyperopt.filter((b: any) => b.strategy === name))
const wfs = computed(() => store.walkforward.filter((b: any) => b.strategy === name))

const benchEngaged = computed(() => benches.value.filter((r: any) => (r.total_trades || 0) > 0).sort((a: any, b: any) => (b.run_time || '').localeCompare(a.run_time || ''))[0])

const configRows = computed(() => {
  const raw = (strategy.value as any).config_json
  if (!raw) return []
  let cfg: any = {}
  try { cfg = JSON.parse(raw) } catch (e) { return [] }
  const keys = ['stake_currency', 'stake_amount', 'max_open_trades', 'timeframe', 'trading_mode', 'stoploss', 'exchange', 'timeframe']
  return keys.filter((k) => cfg[k] !== undefined).map((k) => ({ k: k, v: typeof cfg[k] === 'object' ? JSON.stringify(cfg[k]) : String(cfg[k]) }))
})

const metricCards = computed(() => {
  const c: any = strategy.value
  return [
    { k: 'Profit', v: fmtPct1((c.profit_total || 0) * 100), c: (c.profit_total || 0) >= 0 ? 'good' : 'bad' },
    { k: 'Sortino', v: fmt(c.sortino), c: '' },
    { k: 'Calmar', v: fmt(c.calmar), c: '' },
    { k: 'Profit factor', v: fmt(c.profit_factor), c: '' },
    { k: 'Max drawdown', v: fmtPct(c.max_drawdown_account), c: '' },
    { k: 'Win rate', v: fmtPct(c.winrate), c: '' },
    { k: 'Trades', v: fmt0(c.total_trades), c: '' },
    { k: 'Holding avg', v: c.holding_avg_s ? fmt(c.holding_avg_s / 3600, 1) + 'h' : '—', c: '' }
  ]
})

const scorecardRows = computed(() => {
  const c: any = strategy.value
  const bench: any = benchEngaged.value
  return Object.entries(store.scorecard).map(([k, spec]: [string, any]) => {
    const v = c[k]
    const g = c.score?.grades?.[k] || 'na'
    const isPctMetric = k === 'max_drawdown_account' || k === 'worst_trade'
    const metricShown = (kk: string, vv: any) => {
      if (kk === 'winrate' || kk === 'max_drawdown_account' || kk === 'worst_trade') return fmtPct(vv)
      if (kk === 'total_trades') return fmt0(vv)
      return fmt(vv)
    }
    const passStr = isPctMetric ? '≤ ' + fmtPct(spec.pass) : (k === 'total_trades' ? fmt0(spec.pass) : fmt(spec.pass))
    const warnStr = isPctMetric ? '≤ ' + fmtPct(spec.warn) : (k === 'total_trades' ? fmt0(spec.warn) : fmt(spec.warn))
    let benchVal = ''
    let bg = 'na'
    if (bench) {
      benchVal = metricShown(k, bench[k])
      bg = bench.score ? (bench.score.grades[k] || 'na') : 'na'
    }
    return { k: k, label: spec.label, value: metricShown(k, v), g: g, bench: benchVal, bg: bg, pass: passStr, warn: warnStr }
  })
})

const propChecksHead = computed(() => {
  const pf = (strategy.value as any).prop_firms
  if (!pf) return []
  const first = (Object.values(pf) as any[])[0]
  return [...((first?.checks || []).map((c: any) => c.label || c.name || '')), '']
})

const propRows = computed(() => {
  const pf = (strategy.value as any).prop_firms
  if (!pf) return []
  return Object.keys(pf).map((k) => {
    const p = pf[k]
    const sp = store.propSpec[k] || {}
    return {
      k: k,
      label: p.label,
      basis: sp.daily_dd_basis === 'trailing_intraday_high' ? 'trailing intraday high' : 'midnight balance',
      checks: (p.checks || []).map((c: any) => ({
        status: c.status,
        text: c.status === 'na' ? 'n/a' : fmtCheck(c) + ' / ' + fmtLim(c)
      })),
      verdict: p.verdict
    }
  })
})

const diagnostics = computed(() => {
  const c: any = strategy.value
  const pct2 = (v: any) => v != null ? (v * 100).toFixed(2) + '%' : '—'
  return [
    { k: 'Max loss streak', v: fmt0(c.max_loss_streak), c: (c.max_loss_streak || 0) >= 8 ? 'bad' : (c.max_loss_streak || 0) >= 5 ? 'warn' : '' },
    { k: 'Max win streak', v: fmt0(c.max_win_streak), c: '' },
    { k: 'Payoff (avg win/loss)', v: c.payoff_ratio != null ? fmt(c.payoff_ratio) : '—', c: (c.payoff_ratio != null && c.payoff_ratio < 1 ? 'bad' : '') },
    { k: 'Avg MFE', v: c.avg_mfe != null ? pct2(c.avg_mfe) : '—', c: '' },
    { k: 'Avg MAE', v: c.avg_mae != null ? pct2(c.avg_mae) : '—', c: '' },
    { k: 'Capture of MFE', v: c.capture_ratio != null ? (c.capture_ratio * 100).toFixed(0) + '%' : '—', c: (c.capture_ratio != null && c.capture_ratio < 0.25 ? 'bad' : '') },
    { k: 'Avg win', v: c.avg_win != null ? pct2(c.avg_win) : '—', c: '' },
    { k: 'Avg loss', v: c.avg_loss != null ? pct2(c.avg_loss) : '—', c: '' },
    { k: 'Worst trade' + (c.worst_trade_pair ? ' · ' + c.worst_trade_pair : ''), v: c.worst_trade != null ? pct2(c.worst_trade) : '—', c: ((c.worst_trade ?? 0) <= -0.60 ? 'bad' : (c.worst_trade ?? 0) <= -0.25 ? 'warn' : '') }
  ]
})

const recommendations = computed(() => (strategy.value as any).recommendations || [])

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

function fmt(v: any, d = 3) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!isFinite(n)) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: d })
}
function fmt0(v: any) { return fmt(v, 0) }
function fmtPct(v: any) { return v === null || v === undefined || v === '' ? '—' : (Number(v) * 100).toFixed(1) + '%' }
function fmtPct1(v: any) { return v === null || v === undefined || v === '' ? '—' : Number(v).toFixed(1) + '%' }
function pfFmt(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (n === Infinity) return '∞'
  if (!isFinite(n)) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
function fmtNum(v: number) { return fmt(v, 2) }
function fmtRange(tr: string) {
  if (!tr) return '—'
  const p = String(tr).split('-')
  const d = (s: string) => (s && s.length === 8) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '?')
  return d(p[0]) + ' → ' + (p[1] ? d(p[1]) : 'live')
}
function fmtCheck(c: any) { return c.fmt === 'int' ? fmt0(c.value) : fmtPct(c.value) }
function fmtLim(c: any) { return c.fmt === 'int' ? fmt0(c.limit) : fmtPct(c.limit) }
function checkPill(s: string) {
  if (s === 'pass') return 'A'
  if (s === 'warn') return 'C'
  if (s === 'fail') return 'F'
  return 'na'
}
function recClass(level: string) {
  if (level === 'fail') return 'F'
  if (level === 'warn') return 'C'
  if (level === 'good') return 'A'
  return 'na'
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
function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'active') return 'status active'
  if (sl === 'experimental') return 'status experimental'
  if (sl === 'retired') return 'status retired'
  return 'status'
}
function basisLabel(r: any) {
  if (!r || r.basis === 'registry') return 'no runs yet'
  return r.basis === 'benchmark' ? 'benchmark (fallback)' : 'last backtest'
}
function basisTooltip(r: any) {
  if (!r || r.basis === 'registry') return 'registered in the strategies table; no backtest or benchmark ingested yet'
  return 'metrics from ' + (r.basis === 'benchmark' ? 'benchmark' : 'backtest') + ' run ' + (r.source || '?') + ' · ' + (r.run_time || '?')
}
function passWarnFail() {
  const s: any = (strategy.value as any).score
  if (!s) return ''
  return (s.pass_count || 0) + ' pass, ' + (s.warn_count || 0) + ' warn, ' + (s.fail_count || 0) + ' fail'
}
function codeBadgeText() {
  const c: any = strategy.value
  const hash = c.code_hash
  if (!hash) return 'code unknown'
  const setSnap = store.snapshotCombined[hash]
  const setCur = store.currentCodeSet[name]
  if (setSnap && setCur) return setSnap === setCur ? 'code current' : 'code changed since run'
  const cur = store.currentCode[name]
  if (!cur) return 'no .py on disk'
  return cur === hash ? 'code current' : 'code changed since run'
}
function codeBadgeClass() {
  const t = codeBadgeText()
  if (t === 'code current') return 'pill gA'
  if (t === 'code changed since run') return 'pill gF'
  return 'pill gna'
}
function codeBadgeTitle() {
  const c: any = strategy.value
  const meta = store.snapshotPaths[c.code_hash]
  return 'snapshot ' + (c.code_hash || '?').slice(0, 12) + (meta && meta.mtime ? ' · ' + meta.mtime : '')
}

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
.hint { color: var(--text-faint); font-size: 12px; }
.basis-badge { font-size: 11px; color: var(--text-dim); background: var(--bg-soft); border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.metric-card { display: flex; flex-direction: column; gap: 2px; background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; }
.mk { font-size: 11px; color: var(--text-dim); }
.mv { font-size: 15px; font-weight: 600; }
.mv.good { color: var(--good); }
.mv.bad { color: var(--bad); }
.mv.warn { color: var(--warn); }
.drawer-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.drawer-table td { padding: 6px 8px; border-top: 1px solid var(--border); }
.runs-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.rec-row { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; display: flex; gap: 10px; align-items: flex-start; margin-bottom: 8px; }
.code-block { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; overflow: auto; max-height: 300px; font-size: 11px; white-space: pre-wrap; }
</style>
