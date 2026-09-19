<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { sortableHeader } from '../utils/table'
import { useStrategiesStore } from '../stores/strategies'
import { api } from '../api/client'
import StrategyDrawer from '../components/StrategyDrawer.vue'
import { useUrlState } from '../composables/useUrlState'
import { useStrategyFormat } from '../composables/useStrategyFormat'
import type { StrategyRow } from '../stores/strategies'

const store = useStrategiesStore()
const format = useStrategyFormat()
const registry = ref([] as StrategyRow[])
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

const baseRows = computed(() => store.items.map((c) => {
  const reg = registry.value.find((r) => r.strategy === c.strategy)
  let nb = 0
  let nt = 0
  if (reg) {
    nb = reg.n_backtests || 0
    nt = reg.n_trades || 0
  }
  return { strategy: c.strategy, status: c.status || 'active', score: c.score, profit_total: c.profit_total, profit_factor: c.profit_factor, sortino: c.sortino, calmar: c.calmar, max_drawdown_account: c.max_drawdown_account, prop_firms: c.prop_firms, source: c.source, run_time: c.run_time, timerange: c.timerange, basis: c.basis || '', n_backtests: nb, n_trades: nt, notes: c.notes || '' }
}))

const filteredRows = computed(() => baseRows.value.filter((r) => {
  const q = query.value.toLowerCase()
  if (q && !(r.strategy || '').toLowerCase().includes(q)) return false
  const gf = globalFilter.value.trim().toLowerCase()
  if (gf && !(r.strategy || '').toLowerCase().includes(gf)) return false
  if (statusFilter.value !== 'all' && (r.status || 'active') !== statusFilter.value) return false
  return true
}))

const columns = [
  { accessorKey: 'strategy', header: sortableHeader('Name') },
  { accessorKey: 'status', header: sortableHeader('Status') },
  { accessorKey: 'score.grade', header: sortableHeader('Grade') },
  { accessorKey: 'profit_total', header: sortableHeader('Profit%') },
  { accessorKey: 'profit_factor', header: sortableHeader('PF') },
  { accessorKey: 'sortino', header: sortableHeader('Sortino') },
  { accessorKey: 'calmar', header: sortableHeader('Calmar') },
  { accessorKey: 'max_drawdown_account', header: sortableHeader('MaxDD') },
  { accessorKey: 'propPass', accessorFn: (r: StrategyRow) => format.propPassCount(r as unknown as Record<string, unknown>), header: sortableHeader('Prop') },
  { accessorKey: 'n_backtests', header: sortableHeader('Backtests') },
  { accessorKey: 'n_trades', header: sortableHeader('Trades') },
  { accessorKey: 'basis', header: sortableHeader('Basis') },
  { accessorKey: 'timerange', header: sortableHeader('Range') },
  { accessorKey: 'run_time', header: sortableHeader('Run') },
  { accessorKey: 'actions', header: '', enableSorting: false, enableGlobalFilter: false },
]

function resetFilters() {
  query.value = ''
  statusFilter.value = 'all'
  columnVisibility.value = {}
  sorting.value = [{ id: 'strategy', desc: false }]
}

function openStrategy(s: StrategyRow) {
  selected.value = s.strategy
  drawerKind.value = s.source || 'backtest'
  drawerSource.value = s.source || ''
}

function startEdit(s: StrategyRow) {
  editName.value = s.strategy
  editStatus.value = s.status
  editNotes.value = s.notes || ''
  editMsg.value = ''
}

function cancelEdit() { editName.value = '' }
async function saveEdit() {
  await api.post('/api/strategies', { name: editName.value, status: editStatus.value, notes: editNotes.value })
  editMsg.value = 'saved'
  await store.fetchAll(true)
}
function refreshData() {
  store.fetchAll(true)
  loadRegistry()
}

async function loadRegistry() {
  const { data } = await api.get('/api/strategies')
  registry.value = (data as StrategyRow[]) || []
}

onMounted(() => {
  store.fetchAll()
  loadRegistry()
})
</script>

