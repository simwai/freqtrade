<template>
  <section>
    <div class="section-head">
      <h2>History</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else>
      <div class="card filters">
        <label class="filter-label">Strategies
          <select v-model="selected" multiple size="6" class="filter-select">
            <option value="__top">top 8 by runs</option>
            <option value="__all">all strategies</option>
            <option v-for="name in names" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <div class="btn-row">
          <button class="btn-secondary btn-sm" v-on:click="selectAll">Select all</button>
          <button class="btn-secondary btn-sm" v-on:click="selectTop">Top 8</button>
          <button class="btn-secondary btn-sm" v-on:click="clearAll">Clear</button>
        </div>
        <label class="filter-label">Second metric
          <select v-model="metric2" v-on:change="persistMetric2" class="filter-select">
            <option v-for="(m, k) in metrics2" :key="k" :value="k">{{ m.label }}</option>
          </select>
        </label>
        <label class="check"><input type="checkbox" v-model="useLog" /> Log scale</label>
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

const store = useDashboardStore()
const selected = ref([] as string[])
const useLog = ref(false)

const metrics2: Record<string, { label: string, pct: boolean }> = {
  sortino: { label: 'Sortino', pct: false },
  calmar: { label: 'Calmar', pct: false },
  profit_factor: { label: 'Profit factor', pct: false },
  max_drawdown: { label: 'Max drawdown', pct: true },
  winrate: { label: 'Win rate', pct: true },
  trades: { label: 'Trades', pct: false }
}

const metric2 = ref('sortino')
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

const picked = computed(() => {
  if (selected.value.includes('__top')) {
    return Object.entries(store.history).sort((a, b) => b[1].dates.length - a[1].dates.length).slice(0, 8).map(([name]) => name)
  }
  if (selected.value.includes('__all')) return Object.keys(store.history)
  return selected.value.filter((v) => !v.startsWith('__'))
})

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
function selectTop() { selected.value = ['__top'] }
function clearAll() { selected.value = [] }

onMounted(async () => {
  await store.fetchAll()
  if (!selected.value.length && names.value.length) selected.value = [names.value[0]]
})
</script>

<style scoped>
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
.hist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 14px; }
</style>
