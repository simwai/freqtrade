<template>
  <section>
    <div class="section-head">
      <h2>Hyperopt</h2>
      <div class="controls">
        <UInput v-model="q" placeholder="Filter runs..." class="filter-input" @input="debugFilter" />
        <USelect v-model="selectedFile" :options="fileOptions" placeholder="Hyperopt result file" class="filter-select" @change="loadFile" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!q && !selectedFile && !minTrades && !Object.keys(columnVisibility).length">
          <template #leading>
            <UIcon name="i-lucide-rotate-ccw" />
          </template>
          Reset
        </UButton>
        <ColumnToggle :columns="columns" :visibility="columnVisibility" @update:visibility="columnVisibility = $event" />
      </div>
    </div>

    <div v-if="store.loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading hyperopt runs...</span>
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
        <div class="filters-inline">
          <UFormField name="minTrades" label="Min Trades">
            <UInput type="number" v-model.number="minTrades" />
          </UFormField>
          <UFormField name="epochLimit" label="Epoch limit">
            <UInput type="number" v-model.number="epochLimit" />
          </UFormField>
        </div>
        <span class="hint">{{ filtered.length }} / {{ store.hyperopt.length }} runs</span>
      </div>

      <div class="card">
        <UTable
          :data="sortedFiltered"
          :columns="columns"
          :loading="false"
          :sticky="true"
          :sorting="sorting"
          @update:sorting="sorting = $event"
          :column-visibility="columnVisibility"
          @update:column-visibility="columnVisibility = $event"
          @select="(row: any) => drill(row.original?.source ?? row.source)"
          class="w-full"
          empty="No hyperopt runs found matching your filters."
        >
          <template #strategy-cell="{ row }">
            <span>{{ (row.original as any).strategy }}</span>
          </template>
          <template #best_loss-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).best_loss) }}</span>
          </template>
          <template #best_profit_total-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).best_profit_total) }}</span>
          </template>
          <template #best_sortino-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).best_sortino) }}</span>
          </template>
          <template #best_profit_factor-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).best_profit_factor) }}</span>
          </template>
          <template #loss_function-cell="{ row }">
            <span :title="(row.original as any).spaces || ''">{{ shortLoss((row.original as any).loss_function) }}</span>
          </template>
          <template #spaces-cell="{ row }">
            <span :title="(row.original as any).spaces || ''">{{ ((row.original as any).spaces || '').slice(0, 18) }}</span>
          </template>
          <template #run_time-cell="{ row }">
            <span class="num">{{ ((row.original as any).run_time || '').slice(0, 16) }}</span>
          </template>
          <template #actions-cell="{ row }">
            <UButton size="sm" variant="ghost" @click.stop="openRun('hyperopt', (row.original as any).source)">Config &amp; code</UButton>
          </template>
        </UTable>
        <p class="hint">Showing up to 60 runs — refine the filter to narrow results.</p>
      </div>

      <div v-if="detail" class="card detail-panel">
        <div class="section-head">
          <h3>Epochs {{ detail.count }}</h3>
        </div>
        <div class="corr-grid">
          <div v-for="(v, k) in detail.corr" :key="k" :class="corrClass(v)">{{ k }} {{ signed(v) }}</div>
        </div>
        <details class="paramsBlock" open>
          <summary>Best epoch params — {{ detail.loss_function || '' }} · loss {{ fmtNum(detail.best_loss) }}</summary>
          <pre class="code-block">{{ detail.paramsText }}</pre>
        </details>
        <UTable
          :data="detailRecords"
          :columns="detailColumns"
          :loading="false"
          :sticky="true"
          :sorting="detailSorting"
          @update:sorting="detailSorting = $event"
          class="w-full"
          empty="No epochs."
        >
          <template #loss-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).loss) }}</span>
          </template>
          <template #profit_total-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).profit_total) }}</span>
          </template>
          <template #sortino-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).sortino) }}</span>
          </template>
          <template #calmar-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).calmar) }}</span>
          </template>
          <template #profit_factor-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).profit_factor) }}</span>
          </template>
          <template #sqn-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).sqn) }}</span>
          </template>
          <template #max_drawdown-cell="{ row }">
            <span class="num">{{ fmtPct((row.original as any).max_drawdown) }}</span>
          </template>
          <template #mae-cell="{ row }">
            <span class="num">{{ fmtPct2((row.original as any).mae) }}</span>
          </template>
          <template #exit_eff-cell="{ row }">
            <span class="num">{{ fmtPct0((row.original as any).exit_eff) }}</span>
          </template>
          <template #best-cell="{ row }">
            <span v-if="(row.original as any).best" class="pill gA">best</span><span v-else-if="(row.original as any).init" class="pill gna">init</span>
          </template>
        </UTable>
        <div class="chart-box">
          <VChart :option="scatterOption" autoresize class="chart" style="height: 280px" />
        </div>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { sortableHeader } from '../utils/table'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
