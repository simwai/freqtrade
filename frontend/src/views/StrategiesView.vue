<template>
  <section>
    <div class="section-head">
      <h2>Strategies</h2>
      <div class="controls">
        <UInput v-model="query" placeholder="Filter strategies..." class="filter-input" />
        <USelect v-model="statusFilter" :options="statusOptions" class="filter-select" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!query && statusFilter === 'all' && !Object.keys(columnVisibility).length">
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
        <span class="ml-3 text-muted">Loading strategies...</span>
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
      <UTable
        :data="filteredRows"
        :columns="columns"
        :loading="false"
        :sticky="true"
        :sorting="sorting"
        @update:sorting="sorting = $event"
        :column-visibility="columnVisibility"
        @update:column-visibility="columnVisibility = $event"
        @select="(row: any) => openStrategy(row.original ?? row)"
        class="w-full"
        empty="No strategies found matching your filters."
      >
        <template #cell-strategy="{ row }">
          <span>{{ (row.original as any).strategy }}</span>
        </template>
        <template #cell-status="{ row }">
          <span :class="statusClass((row.original as any).status)">{{ (row.original as any).status }}</span>
        </template>
        <template #cell-score.grade="{ row }">
          <span :class="gradePill((row.original as any).score?.grade)">{{ (row.original as any).score?.grade || '?' }}</span>
        </template>
        <template #cell-profit_total="{ row }">
          <span class="num" :class="profitClass((row.original as any).profit_total)">{{ fmtProfitPct((row.original as any).profit_total) }}</span>
        </template>
        <template #cell-profit_factor="{ row }">
          <span class="num">{{ pfFmt((row.original as any).profit_factor) }}</span>
        </template>
        <template #cell-sortino="{ row }">
          <span class="num">{{ fmt3((row.original as any).sortino) }}</span>
        </template>
        <template #cell-calmar="{ row }">
          <span class="num">{{ fmt3((row.original as any).calmar) }}</span>
        </template>
        <template #cell-max_drawdown_account="{ row }">
          <span class="num">{{ fmtPct((row.original as any).max_drawdown_account) }}</span>
        </template>
        <template #cell-n_backtests="{ row }">
          <span class="num">{{ (row.original as any).n_backtests }}</span>
        </template>
        <template #cell-n_trades="{ row }">
          <span class="num">{{ (row.original as any).n_trades }}</span>
        </template>
        <template #cell-propPass="{ row }">
          <span class="num"><span :class="propClass(row.original)" :title="propTitle(row.original)">{{ propText(row.original) }}</span></span>
        </template>
        <template #cell-basis="{ row }">
          <span :title="basisTooltip(row.original)">{{ basisLabel(row.original) }}</span>
        </template>
        <template #cell-timerange="{ row }">
          <span style="font-size:12px;color:var(--text-dim)">{{ fmtRange((row.original as any).timerange) }}</span>
        </template>
        <template #cell-run_time="{ row }">
          <span>{{ ((row.original as any).run_time || '').slice(0, 10) }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="flex gap-1">
            <UButton size="sm" variant="ghost" aria-label="Open details" @click.stop="openStrategy(row.original ?? row)">
              <UIcon name="i-lucide-chevron-right" size="14" />
            </UButton>
            <UButton size="sm" variant="ghost" aria-label="Edit strategy" @click.stop="startEdit(row.original)">
              <UIcon name="i-lucide-edit" size="14" />
            </UButton>
          </div>
        </template>
      </UTable>
    </div>

    <div v-if="editName" class="card edit-panel">
      <h3>Edit {{ editName }}</h3>
      <UFormField name="status" label="Status">
        <USelect v-model="editStatus" :options="statusOptions" />
      </UFormField>
      <UFormField name="notes" label="Notes">
        <UInput v-model="editNotes" placeholder="notes" />
      </UFormField>
      <div class="edit-actions">
        <UButton @click="saveEdit">Save</UButton>
        <UButton variant="outline" @click="cancelEdit">Cancel</UButton>
      </div>
      <div v-if="editMsg" class="edit-msg">{{ editMsg }}</div>
    </div>

    <StrategyDrawer v-if="selected" :name="selected" :run-kind="drawerKind" :run-source="drawerSource" @close="selected = ''" />
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import StrategyDrawer from '../components/StrategyDrawer.vue'
import { useUrlState } from '../composables/useUrlState'

const store = useDashboardStore()
const selected = ref('')
const drawerKind = ref('')
const drawerSource = ref('')
const editName = ref('')
const editStatus = ref('active')
const editNotes = ref('')
const editMsg = ref('')
const query = useUrlState({ key: 'q', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })
const statusFilter = ref('all')
const globalFilter = ref('')

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'strategy', desc: false }])
const columnVisibility = ref<Record<string, boolean>>({})

const statusOptions = [
  { label: 'all statuses', value: 'all' },
  { label: 'active', value: 'active' },
  { label: 'experimental', value: 'experimental' },
  { label: 'retired', value: 'retired' },
]

const baseRows = computed(() => store.canonical.map((c: any) => {
  const reg = store.strategies.find((r: any) => r.name === c.strategy)
  let nb = 0
  let nt = 0
  if (reg) {
    nb = reg.n_backtests || 0
    nt = reg.n_trades || 0
  }
  return { strategy: c.strategy, status: c.status || 'active', score: c.score, profit_total: c.profit_total, profit_factor: c.profit_factor, sortino: c.sortino, calmar: c.calmar, max_drawdown_account: c.max_drawdown_account, prop_firms: c.prop_firms, source: c.source, run_time: c.run_time, timerange: c.timerange, basis: c.basis || '', n_backtests: nb, n_trades: nt, notes: c.notes || '' }
}))

