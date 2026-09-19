<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])

import { useStrategiesStore } from '../stores/strategies'
import GradeTuner from '../components/GradeTuner.vue'
import StrategyDrawer from '../components/StrategyDrawer.vue'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import { useUrlState } from '../composables/useUrlState'
import { sortableHeader } from '../utils/table'
import { useStrategyFormat } from '../composables/useStrategyFormat'

const store = useStrategiesStore()
const format = useStrategyFormat()
const minProfit = ref(0)
const minTrades = ref(0)
const selected = ref('')
const metric2 = ref('total_trades')
const globalFilter = useUrlState({ key: 'filter', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'profit_total', desc: true }])
const columnVisibility = ref<Record<string, boolean>>({})

const filtered = computed(() => store.canonical.filter((s) => (s.profit_total || 0) >= minProfit.value).filter((s) => (s.total_trades || 0) >= minTrades.value))

const columns = [
  { accessorKey: 'strategy', header: sortableHeader('Strategy') },
  { accessorKey: 'score.grade', header: sortableHeader('Grade'), size: 80 },
  { accessorKey: 'profit_total', header: sortableHeader('Profit%'), size: 100 },
  { accessorKey: 'sortino', header: sortableHeader('Sortino'), size: 90 },
  { accessorKey: 'calmar', header: sortableHeader('Calmar'), size: 90 },
  { accessorKey: 'profit_factor', header: sortableHeader('PF'), size: 90 },
  { accessorKey: 'max_drawdown_account', header: sortableHeader('MaxDD'), size: 90 },
  { accessorKey: 'propPass', accessorFn: (r: StrategyRow) => format.propPassCount(r as unknown as Record<string, unknown>), header: sortableHeader('Prop'), size: 90 },
  { accessorKey: 'winrate', header: sortableHeader('Win%'), size: 90 },
  { accessorKey: 'total_trades', header: sortableHeader('Trades'), size: 90 },
  { accessorKey: 'basis', header: sortableHeader('Basis'), size: 120 },
  { accessorKey: 'timerange', header: sortableHeader('Range'), size: 130 },
  { accessorKey: 'run_time', header: sortableHeader('Run'), size: 100 },
  { accessorKey: 'actions', header: '', size: 50, enableSorting: false, enableGlobalFilter: false },
]

const miniColumns = [
  { accessorKey: 'strategy', header: sortableHeader('Strategy') },
  { accessorKey: 'profit_total', header: sortableHeader('Profit'), size: 100 },
]

const metric2Options = [
  { label: 'profit', value: 'profit_total' },
  { label: 'trades', value: 'total_trades' },
  { label: 'winrate', value: 'winrate' },
]

