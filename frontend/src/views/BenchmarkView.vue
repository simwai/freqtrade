<template>
  <section>
    <div class="section-head">
      <h2>Benchmark</h2>
    </div>

    <div v-if="store.loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading benchmarks...</span>
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
    <div v-else class="card">
      <div class="controls">
        <UFormField name="metric" label="Metric">
          <USelect v-model="metric" :options="metricOptions" />
        </UFormField>
        <UFormField name="sourceMode" label="Source">
          <USelect v-model="sourceMode" :options="sourceOptions" />
        </UFormField>
        <UFormField name="sortMode" label="Sort by">
          <USelect v-model="sortMode" :options="sortOptions" />
        </UFormField>
        <UCheckbox v-model="useLog" label="Log scale" />
        <UCheckbox v-model="showPoints" label="Show every run" />
      </div>

      <div class="chart-box">
        <p class="hint">{{ hint }}</p>
        <VChart v-if="boxData.length" :option="benchOption" autoresize class="chart" :style="{ height: chartHeight + 'px' }" />
        <p v-else class="hint">No rows have a value for this metric. Pick a different metric or run more strategies.</p>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, BoxplotChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, BoxplotChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent])
import { useDashboardStore } from '../stores/dashboard'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'

const store = useDashboardStore()
const metric = ref('sortino')
const sourceMode = ref('auto')
const sortMode = ref('median')
const useLog = ref(false)
const showPoints = ref(true)

const metricOptions = [
  { label: 'Sortino', value: 'sortino' },
  { label: 'Total Profit', value: 'profit_total' },
  { label: 'Calmar', value: 'calmar' },
  { label: 'Profit Factor', value: 'profit_factor' },
  { label: 'Max Drawdown', value: 'max_drawdown_account' },
]
const sourceOptions = [
  { label: 'Benchmark + backtest (default)', value: 'auto' },
  { label: 'Benchmark only', value: 'benchmark' },
  { label: 'Backtest only', value: 'backtest' },
]
const sortOptions = [
  { label: 'Median (default)', value: 'median' },
  { label: 'Run count', value: 'count' },
  { label: 'Strategy name', value: 'name' },
]

const SENTINEL_VALUES: Record<string, number> = { sortino: -100, sharpe: -100, calmar: -100, sqn: -100 }

function benchQuartiles(arr: number[]) {
  if (!arr.length) return null
  const s = [...arr].sort((a, b) => a - b)
  const n = s.length
  const pick = (p: number) => s[Math.min(n - 1, Math.max(0, Math.floor(p * (n - 1))))]
  return [s[0], pick(0.25), pick(0.5), pick(0.75), s[n - 1]]
}

function benchOutliers(arr: number[]) {
  if (arr.length < 4) return 0
  const s = [...arr].sort((a, b) => a - b)
  const med = s[Math.floor(s.length / 2)]
  const dev = [...arr].map((v) => Math.abs(v - med)).sort((a, b) => a - b)
  const mad = dev[Math.floor(dev.length / 2)]
  if (!mad) return 0
  const k = 1.4826
  return arr.filter((v) => Math.abs(v - med) / (k * mad) > 2.5).length
}

function colorOf(v: number) {
  if (metric.value === 'max_drawdown_account') return v <= 0.2 ? '#6ee7a8' : v <= 0.4 ? '#fbbf24' : '#f87171'
  return v >= 1 ? '#6ee7a8' : v >= 0.3 ? '#fbbf24' : '#f87171'
}

function tagFor(entries: any[]) {
  const b = entries.filter((e) => e.src === 'B').length
  const t = entries.filter((e) => e.src === 'T').length
  if (b && t) return 'B+T'
  if (b) return 'B'
  return 'T'
}

function fmtVal(v: number) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 })
}

const boxData = computed(() => {
  const isRetired = (name: string) => {
    const row = store.canonical.find((r: any) => r.strategy === name)
    return !!(row && (row.status || 'active') === 'retired')
  }
  const all: any[] = []
  if (sourceMode.value === 'auto' || sourceMode.value === 'benchmark') {
    store.benchmarks.forEach((r: any) => { if (!isRetired(r.strategy)) all.push({ ...r, _src: 'B' }) })
  }
  if (sourceMode.value === 'auto' || sourceMode.value === 'backtest') {
    store.backtests.forEach((r: any) => { if (!isRetired(r.strategy)) all.push({ ...r, _src: 'T' }) })
  }
  const byStrategy = new Map<string, any[]>()
  all.forEach((r: any) => {
    const v = r[metric.value]
    if (v === null || v === undefined || v === '') return
    if (!byStrategy.has(r.strategy)) byStrategy.set(r.strategy, [])
    byStrategy.get(r.strategy)!.push({ value: Number(v), src: r._src })
  })
  const sentinel = SENTINEL_VALUES[metric.value]
  const rows: any[] = [...byStrategy.keys()].map((name) => {
    const entries = byStrategy.get(name)!
    const kept = sentinel !== undefined ? entries.filter((e) => e.value !== sentinel) : entries
    const q = benchQuartiles(kept.map((e) => e.value))
    return { name: name, entries: kept, q: q, color: q ? colorOf(q[2]) : '#8b83a5', n: kept.length, tag: tagFor(entries) }
  }).filter((b) => b.q !== null)
  if (sortMode.value === 'name') rows.sort((a, b) => a.name.localeCompare(b.name))
  else if (sortMode.value === 'count') rows.sort((a, b) => b.n - a.n || a.name.localeCompare(b.name))
  else rows.sort((a, b) => (b.q as number[])[2] - (a.q as number[])[2])
  return rows
})

