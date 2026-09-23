<template>
  <section>
    <div class="section-head">
      <h2>Backtest History</h2>
      <div class="controls">
        <UInput v-model="query" placeholder="Filter by filename or strategy..." class="filter-input" />
        <USelect v-model="sortBy" :options="sortOptions" class="filter-select" />
        <UButton variant="ghost" size="sm" @click="refreshHistory" :disabled="loading">
          <template #leading>
            <UIcon name="i-lucide-rotate-ccw" />
          </template>
          Refresh
        </UButton>
      </div>
    </div>

    <InlineStatus v-if="historyStatus" :type="historyStatus.type" :title="historyStatus.title" :message="historyStatus.message" :duration="5000" />

    <div v-if="loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading backtest history...</span>
      </div>
    </div>
    <div v-else-if="error" class="card" style="color: var(--bad);">
      <div class="flex items-center gap-3">
        <UIcon name="i-lucide-alert-circle" class="text-error" size="20" />
        <div>
          <p class="font-medium">{{ error }}</p>
          <UButton size="sm" variant="outline" @click="refreshHistory">Retry</UButton>
        </div>
      </div>
    </div>
    <div v-else>
      <div class="card">
        <UTable
          :data="filteredHistory"
          :columns="columns"
          :loading="false"
          :sticky="true"
          :sorting="sorting"
          @update:sorting="sorting = $event"
          :column-visibility="columnVisibility"
          @update:column-visibility="columnVisibility = $event"
          @select="(row: any) => openResult(row.original ?? row)"
          class="w-full"
          empty="No backtest history found."
        >
          <template #filename-cell="{ row }">
            <span class="font-mono">{{ (row.original as any).filename }}</span>
          </template>
          <template #date-cell="{ row }">
            <span>{{ formatDate((row.original as any).date) }}</span>
          </template>
          <template #profit_pct-cell="{ row }">
            <span class="num" :class="profitClass((row.original as any).profit_pct)">{{ fmtPct((row.original as any).profit_pct) }}</span>
          </template>
          <template #profit_total-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).profit_total) }}</span>
          </template>
          <template #trades-cell="{ row }">
            <span class="num">{{ fmtNum((row.original as any).trades) }}</span>
          </template>
          <template #max_drawdown-cell="{ row }">
            <span class="num" :class="ddClass((row.original as any).max_drawdown)">{{ fmtPct((row.original as any).max_drawdown) }}</span>
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
          <template #notes-cell="{ row }">
            <span class="text-muted text-xs" :title="(row.original as any).notes">{{ ((row.original as any).notes || '').slice(0, 50) }}{{ ((row.original as any).notes || '').length > 50 ? '…' : '' }}</span>
          </template>
          <template #actions-cell="{ row }">
            <div class="flex gap-1">
              <UButton size="sm" variant="ghost" @click.stop="openResult(row.original ?? row)">
                <UIcon name="i-lucide-eye" size="14" />
              </UButton>
              <UButton size="sm" variant="ghost" @click.stop="editNotes(row.original ?? row)">
                <UIcon name="i-lucide-edit" size="14" />
              </UButton>
              <UButton size="sm" variant="ghost" color="error" @click.stop="confirmDelete(row.original ?? row)">
                <UIcon name="i-lucide-trash-2" size="14" />
              </UButton>
            </div>
          </template>
        </UTable>
        <p class="hint mt-2">{{ filteredHistory.length }} / {{ history.length }} entries</p>
      </div>

      <!-- Result Detail Drawer -->
      <div v-if="selectedResult" class="drawer-overlay" @click.self="closeResult">
        <div class="drawer-panel" @click.stop>
          <div class="drawer-header">
            <h3>{{ selectedResult.strategy }} — {{ selectedResult.filename }}</h3>
            <UButton variant="ghost" size="sm" @click="closeResult">
              <UIcon name="i-lucide-x" size="16" />
            </UButton>
          </div>
          <div class="drawer-content">
            <div class="drawer-tabs">
              <button :class="['tab', { active: drawerTab === 'metrics' }]" @click="drawerTab = 'metrics'">Metrics</button>
              <button :class="['tab', { active: drawerTab === 'trades' }]" @click="drawerTab = 'trades'">Trades</button>
              <button :class="['tab', { active: drawerTab === 'market' }]" @click="drawerTab = 'market'">Market Change</button>
              <button :class="['tab', { active: drawerTab === 'wallet' }]" @click="drawerTab = 'wallet'">Wallet</button>
              <button :class="['tab', { active: drawerTab === 'notes' }]" @click="drawerTab = 'notes'">Notes</button>
            </div>
            <div class="drawer-tab-content">
              <!-- Metrics Tab -->
              <div v-if="drawerTab === 'metrics'" class="tab-panel">
                <div v-if="loadingResult" class="flex items-center justify-center py-12">
                  <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
                </div>
                <div v-else class="metric-grid">
                  <div class="metric-card">
                    <span class="mk">Profit %</span>
                    <span class="mv" :class="profitClass(resultData?.profit_pct)">{{ fmtPct(resultData?.profit_pct) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Profit Abs</span>
                    <span class="mv">{{ fmtNum(resultData?.profit_total) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Trades</span>
                    <span class="mv">{{ fmtNum(resultData?.trades) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Max Drawdown</span>
                    <span class="mv" :class="ddClass(resultData?.max_drawdown)">{{ fmtPct(resultData?.max_drawdown) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Sortino</span>
                    <span class="mv">{{ fmtNum(resultData?.sortino) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Calmar</span>
                    <span class="mv">{{ fmtNum(resultData?.calmar) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Profit Factor</span>
                    <span class="mv">{{ fmtNum(resultData?.profit_factor) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Sharpe</span>
                    <span class="mv">{{ fmtNum(resultData?.sharpe) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">SQN</span>
                    <span class="mv">{{ fmtNum(resultData?.sqn) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Win Rate</span>
                    <span class="mv">{{ fmtPct(resultData?.winrate) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Avg Profit/Trade</span>
                    <span class="mv">{{ fmtNum(resultData?.avg_profit) }}</span>
                  </div>
                  <div class="metric-card">
                    <span class="mk">Expectancy</span>
                    <span class="mv">{{ fmtNum(resultData?.expectancy) }}</span>
                  </div>
                </div>
              </div>

              <!-- Trades Tab -->
              <div v-if="drawerTab === 'trades'" class="tab-panel">
                <div v-if="loadingResult" class="flex items-center justify-center py-12">
                  <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
                </div>
                <div v-else-if="resultTrades.length === 0" class="hint text-center py-8">No trades in this backtest</div>
                <UTable v-else
                  :data="resultTrades"
                  :columns="tradeColumns"
                  :loading="false"
                  :sticky="true"
                  class="w-full"
                >
                  <template #pair-cell="{ row }">{{ (row.original as any).pair }}</template>
                  <template #side-cell="{ row }">
                    <span :class="sideClass((row.original as any).side)">{{ (row.original as any).side }}</span>
                  </template>
                  <template #enter_tag-cell="{ row }">{{ (row.original as any).enter_tag }}</template>
                  <template #exit_reason-cell="{ row }">{{ (row.original as any).exit_reason }}</template>
                  <template #open_date-cell="{ row }">{{ formatDateTime((row.original as any).open_date) }}</template>
                  <template #close_date-cell="{ row }">{{ formatDateTime((row.original as any).close_date) }}</template>
                  <template #open_rate-cell="{ row }"><span class="num">{{ fmtNum((row.original as any).open_rate) }}</span></template>
                  <template #close_rate-cell="{ row }"><span class="num">{{ fmtNum((row.original as any).close_rate) }}</span></template>
                  <template #profit_ratio-cell="{ row }">
                    <span class="num" :class="profitClass((row.original as any).profit_ratio)">{{ fmtPct((row.original as any).profit_ratio) }}</span>
                  </template>
                  <template #profit_abs-cell="{ row }"><span class="num" :class="profitClass((row.original as any).profit_abs)">{{ fmtNum((row.original as any).profit_abs) }}</span></template>
                  <template #duration-cell="{ row }">{{ formatDuration((row.original as any).duration) }}</template>
                </UTable>
              </div>

              <!-- Market Change Tab -->
              <div v-if="drawerTab === 'market'" class="tab-panel">
                <div v-if="loadingMarket" class="flex items-center justify-center py-12">
                  <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
                </div>
                <div v-else-if="marketData?.columns?.length" class="tab-panel">
                  <UTable
                    :data="marketData.data.slice(0, 100)"
                    :columns="marketColumns"
                    :loading="false"
                    :sticky="true"
                    class="w-full"
                  >
                    <template #date-cell="{ row }">{{ formatDate((row as any).original[marketData.columns.indexOf('date')]) }}</template>
                    <template #close-cell="{ row }"><span class="num">{{ fmtNum((row as any).original[marketData.columns.indexOf('close')]) }}</span></template>
                    <template #pct_change-cell="{ row }"><span class="num" :class="profitClass((row as any).original[marketData.columns.indexOf('pct_change')])">{{ fmtPct((row as any).original[marketData.columns.indexOf('pct_change')]) }}</span></template>
                  </UTable>
                  <p class="hint mt-2">Showing first 100 rows of {{ marketData.length }} total</p>
                </div>
                <p v-else class="hint">No market change data available for this backtest</p>
              </div>

              <!-- Wallet Tab -->
              <div v-if="drawerTab === 'wallet'" class="tab-panel">
                <div v-if="loadingWallet" class="flex items-center justify-center py-12">
                  <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
                </div>
                <div v-else-if="walletData?.columns?.length" class="tab-panel">
                  <VChart :option="walletChartOption" autoresize class="chart" style="height: 400px" />
                  <UTable
                    :data="walletData.data.slice(0, 100)"
                    :columns="walletColumns"
                    :loading="false"
                    :sticky="true"
                    class="w-full mt-4"
                  >
                    <template #date-cell="{ row }">{{ formatDate((row as any).original[walletData.columns.indexOf('date')]) }}</template>
                    <template #total_quote-cell="{ row }"><span class="num">{{ fmtNum((row as any).original[walletData.columns.indexOf('total_quote')]) }}</span></template>
                  </UTable>
                  <p class="hint mt-2">Showing first 100 rows of {{ walletData.length }} total</p>
                </div>
                <p v-else class="hint">No wallet history available for this backtest</p>
              </div>

              <!-- Notes Tab -->
              <div v-if="drawerTab === 'notes'" class="tab-panel">
                <UFormField name="notes" label="Notes">
                  <UInput v-model="editNotesText" placeholder="Add notes..." />
                </UFormField>
                <div class="drawer-actions">
                  <UButton @click="saveNotes" :disabled="savingNotes">{{ savingNotes ? 'Saving...' : 'Save Notes' }}</UButton>
                  <UButton variant="outline" @click="() => { drawerTab = 'metrics' }">Cancel</UButton>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Delete Confirmation Dialog -->
      <ConfirmDialog v-if="deleteConfirm" :open="true" @confirm="executeDelete" @cancel="deleteConfirm = null" title="Delete Backtest Result" description="Are you sure you want to delete this backtest result? This action cannot be undone." confirm-label="Delete" color="error" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import VChart from 'vue-echarts'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import type { BacktestHistoryEntry } from '../api/schemas'
import InlineStatus from '../components/InlineStatus.vue'

echarts.use([CanvasRenderer, LineChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'

useConfirmDialog()

// Inline status state (replaces toast)
const historyStatus = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showHistoryStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  historyStatus.value = { type, title, message }
  setTimeout(() => { historyStatus.value = null }, 5000)
}

const loading = ref(true)
const error = ref('')
const history = ref<BacktestHistoryEntry[]>([])
const query = ref('')
const sortBy = ref('date_desc')

const sortOptions = [
  { label: 'Date (newest)', value: 'date_desc' },
  { label: 'Date (oldest)', value: 'date_asc' },
  { label: 'Profit % (high)', value: 'profit_desc' },
  { label: 'Profit % (low)', value: 'profit_asc' },
  { label: 'Trades (high)', value: 'trades_desc' },
]

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'date', desc: true }])
const columnVisibility = ref<Record<string, boolean>>({})

const columns = [
  { accessorKey: 'filename', header: 'Filename', size: 200 },
  { accessorKey: 'strategy', header: 'Strategy', size: 150 },
  { accessorKey: 'date', header: 'Date', size: 130 },
  { accessorKey: 'profit_pct', header: 'Profit %', size: 100 },
  { accessorKey: 'profit_total', header: 'Profit Abs', size: 100 },
  { accessorKey: 'trades', header: 'Trades', size: 80 },
  { accessorKey: 'max_drawdown', header: 'Max DD', size: 80 },
  { accessorKey: 'sortino', header: 'Sortino', size: 80 },
  { accessorKey: 'calmar', header: 'Calmar', size: 80 },
  { accessorKey: 'profit_factor', header: 'PF', size: 80 },
  { accessorKey: 'notes', header: 'Notes', size: 150 },
  { accessorKey: 'actions', header: '', size: 100, enableSorting: false, enableGlobalFilter: false },
] as any[]

const filteredHistory = computed(() => {
  let arr = [...history.value]
  const q = query.value.trim().toLowerCase()
  if (q) {
    arr = arr.filter((r) =>
      (r.filename || '').toLowerCase().includes(q) ||
      (r.strategy || '').toLowerCase().includes(q)
    )
  }
  // Apply sort
  const [field, dir] = sortBy.value.split('_')
  arr.sort((a, b) => {
    const av = (a as any)[field] ?? 0
    const bv = (b as any)[field] ?? 0
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
    return dir === 'desc' ? -cmp : cmp
  })
  return arr
})

// Selected result detail
const selectedResult = ref<BacktestHistoryEntry | null>(null)
const drawerTab = ref<'metrics' | 'trades' | 'market' | 'wallet' | 'notes'>('metrics')
const loadingResult = ref(false)
const resultData = ref<any>(null)
const resultTrades = ref<any[]>([])
const loadingMarket = ref(false)
const marketData = ref<any>(null)
const loadingWallet = ref(false)
const walletData = ref<any>(null)
const savingNotes = ref(false)
const editNotesText = ref('')
const deleteConfirm = ref<BacktestHistoryEntry | null>(null)

const tradeColumns = [
  { accessorKey: 'pair', header: 'Pair', size: 100 },
  { accessorKey: 'side', header: 'Side', size: 80 },
  { accessorKey: 'enter_tag', header: 'Enter Tag', size: 100 },
  { accessorKey: 'exit_reason', header: 'Exit Reason', size: 120 },
  { accessorKey: 'open_date', header: 'Open', size: 130 },
  { accessorKey: 'close_date', header: 'Close', size: 130 },
  { accessorKey: 'open_rate', header: 'Open Rate', size: 100 },
  { accessorKey: 'close_rate', header: 'Close Rate', size: 100 },
  { accessorKey: 'profit_ratio', header: 'Profit %', size: 90 },
  { accessorKey: 'profit_abs', header: 'Profit Abs', size: 100 },
  { accessorKey: 'duration', header: 'Duration', size: 100 },
]

const marketColumns = [
  { accessorKey: 'date', header: 'Date', size: 120 },
  { accessorKey: 'close', header: 'Close', size: 100 },
  { accessorKey: 'pct_change', header: 'Change %', size: 100 },
]

const walletColumns = [
  { accessorKey: 'date', header: 'Date', size: 120 },
  { accessorKey: 'total_quote', header: 'Total Quote', size: 120 },
]

async function refreshHistory() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<BacktestHistoryEntry[]>('/api/backtest/history')
    history.value = Array.isArray(data) ? data : []
  } catch (e) {
    error.value = String(e)
    showHistoryStatus('error', 'Failed to load backtest history')
  } finally {
    loading.value = false
  }
}

function profitClass(v: number) {
  if (!v) return ''
  return v > 0 ? 'good' : v < 0 ? 'bad' : ''
}

function ddClass(v: number) {
  if (!v) return ''
  return v > 0.4 ? 'bad' : v > 0.2 ? 'warn' : ''
}

function sideClass(s: string) {
  if (!s) return ''
  return s === 'short' ? 'status retired' : 'status active'
}

function fmtNum(v: number) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 })
}

function fmtPct(v: number) {
  if (v === null || v === undefined) return '—'
  return (Number(v) * 100).toFixed(1) + '%'
}

function formatDate(ts: string | number) {
  if (!ts) return '—'
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  return d.toLocaleDateString()
}

function formatDateTime(ts: string | number) {
  if (!ts) return '—'
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  return d.toLocaleString()
}

function formatDuration(sec: number) {
  if (!sec) return '—'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

async function openResult(entry: BacktestHistoryEntry) {
  selectedResult.value = entry
  drawerTab.value = 'metrics'
  editNotesText.value = entry.notes || ''
  await loadResult(entry.filename, entry.strategy)
}

function closeResult() {
  selectedResult.value = null
  resultData.value = null
  resultTrades.value = []
  marketData.value = null
  walletData.value = null
}

async function loadResult(filename: string, strategy: string) {
  loadingResult.value = true
  resultData.value = null
  resultTrades.value = []
  try {
    const { data } = await api.get<{ backtest_result: any }>('/api/backtest/history/result', { params: { filename, strategy } })
    const btResult = data.backtest_result
    if (btResult?.strategy?.[strategy]) {
      const strat = btResult.strategy[strategy]
      resultData.value = {
        profit_pct: strat.profit_pct,
        profit_total: strat.profit_total_abs,
        trades: strat.trades,
        max_drawdown: strat.max_drawdown,
        sortino: strat.sortino,
        calmar: strat.calmar,
        profit_factor: strat.profit_factor,
        sharpe: strat.sharpe,
        sqn: strat.sqn,
        winrate: strat.winrate,
        avg_profit: strat.avg_profit,
        expectancy: strat.expectancy,
      }
      if (btResult.strategy[strategy].trades) {
        resultTrades.value = btResult.strategy[strategy].trades
      }
    }
  } catch (e) {
    showHistoryStatus('error', 'Failed to load backtest result')
  } finally {
    loadingResult.value = false
  }
}

async function loadMarketChange(filename: string) {
  loadingMarket.value = true
  marketData.value = null
  try {
    const { data } = await api.get<any>('/api/backtest/history/' + filename + '/market_change', { params: { strategy: selectedResult.value?.strategy } })
    marketData.value = data
  } catch (e) {
    // Silently fail - not all backtests have market change data
  } finally {
    loadingMarket.value = false
  }
}

async function loadWalletHistory(filename: string, strategy: string) {
  loadingWallet.value = true
  walletData.value = null
  try {
    const { data } = await api.get<any>('/api/backtest/history/' + filename + '/' + strategy + '/wallet')
    walletData.value = data
  } catch (e) {
    // Silently fail
  } finally {
    loadingWallet.value = false
  }
}

const walletChartOption = computed((): ECOption => {
  if (!walletData.value?.data?.length) return { series: [] }
  const idx = walletData.value.columns.indexOf('date')
  const valIdx = walletData.value.columns.indexOf('total_quote')
  const data = walletData.value.data.map((row: any[]) => [new Date(row[idx] * 1000).getTime(), row[valIdx]])
  return {
    grid: { left: 70, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'time', axisLabel: { color: '#a89fc4' } },
    yAxis: { type: 'value', axisLabel: { color: '#a89fc4' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 6 }],
    series: [{ name: 'Wallet', type: 'line', showSymbol: false, data, lineStyle: { color: '#a78bfa' } }],
  }
})

async function editNotes(entry: BacktestHistoryEntry) {
  selectedResult.value = entry
  drawerTab.value = 'notes'
  editNotesText.value = entry.notes || ''
}

async function saveNotes() {
  if (!selectedResult.value) return
  savingNotes.value = true
  try {
    await api.patch('/api/backtest/history/' + selectedResult.value.filename, {
      strategy: selectedResult.value.strategy,
      notes: editNotesText.value,
    })
    // Update local history
    const idx = history.value.findIndex(h => h.filename === selectedResult.value!.filename)
    if (idx >= 0) history.value[idx].notes = editNotesText.value
    showHistoryStatus('success', 'Notes saved')
    drawerTab.value = 'metrics'
  } catch (e) {
    showHistoryStatus('error', 'Failed to save notes')
  } finally {
    savingNotes.value = false
  }
}

function confirmDelete(entry: BacktestHistoryEntry) {
  deleteConfirm.value = entry
}

async function executeDelete() {
  if (!deleteConfirm.value) return
  try {
    await api.delete('/api/backtest/history/' + deleteConfirm.value.filename)
    history.value = history.value.filter(h => h.filename !== deleteConfirm.value!.filename)
    showHistoryStatus('success', 'Backtest result deleted')
  } catch (e) {
    showHistoryStatus('error', 'Failed to delete')
  } finally {
    deleteConfirm.value = null
  }
}

// Watch for tab changes to load data lazily
import { watch } from 'vue'
watch(() => drawerTab.value, async (tab) => {
  if (!selectedResult.value) return
  const filename = selectedResult.value.filename
  const strategy = selectedResult.value.strategy
  if (tab === 'market' && !marketData.value) await loadMarketChange(filename)
  if (tab === 'wallet' && !walletData.value) await loadWalletHistory(filename, strategy)
})

onMounted(async () => {
  await refreshHistory()
})
</script>

<style scoped>
.filter-input {
  flex: 1; min-width: 200px;
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
  min-width: 180px;
}
.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.metric-card { display: flex; flex-direction: column; gap: 2px; background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; }
.mk { font-size: 11px; color: var(--text-dim); }
.mv { font-size: 15px; font-weight: 600; }
.mv.good { color: var(--good); }
.mv.bad { color: var(--bad); }
.mv.warn { color: var(--warn); }
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px; }
.drawer-panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 900px; max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; }
.drawer-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.drawer-header h3 { margin: 0; font-size: 16px; }
.drawer-content { flex: 1; overflow: auto; padding: 16px 20px; }
.drawer-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px; }
.tab { background: none; border: none; color: var(--text-dim); font-size: 13px; padding: 8px 12px; border-radius: 6px 6px 0 0; cursor: pointer; }
.tab.active { color: var(--primary); background: var(--bg-soft); font-weight: 600; }
.tab-panel { animation: fadeIn 0.15s; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.drawer-actions { display: flex; gap: 8px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.progress-task { padding: 8px; background: var(--bg-soft); border-radius: 6px; }
</style>
