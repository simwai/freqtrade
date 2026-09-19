/**
 * Shared formatting composable for strategy display logic.
 * Eliminates duplication across DashboardView, StrategiesView, and StrategyDrawer.
 */
export function useStrategyFormat() {
  function gradePill(grade: string | undefined): string {
    if (!grade || grade === '—') return 'pill gna'
    if (grade === 'A') return 'pill gA'
    if (grade === 'B') return 'pill gB'
    if (grade === 'C') return 'pill gC'
    if (grade === 'D') return 'pill gD'
    if (grade === 'F') return 'pill gF'
    return 'pill gna'
  }

  function statusClass(status: string | undefined): string {
    if (!status) return 'status'
    const sl = status.toLowerCase()
    if (sl === 'active') return 'status active'
    if (sl === 'experimental') return 'status experimental'
    if (sl === 'retired') return 'status retired'
    return 'status'
  }

  function profitClass(value: number | undefined): string {
    if (!value) return ''
    return value > 0 ? 'good' : value < 0 ? 'bad' : ''
  }

  function fmt(value: any, d = 3): string {
    if (value === null || value === undefined || value === '') return '—'
    const n = Number(value)
    if (!isFinite(n)) return '—'
    return n.toLocaleString('en-US', { maximumFractionDigits: d })
  }

  function fmtProfitPct(value: number | undefined): string {
    return value === null || value === undefined ? '—' : ((value || 0) * 100).toFixed(1) + '%'
  }

  function fmtRange(timerange: string | undefined): string {
    if (!timerange) return '—'
    const parts = String(timerange).split('-')
    const formatDate = (s: string) => (s && s.length === 8) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '?')
    return formatDate(parts[0]) + ' → ' + (parts[1] ? formatDate(parts[1]) : 'live')
  }

  function basisLabel(record: any): string {
    if (record.basis === 'registry') return 'no runs yet'
    return record.basis === 'benchmark' ? 'benchmark (fallback)' : 'last backtest'
  }

  function basisTooltip(record: any): string {
    if (record.basis === 'registry') return 'registered in the strategies table; no backtest or benchmark ingested yet'
    return 'metrics from ' + (record.basis === 'benchmark' ? 'benchmark' : 'backtest') + ' run ' + (record.source || '?') + ' · ' + (record.run_time || '?')
  }

  function propPassCount(record: any): number {
    const pf = record.prop_firms
    if (!pf) return -1
    const vals = Object.values(pf) as any[]
    if (vals.every((p: any) => p.verdict === 'na')) return -1
    return vals.filter((p: any) => p.verdict === 'pass').length
  }

  function propText(record: any): string {
    const pf = record.prop_firms
    if (!pf) return '—'
    const keys = Object.keys(pf)
    if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return '—'
    return keys.filter((k) => (pf as any)[k].verdict === 'pass').length + '/' + keys.length
  }

  function propTitle(record: any, propSpec: Record<string, any>): string {
    const pf = record.prop_firms
    if (!pf) return ''
    const keys = Object.keys(pf)
    const failed = keys.filter((k) => (pf as any)[k].verdict === 'fail').map((k) => propSpec[k]?.label || k)
    return failed.length ? 'failed: ' + failed.join(', ') : 'all programs pass'
  }

  function propClass(record: any): string {
    const pf = record.prop_firms
    if (!pf) return 'pill gna'
    const keys = Object.keys(pf)
    if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return 'pill gna'
    const passed = keys.filter((k) => (pf as any)[k].verdict === 'pass').length
    return passed === keys.length ? 'pill gA' : passed > 0 ? 'pill gC' : 'pill gF'
  }

  function fmt3(value: any): string {
    if (value === null || value === undefined || value === '') return '—'
    const n = Number(value)
    if (!isFinite(n)) return '—'
    return n.toLocaleString('en-US', { maximumFractionDigits: 3 })
  }

  function pfFmt(value: any): string {
    if (value === null || value === undefined || value === '') return '—'
    const n = Number(value)
    if (n === Infinity) return '∞'
    if (!isFinite(n)) return '—'
    return n.toLocaleString('en-US', { maximumFractionDigits: 3 })
  }

  function fmtPct(value: number): string {
    return value ? (value * 100).toFixed(1) + '%' : '—'
  }

  function fmtNum(value: number): string {
    return fmt(value, 2)
  }

  return {
    gradePill,
    statusClass,
    profitClass,
    fmt,
    fmtProfitPct,
    fmtRange,
    basisLabel,
    basisTooltip,
    propPassCount,
    propText,
    propTitle,
    propClass,
    fmt3,
    pfFmt,
    fmtPct,
    fmtNum,
  }
}
