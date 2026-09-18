<template>
  <section>
    <div class="section-head">
      <h2>Trades</h2>
      <div class="controls">
        <UInput v-model="q" placeholder="Filter runs..." class="filter-input" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!q && !Object.keys(columnVisibility).length">
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
        <span class="ml-3 text-muted">Loading trade runs...</span>
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
    <div v-else class="card">
      <p v-if="newestKey" class="hint">auto-loaded · newest run {{ newestKey }}</p>
      <UTable
        :data="filteredRuns"
        :columns="columns"
        :loading="false"
        :sticky="true"
        :sorting="sorting"
        @update:sorting="sorting = $event"
        :column-visibility="columnVisibility"
        @update:column-visibility="columnVisibility = $event"
        :meta="{ class: { tr: runRowClass } }"
        @select="(row: any) => openRun(row.original ?? row)"
        class="w-full"
        empty="No trade runs found matching your filters."
      >
        <template #strategy-cell="{ row }">
          <router-link :to="'/trades/' + (row.original as any).key">{{ (row.original as any).strategy }}</router-link>
        </template>
        <template #file-cell="{ row }">
          <a :href="'/trades/' + (row.original as any).key + '.json'" target="_blank" @click.stop>JSON</a>
        </template>
        <template #actions-cell="{ row }">
          <UButton size="sm" variant="ghost" @click.stop="openRun(row.original ?? row)">Open</UButton>
        </template>
      </UTable>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { sortableHeader } from '../utils/table'
import { useRouter } from 'vue-router'
import { useDashboardStore } from '../stores/dashboard'
import { useUrlState } from '../composables/useUrlState'

const store = useDashboardStore()
const router = useRouter()
const q = useUrlState({ key: 'q', defaultValue: '', parse: (v) => v ?? '', serialize: (v) => v })

const sorting = ref<{ id: string; desc: boolean }[]>([{ id: 'strategy', desc: false }])
const columnVisibility = ref<Record<string, boolean>>({})

const columns = [
  { accessorKey: 'strategy', header: sortableHeader('Strategy') },
  { accessorKey: 'source', header: sortableHeader('Source') },
  { accessorKey: 'n_trades', header: sortableHeader('Trades') },
  { accessorKey: 'file', header: 'File', enableSorting: false, enableGlobalFilter: false },
  { accessorKey: 'actions', header: '', enableSorting: false, enableGlobalFilter: false },
]

const filteredRuns = computed(() => {
  const ql = q.value.trim().toLowerCase()
  if (!ql) return store.trade_runs
  return store.trade_runs.filter((r: any) =>
    (r.strategy || '').toLowerCase().includes(ql) ||
    (r.source || '').toLowerCase().includes(ql) ||
    (r.key || '').toLowerCase().includes(ql)
  )
})

const newestKey = computed(() => {
  const runs = [...store.trade_runs].sort((a: any, b: any) => (b.run_time || '').localeCompare(a.run_time || ''))
  return runs.length ? runs[0].key : ''
})

function runRowClass(row: any) {
  const key = row?.original?.key ?? row?.key
  return key && key === newestKey.value ? 'row-selected' : ''
}

function resetFilters() {
  q.value = ''
  columnVisibility.value = {}
  sorting.value = [{ id: 'strategy', desc: false }]
}

function refreshData() {
  store.fetchAll(true)
}

function openRun(r: any) {
  if (r && r.key) router.push('/trades/' + r.key)
}

onMounted(async () => {
  await store.fetchAll()
})
</script>

<style scoped>
.row-selected { background: var(--card-hover); }
</style>
