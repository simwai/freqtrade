<template>
  <section>
    <div class="section-head">
      <router-link to="/trades" class="back-link">← Back to Trades</router-link>
      <h2>Trade Detail {{ runLabel }}</h2>
    </div>

    <div v-if="loading" class="card">Loading...</div>
    <div v-else-if="error" class="card" style="color: var(--bad);">{{ error }}</div>
    <div v-else class="card">
      <div class="section-head">
        <h2>Trade map</h2>
        <span class="hint">one marker line per trade - entry arrows + exit dots in fixed colours, dashed line = initial stop loss</span>
      </div>
      <div class="controls">
        <label>Pair <select v-model="pair" v-on:change="onPairChange">
          <option v-for="p in pairs" :key="p" :value="p">{{ p }}</option>
        </select></label>
        <label>Exit reason <select v-model="reason" v-on:change="repaint">
          <option value="all">all exits</option>
          <option v-for="r in reasons" :key="r" :value="r">{{ r }}</option>
        </select></label>
        <label>Candles <select v-model="candlePreset" v-on:change="setPreset('candle', candlePreset)">
          <option v-for="(p, k) in candlePresets" :key="k" :value="k">{{ p.name }}</option>
        </select></label>
        <label>Markers <select v-model="markerPreset" v-on:change="setPreset('marker', markerPreset)">
          <option v-for="(p, k) in markerPresets" :key="k" :value="k">{{ p.name }}</option>
        </select></label>
        <label>Exits <select v-model="exitStyleSel" v-on:change="setPreset('exit', exitStyleSel)">
          <option value="by_reason">By reason</option>
          <option value="win_loss">Win / loss</option>
          <option value="single">Single</option>
        </select></label>
        <label>Tracks <select v-model="markModeSel" v-on:change="setPreset('mark', markModeSel)">
          <option value="hilo">Beside candles</option>
          <option value="rate">At trade rates</option>
        </select></label>
        <label>Indicators <select v-model="indPick" v-on:change="addInd">
          <option value="">+ add</option>
          <option v-for="ind in indList" :key="ind.name" :value="ind.name">{{ ind.title }}</option>
        </select></label>
        <button class="btn-secondary btn-sm" v-on:click="fitZoom">Fit</button>
      </div>
      <div class="legend">
        <span class="tl-chips">
          <span v-if="indNote" class="hint warn-note">⚠ {{ indNote }}</span>
          <span v-if="!inds.length" class="hint">no indicators - add up to 3 via the "Indicators" dropdown, controls appear here</span>
          <span v-for="ind in inds" :key="ind.id" class="pill gB">{{ ind.title }}
            <b class="chip-btn" v-on:click="moveInd(ind.id, -1)">↑</b><b class="chip-btn" v-on:click="moveInd(ind.id, 1)">↓</b><b class="chip-btn" v-on:click="removeInd(ind.id)">x</b>
          </span>
          <span v-if="inds.length >= 3" class="hint">max 3 indicators</span>
        </span>
        <span><span class="sw" :style="{ background: mc.entLong }"></span>entry (↑ long · ↓ short)</span>
        <span><span class="sw" :style="{ background: mc.exit }"></span>exit</span>
        <span><span class="sw" style="background:#00d4aa"></span>tp (roi)</span>
        <span><span class="sw" style="background:#ffd60a"></span>trailing</span>
        <span><span class="sw" style="background:#ff4757"></span>stop / liq</span>
        <span><span class="sw" style="background:#00d4aa"></span>signal</span>
        <span><span class="sw" style="background:#ff4757"></span>force / other</span>
        <span><span class="sw" style="background:transparent;border-top:2px dashed #ff4757"></span>initial stop loss</span>
        <span><span class="sw" style="background:transparent;border-top:2px solid #00d4aa"></span>take-profit level</span>
        <span><span class="sw" style="background:rgba(167,139,250,0.4)"></span>volume</span>
      </div>
      <div v-if="note" class="note">{{ note }}</div>
      <div v-if="emptyBanner" class="empty-banner" v-html="emptyBanner"></div>

      <div class="chart-box">
        <VChart ref="tlVChart" :option="tlOption" autoresize class="chart" :style="{ height: mapHeight + 'px' }" />
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
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart, CustomChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, CustomChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import type { ECOption2 } from '../utils/echarts'
import '../utils/echarts'
import {
  tradeMs, tlBisect, tmSuperSmoother, tpPriceForTrade, tlExitColor, markerItem,
  candleColors, markerColors, markMode, exitStyle, persistPreset,
  TL_CANDLE_PRESETS, TL_MARKER_PRESETS, tlTfMs
} from '../utils/trades'
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
const roiCache: Record<string, any> = {}
const candles = ref([] as number[][])
const times = computed(() => candles.value.map((k) => k[0]))
const inds = ref([] as any[])
const indList = ref([] as any[])
const indPick = ref('')
const indSeq = ref(0)
const indNote = ref('')
const pendingIndName = ref('')
const note = ref('')
const emptyBanner = ref('')
const tradeSortKey = ref('o')
const tradeSortAsc = ref(true)
const tlVChart = ref(null as any)
const tradesTableWrap = ref<HTMLElement | null>(null)
const fetchCache = new Map<string, number[][]>()
const loadSeq = ref(0)
const zoomSeq = ref(0)
const appliedZoomKey = ref('')
const fittedPair = ref('')
let zoomTimer: any = null

