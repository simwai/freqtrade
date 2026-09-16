<template>
  <section>
    <div class="section-head">
      <router-link to="/trades" class="back-link">← Back to Trades</router-link>
      <h2>Trade Detail {{ runLabel }}</h2>
    </div>

    <div v-if="loading" class="card">Loading...</div>
    <div v-else-if="error" class="card" style="color: var(--bad);">{{ error }}</div>
    <div v-else class="card">
      <div class="controls">
        <label>Pair <select v-model="pair" v-on:change="onPairChange">
          <option v-for="p in pairs" :key="p" :value="p">{{ p }}</option>
        </select></label>
        <label>Exit reason <select v-model="reason" v-on:change="repaint">
          <option value="all">all exits</option>
          <option v-for="r in reasons" :key="r" :value="r">{{ r }}</option>
        </select></label>
        <label>Indicators <select v-model="indPick" v-on:change="addInd">
          <option value="">+ add</option>
          <option v-for="ind in indList" :key="ind.name" :value="ind.name">{{ ind.title }}</option>
        </select></label>
        <span class="active-inds">
          <span v-for="ind in inds" :key="ind.name" class="ind-tag">{{ ind.title }} <button v-on:click="removeInd(ind.name)">×</button></span>
        </span>
      </div>
      <div v-if="note" class="note">{{ note }}</div>

      <div class="chart-box">
        <VChart :option="tlOption" autoresize class="chart" style="height: 420px" />
      </div>

      <div class="chart-box">
        <h3>Equity</h3>
        <VChart :option="equityOption" autoresize class="chart" style="height: 280px" />
      </div>

      <div class="chart-box">
        <h3>Profit histogram</h3>
        <VChart :option="histOption" autoresize class="chart" style="height: 280px" />
      </div>

      <div class="card">
        <h3>Trades {{ trades.length }}</h3>
        <div class="table-wrap table-stack">
          <div class="thead-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col" v-on:click="sortTrades('p')">Pair <span class="arrow" v-if="tradeSortKey==='p'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('s')">Side <span class="arrow" v-if="tradeSortKey==='s'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('t')">Enter tag <span class="arrow" v-if="tradeSortKey==='t'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('e')">Exit reason <span class="arrow" v-if="tradeSortKey==='e'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('o')" class="num">Open <span class="arrow" v-if="tradeSortKey==='o'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('c')" class="num">Close <span class="arrow" v-if="tradeSortKey==='c'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('or')" class="num">Open rate <span class="arrow" v-if="tradeSortKey==='or'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('cr')" class="num">Close rate <span class="arrow" v-if="tradeSortKey==='cr'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('pr')" class="num">Profit% <span class="arrow" v-if="tradeSortKey==='pr'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('pa')" class="num">Profit abs <span class="arrow" v-if="tradeSortKey==='pa'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('sl')" class="num">Stop loss <span class="arrow" v-if="tradeSortKey==='sl'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('slr')" class="num">SL% <span class="arrow" v-if="tradeSortKey==='slr'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortTrades('d')" class="num">Duration <span class="arrow" v-if="tradeSortKey==='d'">{{ tradeSortAsc ? '▲' : '▼' }}</span></th>
                </tr>
              </thead>
            </table>
          </div>
          <div class="table-wrap" ref="tradesTableWrap">
            <table>
              <tbody>
                <tr v-for="t in sortedTrades" :key="t.o + t.c + t.p">
                  <td>{{ t.p }}</td>
                  <td><span :class="sideClass(t.s)">{{ t.s ? 'short' : 'long' }}</span></td>
                  <td>{{ t.t }}</td>
                  <td>{{ t.e }}</td>
                  <td class="num">{{ t.o }}</td>
                  <td class="num">{{ t.c }}</td>
                  <td class="num">{{ fmtNum(t.or) }}</td>
                  <td class="num">{{ fmtNum(t.cr) }}</td>
                  <td class="num" :class="profitClass(t.pr)">{{ ((t.pr || 0) * 100).toFixed(2) }}%</td>
                  <td class="num">{{ fmtNum(t.pa) }}</td>
                  <td class="num">{{ fmtNum(t.sl) }}</td>
                  <td class="num">{{ (t.slr || 0) * 100 }}%</td>
                  <td class="num">{{ durText(t) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import type { ECOption2 } from '../utils/echarts'
import '../utils/echarts'
import { tradeMs, tlBisect, tpPriceForTrade, tlExitColor, markerItem, MARK } from '../utils/trades'
import type { CompactTrade } from '../utils/trades'

const route = useRoute()
const store = useDashboardStore()
const key = route.params.key as string
const loading = ref(true)
const error = ref('')
const strategy = ref('')
const source = ref('')
const trades = ref([] as CompactTrade[])
const pair = ref('')
const reason = ref('all')
const tf = ref('5m')
const mode = ref('')
const roi = ref(null as any)
const candles = ref([] as number[][])
const inds = ref([] as any[])
const indList = ref([] as any[])
const indPick = ref('')
const note = ref('')
const tradeSortKey = ref('o')
const tradeSortAsc = ref(true)
const tradesTableWrap = ref<HTMLElement | null>(null)

const runLabel = computed(() => strategy.value + ' ' + source.value)

const pairs = computed(() => {
  const m: Record<string, number> = {}
  trades.value.forEach((t) => { m[t.p] = (m[t.p] || 0) + 1 })
  return Object.keys(m).sort((a, b) => m[b] - m[a])
})

const reasons = computed(() => Array.from(new Set(trades.value.filter((t) => !pair.value || t.p === pair.value).map((t) => t.e || 'unknown'))))

const shown = computed(() => trades.value.filter((t) => {
  if (pair.value && t.p !== pair.value) return false
  if (reason.value !== 'all' && (t.e || 'unknown') !== reason.value) return false
  return t.o && t.c && t.or != null && t.cr != null
}).sort((a, b) => tradeMs(a.o) - tradeMs(b.o)))

function durText(t: any) {
  if (!t.d) return '--'
  return Math.floor(t.d / 3600) + 'h' + Math.round((t.d % 3600) / 60) + 'm'
}

async function load() {
  loading.value = true
  try {
    await store.fetchAll()
    const { data } = await api.get('/trades/' + key + '.json')
    strategy.value = data.strategy || ''
    source.value = data.source || ''
    trades.value = data.trades || []
    const runRow = store.backtests.find((r: any) => r.strategy === strategy.value) || store.benchmarks.find((r: any) => r.strategy === strategy.value)
    if (runRow) { tf.value = runRow.timeframe || '5m'; mode.value = runRow.trading_mode || '' }
    if (!pair.value && pairs.value.length) pair.value = pairs.value[0]
    await loadCandles()
    await loadRoi()
    const { data: il } = await api.get('/api/indicators')
    indList.value = il
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
}

async function loadCandles() {
  if (!pair.value || !shown.value.length) return
  const ms = shown.value.map((t) => tradeMs(t.o))
  let t0 = Math.min(...ms)
  let t1 = Math.max(...ms)
  const pad = Math.max((t1 - t0) * 0.02, 3600e3)
  t0 = Math.round(t0 - pad); t1 = Math.round(t1 + pad)
  try {
    const { data } = await api.get('/api/candles', { params: { pair: pair.value, timeframe: tf.value, trading_mode: mode.value, start: t0, end: t1 } })
    if (data && data.candles && data.candles.length) { candles.value = data.candles; note.value = '' } else { candles.value = []; note.value = 'no candle data' }
  } catch (e) { candles.value = []; note.value = 'no candle data' }
}

async function loadRoi() {
  try {
    const { data } = await api.get('/api/tp', { params: { strategy: strategy.value } })
    roi.value = (data && data.roi) || null
  } catch (e) { roi.value = null }
}

function onPairChange() { loadCandles() }
function repaint() {}

const IND_COLORS = ['#fbbf24', '#22d3ee', '#f472b6']

async function addInd() {
  const name = indPick.value
  indPick.value = ''
  if (!name || inds.value.some((x: any) => x.name === name)) return
  if (inds.value.length >= 3) return
  if (!candles.value.length || !pair.value) return
  const t0 = candles.value[0][0]
  const t1 = candles.value[candles.value.length - 1][0]
  try {
    const { data } = await api.get('/api/indicator', { params: { name: name, pair: pair.value, timeframe: tf.value, trading_mode: mode.value, start: t0, end: t1 } })
    if (data.error || !data.series || !data.series.length) { note.value = name + ': no data'; return }
    inds.value.push({ name: name, title: data.title || name, scale: data.scale, color: IND_COLORS[inds.value.length % IND_COLORS.length], cfg: data.series.map((s: any) => ({ data: s.times.map((t: number, i: number) => [t, s.values[i]]) })) })
  } catch (e) { note.value = name + ': failed to load' }
}

function removeInd(name: string) { inds.value = inds.value.filter((x: any) => x.name !== name) }

const tlOption = computed((): ECOption2 => {
  const cs: number[][] = candles.value
  const times: number[] = cs.map((k) => k[0])
  const candleData = cs.map((k) => [k[0], k[1], k[4], k[3], k[2]])
  const volData = cs.map((k) => ({ value: [k[0], k[5] || 0], itemStyle: { color: k[4] >= k[1] ? 'rgba(110,231,168,0.30)' : 'rgba(248,113,113,0.30)' } }))
  const markers: any[] = []
  const winPts: any[] = []
  const lossPts: any[] = []
  const slPts: any[] = []
  const tpPts: any[] = []
  let winEnd: any = null, lossEnd: any = null, slPrevEnd: any = null

  shown.value.forEach((t) => {
    const t0 = tradeMs(t.o), t1 = tradeMs(t.c)
    const i0 = cs.length ? tlBisect(times, t0) : -1
    const i1 = cs.length ? tlBisect(times, t1) : -1
    const lo0 = cs.length ? Math.min(cs[i0][1], cs[i0][4]) : t.or
    const hi0 = cs.length ? Math.max(cs[i0][1], cs[i0][4]) : t.or
    const lo1 = cs.length ? Math.min(cs[i1][1], cs[i1][4]) : t.cr
    const hi1 = cs.length ? Math.max(cs[i1][1], cs[i1][4]) : t.cr
    const fills = t.px && t.px.length > 2 ? t.px : null

    if (fills) {
      let lastExit = -1
      fills.forEach((f: any, fi: number) => { if (!f[3]) lastExit = fi })
      fills.forEach((f: any, fi: number) => {
        const i = cs.length ? tlBisect(times, f[0]) : -1
        const lo = cs.length ? Math.min(cs[i][1], cs[i][4]) : f[1]
        const hi = cs.length ? Math.max(cs[i][1], cs[i][4]) : f[1]
        if (f[3]) { markers.push([f[0], t.s ? hi * 1.005 : lo * 0.995, t.s ? 1 : 0, MARK.entLong, '']) } else {
          const txt = fi === lastExit ? ((t.pr || 0) * 100).toFixed(1) + '%' : ''
          markers.push([f[0], t.s ? lo * 0.99 : hi * 1.01, t.s ? 3 : 2, tlExitColor(t), txt])
        }
      })
    } else {
      markers.push([t0, t.s ? hi0 * 1.005 : lo0 * 0.995, t.s ? 1 : 0, MARK.entLong, ''])
      markers.push([t1, t.s ? lo1 * 0.99 : hi1 * 1.01, t.s ? 3 : 2, tlExitColor(t), ((t.pr || 0) * 100).toFixed(1) + '%'])
    }

    const spanOk = cs.length > 0 && i0 >= 0 && i1 >= i0 && i1 < cs.length && t0 >= times[0] && t1 <= times[times.length - 1] + 300000
    if (spanOk) {
      const win = (t.pr || 0) >= 0
      const seg = win ? winPts : lossPts
      let end = win ? winEnd : lossEnd
      if (end == null || t0 > end) {
        if (end != null) seg.push([Math.round((end + t0) / 2), null])
        seg.push([t0, t.or], [t1, t.cr])
        end = t1
      }
      if (win) winEnd = end; else lossEnd = end
    }

    let sl: any = t.isl, r: any = t.islr
    if (sl == null || (r != null && Math.abs(r) > 0.35)) { sl = t.sl; r = t.slr }
    if (sl != null && sl > 0 && !(r != null && Math.abs(r) > 0.35)) {
      if (slPrevEnd == null || t0 - 0 > slPrevEnd) {
        if (slPrevEnd != null) slPts.push([Math.round((slPrevEnd + t0) / 2), null])
        slPts.push([t0, sl], [t1, sl])
        slPrevEnd = t1
      }
    }

    const tp = tpPriceForTrade(t, roi.value)
    if (tp != null) tpPts.push([t0, tp], [t1, tp])
  })

  markers.sort((a: any, b: any) => a[0] - b[0])

  const series: any[] = [
    { type: 'candlestick', z: 2, data: candleData },
    { type: 'bar', yAxisIndex: 1, z: 1, silent: true, data: volData },
    { type: 'line', showSymbol: false, silent: true, data: winPts },
    { type: 'line', showSymbol: false, silent: true, data: lossPts },
    { type: 'line', showSymbol: false, silent: true, z: 3, lineStyle: { width: 2, type: 'dashed' }, data: slPts },
    { type: 'custom', z: 12, silent: true, renderItem: (params: any, api: any) => markerItem(params, api), encode: { x: 0, y: 1 }, data: markers },
    { type: 'line', showSymbol: false, silent: true, z: 2, data: tpPts }
  ]

  inds.value.forEach((e: any) => {
    e.cfg.forEach((s: any) => series.push({ type: 'line', showSymbol: false, silent: true, data: s.data }))
  })

  return {
    animation: false,
    grid: { top: 10, left: 10, right: 62, bottom: 26 },
    xAxis: [{ type: 'time' }],
    yAxis: [{ position: 'right', scale: true }, { show: false }],
    dataZoom: [{ type: 'inside', xAxisIndex: 0 }],
    tooltip: { trigger: 'axis' },
    series: series
  }
})

const equityOption = computed((): ECOption2 => {
  const chrono = trades.value.filter((t) => t && t.c).sort((a, b) => String(a.c).localeCompare(String(b.c)))
  let cum = 0
  const points = chrono.map((t) => { cum += (t.pa || 0); return [t.c, Math.round(cum * 100) / 100] })
  return {
    grid: { left: 70, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
    yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 6 }],
    series: [{ name: 'Cumulative profit', type: 'line', showSymbol: false, data: points, lineStyle: { color: '#a78bfa' } }]
  }
})

const histOption = computed((): ECOption2 => {
  const profits = trades.value.map((t) => t.pr).filter((v) => v !== null && v !== undefined)
  if (!profits.length) return { series: [] }
  const min = Math.min(...profits)
  const max = Math.max(...profits)
  const bins = 40
  const width = (max - min) || 1
  const counts = new Array(bins).fill(0)
  profits.forEach((v) => { let i = Math.floor((v - min) / width * bins); if (i === bins) i = bins - 1; counts[i]++ })
  const labels = counts.map((_, i) => { const lo = min + i * width / bins, hi = lo + width / bins; return (((lo + hi) / 2 * 100).toFixed(1) + '%') })
  return {
    grid: { left: 50, right: 16, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: labels, axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } } },
    yAxis: { type: 'value', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
    series: [{ name: 'Trades', type: 'bar', data: counts, itemStyle: { color: '#a78bfa' } }]
  }
})

function sortTrades(key: string) {
  if (tradeSortKey.value === key) tradeSortAsc.value = !tradeSortAsc.value
  else { tradeSortKey.value = key; tradeSortAsc.value = true }
}

const sortedTrades = computed(() => {
  const arr = [...shown.value]
  arr.sort((a: any, b: any) => {
    let av = a[tradeSortKey.value]
    let bv = b[tradeSortKey.value]
    if (av === undefined && bv === undefined) return 0
    if (av === '' || av === undefined || av === null) return tradeSortAsc.value ? 1 : -1
    if (bv === '' || bv === undefined || bv === null) return tradeSortAsc.value ? -1 : 1
    const an = Number(av), bn = Number(bv)
    const useNum = !isNaN(an) && !isNaN(bn)
    const r = useNum ? an - bn : String(av).localeCompare(String(bv))
    return tradeSortAsc.value ? r : -r
  })
  return arr
})

function sideClass(s: number | boolean) { return s ? 'status retired' : 'status active' }
function profitClass(v: number) { if (!v) return ''; return v > 0 ? 'good' : v < 0 ? 'bad' : '' }
function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—' }

onMounted(async () => {
  await load()
  await nextTick()
  if (tradesTableWrap.value) {
    tradesTableWrap.value.addEventListener('scroll', () => {
      const tw = tradesTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
})
</script>

<style scoped>
.back-link { color: var(--text-dim); font-size: 13px; text-decoration: none; }
.back-link:hover { color: var(--lavender); }
.controls { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 16px; }
.controls label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.controls select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  min-width: 140px;
}
.active-inds { display: flex; gap: 8px; flex-wrap: wrap; }
.ind-tag { display: inline-flex; align-items: center; gap: 4px; background: var(--bg-soft); border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; font-size: 11px; }
.ind-tag button { background: none; border: none; color: var(--text-faint); cursor: pointer; font-size: 12px; padding: 0 2px; }
.ind-tag button:hover { color: var(--bad); }
.note { color: var(--text-faint); font-size: 12px; margin: 8px 0; }
</style>