echarts.use([CanvasRenderer, BarChart, LineChart, ScatterChart, CandlestickChart, TitleComponent, TooltipComponent, 
GridComponent, LegendComponent, DataZoomComponent])
import { useStrategiesStore } from '../stores/strategies'
import { api } from '../api/client'
const router = useRouter()
import type { ECScatterOption } from '../utils/echarts'
import { corrClass } from '../utils/pills'
import '../utils/echarts'
import { useUrlState } from '../composables/useUrlState'

const store = useStrategiesStore()
const q = useUrlState({ key: 'q', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })
const minTrades = ref(0)
const epochLimit = ref(200)
const selectedFile = ref('')
const detail = ref(null as any)
const files = ref([] as any[])

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'epochs', desc: true }])
const columnVisibility = ref<Record<string, boolean>>({})
const detailSorting = ref<{ id: string; desc: boolean }[]>([{ id: 'epoch', desc: false }])

const fileOptions = computed(() => files.value.map((f: any) => ({ label: fileLabel(f), value: fileKey(f) })))

const columns = [
  { accessorKey: 'strategy', header: sortableHeader('Strategy') },
  { accessorKey: 'epochs', header: sortableHeader('Epochs') },
  { accessorKey: 'best_loss', header: sortableHeader('Best Loss') },
  { accessorKey: 'best_profit_total', header: sortableHeader('Best Profit') },
  { accessorKey: 'best_sortino', header: sortableHeader('Best Sortino') },
  { accessorKey: 'best_profit_factor', header: sortableHeader('Best PF') },
  { accessorKey: 'best_trades', header: sortableHeader('Trades') },
  { accessorKey: 'loss_function', header: sortableHeader('Loss') },
  { accessorKey: 'spaces', header: sortableHeader('Spaces') },
  { accessorKey: 'run_time', header: sortableHeader('Run') },
  { accessorKey: 'actions', header: '', enableSorting: false, enableGlobalFilter: false },
] as any[]

const detailColumns = [
  { accessorKey: 'epoch', header: sortableHeader('Epoch') },
  { accessorKey: 'loss', header: sortableHeader('Loss') },
  { accessorKey: 'trades', header: sortableHeader('Trades') },
  { accessorKey: 'profit_total', header: sortableHeader('Profit') },
  { accessorKey: 'sortino', header: sortableHeader('Sortino') },
  { accessorKey: 'calmar', header: sortableHeader('Calmar') },
  { accessorKey: 'profit_factor', header: sortableHeader('PF') },
  { accessorKey: 'sqn', header: sortableHeader('SQN') },
  { accessorKey: 'max_drawdown', header: sortableHeader('DD') },
  { accessorKey: 'mae', header: sortableHeader('MAE%') },
  { accessorKey: 'exit_eff', header: sortableHeader('ExitEff') },
  { accessorKey: 'best', header: 'Best?', enableSorting: false },
] as any[]

const filtered = computed(() => {
  const ql = q.value.toLowerCase()
  return store.hyperopt.filter((r: any) => {
    const reg = store.canonical.find((c: any) => c.strategy === r.strategy)
    if (reg && (reg.status || 'active') === 'retired') return false
    if ((r.best_trades || 0) < minTrades.value) return false
    if (!ql) return true
    return (r.strategy || '').toLowerCase().includes(ql) || (r.source || '').toLowerCase().includes(ql) || (r.loss_function || '').toLowerCase().includes(ql)
  })
})