const candlePreset = ref('lab')
const markerPreset = ref('lab')
const markModeSel = ref('rate')
const exitStyleSel = ref('by_reason')
try {
  candlePreset.value = localStorage.getItem('tlCandlePreset') || 'lab'
  markerPreset.value = localStorage.getItem('tlMarkerPreset') || 'lab'
  markModeSel.value = markMode()
  exitStyleSel.value = exitStyle()
} catch (e) {}
const candlePresets = TL_CANDLE_PRESETS
const markerPresets = TL_MARKER_PRESETS
const mc = computed(() => markerColors())
const cp = computed(() => candleColors())

const IND_COLORS = ['#fbbf24', '#22d3ee', '#f472b6', '#a3e635', '#fb923c', '#e879f9']

const runLabel = computed(() => strategy.value + ' ' + source.value)

const paneInds = computed(() => inds.value.filter((e: any) => e.scale !== 'price'))
const mapHeight = computed(() => 420 + paneInds.value.length * 120)

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

function chartInst(): any {
  try {
    const c = tlVChart.value as any
    if (!c) return null
    return c.chart ?? c
  } catch (e) { return null }
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
    dropAllInds()
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

function candleKey(t0: number, t1: number) {
  return pair.value + '|' + tf.value + '|' + mode.value + '|' + t0 + '|' + t1
}

async function loadCandles() {
  if (!pair.value || !shown.value.length) return
  const ms = shown.value.map((t) => tradeMs(t.o))
  const msC = shown.value.map((t) => tradeMs(t.c))
  let t0 = Math.min(...ms)
  let t1 = Math.max(...msC)
  const pad = Math.max((t1 - t0) * 0.02, 3600e3)
  t0 = Math.round(t0 - pad); t1 = Math.round(t1 + pad)
  const cacheKey = candleKey(t0, t1)
  appliedZoomKey.value = cacheKey
  if (fetchCache.has(cacheKey)) {
    candles.value = fetchCache.get(cacheKey) as number[][]
    note.value = ''
    emptyBanner.value = ''
    afterCandles()
    return
  }
  const mySeq = ++loadSeq.value
  try {
    const { data } = await api.get('/api/candles', { params: { pair: pair.value, timeframe: tf.value, trading_mode: mode.value, start: t0, end: t1 } })
    if (loadSeq.value !== mySeq) return
    if (data && data.candles && data.candles.length) {
      fetchCache.set(cacheKey, data.candles)
      candles.value = data.candles
      note.value = ''
      emptyBanner.value = ''
    } else {
      setEmpty('no-data')
    }
  } catch (e) {
    if (loadSeq.value !== mySeq) return
    fallbackCandles()
  }
  afterCandles()
}

function setEmpty(reasonKind: string) {
  candles.value = []
  fittedPair.value = ''
  if (reasonKind === 'no-data') {
    emptyBanner.value = '<b>No candle data</b> for <b>' + pair.value + '</b> on <b>' + tf.value + '</b> &mdash; entry/exit arrows and the stop-loss line still render, but the candle background is omitted to avoid a misleading chart.'
    indNote.value = 'no candle data for ' + pair.value + ' ' + tf.value + ' - chart omitted, markers still render'
  } else {
    emptyBanner.value = 'Trade map is empty.'
  }
}

function fallbackCandles() {
  if (candles.value.length) return
  const byTime: Record<number, number[]> = {}
  shown.value.forEach((t) => {
    const ts = tradeMs(t.o), o = t.or, c = t.cr
    if (!byTime[ts]) byTime[ts] = [ts, o, Math.max(o, c), Math.min(o, c), c, 0]
    else { const k = byTime[ts]; k[2] = Math.max(k[2], o, c); k[3] = Math.min(k[3], o, c) }
  })
  candles.value = Object.values(byTime).sort((a, b) => a[0] - b[0])
  indNote.value = 'could not load candles - chart approximated from trade prices'
}

function afterCandles() {
  if (pendingIndName.value) { const n = pendingIndName.value; pendingIndName.value = ''; addIndByName(n) }
  if (fittedPair.value !== pair.value) { fitZoom(); fittedPair.value = pair.value }
}

async function loadRoi() {
  const name = strategy.value
  if (!name) { roi.value = null; return }
  if (Object.prototype.hasOwnProperty.call(roiCache, name)) { roi.value = roiCache[name]; return }
  try {
    const { data } = await api.get('/api/tp', { params: { strategy: name } })
    roiCache[name] = (data && data.roi) || null
    roi.value = roiCache[name]
  } catch (e) { roiCache[name] = null; roi.value = null }
}

function onPairChange() {
  fittedPair.value = ''
  loadCandles()
}

function repaint() {}

function setPreset(kind: string, value: string) {
  persistPreset(kind, value)
}

function fitZoom() {
  try { chartInst()?.dispatchAction?.({ type: 'dataZoom', start: 0, end: 100 }) } catch (e) {}
}

function visibleSpan(): number {
  const cs = candles.value
  if (!cs.length) return 0
  try {
    const opt = chartInst()?.getOption?.()
    const dz = opt && opt.dataZoom && opt.dataZoom[0]
    const first = cs[0][0], last = cs[cs.length - 1][0]
    if (dz && dz.startValue != null && dz.endValue != null) {
      return Math.max(0, Number(dz.endValue) - Number(dz.startValue))
    }
    if (dz) {
      const s = dz.start == null ? 0 : dz.start, e = dz.end == null ? 100 : dz.end
      return Math.max(0, (last - first) * (e - s) / 100)
    }
    return last - first
  } catch (e) {
    return cs[cs.length - 1][0] - cs[0][0]
  }
}

function onDataZoom() {
  if (zoomTimer) clearTimeout(zoomTimer)
  zoomTimer = setTimeout(() => { zoomFetch() }, 350)
}

function zoomFetch() {
  const cs = candles.value
  if (!cs.length || !pair.value) return
  let dz: any = null
  try {
    const opt = chartInst()?.getOption?.()
    dz = opt && opt.dataZoom && opt.dataZoom[0]
  } catch (e) { return }
  if (!dz) return
  const first = cs[0][0], last = cs[cs.length - 1][0]
  let v0: number, v1: number
  if (dz.startValue != null && dz.endValue != null) {
    v0 = Math.round(Number(dz.startValue)); v1 = Math.round(Number(dz.endValue))
  } else {
    const s = dz.start == null ? 0 : dz.start, e = dz.end == null ? 100 : dz.end
    v0 = Math.round(first + (last - first) * s / 100)
    v1 = Math.round(first + (last - first) * e / 100)
  }
  if (!Number.isFinite(v0) || !Number.isFinite(v1) || v1 <= v0) return
  if (v1 < first || v0 > last) return
  const midIdx = tlBisect(times.value, (v0 + v1) / 2)
  const a = cs[midIdx]
  const b = cs[Math.min(midIdx + 1, cs.length - 1)]
  const spacing = Math.max(1, b[0] - a[0])
  const tfMs = tlTfMs(tf.value) || spacing
  const covered = v0 >= first && v1 <= last
  const zoomIn = covered && spacing > tfMs * 1.5 && (v1 - v0) < (last - first) * 0.6
  if (covered && !zoomIn) return
  const cacheKey = pair.value + '|' + tf.value + '|' + mode.value + '|' + v0 + '|' + v1
  if (cacheKey === appliedZoomKey.value) return
  appliedZoomKey.value = cacheKey
  const mySeq = ++zoomSeq.value
  const apply = (fine: number[][]) => {
    const inside = fine.filter((k) => k[0] >= v0 && k[0] <= v1)
    const merged = cs.filter((k) => k[0] < v0 || k[0] > v1).concat(inside).sort((x, y) => x[0] - y[0])
    candles.value = merged.length > 20000 ? cs : merged
    refreshInds()
  }
  if (fetchCache.has(cacheKey)) { apply(fetchCache.get(cacheKey) as number[][]); return }
  if (fetchCache.size > 60) {
    for (const k of Array.from(fetchCache.keys())) { if (k !== cacheKey) fetchCache.delete(k) }
  }
  api.get('/api/candles', { params: { pair: pair.value, timeframe: tf.value, trading_mode: mode.value, start: v0, end: v1 } })
    .then(({ data }: any) => {
      if (zoomSeq.value !== mySeq) return
      if (data && data.candles && data.candles.length) {
        fetchCache.set(cacheKey, data.candles)
        apply(data.candles)
      }
    }).catch(() => {})
}

function indParse(s: any) {
  return s.times.map((t: number, i: number) => s.values[i] == null ? [t, null] : [t, s.values[i]])
}

async function addInd() {
  const name = indPick.value
  indPick.value = ''
  if (name) addIndByName(name)
}

async function addIndByName(name: string) {
  if (!name || inds.value.some((x: any) => x.name === name)) return
  if (inds.value.length >= 3) return
  if (!candles.value.length || !pair.value) { pendingIndName.value = name; return }
  const t0 = candles.value[0][0]
  const t1 = candles.value[candles.value.length - 1][0]
  try {
    const { data } = await api.get('/api/indicator', { params: { name: name, pair: pair.value, timeframe: tf.value, trading_mode: mode.value, start: t0, end: t1 } })
    if (data.error || !data.series || !data.series.length) { indNote.value = name + ': no data for ' + pair.value + ' ' + tf.value + ' in this window'; return }
    if (inds.value.length >= 3) return
    indNote.value = ''
    inds.value.push({
      id: name + '#' + (++indSeq.value),
      name: name,
      title: data.title || name,
      scale: data.scale,
      colors: data.series.map((_: any, si: number) => IND_COLORS[(inds.value.length + si) % IND_COLORS.length]),
      cfg: data.series.map((s: any) => ({ data: indParse(s) }))
    })
  } catch (e) { indNote.value = name + ': failed to load' }
}

function removeInd(id: string) {
  inds.value = inds.value.filter((x: any) => x.id !== id)
}

function moveInd(id: string, dir: number) {
  const idx = inds.value.findIndex((x: any) => x.id === id)
  const j = idx + dir
  if (idx < 0 || j < 0 || j >= inds.value.length) return
  const moved = inds.value.splice(idx, 1)[0]
  inds.value.splice(j, 0, moved)
}

function dropAllInds() {
  inds.value = []
  indNote.value = ''
  pendingIndName.value = ''
}

async function refreshInds() {
  if (!inds.value.length || !candles.value.length || !pair.value) return
  const t0 = candles.value[0][0], t1 = candles.value[candles.value.length - 1][0]
  inds.value.forEach((e: any) => {
    api.get('/api/indicator', { params: { name: e.name, pair: pair.value, timeframe: tf.value, trading_mode: mode.value, start: t0, end: t1 } })
      .then(({ data }: any) => {
        if (data.error || !data.series) return
        e.cfg = data.series.map((s: any) => ({ data: indParse(s) }))
      }).catch(() => {})
  })
}

function fmtTt(v: any, d = 3) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: d })
}

