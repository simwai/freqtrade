<template>
  <section>
    <div class="section-head">
      <h2>History</h2>
    </div>

    <div v-if="store.loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading history...</span>
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
        <div class="strategy-picker">
          <span class="filter-label">Strategies</span>
          <UInput v-model="strategySearch" placeholder="Search strategies..." size="sm" class="picker-search" />
          <div class="btn-row">
            <UButton size="xs" variant="ghost" @click="selectAll">Select all</UButton>
            <UButton size="xs" variant="ghost" @click="selectTop">Top 8</UButton>
            <UButton size="xs" variant="ghost" @click="clearAll">Clear</UButton>
          </div>
          <div class="picker-list">
            <UCheckbox
              v-for="name in visibleNames"
              :key="name"
              :label="name"
              :model-value="selected.includes(name)"
              @update:model-value="toggleName(name, $event === true)"
            />
            <p v-if="!visibleNames.length" class="hint">No strategies match the search.</p>
          </div>
          <span class="hint">{{ selected.length }} selected</span>
        </div>
        <UFormField name="metric2" label="Second metric">
          <USelect v-model="metric2" :options="metric2Options" @change="persistMetric2" class="filter-select" />
        </UFormField>
        <UCheckbox v-model="useLog" label="Log scale" />
      </div>

      <p v-if="!picked.length" class="hint">No history to chart. Strategies need at least two backtest runs.</p>
      <div class="hist-grid">
        <div v-for="name in picked" :key="name" class="chart-box">
          <div class="section-head" style="margin-bottom:4px">
            <b>{{ name }}</b>
            <span class="hint">{{ seriesOf(name).dates.length }} runs</span>
          </div>
          <VChart :option="optionFor(name)" autoresize class="chart" style="height: 260px" />
        </div>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent])
import { useDashboardStore } from '../stores/dashboard'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import { useUrlState } from '../composables/useUrlState'

const store = useDashboardStore()
const selected = useUrlState<string[]>({ key: 'sel', defaultValue: [], parse: (v) => (v ? v.split(',') : []), serialize: (v) => v.join(',') })
const useLog = ref(false)
const strategySearch = ref('')

const metrics2: Record<string, { label: string, pct: boolean }> = {
  sortino: { label: 'Sortino', pct: false },
  calmar: { label: 'Calmar', pct: false },
  profit_factor: { label: 'Profit factor', pct: false },
  max_drawdown: { label: 'Max drawdown', pct: true },
  winrate: { label: 'Win rate', pct: true },
  trades: { label: 'Trades', pct: false }
}

const metric2 = ref('sortino')

const metric2Options = computed(() => Object.entries(metrics2).map(([value, m]) => ({ label: m.label, value: value })))
try {
  const saved = localStorage.getItem('histMetric2')
  if (saved && metrics2[saved]) metric2.value = saved
} catch (e) {}

function persistMetric2() {
  try { localStorage.setItem('histMetric2', metric2.value) } catch (e) {}
}

const names = computed(() => Object.keys(store.history).filter((n) => {
  const row = store.canonical.find((c: any) => c.strategy === n)
  return !row || (row.status || 'active') !== 'retired'
}).sort((a, b) => (store.history[b].dates.length - store.history[a].dates.length)))

const visibleNames = computed(() => {
  const s = strategySearch.value.trim().toLowerCase()
  if (!s) return names.value
  return names.value.filter((n) => n.toLowerCase().includes(s))
})

function toggleName(name: string, checked: boolean) {
  if (checked) {
    if (!selected.value.includes(name)) selected.value = [...selected.value, name]
  } else {
    selected.value = selected.value.filter((v) => v !== name)
  }
}

const picked = computed(() => selected.value.filter((v) => !v.startsWith('__')))

function refreshData() {
  store.fetchAll(true)
}

function seriesOf(name: string) {
  return store.history[name] || { dates: [], profit: [] }
}

function fmtProfit(v: number) {
  return v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%'
}

function fmtM2(v: number) {
  if (v === null || v === undefined) return '—'
  const m = metrics2[metric2.value]
  return m.pct ? (v * 100).toFixed(1) + '%' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function optionFor(name: string): ECOption {
  const h = seriesOf(name)
  const m = metrics2[metric2.value]
  const byD = (p: any[], q: any[]) => String(p[0]).localeCompare(String(q[0]))
  const profit = h.dates.map((d: string, j: number) => {
    let v = h.profit[j]
    if (useLog.value && v <= 0) v = null
    return [d, v]
  }).sort(byD)
  const second = h.dates.map((d: string, j: number) => [d, h[metric2.value][j]]).sort(byD)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      formatter: (ps: any) => ps.map((p: any) => {
        const v = Array.isArray(p.value) ? p.value[1] : p.value
        const txt = p.seriesName === 'Profit %' ? fmtProfit(v) : fmtM2(v)
        return p.marker + ' ' + p.seriesName + ': <b>' + txt + '</b>'
      }).join('<br/>')
    },
    legend: { textStyle: { color: '#a89fc4' }, top: 0, data: ['Profit %', m.label] },
    grid: { left: 56, right: 44, top: 28, bottom: 26 },
    xAxis: { type: 'time', axisLabel: { color: '#a89fc4', hideOverlap: true, formatter: '{yyyy}-{MM}-{dd}' }, axisLine: { lineStyle: { color: '#2f2745' } } },
    yAxis: [
      useLog.value
        ? { type: 'log', logBase: 10, axisLabel: { color: '#a89fc4', formatter: (v: number) => v === 0 ? '0' : (v * 100).toFixed(0) + '%' }, splitLine: { lineStyle: { color: '#241d36' } } }
        : { type: 'value', scale: true, axisLabel: { color: '#a89fc4', formatter: (v: number) => (v * 100).toFixed(0) + '%' }, splitLine: { lineStyle: { color: '#241d36' } } },
      { type: 'value', scale: true, position: 'right', splitLine: { show: false }, axisLabel: { color: '#a89fc4', formatter: m.pct ? (v: number) => (v * 100).toFixed(0) + '%' : (v: number) => Number(v).toLocaleString('en-US', { maximumFractionDigits: 1 }) } }
    ],
    series: [
      { name: 'Profit %', type: 'line', showSymbol: true, symbolSize: 6, connectNulls: true, data: profit, lineStyle: { color: '#c4b5fd', width: 2 }, itemStyle: { color: '#c4b5fd' } },
      { name: m.label, type: 'line', yAxisIndex: 1, showSymbol: true, symbolSize: 5, data: second, lineStyle: { color: '#74c7ec', width: 1, type: 'dashed' }, itemStyle: { color: '#74c7ec' } }
    ]
  }
}

function selectAll() { selected.value = [...names.value] }
function selectTop() { selected.value = names.value.slice(0, 8) }
function clearAll() { selected.value = [] }

onMounted(async () => {
  await store.fetchAll()
  if (!selected.value.length && names.value.length) selected.value = [names.value[0]]
})
</script>

<style scoped>
.strategy-picker { display: flex; flex-direction: column; gap: 8px; min-width: 240px; max-width: 340px; }
.picker-search { width: 100%; }
.picker-list { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; padding: 4px 2px; }
.filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 16px; }
.filter-label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.filter-select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  min-width: 200px;
}
.filter-input {
  flex: 1; min-width: 180px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
}
.btn-row { display: flex; gap: 8px; }
.check { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--text-dim); }
.hint { color: var(--text-faint); font-size: 12px; }
.hist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; }
</style>