function compareCells(av: any, bv: any, desc: boolean): number {
  if (av === undefined && bv === undefined) return 0
  if (av === '' || av === undefined || av === null) return 1
  if (bv === '' || bv === undefined || bv === null) return -1
  const an = Number(av), bn = Number(bv)
  const useNum = !isNaN(an) && !isNaN(bn)
  const r = useNum ? an - bn : String(av).localeCompare(String(bv))
  return desc ? -r : r
}

const sortedFiltered = computed(() => {
  const s = sorting.value[0] || { id: 'epochs', desc: true }
  const arr = [...filtered.value]
  arr.sort((a: any, b: any) => compareCells(a[s.id], b[s.id], s.desc))
  return arr.slice(0, 60)
})

const detailRecords = computed(() => {
  if (!detail.value || !detail.value.records) return []
  return detail.value.records
})

function resetFilters() {
  q.value = ''
  selectedFile.value = ''
  minTrades.value = 0
  columnVisibility.value = {}
  sorting.value = [{ id: 'epochs', desc: true }]
}

function debugFilter() {
  console.log('Filter q:', q.value, 'filtered count:', filtered.value.length)
}

function refreshData() {
  store.fetchAll(true)
}

function fileKey(f: any) { return typeof f === 'string' ? f : (f.source || f.name || f.path || JSON.stringify(f)) }
function fileLabel(f: any) { return typeof f === 'string' ? f : (f.name || f.source || f.path || JSON.stringify(f)) }
async function loadFile() { if (selectedFile.value) await drill(selectedFile.value) }
async function drill(source: string) {
  selectedFile.value = source
  try {
    const { data } = await api.get('/api/hyperopt', { params: { source, limit: Number(epochLimit.value) || 200 } })
    if ((data as any).error) { detail.value = null; return }
    const hoRow = store.hyperopt.find((x: any) => x.source === (data as any).source)
    let paramsText = ''
    if (hoRow && hoRow.best_params) {
      try { paramsText = JSON.stringify(JSON.parse(hoRow.best_params as string), null, 2) } catch (e) {}
    }
    detail.value = Object.assign({}, data, { paramsText, loss_function: hoRow?.loss_function || '', best_loss: hoRow?.best_loss })
  } catch (e) {
    detail.value = null
  }
}
function shortLoss(s: string) { return (s || '').replace('HyperOptLoss', '') }
function openRun(_kind: string, source: string) {
  const r = store.hyperopt.find((x: any) => x.source === source)
  if (r) {
    const strategy = r.strategy
    const kind = r.kind || 'hyperopt'
    // Open drawer with the specific run context
    // We'll use the StrategyDrawer component which needs to be imported
    // For now, we'll use a simple approach - navigate to strategy detail
    router.push(`/strategies/${encodeURIComponent(strategy)}?source=${encodeURIComponent(source)}&kind=${kind}`)
  }
}
function signed(v: number) { return (v > 0 ? '+' : '') + Number(v).toFixed(2) }
function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : '—' }
function fmtPct(v: number) { return v ? (v * 100).toFixed(1) + '%' : '—' }
function fmtPct2(v: number) { return v === null || v === undefined ? '—' : (Number(v) * 100).toFixed(2) + '%' }
function fmtPct0(v: number) { return v === null || v === undefined ? '—' : (Number(v) * 100).toFixed(0) + '%' }

const scatterOption = computed((): ECScatterOption => ({
  xAxis: { type: 'value', name: 'loss', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  yAxis: { type: 'value', name: 'sortino', axisLabel: { color: '#a89fc4' }, axisLine: { lineStyle: { color: '#2f2745' } }, splitLine: { lineStyle: { color: '#2f2745' } } },
  grid: { left: 50, right: 20, top: 10, bottom: 40 },
  series: [{ type: 'scatter', data: ((detail.value && detail.value.records) || []).map((r: any) => [r.loss, r.sortino]), itemStyle: { color: '#a78bfa' }, symbolSize: 8 }]
}))

onMounted(async () => {
  await store.fetchAll()
  const { data } = await api.get('/api/hyperopt/files')
  files.value = data as any[]
})
</script>

<style scoped>
.filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }
.filters-inline { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; width: 100%; }
.filters-inline > .filter-label { flex: 1; min-width: 180px; }
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