function tooltipFormatter(ps: any) {
  const arr = Array.isArray(ps) ? ps : [ps]
  const p = arr.find((x: any) => x.seriesType === 'candlestick')
  if (!p) return ''
  const ms = Math.round(p.axisValue)
  let html = ''
  const cs = candles.value
  if (cs.length) {
    const k = cs[tlBisect(times.value, ms)]
    if (k && Math.abs(k[0] - ms) < 12 * 3600e3) {
      const dt = new Date(k[0]).toISOString().slice(0, 16).replace('T', ' ')
      html += '<b>' + dt + '</b><br/>O ' + fmtTt(k[1]) + ' H ' + fmtTt(k[2]) + '<br/>L ' + fmtTt(k[3]) + ' C ' + fmtTt(k[4]) + '<br/>'
    }
  }
  shown.value.filter((t) => tradeMs(t.o) <= ms && tradeMs(t.c) >= ms).slice(0, 6).forEach((t) => {
    const pc = (t.pr || 0) >= 0 ? mc.value.win : mc.value.loss
    html += '<hr style="border:0;border-top:1px solid #2f2745;margin:4px 0" />'
      + '<b>' + t.p + '</b> ' + (t.s ? 'short' : 'long') + ' | ' + (t.e || 'unknown') + '<br/>'
      + fmtTt(t.or) + ' -&gt; ' + fmtTt(t.cr) + ' | <b style="color:' + pc + '">' + ((t.pr || 0) * 100).toFixed(2) + '%</b>'
  })
  return html
}

