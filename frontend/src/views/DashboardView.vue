<template>
  <section>
    <div class="section-head">
      <h2>Dashboard</h2>
      <div class="controls">
        <UInput v-model="globalFilter" placeholder="Filter strategies..." class="filter-input" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!globalFilter && !Object.keys(columnVisibility).length">
          <template #leading>
            <UIcon name="i-lucide-rotate-ccw" />
          </template>
          Reset
        </UButton>
      </div>
    </div>

    <GradeTuner v-model:min-profit="minProfit" v-model:min-trades="minTrades" />

    <div v-if="store.loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading strategies...</span>
      </div>
    </div>
    <div v-else-if="store.error" class="card" style="color: var(--bad);">
      <div class="flex items-center gap-3">
        <UIcon name="i-lucide-alert-circle" class="text-error" size="20" />
        <div>
          <p class="font-medium">{{ store.error }}</p>
          <UButton size="sm" variant="outline" @click="refreshData">Retry</UButton>
        </div>
      </div>
    </div>
    <div v-else>
      <UTable
        :data="filtered"
        :columns="columns"
        :loading="false"
        :sticky="true"
        :global-filter="globalFilter"
        @update:global-filter="globalFilter = $event"
        :sorting="sorting"
        @update:sorting="sorting = $event"
        :column-visibility="columnVisibility"
        @update:column-visibility="columnVisibility = $event"
        @row-click="openStrategy"
        class="w-full"
        empty="No strategies found matching your filters."
      >
        <template #strategy-cell="{ row }">
          <div class="flex items-center gap-2">
            <span>{{ row.strategy }}</span>
            <span :class="statusClass(row.status)">{{ row.status }}</span>
          </div>
        </template>
        <template #grade-cell="{ row }">
          <span :class="gradePill(row.score?.grade)">{{ row.score?.grade || '?' }}</span>
        </template>
        <template #profit-cell="{ row }">
          <span class="num" :class="profitClass(row.profit_total)">{{ fmtProfitPct(row.profit_total) }}</span>
        </template>
        <template #prop-cell="{ row }">
          <span class="num"><span :class="propClass(row)" :title="propTitle(row)">{{ propText(row) }}</span></span>
        </template>
        <template #basis-cell="{ row }">
          <span :title="basisTooltip(row)">{{ basisLabel(row) }}</span>
        </template>
        <template #timerange-cell="{ row }">
          <span style="font-size:12px;color:var(--text-dim)">{{ fmtRange(row.timerange) }}</span>
        </template>
        <template #run-time-cell="{ row }">
          <span>{{ (row.run_time || '').slice(0, 10) }}</span>
        </template>
        <template #actions-cell="{ row }">
          <UButton size="sm" variant="ghost" @click.stop="openStrategy(row.strategy)">
            <UIcon name="i-lucide-chevron-right" size="14" />
          </UButton>
        </template>
      </UTable>
    </div>

    <div class="charts">
      <div class="chart-box">
        <VChart :option="profitOption" autoresize class="chart" style="height: 300px" />
      </div>
      <div class="chart-box">
        <USelect v-model="metric2" :options="metric2Options" class="metric-select" />
        <VChart :option="metric2Option" autoresize class="chart" style="height: 300px" />
      </div>
    </div>

    <div class="stats-row">
      <div class="card">
        <h3>What to improve next</h3>
        <div v-for="s in improveNext" :key="s.strategy" class="metric-card" @click="openStrategy(s.strategy)">
          <div class="mk">{{ s.strategy }} — {{ s.score.grade }}</div>
          <div class="mv">{{ s.focus || '—' }}</div>
        </div>
      </div>
      <div class="card">
        <h3>Top 5</h3>
        <UTable
          :data="topRows"
          :columns="miniColumns"
          :loading="false"
          @row-click="openStrategy"
          class="w-full"
          empty="No data"
        >
          <template #profit-cell="{ row }">
            <span class="num">{{ fmtNum(row.profit_total) }}</span>
          </template>
        </UTable>
      </div>
      <div class="card">
        <h3>Bottom 5</h3>
        <UTable
          :data="flopRows"
          :columns="miniColumns"
          :loading="false"
          @row-click="openStrategy"
          class="w-full"
          empty="No data"
        >
          <template #profit-cell="{ row }">
            <span class="num">{{ fmtNum(row.profit_total) }}</span>
          </template>
        </UTable>
      </div>
    </div>

    <StrategyDrawer v-if="selected" :name="selected" @close="selected = ''" />
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
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

const filtered = computed(() => store.canonical.filter((s: any) => (s.profit_total || 0) >= minProfit.value).filter((s: any) => (s.total_trades || 0) >= minTrades.value))

const sortedFiltered = computed(() => {
  const arr = [...filtered.value]
  arr.sort((a: any, b: any) => {
    let av = sortKey.value === 'propPass' ? propPassCount(a) : sortKey.value.split('.').reduce((o: any, k: string) => o?.[k], a)
    let bv = sortKey.value === 'propPass' ? propPassCount(b) : sortKey.value.split('.').reduce((o: any, k: string) => o?.[k], b)
    if (av === undefined && bv === undefined) return 0
    if (av === '' || av === undefined || av === null) return 1
    if (bv === '' || bv === undefined || bv === null) return -1
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
function fmt(v: any, d = 3) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!isFinite(n)) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: d })
}
function fmtNum(v: number) { return fmt(v, 2) }
function fmt3(v: number) { return fmt(v, 3) }
function pfFmt(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (n === Infinity) return '∞'
  if (!isFinite(n)) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
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
function fmtRange(tr: string) {
  if (!tr) return '—'
  const p = String(tr).split('-')
  const d = (s: string) => (s && s.length === 8) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '?')
  return d(p[0]) + ' → ' + (p[1] ? d(p[1]) : 'live')
}
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