const chartHeight = computed(() => Math.max(380, boxData.value.length * 26 + 90))

const effectiveLog = computed(() => {
  if (!useLog.value) return false
  return !boxData.value.some((b) => b.q && (b.q as number[]).some((v) => v <= 0))
})

const hint = computed(() => {
  if (!boxData.value.length) return ''
  const totalRuns = boxData.value.reduce((s, b) => s + b.n, 0)
  const totalOut = boxData.value.reduce((s, b) => s + benchOutliers(b.entries.map((e: any) => e.value)), 0)
  const benchCount = boxData.value.filter((b) => b.tag === 'B' || b.tag === 'B+T').length
  const backtestOnly = boxData.value.length - benchCount
  const sourceTag = sourceMode.value === 'benchmark' ? 'benchmark only'
    : sourceMode.value === 'backtest' ? 'backtest only'
    : benchCount + ' benchmarked · ' + backtestOnly + ' backtest-only'
  const logNote = useLog.value && !effectiveLog.value ? ' · log scale off: values <=0 cannot be shown on a log axis' : ''
  return boxData.value.length + ' strategies · ' + totalRuns + ' runs · ' + totalOut + ' outlier' + (totalOut === 1 ? '' : 's') + ' (|z|>2.5) · ' + sourceTag + logNote
})

const benchOption = computed((): ECOption => {
  const data = boxData.value
  const pointData: any[] = []
  if (showPoints.value) {
    data.forEach((b, i) => {
      b.entries.forEach((e: any, j: number) => {
        const jitter = ((j % 3) - 1) * 0.12
        pointData.push([e.value, i + jitter, b.name, j, jitter, colorOf(e.value), e.src])
      })
    })
  }
  return {
    backgroundColor: 'transparent',
    title: { text: metric.value + ' by strategy', left: 'center', textStyle: { color: '#a89fc4', fontSize: 13, fontWeight: 600 } },
    legend: { textStyle: { color: '#a89fc4' }, bottom: 0, data: showPoints.value ? [metric.value, 'median', 'runs'] : [metric.value, 'median'] },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (p.seriesType === 'boxplot' || p.seriesName === metric.value) {
          const b = data[p.dataIndex]
          const q = b.q as number[]
          return '<b>' + b.name + '</b> [' + b.tag + '] · ' + b.n + ' run' + (b.n === 1 ? '' : 's') + '<br/>'
            + 'min ' + fmtVal(q[0]) + ' · Q1 ' + fmtVal(q[1]) + ' · med ' + fmtVal(q[2]) + ' · Q3 ' + fmtVal(q[3]) + ' · max ' + fmtVal(q[4])
        }
        return '<b>' + p.data[2] + '</b> [' + p.data[6] + '] · run #' + (p.data[3] + 1) + '<br/>value ' + fmtVal(p.data[0])
      }
    },
    grid: { left: 180, right: 60, top: 20, bottom: 40 },
    xAxis: effectiveLog.value
      ? { type: 'log', logBase: 10, axisLabel: { color: '#a89fc4' }, splitLine: { lineStyle: { color: '#241d36' } } }
      : { type: 'value', scale: true, axisLabel: { color: '#a89fc4' }, splitLine: { lineStyle: { color: '#241d36' } } },
    yAxis: {
      type: 'category',
      data: data.map((b) => b.name + '  [' + b.tag + ']'),
      axisLabel: { color: '#a89fc4' }
    },
    series: [
      {
        name: metric.value, type: 'boxplot',
        data: data.map((b) => b.q),
        itemStyle: { color: 'rgba(167, 139, 250, 0.25)', borderColor: '#a78bfa' }
      },
      {
        name: 'median', type: 'scatter',
        symbol: 'diamond', symbolSize: 10,
        data: data.map((b, i) => ({ value: [(b.q as number[])[2], i], itemStyle: { color: b.color, borderColor: '#fff', borderWidth: 1 } })),
        tooltip: { show: false }
      },
      ...(showPoints.value ? [{
        name: 'runs', type: 'scatter',
        symbolSize: 6, symbol: 'circle',
        data: pointData,
        itemStyle: { color: (p: any) => p.data[5], opacity: 0.6, borderColor: '#1a1430', borderWidth: 0.5 }
      }] : [])
    ] as any[]
  }
})

onMounted(() => { store.fetchAll() })
</script>

<style scoped>
.controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 16px; }
.controls label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.controls select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  min-width: 200px;
}
.controls label:has(input[type="checkbox"]) { flex-direction: row; align-items: center; }
.hint { color: var(--text-faint); font-size: 12px; }
</style>
