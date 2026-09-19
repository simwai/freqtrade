<template>
  <section>
    <div class="section-head">
      <h2>WalkForward</h2>
      <div class="controls">
        <UInput v-model="q" placeholder="Filter runs..." class="filter-input" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!q && !Object.keys(columnVisibility).length">
          <template #leading>
            <UIcon name="i-lucide-rotate-ccw" />
          </template>
          Reset
        </UButton>
        <ColumnToggle :columns="columns" :visibility="columnVisibility" @update:visibility="columnVisibility = $event" />
      </div>
    </div>

    <InlineStatus v-if="drillStatus" :type="drillStatus.type" :title="drillStatus.title" :message="drillStatus.message" :duration="5000" />

    <div v-if="store.loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading walk-forward runs...</span>
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
      <div class="card filters">
        <span class="hint">{{ filtered.length }} / {{ store.walkforward.length }} runs</span>
      </div>

      <div class="card">
        <UTable
          :data="sortedFiltered"
          :columns="columns"
          :loading="false"
          :sticky="true"
          :sorting="sorting"
          @update:sorting="sorting = $event"
          :column-visibility="columnVisibility"
          @update:column-visibility="columnVisibility = $event"
          :meta="{ class: { tr: wfRowClass } }"
          @select="(row: any) => drill(row.original?.source ?? row.source)"
          class="w-full"
          empty="No walk-forward runs found matching your filters."
        >
          <template #run_id-cell="{ row }">
            <span class="num" :title="(row.original as any).source || ''">{{ ((row.original as any).run_id || (row.original as any).source || '').slice(0, 18) }}</span>
          </template>
          <template #timerange-cell="{ row }">
            <span :title="(row.original as any).timerange || ''">{{ fmtRange((row.original as any).timerange) }}</span>
          </template>
          <template #profitable_windows-cell="{ row }">
            <span :class="ratioClass(profitableRatio(row.original))">{{ (row.original as any).profitable_windows }}/{{ (row.original as any).n_windows }}</span>
          </template>
          <template #oos_profit_abs-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).oos_profit_abs) }}</span>
          </template>
          <template #avg_oos_sortino-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).avg_oos_sortino) }}</span>
          </template>
          <template #avg_oos_profit_factor-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).avg_oos_profit_factor) }}</span>
          </template>
          <template #actions-cell="{ row }">
            <UButton size="sm" variant="ghost" @click.stop="openRun('walkforward', (row.original as any).source)">Config &amp; code</UButton>
          </template>
        </UTable>
        <p class="hint">Showing up to 80 runs — refine the filter to narrow results.</p>
      </div>

      <div v-if="detail" class="card detail-panel">
        <div class="section-head">
          <h3>OOS per window {{ detail.r?.strategy }} · {{ (detail.r?.run_id || '').slice(0, 16) }}</h3>
          <span class="hint">{{ detailWins.length }} windows · {{ detail.r?.train_days }}/{{ detail.r?.test_days }}/{{ detail.r?.step_days }} d</span>
        </div>
        <div class="chart-box">
          <VChart :option="comboOption" autoresize class="chart" style="height: 280px" />
        </div>
        <UTable
          :data="detailWins"
          :columns="detailColumns"
          :loading="false"
          :sticky="true"
          :sorting="detailSorting"
          @update:sorting="detailSorting = $event"
          class="w-full"
          empty="No windows."
        >
          <template #oos_profit_abs-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).oos_profit_abs) }}</span>
          </template>
          <template #oos_winrate-cell="{ row }">
            <span class="num">{{ fmtPct((row.original as any).oos_winrate) }}</span>
          </template>
          <template #oos_sortino-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).oos_sortino) }}</span>
          </template>
          <template #oos_pf-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).oos_pf) }}</span>
          </template>
          <template #oos_dd-cell="{ row }">
            <span class="num">{{ fmtPct((row.original as any).oos_dd) }}</span>
          </template>
        </UTable>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { sortableHeader } from '../utils/table'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])
import { useStrategiesStore } from '../stores/strategies'
import { api } from '../api/client'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import { ratioClass } from '../utils/pills'
import { useUrlState } from '../composables/useUrlState'
import InlineStatus from '../components/InlineStatus.vue'
const router = useRouter()

const store = useStrategiesStore()

// Inline status state (replaces toast)
const drillStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showDrillStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  drillStatus.value = { type, title, message }
  setTimeout(() => { drillStatus.value = null }, 5000)
}
const q = useUrlState({ key: 'q', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })
const selected = ref('')
const detail = ref(null as any)

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'run_id', desc: true }])
const columnVisibility = ref<Record<string, boolean>>({})
const detailSorting = ref<{ id: string; desc: boolean }[]>([{ id: '_idx', desc: false }])

const columns = [
  { accessorKey: 'strategy', header: sortableHeader('Strategy') },
  { accessorKey: 'run_id', header: sortableHeader('Run') },
  { accessorKey: 'timerange', header: sortableHeader('Date Range') },
  { accessorKey: 'n_windows', header: sortableHeader('Windows') },
  { accessorKey: 'profitable_windows', header: sortableHeader('Profitable') },
  { accessorKey: 'oos_trades', header: sortableHeader('OOS Trades') },
  { accessorKey: 'oos_profit_abs', header: sortableHeader('OOS Profit') },
  { accessorKey: 'avg_oos_sortino', header: sortableHeader('Avg Sortino') },
  { accessorKey: 'avg_oos_profit_factor', header: sortableHeader('Avg PF') },
  { accessorKey: 'loss_function', header: sortableHeader('Loss') },
  { accessorKey: 'actions', header: '', enableSorting: false, enableGlobalFilter: false },
]

