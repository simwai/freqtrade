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
        <ColumnToggle :columns="columns" :visibility="columnVisibility" @update:visibility="columnVisibility = $event" />
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
        @select="(row: any) => openStrategy(row.original?.strategy ?? row.strategy)"
        class="w-full"
        empty="No strategies found matching your filters."
      >
        <template #cell-strategy="{ row }">
          <div class="flex items-center gap-2">
            <span>{{ (row.original as any).strategy }}</span>
            <span :class="statusClass((row.original as any).status)">{{ (row.original as any).status }}</span>
          </div>
        </template>
        <template #cell-score.grade="{ row }">
          <span :class="gradePill((row.original as any).score?.grade)">{{ (row.original as any).score?.grade || '?' }}</span>
        </template>
        <template #cell-profit_total="{ row }">
          <span class="num" :class="profitClass((row.original as any).profit_total)">{{ fmtProfitPct((row.original as any).profit_total) }}</span>
        </template>
        <template #cell-propPass="{ row }">
          <span class="num"><span :class="propClass(row.original)" :title="propTitle(row.original)">{{ propText(row.original) }}</span></span>
        </template>
        <template #cell-basis="{ row }">
          <span :title="basisTooltip(row.original)">{{ basisLabel(row.original) }}</span>
        </template>
        <template #cell-timerange="{ row }">
          <span style="font-size:12px;color:var(--text-dim)">{{ fmtRange((row.original as any).timerange) }}</span>
        </template>
        <template #cell-run_time="{ row }">
          <span>{{ ((row.original as any).run_time || '').slice(0, 10) }}</span>
        </template>
        <template #cell-actions="{ row }">
          <UButton size="sm" variant="ghost" @click.stop="openStrategy((row.original as any).strategy)">
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
          @select="(row: any) => openStrategy(row.original?.strategy ?? row.strategy)"
          class="w-full"
          empty="No data"
        >
          <template #cell-profit_total="{ row }">
            <span class="num">{{ fmtNum((row.original as any).profit_total) }}</span>
          </template>
        </UTable>
      </div>
      <div class="card">
        <h3>Bottom 5</h3>
        <UTable
          :data="flopRows"
          :columns="miniColumns"
          :loading="false"
          @select="(row: any) => openStrategy(row.original?.strategy ?? row.strategy)"
          class="w-full"
          empty="No data"
        >
          <template #cell-profit_total="{ row }">
            <span class="num">{{ fmtNum((row.original as any).profit_total) }}</span>
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
import { useUrlState } from '../composables/useUrlState'

const store = useDashboardStore()
const minProfit = ref(0)
const minTrades = ref(0)
const selected = ref('')
const metric2 = ref('total_trades')
const globalFilter = useUrlState({ key: 'filter', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'profit_total', desc: true }])
const columnVisibility = ref<Record<string, boolean>>({})

const filtered = computed(() => store.canonical.filter((s: any) => (s.profit_total || 0) >= minProfit.value).filter((s: any) => (s.total_trades || 0) >= minTrades.value))

const columns = [
  { accessorKey: 'strategy', header: 'Strategy' },
  { accessorKey: 'score.grade', header: 'Grade', size: 80 },
  { accessorKey: 'profit_total', header: 'Profit%', size: 100 },
  { accessorKey: 'sortino', header: 'Sortino', size: 90 },
  { accessorKey: 'calmar', header: 'Calmar', size: 90 },
  { accessorKey: 'profit_factor', header: 'PF', size: 90 },
  { accessorKey: 'max_drawdown_account', header: 'MaxDD', size: 90 },
  { accessorKey: 'propPass', header: 'Prop', size: 90 },
  { accessorKey: 'winrate', header: 'Win%', size: 90 },
  { accessorKey: 'total_trades', header: 'Trades', size: 90 },
  { accessorKey: 'basis', header: 'Basis', size: 120 },
  { accessorKey: 'timerange', header: 'Range', size: 130 },
  { accessorKey: 'run_time', header: 'Run', size: 100 },
  { accessorKey: 'actions', header: '', size: 50, enableSorting: false, enableGlobalFilter: false },
]

const miniColumns = [
  { accessorKey: 'strategy', header: 'Strategy' },
  { accessorKey: 'profit_total', header: 'Profit', size: 100 },
]

const metric2Options = [
  { label: 'profit', value: 'profit_total' },
  { label: 'trades', value: 'total_trades' },
  { label: 'winrate', value: 'winrate' },
]

const filteredData = computed(() => {
  const q = globalFilter.value.trim().toLowerCase()
  if (!q) return filtered.value
  return filtered.value.filter((s: any) => {
    return Object.values(s).some((v) => {
      if (v === null || v === undefined || v === '') return false
      return String(v).toLowerCase().includes(q)
    })
  })
})

function resetFilters() {
  globalFilter.value = ''
  columnVisibility.value = {}
  sorting.value = [{ id: 'profit_total', desc: true }]
}

const profitOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: filteredData.value.map((s: any) => s.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'bar', data: filteredData.value.map((s: any) => (s.profit_total || 0) * 100), itemStyle: { color: '#a78bfa' } }]
}))

const metric2Option = computed((): ECOption => ({
  xAxis: { type: 'category', data: filteredData.value.map((s: any) => s.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'bar', data: filteredData.value.map((s: any) => s[metric2.value] || 0), itemStyle: { color: '#c4b5fd' } }]
}))

const topRows = computed(() => [...store.canonical].sort((a: any, b: any) => (b.profit_total || 0) - (a.profit_total || 0)).slice(0, 5))
const flopRows = computed(() => [...store.canonical].sort((a: any, b: any) => (a.profit_total || 0) - (b.profit_total || 0)).slice(0, 5))

const improveNext = computed(() => {
  const rows = filteredData.value.filter((r: any) => r.basis !== 'registry' && r.score?.grade !== 'A').slice(0, 6)
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
function fmtProfitPct(v: number) { return v === null || v === undefined ? '—' : ((v || 0) * 100).toFixed(1) + '%' }
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

function refreshData() {
  store.fetchAll(true)
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
.stats-row { display: flex; gap: 16px; flex-wrap: wrap; }
.mini-table { width: 100%; font-size: 12px; }
.mini-table td { padding: 6px 8px; border-top: 1px solid var(--border); }
.mini-table td.num { text-align: right; }
.mini-table tbody tr:hover { background: var(--card-hover); cursor: pointer; }
.mini-table tbody tr:hover td { color: var(--accent); }
</style>