const filteredData = computed(() => {
  const q = globalFilter.value.trim().toLowerCase()
  if (!q) return filtered.value
  return filtered.value.filter((s) => {
    return Object.values(s as Record<string, unknown>).some((v) => {
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
  title: { text: 'Profit by strategy', left: 'center', textStyle: { color: '#a89fc4', fontSize: 13, fontWeight: 600 } },
  xAxis: { type: 'category', data: filteredData.value.map((s) => s.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'bar', data: filteredData.value.map((s) => (s.profit_total || 0) * 100), itemStyle: { color: '#a78bfa' } }]
}))

const metric2Option = computed((): ECOption => ({
  title: { text: 'Second metric by strategy', left: 'center', textStyle: { color: '#a89fc4', fontSize: 13, fontWeight: 600 } },
  xAxis: { type: 'category', data: filteredData.value.map((s) => s.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'bar', data: filteredData.value.map((s) => (s as Record<string, unknown>)[metric2.value] || 0), itemStyle: { color: '#c4b5fd' } }]
}))

const topRows = computed(() => [...store.canonical].sort((a, b) => (b.profit_total || 0) - (a.profit_total || 0)).slice(0, 5))
const flopRows = computed(() => [...store.canonical].sort((a, b) => (a.profit_total || 0) - (b.profit_total || 0)).slice(0, 5))

const improveNext = computed(() => {
  const rows = filteredData.value.filter((r) => r.basis !== 'registry' && r.score?.grade !== 'A').slice(0, 6)
  return rows.map((r) => {
    const grades = r.score?.grades || {}
    const labels = (store.scorecard || {}) as Record<string, { label: string }>
    const fails = Object.entries(grades).filter(([_kf, g]) => g === 'fail').map(([k]) => labels[k]?.label || k).join(', ')
    const warns = Object.entries(grades).filter(([_kw, g]) => g === 'warn').map(([k]) => labels[k]?.label || k).join(', ')
    let focus = fails ? fails : ''
    if (warns) focus += (focus ? ' + ' : '') + warns
    return { strategy: r.strategy, score: r.score, focus: focus }
  })
})

function openStrategy(name: string) { selected.value = name }

function refreshData() {
  store.fetchFullData()
}

onMounted(async () => {
  await store.fetchFullData()
})
</script>

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
        @select="(row) => openStrategy((row as any).original?.strategy ?? (row as any).strategy)"
        class="w-full"
        empty="No strategies found matching your filters."
      >
        <template #strategy-cell="{ row }">
          <div class="flex items-center gap-2">
            <span>{{ row.original.strategy }}</span>
            <span :class="format.statusClass(row.original.status)">{{ row.original.status }}</span>
          </div>
        </template>
        <template #["score.grade-cell"]="{ row }">
          <span :class="format.gradePill(row.original.score?.grade)">{{ row.original.score?.grade || '?' }}</span>
        </template>
        <template #profit_total-cell="{ row }">
          <span class="num" :class="format.profitClass(row.original.profit_total)">{{ format.fmtProfitPct(row.original.profit_total) }}</span>
        </template>
        <template #propPass-cell="{ row }">
          <span class="num"><span :class="format.propClass(row.original)" :title="format.propTitle(row.original, store.propSpec)">{{ format.propText(row.original) }}</span></span>
        </template>
        <template #basis-cell="{ row }">
          <span :title="format.basisTooltip(row.original)">{{ format.basisLabel(row.original) }}</span>
        </template>
        <template #timerange-cell="{ row }">
          <span style="font-size:12px;color:var(--text-dim)">{{ format.fmtRange(row.original.timerange) }}</span>
        </template>
        <template #run_time-cell="{ row }">
          <span>{{ (row.original.run_time || '').slice(0, 10) }}</span>
        </template>
        <template #actions-cell="{ row }">
          <UButton size="sm" variant="ghost" @click.stop="openStrategy(row.original.strategy)">
            <UIcon name="i-lucide-chevron-right" size="14" />
          </UButton>
        </template>
      </UTable>
    </div>

    <div class="charts">
      <div class="chart-box">
        <VChart :option="profitOption" autoresize class="chart" style="aspect-ratio: 16/9; min-height: 200px;" />
      </div>
      <div class="chart-box">
        <USelect v-model="metric2" :options="metric2Options" class="metric-select" />
        <VChart :option="metric2Option" autoresize class="chart" style="aspect-ratio: 16/9; min-height: 200px;" />
      </div>
    </div>

    <div class="stats-row">
      <div class="card">
        <h3>What to improve next</h3>
        <div v-for="s in improveNext" :key="s.strategy" class="metric-card" @click="openStrategy(s.strategy)">
          <div class="mk">{{ s.strategy }} — {{ s.score?.grade }}</div>
          <div class="mv">{{ s.focus || '—' }}</div>
        </div>
      </div>
      <div class="card">
        <h3>Top 5</h3>
        <UTable
          :data="topRows"
          :columns="miniColumns"
          :loading="false"
          @select="(row) => openStrategy((row as any).original?.strategy ?? (row as any).strategy)"
          class="w-full"
          empty="No data"
        >
          <template #profit_total-cell="{ row }">
            <span class="num">{{ format.fmt(row.original.profit_total, 2) }}</span>
          </template>
        </UTable>
      </div>
      <div class="card">
        <h3>Bottom 5</h3>
        <UTable
          :data="flopRows"
          :columns="miniColumns"
          :loading="false"
          @select="(row) => openStrategy((row as any).original?.strategy ?? (row as any).strategy)"
          class="w-full"
          empty="No data"
        >
          <template #profit_total-cell="{ row }">
            <span class="num">{{ format.fmt(row.original.profit_total, 2) }}</span>
          </template>
        </UTable>
      </div>
    </div>

    <StrategyDrawer v-if="selected" :name="selected" @close="selected = ''" />
  </section>
</template>

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

@media (max-width: 768px) {
  .charts { flex-direction: column; }
  .chart-box { width: 100%; }
  .chart { aspect-ratio: 16/9; min-height: 200px; }
}
</style>