const detailColumns = [
  { accessorKey: '_idx', header: sortableHeader('#') },
  { accessorKey: 'test_range', header: sortableHeader('Test range') },
  { accessorKey: 'oos_trades', header: sortableHeader('Trades') },
  { accessorKey: 'oos_profit_abs', header: sortableHeader('Profit') },
  { accessorKey: 'oos_winrate', header: sortableHeader('WinRate') },
  { accessorKey: 'oos_sortino', header: sortableHeader('Sortino') },
  { accessorKey: 'oos_pf', header: sortableHeader('PF') },
  { accessorKey: 'oos_dd', header: sortableHeader('DD') },
]

function profitableRatio(r: any) {
  if (!r.n_windows) return 0
  return r.profitable_windows / r.n_windows
}

function wfRowClass(row: any) {
  const src = row?.original?.source ?? row?.source
  return src && src === selected.value ? 'row-selected' : ''
}

const filtered = computed(() => {
  const ql = q.value.toLowerCase()
  return store.walkforward.filter((r: any) => {
    const reg = store.canonical.find((c: any) => c.strategy === r.strategy)
    if (reg && (reg.status || 'active') === 'retired') return false
    if (!ql) return true
    return (r.strategy || '').toLowerCase().includes(ql) || (r.run_id || '').toLowerCase().includes(ql) || (r.source || '').toLowerCase().includes(ql)
  })
})

function compareCells(av: any, bv: any, desc: boolean): number {
  if (av === undefined && bv === undefined) return 0
  if (av === '' || av === undefined || av === null) return 1
  if (bv === '' || bv === undefined || bv === null) return -1
  const an = Number(av), bn = Number(bv)
  const useNum = !isNaN(an) && !isNaN(bn)
  const r = useNum ? an - bn : String(av).localeCompare(String(bv))
  return desc ? -r : r
}

const sortedFiltered = computed(() => {
  const s = sorting.value[0] || { id: 'run_id', desc: true }
  const arr = [...filtered.value]
  arr.sort((a: any, b: any) => compareCells(a[s.id], b[s.id], s.desc))
  return arr.slice(0, 80)
})

const detailWins = computed(() => {
  if (!detail.value || !detail.value.wins) return []
  return (detail.value.wins as any[]).map((w: any, i: number) => ({ ...w, _idx: i + 1 }))
})

function resetFilters() {
  q.value = ''
  columnVisibility.value = {}
  sorting.value = [{ id: 'run_id', desc: true }]
}

function refreshData() {
  store.fetchFullData()
}

async function drill(source: string) {
  selected.value = source
  try {
    const local = store.walkforward.find((r: any) => r.source === source)
    if (local && local.windows_json) {
      try {
        const wins = JSON.parse(local.windows_json)
        if (wins && wins.length) { detail.value = { r: local, wins: wins }; return }
      } catch (e) {}
    }
    const { data } = await api.get('/api/walkforward', { params: { source: source } })
    const wrows = data.rows || []
    if (!wrows.length) { detail.value = null; showDrillStatus('warning', 'Walk-forward detail empty', 'No windows returned for this run.'); return }
    detail.value = { r: wrows[0], wins: wrows[0].windows || [] }
  } catch (e) {
    detail.value = null
  }
}

function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : '—' }
function fmtPct(v: number) { return v ? (v * 100).toFixed(1) + '%' : '—' }
function fmtRange(tr: string) {
  if (!tr) return '—'
  const p = String(tr).split('-')
  const d = (s: string) => (s && s.length === 8) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '?')
  return d(p[0]) + ' → ' + (p[1] ? d(p[1]) : 'live')
}
function openRun(kind: string, source: string) {
  const r = store.walkforward.find((x: any) => x.source === source)
  if (r) {
    const strategy = r.strategy
    router.push(`/strategies/${encodeURIComponent(strategy)}?source=${encodeURIComponent(source)}&kind=${kind}`)
  }
}

const comboOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: ((detail.value && detail.value.wins) || []).map((_w: any, i: number) => 'W' + (i + 1)), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: [{ type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } }],
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [
    { type: 'bar', data: ((detail.value && detail.value.wins) || []).map((w: any) => ({ value: w.oos_profit_abs || 0, itemStyle: { color: (w.oos_profit_abs || 0) >= 0 ? '#6ee7a8' : '#f87171' } })) },
    { type: 'line', data: ((detail.value && detail.value.wins) || []).map((w: any) => w.oos_profit_abs || 0), smooth: true, lineStyle: { color: '#c4b5fd' } }
  ]
}))

onMounted(async () => {
  await store.fetchFullData()
})
</script>

<style scoped>
.row-selected { background: var(--card-hover); }
.filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }
.filter-input {
  flex: 1; min-width: 180px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
}
.detail-panel { display: flex; flex-direction: column; gap: 16px; }
</style>
