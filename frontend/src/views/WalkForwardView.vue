<template>
  <section>
    <div class="section-head">
      <h2>WalkForward</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else>
      <div class="card filters">
        <input v-model="q" placeholder="filter" class="filter-input" />
        <div>{{ filtered.length }} / {{ store.walkforward.length }} runs</div>
      </div>

      <div class="card">
        <div class="table-wrap table-stack">
          <div class="thead-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col" v-on:click="sortBy('strategy')">Strategy <span class="arrow" v-if="sortKey==='strategy'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('run_id')" class="num">Run <span class="arrow" v-if="sortKey==='run_id'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('timerange')" class="num">Date Range <span class="arrow" v-if="sortKey==='timerange'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('n_windows')" class="num">Windows <span class="arrow" v-if="sortKey==='n_windows'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('profitable_windows')" class="num">Profitable <span class="arrow" v-if="sortKey==='profitable_windows'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('oos_trades')" class="num">OOS Trades <span class="arrow" v-if="sortKey==='oos_trades'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('oos_profit_abs')" class="num">OOS Profit <span class="arrow" v-if="sortKey==='oos_profit_abs'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('avg_oos_sortino')" class="num">Avg Sortino <span class="arrow" v-if="sortKey==='avg_oos_sortino'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('avg_oos_profit_factor')" class="num">Avg PF <span class="arrow" v-if="sortKey==='avg_oos_profit_factor'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('loss_function')">Loss <span class="arrow" v-if="sortKey==='loss_function'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                </tr>
              </thead>
            </table>
          </div>
          <div class="table-wrap" ref="wfTableWrap">
            <table>
              <tbody>
                <tr v-for="r in sortedFiltered" :key="r.source" v-on:click="drill(r.source)" :style="selected === r.source ? 'background:var(--card-hover)' : ''">
                  <td>{{ r.strategy }}</td>
                  <td class="num" :title="r.source || ''">{{ (r.run_id || r.source || '').slice(0, 18) }}</td>
                  <td :title="r.timerange || ''">{{ fmtRange(r.timerange) }}</td>
                  <td class="num">{{ r.n_windows }}</td>
                  <td :class="ratioClass(profitableRatio(r))">{{ r.profitable_windows }}/{{ r.n_windows }}</td>
                  <td class="num">{{ r.oos_trades }}</td>
                  <td class="num">{{ fmtNum(r.oos_profit_abs) }}</td>
                  <td class="num">{{ fmtNum(r.avg_oos_sortino) }}</td>
                  <td class="num">{{ fmtNum(r.avg_oos_profit_factor) }}</td>
                  <td>{{ r.loss_function }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="detail" class="card detail-panel">
        <div class="section-head">
          <h3>OOS per window {{ detail.r?.strategy }} · {{ (detail.r?.run_id || '').slice(0, 16) }}</h3>
          <span class="hint">{{ detailWins.length }} windows · {{ detail.r?.train_days }}/{{ detail.r?.test_days }}/{{ detail.r?.step_days }} d</span>
        </div>
        <div class="chart-box">
          <VChart :option="comboOption" autoresize class="chart" style="height: 280px" />
        </div>
        <div class="table-wrap table-stack">
          <div class="thead-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col" v-on:click="sortDetail('oos_trades')" class="num"># <span class="arrow" v-if="detailSortKey==='oos_trades'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('test_range')">Test range <span class="arrow" v-if="detailSortKey==='test_range'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('oos_trades')" class="num">Trades <span class="arrow" v-if="detailSortKey==='oos_trades'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('oos_profit_abs')" class="num">Profit <span class="arrow" v-if="detailSortKey==='oos_profit_abs'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('oos_winrate')" class="num">WinRate <span class="arrow" v-if="detailSortKey==='oos_winrate'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('oos_sortino')" class="num">Sortino <span class="arrow" v-if="detailSortKey==='oos_sortino'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('oos_pf')" class="num">PF <span class="arrow" v-if="detailSortKey==='oos_pf'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('oos_dd')" class="num">DD <span class="arrow" v-if="detailSortKey==='oos_dd'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                </tr>
              </thead>
            </table>
          </div>
          <div class="table-wrap" ref="wfDetailTableWrap">
            <table>
              <tbody>
                <tr v-for="(w, i) in sortedWins" :key="i">
                  <td>{{ i + 1 }}</td>
                  <td>{{ w.test_range }}</td>
                  <td class="num">{{ w.oos_trades }}</td>
                  <td class="num">{{ fmtNum(w.oos_profit_abs) }}</td>
                  <td class="num">{{ fmtPct(w.oos_winrate) }}</td>
                  <td class="num">{{ fmtNum(w.oos_sortino) }}</td>
                  <td class="num">{{ fmtNum(w.oos_pf) }}</td>
                  <td class="num">{{ fmtPct(w.oos_dd) }}</td>
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
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'

echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
import { ratioClass } from '../utils/pills'

const store = useDashboardStore()
const q = ref('')
const selected = ref('')
const detail = ref(null as any)
const sortKey = ref('run_time')
const sortAsc = ref(false)
const detailSortKey = ref('oos_trades')
const detailSortAsc = ref(true)
const wfTableWrap = ref<HTMLElement | null>(null)
const wfDetailTableWrap = ref<HTMLElement | null>(null)

function profitableRatio(r: any) {
  if (!r.n_windows) return 0
  return r.profitable_windows / r.n_windows
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

const sortedFiltered = computed(() => {
  const arr = [...filtered.value]
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
  return arr.slice(0, 80)
})

const sortedWins = computed(() => {
  if (!detail.value || !detail.value.wins) return []
  const arr = [...detail.value.wins]
  arr.sort((a: any, b: any) => {
    let av = a[detailSortKey.value]
    let bv = b[detailSortKey.value]
    if (av === undefined && bv === undefined) return 0
    if (av === '' || av === undefined || av === null) return detailSortAsc.value ? 1 : -1
    if (bv === '' || bv === undefined || bv === null) return detailSortAsc.value ? -1 : 1
    const an = Number(av), bn = Number(bv)
    const useNum = !isNaN(an) && !isNaN(bn)
    const r = useNum ? an - bn : String(av).localeCompare(String(bv))
    return detailSortAsc.value ? r : -r
  })
  return arr
})

async function drill(source: string) {
  selected.value = source
  const local = store.walkforward.find((r: any) => r.source === source)
  if (local && local.windows_json) {
    try {
      const wins = JSON.parse(local.windows_json)
      if (wins && wins.length) { detail.value = { r: local, wins: wins }; return }
    } catch (e) {}
  }
  const { data } = await api.get('/api/walkforward', { params: { source: source } })
  const wrows = data.rows || []
  if (!wrows.length) { detail.value = null; return }
  detail.value = { r: wrows[0], wins: wrows[0].windows || [] }
}

function sortBy(key: string) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = true }
}
function sortDetail(key: string) {
  if (detailSortKey.value === key) detailSortAsc.value = !detailSortAsc.value
  else { detailSortKey.value = key; detailSortAsc.value = true }
}
function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : '—' }
function fmtPct(v: number) { return v ? (v * 100).toFixed(1) + '%' : '—' }
function fmtRange(tr: string) {
  if (!tr) return '—'
  const p = String(tr).split('-')
  const d = (s: string) => (s && s.length === 8) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '?')
  return d(p[0]) + ' → ' + (p[1] ? d(p[1]) : 'live')
}

const detailWins = computed(() => sortedWins.value)

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
  await store.fetchAll()
  await nextTick()
  if (wfTableWrap.value) {
    wfTableWrap.value.addEventListener('scroll', () => {
      const tw = wfTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
  if (wfDetailTableWrap.value) {
    wfDetailTableWrap.value.addEventListener('scroll', () => {
      const tw = wfDetailTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
})
</script>

<style scoped>
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