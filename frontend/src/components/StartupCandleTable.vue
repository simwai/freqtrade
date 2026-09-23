<template>
  <div class="startup-candle-table">
    <UTable
      :data="indicators"
      :columns="columns"
      :loading="false"
      :sticky="true"
      class="w-full"
    >
      <template #name-cell="{ row }">
        <span class="font-mono">{{ (row.original as any).name }}</span>
      </template>
      <template #startup_candles-cell="{ row }">
        <span class="num" :class="startupClass((row.original as any).startup_candles)">{{ fmtNum((row.original as any).startup_candles) }}</span>
      </template>
      <template #num_candles-cell="{ row }">
        <span class="num">{{ fmtNum((row.original as any).num_candles) }}</span>
      </template>
      <template #max_diff-cell="{ row }">
        <span class="num" :class="diffClass((row.original as any).max_diff)">{{ fmtNum((row.original as any).max_diff) }}</span>
      </template>
      <template #details-cell="{ row }">
        <button class="btn-detail" @click="toggleDetails((row.original as any).name)">
          {{ expanded.has((row.original as any).name) ? '▼' : '▶' }}
        </button>
      </template>
    </UTable>

    <!-- Expanded details rows -->
    <template v-for="ind in indicators" :key="ind.name">
      <div v-if="expanded.has(ind.name)" class="detail-row">
      <div class="detail-header">
        <span class="detail-title">Candle-by-candle diffs for {{ ind.name }}</span>
        <span class="detail-count">{{ ind.diffs?.length || 0 }} candles</span>
      </div>
      <UTable
        :data="ind.diffs"
        :columns="detailColumns"
        :loading="false"
        :sticky="true"
        class="w-full detail-table"
      >
        <template #candle-cell="{ row }">
          <span class="num">{{ fmtNum((row.original as any).candle) }}</span>
        </template>
        <template #diff-cell="{ row }">
          <span class="num" :class="diffClass((row.original as any).diff)">{{ fmtNum((row.original as any).diff) }}</span>
        </template>
      </UTable>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { sortableHeader } from '../utils/table'

interface IndicatorDetail {
  name: string
  startup_candles: number
  num_candles: number
  max_diff: number
  diffs: Array<{ candle: number; diff: number }>
}

interface Props {
  indicators: IndicatorDetail[]
}

const props = defineProps<Props>()

const expanded = ref<Set<string>>(new Set())

const columns = [
  { accessorKey: 'name', header: sortableHeader('Indicator') },
  { accessorKey: 'startup_candles', header: sortableHeader('Startup Candles') },
  { accessorKey: 'num_candles', header: sortableHeader('Num Candles') },
  { accessorKey: 'max_diff', header: sortableHeader('Max Diff') },
  { accessorKey: 'details', header: '', enableSorting: false, enableGlobalFilter: false },
] as any[]

const detailColumns = [
  { accessorKey: 'candle', header: sortableHeader('Candle'), size: 80 },
  { accessorKey: 'diff', header: sortableHeader('Diff'), size: 120, accessorFn: (r: any) => r.diff },
] as any[]

function toggleDetails(name: string) {
  if (expanded.value.has(name)) {
    expanded.value.delete(name)
  } else {
    expanded.value.add(name)
  }
}

function startupClass(v: number) {
  if (!v) return ''
  return v > 100 ? 'warn' : v > 50 ? 'warn' : ''
}

function diffClass(v: number) {
  if (!v) return ''
  return v > 0 ? 'good' : 'bad'
}

function fmtNum(v: number) {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 6 })
}
</script>

<style scoped>
.startup-candle-table { width: 100%; }
.detail-row { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 12px; color: var(--text-dim); }
.detail-title { font-weight: 600; color: var(--text); }
.detail-count { font-size: 11px; }
.detail-table { margin-top: 8px; }
</style>