const filteredRows = computed(() => baseRows.value.filter((r: any) => {
  const q = query.value.toLowerCase()
  if (q && !(r.strategy || '').toLowerCase().includes(q)) return false
  const gf = globalFilter.value.trim().toLowerCase()
  if (gf && !(r.strategy || '').toLowerCase().includes(gf)) return false
  if (statusFilter.value !== 'all' && (r.status || 'active') !== statusFilter.value) return false
  return true
}))

const columns = [
  { accessorKey: 'strategy', header: 'Name' },
  { accessorKey: 'status', header: 'Status' },
  { accessorKey: 'score.grade', header: 'Grade' },
  { accessorKey: 'profit_total', header: 'Profit%' },
  { accessorKey: 'profit_factor', header: 'PF' },
  { accessorKey: 'sortino', header: 'Sortino' },
  { accessorKey: 'calmar', header: 'Calmar' },
  { accessorKey: 'max_drawdown_account', header: 'MaxDD' },
  { accessorKey: 'propPass', header: 'Prop' },
  { accessorKey: 'n_backtests', header: 'Backtests' },
  { accessorKey: 'n_trades', header: 'Trades' },
  { accessorKey: 'basis', header: 'Basis' },
  { accessorKey: 'timerange', header: 'Range' },
  { accessorKey: 'run_time', header: 'Run' },
  { accessorKey: 'actions', header: '', enableSorting: false, enableGlobalFilter: false },
]

function resetFilters() {
  query.value = ''
  statusFilter.value = 'all'
  columnVisibility.value = {}
  sorting.value = [{ id: 'strategy', desc: false }]
}

function openStrategy(s: any) {
  selected.value = s.strategy
  drawerKind.value = s.source || 'backtest'
  drawerSource.value = s.source || ''
}

function startEdit(s: any) {
  editName.value = s.strategy
  editStatus.value = s.status
  editNotes.value = s.notes || ''
  editMsg.value = ''
}

function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'active') return 'status active'
  if (sl === 'experimental') return 'status experimental'
  if (sl === 'retired') return 'status retired'
  return 'status'
}
function gradePill(g: string) {
  if (!g || g === '—') return 'pill gna'
  if (g === 'A') return 'pill gA'
  if (g === 'B') return 'pill gB'
  if (g === 'C') return 'pill gC'
  if (g === 'D') return 'pill gD'
  if (g === 'F') return 'pill gF'
  return 'pill gna'
}
function fmt3(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!isFinite(n)) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
function pfFmt(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (n === Infinity) return '∞'
  if (!isFinite(n)) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
function fmtPct(v: number) { return v ? (v * 100).toFixed(1) + '%' : '—' }
function fmtProfitPct(v: number) { return v === null || v === undefined ? '—' : ((v || 0) * 100).toFixed(1) + '%' }
function basisLabel(r: any) {
  if (r.basis === 'registry') return 'no runs yet'
  return r.basis === 'benchmark' ? 'benchmark (fallback)' : 'last backtest'
}
function basisTooltip(r: any) {
  if (r.basis === 'registry') return 'registered in the strategies table; no backtest or benchmark ingested yet'
  return 'metrics from ' + (r.basis === 'benchmark' ? 'benchmark' : 'backtest') + ' run ' + (r.source || '?') + ' · ' + (r.run_time || '?')
}
function propText(r: any) {
  const pf = r.prop_firms
  if (!pf) return '—'
  const keys = Object.keys(pf)
  if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return '—'
  return keys.filter((k) => (pf as any)[k].verdict === 'pass').length + '/' + keys.length
}
function propTitle(r: any) {
  const pf = r.prop_firms
  if (!pf) return ''
  const keys = Object.keys(pf)
  const failed = keys.filter((k) => (pf as any)[k].verdict === 'fail').map((k) => store.propSpec[k]?.label || k)
  return failed.length ? 'failed: ' + failed.join(', ') : 'all programs pass'
}
function propClass(r: any) {
  const pf = r.prop_firms
  if (!pf) return 'pill gna'
  const keys = Object.keys(pf)
  if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return 'pill gna'
  const passed = keys.filter((k) => (pf as any)[k].verdict === 'pass').length
  return passed === keys.length ? 'pill gA' : passed > 0 ? 'pill gC' : 'pill gF'
}
function profitClass(v: number) { if (!v) return ''; return v > 0 ? 'good' : v < 0 ? 'bad' : '' }
function fmtRange(tr: string) {
  if (!tr) return '—'
  const p = String(tr).split('-')
  const d = (s: string) => (s && s.length === 8) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '?')
  return d(p[0]) + ' → ' + (p[1] ? d(p[1]) : 'live')
}
function cancelEdit() { editName.value = '' }
async function saveEdit() {
  await api.post('/api/strategies', { name: editName.value, status: editStatus.value, notes: editNotes.value })
  editMsg.value = 'saved'
  await store.fetchAll(true)
}
function refreshData() {
  store.fetchAll(true)
}

onMounted(() => { store.fetchAll() })
</script>

<style scoped>
.edit-panel { margin-top: 16px; padding: 16px; }
.edit-panel h3 { margin: 0 0 12px; font-size: 14px; }
.edit-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); margin-bottom: 12px; }
.edit-field select, .edit-field input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
}
.edit-actions { display: flex; gap: 8px; margin-top: 8px; }
.edit-msg { color: var(--good); font-size: 12px; margin-top: 8px; }
</style>