<template>
  <section>
    <div class="section-head">
      <h2>Hyperopt</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else>
      <div class="card filters">
        <input v-model="q" placeholder="filter" class="filter-input" />
        <select v-model="selectedFile" v-on:change="loadFile" class="filter-select">
          <option value="">ho files ({{ files.length }})</option>
          <option v-for="f in files" :key="fileKey(f)" :value="fileKey(f)">{{ fileLabel(f) }}</option>
        </select>
        <label class="filter-label">Min Trades <input type="number" v-model.number="minTrades" /></label>
      </div>

      <div class="card">
        <div class="section-head">
          <h3>{{ filtered.length }} / {{ store.hyperopt.length }} runs</h3>
        </div>
        <div class="table-wrap table-stack">
          <div class="thead-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col" v-on:click="sortBy('strategy')">Strategy <span class="arrow" v-if="sortKey==='strategy'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('epochs')" class="num">Epochs <span class="arrow" v-if="sortKey==='epochs'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('best_loss')" class="num">Best Loss <span class="arrow" v-if="sortKey==='best_loss'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('best_profit_total')" class="num">Best Profit <span class="arrow" v-if="sortKey==='best_profit_total'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('best_sortino')" class="num">Best Sortino <span class="arrow" v-if="sortKey==='best_sortino'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('best_profit_factor')" class="num">Best PF <span class="arrow" v-if="sortKey==='best_profit_factor'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('best_trades')" class="num">Trades <span class="arrow" v-if="sortKey==='best_trades'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('loss_function')">Loss <span class="arrow" v-if="sortKey==='loss_function'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortBy('run_time')" class="num">Run <span class="arrow" v-if="sortKey==='run_time'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                </tr>
              </thead>
            </table>
          </div>
          <div class="table-wrap" ref="hoTableWrap">
            <table>
              <tbody>
                <tr v-for="r in sortedFiltered" :key="r.source" v-on:click="drill(r.source)">
                  <td>{{ r.strategy }}</td>
                  <td class="num">{{ r.epochs }}</td>
                  <td class="num">{{ fmtNum(r.best_loss) }}</td>
                  <td class="num">{{ fmtNum(r.best_profit_total) }}</td>
                  <td class="num">{{ fmtNum(r.best_sortino) }}</td>
                  <td class="num">{{ fmtNum(r.best_profit_factor) }}</td>
                  <td class="num">{{ r.best_trades }}</td>
                  <td>{{ r.loss_function }}</td>
                  <td class="num">{{ fmtNum(r.run_time) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="detail" class="card detail-panel">
        <div class="section-head">
          <h3>Epochs {{ detail.count }}</h3>
        </div>
        <div class="corr-grid">
          <div v-for="(v, k) in detail.corr" :key="k" :class="corrClass(v)">{{ k }}: {{ v.toFixed(3) }}</div>
        </div>
        <pre class="code-block">{{ detail.paramsText }}</pre>
        <div class="table-wrap table-stack">
          <div class="thead-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col" v-on:click="sortDetail('epoch')">Epoch <span class="arrow" v-if="detailSortKey==='epoch'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('loss')" class="num">Loss <span class="arrow" v-if="detailSortKey==='loss'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('trades')" class="num">Trades <span class="arrow" v-if="detailSortKey==='trades'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('profit_total')" class="num">Profit <span class="arrow" v-if="detailSortKey==='profit_total'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('sortino')" class="num">Sortino <span class="arrow" v-if="detailSortKey==='sortino'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('calmar')" class="num">Calmar <span class="arrow" v-if="detailSortKey==='calmar'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('profit_factor')" class="num">PF <span class="arrow" v-if="detailSortKey==='profit_factor'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('sqn')" class="num">SQN <span class="arrow" v-if="detailSortKey==='sqn'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                  <th scope="col" v-on:click="sortDetail('max_drawdown')" class="num">DD <span class="arrow" v-if="detailSortKey==='max_drawdown'">{{ detailSortAsc ? '▲' : '▼' }}</span></th>
                </tr>
              </thead>
            </table>
          </div>
          <div class="table-wrap" ref="hoDetailTableWrap">
            <table>
              <tbody>
                <tr v-for="r in sortedDetail" :key="r.epoch">
                  <td>{{ r.epoch }}</td>
                  <td class="num">{{ fmtNum(r.loss) }}</td>
                  <td class="num">{{ r.trades }}</td>
                  <td class="num">{{ fmtNum(r.profit_total) }}</td>
                  <td class="num">{{ fmtNum(r.sortino) }}</td>
                  <td class="num">{{ fmtNum(r.calmar) }}</td>
                  <td class="num">{{ fmtNum(r.profit_factor) }}</td>
                  <td class="num">{{ fmtNum(r.sqn) }}</td>
                  <td class="num">{{ fmtPct(r.max_drawdown) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="chart-box">
          <VChart :option="scatterOption" autoresize class="chart" style="height: 280px" />
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
import type { ECScatterOption } from '../utils/echarts'
import { corrClass } from '../utils/pills'
import '../utils/echarts'

const store = useDashboardStore()
const q = ref('')
const minTrades = ref(0)
const selectedFile = ref('')
const detail = ref(null as any)
const files = ref([] as any[])
const sortKey = ref('epochs')
const sortAsc = ref(false)
const detailSortKey = ref('epoch')
const detailSortAsc = ref(true)
const hoTableWrap = ref<HTMLElement | null>(null)
const hoDetailTableWrap = ref<HTMLElement | null>(null)

const filtered = computed(() => {
  const ql = q.value.toLowerCase()
  return store.hyperopt.filter((r: any) => {
    const reg = store.canonical.find((c: any) => c.strategy === r.strategy)
    if (reg && (reg.status || 'active') === 'retired') return false
    if ((r.best_trades || 0) < minTrades.value) return false
    if (!ql) return true
    return (r.strategy || '').toLowerCase().includes(ql)
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
  return arr.slice(0, 60)
})

const sortedDetail = computed(() => {
  if (!detail.value || !detail.value.records) return []
  const arr = [...detail.value.records]
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

function fileKey(f: any) { return typeof f === 'string' ? f : (f.source || f.name || f.path || JSON.stringify(f)) }
function fileLabel(f: any) { return typeof f === 'string' ? f : (f.name || f.source || f.path || JSON.stringify(f)) }
async function loadFile() { if (selectedFile.value) await drill(selectedFile.value) }
async function drill(source: string) {
  selectedFile.value = source
  const { data } = await api.get('/api/hyperopt', { params: { source, limit: 200 } })
  if (data.error) { detail.value = null; return }
  const hoRow = store.hyperopt.find((x: any) => x.source === data.source)
  let paramsText = ''
  if (hoRow && hoRow.best_params) {
    try { paramsText = JSON.stringify(JSON.parse(hoRow.best_params), null, 2) } catch (e) {}
  }
  detail.value = Object.assign({}, data, { paramsText })
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

const scatterOption = computed((): ECScatterOption => ({
  xAxis: { type: 'value', name: 'loss', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', name: 'sortino', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'scatter', data: ((detail.value && detail.value.records) || []).map((r: any) => [r.loss, r.sortino]), itemStyle: { color: '#a78bfa' }, symbolSize: 8 }]
}))

onMounted(async () => {
  await store.fetchAll()
  const { data } = await api.get('/api/hyperopt/files')
  files.value = data
  await nextTick()
  if (hoTableWrap.value) {
    hoTableWrap.value.addEventListener('scroll', () => {
      const tw = hoTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
  if (hoDetailTableWrap.value) {
    hoDetailTableWrap.value.addEventListener('scroll', () => {
      const tw = hoDetailTableWrap.value!
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
.filter-select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  min-width: 200px;
}
.filter-label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.filter-label input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
  width: 80px;
}
.detail-panel { display: flex; flex-direction: column; gap: 16px; }
.corr-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.corr-grid > div { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 500; }
</style>