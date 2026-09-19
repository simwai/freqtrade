export function compareCells(av: unknown, bv: unknown, asc: boolean): number {
  const aEmpty = av === '' || av === undefined || av === null
  const bEmpty = bv === '' || bv === undefined || bv === null
  if (aEmpty && bEmpty) return 0
  if (aEmpty) return 1
  if (bEmpty) return -1
  const an = Number(av), bn = Number(bv)
  const useNum = !isNaN(an) && !isNaN(bn)
  const r = useNum ? an - bn : String(av).localeCompare(String(bv))
  return asc ? r : -r
}

export function sortTableBy(table: HTMLTableElement, idx: number, asc: boolean) {
  const tbody = table.querySelector('tbody')
  if (!tbody) return
  const rows = Array.from(tbody.rows)
  rows.sort((a, b) => {
    const av = a.cells[idx]?.textContent || ''
    const bv = b.cells[idx]?.textContent || ''
    return compareCells(av, bv, asc)
  })
  rows.forEach((r) => tbody.appendChild(r))
}

export function syncScrollStack(stack: HTMLElement) {
  if (!stack || stack.dataset.syncWired) return
  stack.dataset.syncWired = '1'
  const head = stack.querySelector('.thead-scroll') as HTMLElement | null
  const body = stack.querySelectorAll(':scope > .table-wrap')
  const bodyEl = body.length ? body[body.length - 1] : stack.querySelector('.table-wrap') as HTMLElement | null
  if (!head || !bodyEl || head === bodyEl) return
  const paint = (el: HTMLElement) => {
    el.classList.toggle('scroll-left', el.scrollLeft > 0)
    el.classList.toggle('scroll-right', el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }
  let lock = false
  const link = (from: HTMLElement, to: HTMLElement) => {
    from.addEventListener('scroll', () => {
      paint(from)
      paint(to)
      if (lock) return
      lock = true
      to.scrollLeft = from.scrollLeft
      paint(to)
      lock = false
    })
  }
  link(head as HTMLElement, bodyEl as HTMLElement)
  link(bodyEl as HTMLElement, head as HTMLElement)
  paint(head as HTMLElement)
  paint(bodyEl as HTMLElement)
}

export function sortableTable(table: HTMLTableElement) {
  if (table.dataset.sortWired) return
  table.dataset.sortWired = '1'
  table.querySelectorAll('thead th').forEach((th, idx) => {
    const thEl = th as HTMLElement
    thEl.style.cursor = 'pointer'
    thEl.addEventListener('click', () => {
      table.querySelectorAll('thead th .arrow').forEach((x) => x.remove())
      const asc = thEl.getAttribute('data-asc') !== '1'
      sortTableBy(table, idx, asc)
      thEl.setAttribute('data-asc', asc ? '1' : '0')
      const arrow = document.createElement('span')
      arrow.className = 'arrow'
      arrow.textContent = asc ? String.fromCharCode(9650) : String.fromCharCode(9660)
      th.appendChild(arrow)
    })
  })
}
