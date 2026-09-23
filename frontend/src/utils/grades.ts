export const DEFAULT_GRADE_DEFS = {
  sortino: { pass: 1.0, warn: 0.3, dir: 1, label: 'Sortino' },
  calmar: { pass: 1.0, warn: 0.3, dir: 1, label: 'Calmar' },
  profit_factor: { pass: 1.2, warn: 1.0, dir: 1, label: 'Profit factor' },
  max_drawdown: { pass: 0.2, warn: 0.4, dir: -1, label: 'Max drawdown' },
  winrate: { pass: 0.45, warn: 0.35, dir: 1, label: 'Win rate' },
  trades: { pass: 100, warn: 30, dir: 1, label: 'Trades' },
  worst_trade: { pass: -0.15, warn: -0.25, dir: 1, label: 'Worst trade' }
}
export const GRADE_ORDER = ['A','B','C','D','na']
export function gradeFromScore(score: number): string {
  if (score >= 0.8) return 'A'
  if (score >= 0.6) return 'B'
  if (score >= 0.4) return 'C'
  if (score >= 0.2) return 'D'
  return 'na'
}
export function scoreStrategy(row: any): number {
  const d: Record<string, any> = DEFAULT_GRADE_DEFS
  let s = 0
  let cnt = 0
  for (const k of Object.keys(d)) {
    const v = row[k]
    if (v === undefined || v === null) continue
    const def = d[k]
    const dir = def.dir
    const pass = def.pass
    const warn = def.warn
    let metricScore = 0
    if (dir > 0) {
      if (v >= pass) metricScore = 1
      else if (v >= warn) metricScore = 0.5
      else metricScore = 0
    } else {
      if (v <= pass) metricScore = 1
      else if (v <= warn) metricScore = 0.5
      else metricScore = 0
    }
    s += metricScore
    cnt += 1
  }
  return cnt ? s / cnt : 0
}
export function activeGradeFactors(scorecard: any) {
  const saved = localStorage.getItem('gradeFactors')
  if (saved) {
    try { return JSON.parse(saved) } catch (e) {}
  }
  const base: any = {
    sortino: { pass: scorecard.sortino?.pass || 1.0, warn: scorecard.sortino?.warn || 0.3, dir: 1, higher_is_better: true, label: 'Sortino' },
    calmar: { pass: scorecard.calmar?.pass || 1.0, warn: scorecard.calmar?.warn || 0.3, dir: 1, higher_is_better: true, label: 'Calmar' },
    profit_factor: { pass: scorecard.profit_factor?.pass || 1.2, warn: scorecard.profit_factor?.warn || 1.0, dir: 1, higher_is_better: true, label: 'Profit factor' },
    max_drawdown: { pass: scorecard.max_drawdown?.pass || 0.2, warn: scorecard.max_drawdown?.warn || 0.4, dir: -1, higher_is_better: false, label: 'Max drawdown' },
    winrate: { pass: scorecard.winrate?.pass || 0.45, warn: scorecard.winrate?.warn || 0.35, dir: 1, higher_is_better: true, label: 'Win rate' },
    trades: { pass: scorecard.trades?.pass || 100, warn: scorecard.trades?.warn || 30, dir: 1, higher_is_better: true, label: 'Trades' },
    worst_trade: { pass: scorecard.worst_trade?.pass || -0.15, warn: scorecard.worst_trade?.warn || -0.25, dir: 1, higher_is_better: true, label: 'Worst trade' }
  }
  return base
}
export function saveGradeFactors(factors: any) {
  try { localStorage.setItem('gradeFactors', JSON.stringify(factors)) } catch (e) {}
}
export function scoreRowTuned(row: any, factors: any): number {
  let s = 0
  let cnt = 0
  for (const k of Object.keys(factors)) {
    const v = row[k]
    if (v === undefined || v === null) continue
    const f = factors[k]
    const dir = f.dir || (f.higher_is_better ? 1 : -1)
    const pass = f.pass
    const warn = f.warn
    let metricScore = 0
    if (dir > 0) {
      if (v >= pass) metricScore = 1
      else if (v >= warn) metricScore = 0.5
      else metricScore = 0
    } else {
      if (v <= pass) metricScore = 1
      else if (v <= warn) metricScore = 0.5
      else metricScore = 0
    }
    s += metricScore
    cnt += 1
  }
  return cnt ? s / cnt : 0
}
