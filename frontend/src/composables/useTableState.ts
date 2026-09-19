import { ref, computed, watch, type Ref, type WritableComputedRef } from 'vue'
import type { SortingState, VisibilityState, RowSelectionState } from '@tanstack/vue-table'

export interface UseTableStateOptions<T> {
  data: Ref<T[]> | WritableComputedRef<T[]>
  defaultSort?: SortingState[number]
  defaultVisibleColumns?: string[]
  defaultGlobalFilter?: string
  onRowSelect?: (rows: T[]) => void
}

export function useTableState<T>(options: UseTableStateOptions<T>) {
  const globalFilter = ref(options.defaultGlobalFilter ?? '')
  const sorting = ref<SortingState>(options.defaultSort ? [options.defaultSort] : [])
  const columnVisibility = ref<VisibilityState>({})
  const rowSelection = ref<RowSelectionState>({})

  if (options.defaultVisibleColumns) {
    const vis: VisibilityState = {}
    const visible = new Set(options.defaultVisibleColumns)
    for (const col of visible) { vis[col] = true }
    columnVisibility.value = vis
  }

  const filteredData = computed(() => {
    const q = globalFilter.value.trim().toLowerCase()
    if (!q) return options.data.value
    return options.data.value.filter((item) => {
      return Object.values(item as Record<string, unknown>).some((v) => {
        if (v === null || v === undefined || v === '') return false
        return String(v).toLowerCase().includes(q)
      })
    })
  })

  watch(
    rowSelection,
    (newSelection) => {
      if (options.onRowSelect) {
        const selected = options.data.value.filter((_item, idx: number) => newSelection[idx])
        options.onRowSelect(selected)
      }
    },
    { deep: true }
  )

  return {
    globalFilter,
    sorting,
    columnVisibility,
    rowSelection,
    filteredData,
    reset() {
      globalFilter.value = options.defaultGlobalFilter ?? ''
      sorting.value = options.defaultSort ? [options.defaultSort] : []
      columnVisibility.value = {}
      rowSelection.value = {}
    }
  }
}
