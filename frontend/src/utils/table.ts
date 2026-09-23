import { h, type VNode } from 'vue'
import type { Column } from '@tanstack/vue-table'

// Shared TanStack column header renderer. Nuxt UI's UTable does not wire
// header-click sorting itself, so every sortable column uses this helper to
// keep the affordance (and the arrow indicator) identical across all views.
export function sortArrow(state: 'asc' | 'desc' | false): string {
  if (state === 'asc') return ' ▲'
  if (state === 'desc') return ' ▼'
  return ''
}

export function sortableHeader<T>(label: string) {
  const render = (ctx: { column: Column<T> }): VNode =>
    h(
      'span',
      {
        class: 'th-sort',
        onClick: () => ctx.column.toggleSorting(ctx.column.getIsSorted() === 'asc')
      },
      [label, h('span', { class: 'arrow' }, sortArrow(ctx.column.getIsSorted()))]
    )
  return Object.assign(render, { toggleLabel: label })
}
