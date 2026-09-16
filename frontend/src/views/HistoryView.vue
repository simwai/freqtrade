<template>
  <section>
    <div class="section-head">
      <h2>History</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else class="card">
      <div class="controls">
        <label>Strategies
          <select v-model="selected" multiple size="6">
            <option v-for="name in names" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <div class="btn-row">
          <button class="btn-secondary btn-sm" v-on:click="selectAll">Select all</button>
          <button class="btn-secondary btn-sm" v-on:click="selectTop">Top 5</button>
          <button class="btn-secondary btn-sm" v-on:click="clearAll">Clear</button>
        </div>
      </div>

      <div class="chart-box">
        <VChart :option="histOption" autoresize class="chart" style="height: 320px" />
      </div>
    </div>
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
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'

const store = useDashboardStore()
const selected = ref([] as string[])

const names = computed(() => Object.keys(store.history))

const palette = ['#a78bfa', '#c4b5fd', '#22d3ee', '#fbbf24', '#f472b6', '#6ee7a8']

const histOption = computed((): ECOption => {
  const first = selected.value[0] ? (store.history[selected.value[0]] || { dates: [], profit: [] }) : { dates: [], profit: [] }
  return {
    legend: { show: selected.value.length > 1 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: first.dates, axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
    yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
    grid: { left: 50, right: 20, top: 30, bottom: 40 },
    series: selected.value.map((name, i) => {
      const s = store.history[name] || { profit: [] }
      return { name: name, type: 'line', data: s.profit, lineStyle: { color: palette[i % palette.length] }, showSymbol: false }
    })
  }
})

function selectAll() { selected.value = [...names.value] }
function selectTop() { selected.value = names.value.slice(0, 5) }
function clearAll() { selected.value = [] }

onMounted(async () => {
  await store.fetchAll()
  if (!selected.value.length && names.value.length) selected.value = [names.value[0]]
})
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
</style>