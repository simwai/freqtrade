export function compareCells(av: any, bv: any, asc: boolean): number {
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
export function sortTableBy(table: any, idx: number, asc: boolean) {
  const tbody = table.querySelector('tbody')
  if (!tbody) return
  const rows = Array.from(tbody.rows)
  rows.sort((a: any, b: any) => {
    const av = a.cells[idx] ? a.cells[idx].textContent : ''
    const bv = b.cells[idx] ? b.cells[idx].textContent : ''
    return compareCells(av, bv, asc)
  })
  rows.forEach((r: any) => tbody.appendChild(r))
}
export function syncScrollStack(stack: any) {
  if (!stack || stack.dataset.syncWired) return
  stack.dataset.syncWired = '1'
  const head = stack.querySelector('.thead-scroll')
  const body = stack.querySelectorAll(':scope > .table-wrap')
  const bodyEl = body.length ? body[body.length - 1] : stack.querySelector('.table-wrap')
  if (!head || !bodyEl || head === bodyEl) return
  const paint = (el: any) => {
    el.classList.toggle('scroll-left', el.scrollLeft > 0)
    el.classList.toggle('scroll-right', el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }
  let lock = false
  const link = (from: any, to: any) => {
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
  link(head, bodyEl)
  link(bodyEl, head)
  paint(head)
  paint(bodyEl)
}
export function sortableTable(table: any) {
  if (table.dataset.sortWired) return
  table.dataset.sortWired = '1'
  table.querySelectorAll('thead th').forEach((th: any, idx: number) => {
    th.style.cursor = 'pointer'
    th.addEventListener('click', () => {
      table.querySelectorAll('thead th .arrow').forEach((x: any) => x.remove())
      const asc = th.getAttribute('data-asc') !== '1'
      sortTableBy(table, idx, asc)
      th.setAttribute('data-asc', asc ? '1' : '0')
      const arrow = document.createElement('span')
      arrow.className = 'arrow'
      arrow.textContent = asc ? String.fromCharCode(9650) : String.fromCharCode(9660)
      th.appendChild(arrow)
    })
  })
}