const tlOption = computed((): any => {
  const cs: number[][] = candles.value
  const tm = times.value
  const mcolors = mc.value
  const ccolors = cp.value
  const hilo = markModeSel.value === 'hilo' && cs.length > 0
  const style = exitStyleSel.value
  const candleData = cs.map((k) => [k[0], k[1], k[4], k[3], k[2]])
  const volData = cs.map((k) => ({ value: [k[0], k[5] || 0], itemStyle: { color: k[4] >= k[1] ? 'rgba(110,231,168,0.30)' : 'rgba(248,113,113,0.30)' } }))
  const markers: any[] = []
  const underPts: any[] = []
  const overPts: any[] = []
  const longRatePts: any[] = []
  const shortRatePts: any[] = []
  const slPts: any[] = []
  const tpPts: any[] = []
  const underSegs: any[] = []
  const overSegs: any[] = []
  let underEnd: any = null, overEnd: any = null, winEnd: any = null, lossEnd: any = null, slPrevEnd: any = null

  shown.value.forEach((t) => {
    const t0 = tradeMs(t.o), t1 = tradeMs(t.c)
    const i0 = cs.length ? tlBisect(tm, t0) : -1
    const i1 = cs.length ? tlBisect(tm, t1) : -1
    const lo0 = cs.length ? Math.min(cs[i0][1], cs[i0][4]) : t.or
    const hi0 = cs.length ? Math.max(cs[i0][1], cs[i0][4]) : t.or
    const lo1 = cs.length ? Math.min(cs[i1][1], cs[i1][4]) : t.cr
    const hi1 = cs.length ? Math.max(cs[i1][1], cs[i1][4]) : t.cr
    const fills = t.px && t.px.length > 2 ? t.px : null

    if (fills) {
      let lastExit = -1
      fills.forEach((f: any, fi: number) => { if (!f[3]) lastExit = fi })
      fills.forEach((f: any, fi: number) => {
        const i = cs.length ? tlBisect(tm, f[0]) : -1
        const lo = cs.length ? Math.min(cs[i][1], cs[i][4]) : f[1]
        const hi = cs.length ? Math.max(cs[i][1], cs[i][4]) : f[1]
        if (f[3]) { markers.push([f[0], t.s ? hi * 1.005 : lo * 0.995, t.s ? 1 : 0, mcolors.entLong, '']) } else {
          const txt = fi === lastExit ? ((t.pr || 0) * 100).toFixed(1) + '%' : ''
          markers.push([f[0], t.s ? lo * 0.99 : hi * 1.01, t.s ? 3 : 2, tlExitColor(t, style, mcolors), txt])
        }
      })
    } else {
      markers.push([t0, t.s ? hi0 * 1.005 : lo0 * 0.995, t.s ? 1 : 0, mcolors.entLong, ''])
      markers.push([t1, t.s ? lo1 * 0.99 : hi1 * 1.01, t.s ? 3 : 2, tlExitColor(t, style, mcolors), ((t.pr || 0) * 100).toFixed(1) + '%'])
    }

    const spanOk = cs.length > 0 && i0 >= 0 && i1 >= i0 && i1 < cs.length && t0 >= tm[0] && t1 <= tm[tm.length - 1] + 300000
    const slOk = spanOk || (cs.length === 0 && (t as any).isl != null)
    if (spanOk) {
      if (hilo) {
        const segs = t.s ? overSegs : underSegs
        let end = t.s ? overEnd : underEnd
        const start = tm[i0]
        if (end == null || start > end) {
          const raw: number[] = []
          for (let i = i0; i <= i1; i++) {
            const bodyLo = Math.min(cs[i][1], cs[i][4]) * 0.975
            const bodyHi = Math.max(cs[i][1], cs[i][4]) * 1.025
            raw.push(t.s ? bodyHi : bodyLo)
          }
          segs.push({ t: tm.slice(i0, i1 + 1), raw: raw })
          end = tm[i1]
        }
        if (t.s) overEnd = end; else underEnd = end
      } else {
        const win = (t.pr || 0) >= 0
        const seg = win ? longRatePts : shortRatePts
        let end = win ? winEnd : lossEnd
        if (end == null || t0 > end) {
          if (end != null) seg.push([Math.round((end + t0) / 2), null])
          seg.push([t0, t.or], [t1, t.cr])
          end = t1
        }
        if (win) winEnd = end; else lossEnd = end
      }
    }

    let sl: any = (t as any).isl, r: any = (t as any).islr
    if (sl == null || (r != null && Math.abs(r) > 0.35)) { sl = t.sl; r = t.slr }
    if (slOk && sl != null && sl > 0 && !(r != null && Math.abs(r) > 0.35)) {
      const pad = Math.max(0, (visibleSpan() * 0.008 - (t1 - t0)) / 2)
      const a = Math.round(t0 - pad), b = Math.round(t1 + pad)
      if (slPrevEnd == null || a > slPrevEnd) {
        if (slPrevEnd != null) slPts.push([Math.round((slPrevEnd + a) / 2), null])
        slPts.push([a, sl], [b, sl])
        slPrevEnd = b
      }
    }

    if (slOk) {
      const tp = tpPriceForTrade(t, roi.value)
      if (tp != null) tpPts.push([t0, tp], [t1, tp])
    }
  })

  const smoothJoin = (segs: any[], pts: any[]) => {
    segs.forEach((sg: any, gi: number) => {
      if (gi > 0) {
        const prevLast = segs[gi - 1].t[segs[gi - 1].t.length - 1]
        pts.push([Math.round((prevLast + sg.t[0]) / 2), null])
      }
      const sm = tmSuperSmoother(sg.raw)
      sg.t.forEach((tt: number, k: number) => pts.push([tt, sm[k]]))
    })
  }
  smoothJoin(underSegs, underPts)
  smoothJoin(overSegs, overPts)

  markers.sort((a: any, b: any) => a[0] - b[0])

  const priceOverlays = inds.value.filter((e: any) => e.scale === 'price')
  const oscillatorInds = inds.value.filter((e: any) => e.scale !== 'price')

  const mainH = 300
  const paneH = 104
  const gap = 14
  const grids: any[] = [{ top: 10, left: 10, right: 62, height: mainH }]
  const xAxes: any[] = [{
    type: 'time', gridIndex: 0,
    axisLine: { lineStyle: { color: '#2f2745' } },
    axisTick: { show: false }, splitLine: { show: false },
    axisLabel: oscillatorInds.length ? { show: false } : { color: '#a89fc4', fontSize: 11, hideOverlap: true }
  }]
  const yAxes: any[] = [
    { gridIndex: 0, position: 'right', scale: true, axisLine: { show: false }, axisLabel: { color: '#a89fc4', fontSize: 11 }, splitLine: { lineStyle: { color: '#241d36' } } },
    { gridIndex: 0, show: false, max: (v: any) => (v.max || 1) * 6 }
  ]
  oscillatorInds.forEach((_: any, i: number) => {
    const top = 10 + mainH + gap + i * (paneH + gap)
    grids.push({ top: top, left: 10, right: 62, height: paneH })
    const last = i === oscillatorInds.length - 1
    xAxes.push({ type: 'time', gridIndex: i + 1, show: last, axisLine: { lineStyle: { color: '#2f2745' } }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: '#a89fc4', fontSize: 11, hideOverlap: true } })
    yAxes.push({ gridIndex: i + 1, position: 'right', scale: true, axisLine: { show: false }, axisLabel: { color: '#a89fc4', fontSize: 10 }, splitLine: { lineStyle: { color: '#241d36' } } })
  })
  const axisCount = oscillatorInds.length + 1
  const axisIdx = Array.from({ length: axisCount }, (_: any, i: number) => i)

  const series: any[] = [
    {
      type: 'candlestick', z: 2, xAxisIndex: 0, yAxisIndex: 0,
      data: candleData,
      itemStyle: { color: ccolors.up, color0: ccolors.down, borderColor: ccolors.upB, borderColor0: ccolors.downB }
    },
    { type: 'bar', xAxisIndex: 0, yAxisIndex: 1, z: 1, silent: true, data: volData },
    { type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, emphasis: { disabled: true }, lineStyle: { width: 2, color: mcolors.entLong }, data: underPts },
    { type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, emphasis: { disabled: true }, lineStyle: { width: 2, color: mcolors.entShort }, data: overPts },
    { type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, emphasis: { disabled: true }, lineStyle: { width: 2, color: mcolors.entLong }, data: hilo ? [] : longRatePts },
    { type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, emphasis: { disabled: true }, lineStyle: { width: 2, color: mcolors.entShort }, data: hilo ? [] : shortRatePts },
    { type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, z: 3, lineStyle: { width: 2, type: 'dashed', color: mcolors.loss }, data: slPts },
    { type: 'custom', xAxisIndex: 0, yAxisIndex: 0, z: 12, silent: true, renderItem: (params: any, api: any) => markerItem(params, api), encode: { x: 0, y: 1 }, data: markers }
  ]
  if (tpPts.length) {
    tpPts.sort((a: any, b: any) => a[0] - b[0])
    series.push({ type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, z: 2, lineStyle: { width: 1, type: 'solid', color: mcolors.win + '88' }, data: tpPts })
  }
  priceOverlays.forEach((e: any) => {
    e.cfg.forEach((s: any, si: number) => series.push({ type: 'line', xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, silent: true, lineStyle: { width: 1.5, color: e.colors[si] }, data: s.data }))
  })
  oscillatorInds.forEach((e: any, i: number) => {
    e.cfg.forEach((s: any, si: number) => series.push({ type: 'line', xAxisIndex: i + 1, yAxisIndex: 2 + i, showSymbol: false, silent: true, lineStyle: { width: 1.5, color: e.colors[si] }, data: s.data }))
  })

  return {
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [{ type: 'inside', xAxisIndex: axisIdx }],
    tooltip: { trigger: 'axis', confine: true, formatter: (ps: any) => tooltipFormatter(ps) },
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

function attachZoom() {
  try {
    const inst = chartInst()
    const target = inst?.chart ?? inst
    if (target && target.on && !((target as any).__tlZoomBound)) {
      (target as any).__tlZoomBound = true
      target.on('datazoom', () => { onDataZoom() })
    }
  } catch (e) {}
}

onMounted(async () => {
  await load()
  await nextTick()
  attachZoom()
  if (tradesTableWrap.value) {
    tradesTableWrap.value.addEventListener('scroll', () => {
      const tw = tradesTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
})

onUnmounted(() => {
  if (zoomTimer) clearTimeout(zoomTimer)
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
.legend { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; font-size: 11px; color: var(--text-dim); margin-bottom: 8px; }
.legend .sw { display: inline-block; width: 14px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: baseline; }
.tl-chips { display: contents; }
.chip-btn { cursor: pointer; padding: 0 3px; font-weight: 400; }
.chip-btn:hover { color: #fff; }
.warn-note { color: var(--warn, #fbbf24); }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.note { color: var(--text-faint); font-size: 12px; margin: 8px 0; }
.empty-banner { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; font-size: 12px; margin-bottom: 8px; }
.empty-banner code { font-family: monospace; }
</style>
