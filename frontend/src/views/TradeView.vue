<template>
  <section class="flex flex-col gap-4 min-w-0">
    <div class="section-head flex items-baseline justify-between gap-3 flex-wrap">
      <h2 class="text-lg font-semibold text-lavender">Trades</h2>
      <div class="controls flex gap-2.5 flex-wrap items-center">
        <UInput v-model="q" placeholder="Filter runs..." class="w-64" />
        <UButton variant="ghost" size="sm" @click="resetFilters" :disabled="!q && !Object.keys(columnVisibility).length">
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
        <span class="ml-3 text-text-dim">Loading trade runs...</span>
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
    <div v-else class="card p-4.5">
      <p v-if="newestKey" class="hint text-text-faint text-sm">auto-loaded · newest run {{ newestKey }}</p>
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
          <router-link :to="'/trades/' + (row.original as any).key" class="text-lavender hover:underline">{{ (row.original as any).strategy }}</router-link>
        </template>
        <template #file-cell="{ row }">
          <a :href="'/trades/' + (row.original as any).key + '.json'" target="_blank" @click.stop class="text-lavender hover:underline text-sm">JSON</a>
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
import { useTradeRunsStore } from '../stores/tradeRuns'
import { useUrlState } from '../composables/useUrlState'

const store = useTradeRunsStore()
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
] as any[]

const filteredRuns = computed(() => {
  const ql = q.value.trim().toLowerCase()
  if (!ql) return store.items
  return store.items.filter((r: any) =>
    (r.strategy || '').toLowerCase().includes(ql) ||
    (r.source || '').toLowerCase().includes(ql) ||
    (r.key || '').toLowerCase().includes(ql)
  )
})

const newestKey = computed(() => {
  const runs = [...store.items].sort((a: any, b: any) => (b.run_time || '').localeCompare(a.run_time || ''))
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
  store.fetchAll()
}

function openRun(r: any) {
  if (r && r.key) router.push('/trades/' + r.key)
}

onMounted(async () => {
  await store.fetchAll()
})
</script>

<style scoped>
.row-selected { background: var(--color-card-hover); }
</style>