<template>
  <section class="flex flex-col gap-4 min-w-0">
    <div class="section-head flex items-baseline justify-between gap-3 flex-wrap">
      <h2 class="text-lg font-semibold text-lavender">Strategies</h2>
      <div class="controls flex gap-2.5 flex-wrap items-center">
        <UInput v-model="query" placeholder="Filter strategies..." class="w-64" />
        <USelect v-model="statusFilter" :options="statusOptions" class="w-40" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!query && statusFilter === 'all' && !Object.keys(columnVisibility).length">
          <template #leading>
            <UIcon name="i-lucide-rotate-ccw" />
          </template>
          Reset
        </UButton>
        <ColumnToggle :columns="columns" :visibility="columnVisibility" @update:visibility="columnVisibility = $event" />
      </div>
    </div>

    <div v-if="store.loading" class="card p-4.5">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-text-dim">Loading strategies...</span>
      </div>
    </div>
    <div v-else-if="store.error" class="card p-4.5" style="color: var(--color-bad);">
      <div class="flex items-center gap-3">
        <UIcon name="i-lucide-alert-circle" class="text-bad" size="20" />
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
        @select="(row) => openStrategy(row.original ?? row)"
        class="w-full"
        empty="No strategies found matching your filters."
      >
        <template #strategy-cell="{ row }">
          <span>{{ row.original.strategy }}</span>
        </template>
        <template #status-cell="{ row }">
          <span :class="format.statusClass(row.original.status)">{{ row.original.status }}</span>
        </template>
        <template #["score.grade-cell"]="{ row }">
          <span :class="format.gradePill(row.original.score?.grade)">{{ row.original.score?.grade || '?' }}</span>
        </template>
        <template #profit_total-cell="{ row }">
          <span class="num" :class="format.profitClass(row.original.profit_total)">{{ format.fmtProfitPct(row.original.profit_total) }}</span>
        </template>
        <template #profit_factor-cell="{ row }">
          <span class="num">{{ format.pfFmt(row.original.profit_factor) }}</span>
        </template>
        <template #sortino-cell="{ row }">
          <span class="num">{{ format.fmt3(row.original.sortino) }}</span>
        </template>
        <template #calmar-cell="{ row }">
          <span class="num">{{ format.fmt3(row.original.calmar) }}</span>
        </template>
        <template #max_drawdown_account-cell="{ row }">
          <span class="num">{{ format.fmtPct(row.original.max_drawdown_account ?? 0) }}</span>
        </template>
        <template #n_backtests-cell="{ row }">
          <span class="num">{{ row.original.n_backtests }}</span>
        </template>
        <template #n_trades-cell="{ row }">
          <span class="num">{{ row.original.n_trades }}</span>
        </template>
        <template #propPass-cell="{ row }">
          <span class="num"><span :class="format.propClass(row.original)" :title="format.propTitle(row.original, store.propSpec)">{{ format.propText(row.original) }}</span></span>
        </template>
        <template #basis-cell="{ row }">
          <span :title="format.basisTooltip(row.original)">{{ format.basisLabel(row.original) }}</span>
        </template>
        <template #timerange-cell="{ row }">
          <span class="text-xs text-text-dim">{{ format.fmtRange(row.original.timerange) }}</span>
        </template>
        <template #run_time-cell="{ row }">
          <span>{{ (row.original.run_time || '').slice(0, 10) }}</span>
        </template>
        <template #actions-cell="{ row }">
          <div class="flex gap-1">
            <UButton size="sm" variant="ghost" aria-label="Open details" @click.stop="openStrategy(row.original)">
              <UIcon name="i-lucide-chevron-right" size="14" />
            </UButton>
            <UButton size="sm" variant="ghost" aria-label="Edit strategy" @click.stop="startEdit(row.original)">
              <UIcon name="i-lucide-edit" size="14" />
            </UButton>
          </div>
        </template>
      </UTable>
    </div>

    <div v-if="editName" class="card p-4 mt-4">
      <h3 class="text-base font-semibold mb-3">Edit {{ editName }}</h3>
      <UFormField name="status" label="Status">
        <USelect v-model="editStatus" :options="statusOptions" />
      </UFormField>
      <UFormField name="notes" label="Notes" class="mt-3">
        <UInput v-model="editNotes" placeholder="notes" />
      </UFormField>
      <div class="edit-actions flex gap-2 mt-4">
        <UButton @click="saveEdit">Save</UButton>
        <UButton variant="outline" @click="cancelEdit">Cancel</UButton>
      </div>
      <div v-if="editMsg" class="edit-msg text-good text-sm mt-2">{{ editMsg }}</div>
    </div>

    <StrategyDrawer v-if="selected" :name="selected" :run-kind="drawerKind" :run-source="drawerSource" @close="selected = ''" />
  </section>
</template>

<style scoped>
.edit-panel { margin-top: 1rem; padding: 1rem; }
.edit-panel h3 { margin: 0 0 0.75rem; font-size: 0.875rem; }
.edit-field { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.75rem; color: var(--color-text-dim); margin-bottom: 0.75rem; }
.edit-field select, .edit-field input {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--color-text);
  font-size: 13px;
}
.edit-actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.edit-msg { color: var(--color-good); font-size: 12px; margin-top: 0.5rem; }
</style>
