<template>
  <section>
    <div class="section-head">
      <h2>Benchmark</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else class="card">
      <div class="table-wrap table-stack">
        <div class="thead-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" v-on:click="sortBy('strategy')">Strategy <span class="arrow" v-if="sortKey==='strategy'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('source')">Source <span class="arrow" v-if="sortKey==='source'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('profit_total')" class="num">Profit <span class="arrow" v-if="sortKey==='profit_total'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('total_trades')" class="num">Trades <span class="arrow" v-if="sortKey==='total_trades'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('sortino')" class="num">Sortino <span class="arrow" v-if="sortKey==='sortino'">{{ sortAsc ? '▲' : '▼' }}</span></th>
              </tr>
            </thead>
          </table>
        </div>
        <div class="table-wrap" ref="benchTableWrap">
          <table>
            <tbody>
              <tr v-for="b in sortedBenchmarks" :key="b.strategy + b.source">
                <td>{{ b.strategy }}</td>
                <td>{{ b.source }}</td>
                <td class="num" :class="profitClass(b.profit_total)">{{ fmtNum(b.profit_total) }}</td>
                <td class="num">{{ b.total_trades }}</td>
                <td class="num">{{ fmtNum(b.sortino) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="chart-box">
        <VChart :option="benchOption" autoresize class="chart" style="height: 320px" />
      </div>
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
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'

const store = useDashboardStore()
const sortKey = ref('profit_total')
const sortAsc = ref(false)
const benchTableWrap = ref<HTMLElement | null>(null)

const sortedBenchmarks = computed(() => {
  const arr = [...store.benchmarks]
  arr.sort((a: any, b: any) => {
    let av = a[sortKey.value]
    let bv = b[sortKey.value]
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

function sortBy(key: string) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = true }
}
function profitClass(v: number) { if (!v) return ''; return v > 0 ? 'good' : v < 0 ? 'bad' : '' }
function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—' }

const benchOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: sortedBenchmarks.value.map((b: any) => b.strategy), axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'line', data: sortedBenchmarks.value.map((b: any) => b.profit_total || 0), lineStyle: { color: '#a78bfa' }, showSymbol: false }]
}))

onMounted(async () => {
  await store.fetchAll()
  await nextTick()
  if (benchTableWrap.value) {
    benchTableWrap.value.addEventListener('scroll', () => {
      const tw = benchTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
})
</script>