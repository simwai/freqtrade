export interface GradeDefinition {
  pass: number
  warn: number
  dir: number
  label: string
}

export interface GradeFactor {
  pass: number
  warn: number
  dir: number
  higher_is_better?: boolean
  label: string
}

export const DEFAULT_GRADE_DEFS: Record<string, GradeDefinition> = {
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

export function scoreStrategy(row: Record<string, unknown>): number {
  return gradedScore(row, DEFAULT_GRADE_DEFS)
}

export function activeGradeFactors(scorecard: Record<string, unknown>): Record<string, GradeFactor> {
  const saved = localStorage.getItem('gradeFactors')
  if (saved) {
    try { return JSON.parse(saved) } catch { /* ignore parse errors */ }
  }
  const base: Record<string, GradeFactor> = {
    sortino: { pass: (scorecard.sortino as GradeDefinition)?.pass || 1.0, warn: (scorecard.sortino as GradeDefinition)?.warn || 0.3, dir: 1, higher_is_better: true, label: 'Sortino' },
    calmar: { pass: (scorecard.calmar as GradeDefinition)?.pass || 1.0, warn: (scorecard.calmar as GradeDefinition)?.warn || 0.3, dir: 1, higher_is_better: true, label: 'Calmar' },
    profit_factor: { pass: (scorecard.profit_factor as GradeDefinition)?.pass || 1.2, warn: (scorecard.profit_factor as GradeDefinition)?.warn || 1.0, dir: 1, higher_is_better: true, label: 'Profit factor' },
    max_drawdown: { pass: (scorecard.max_drawdown as GradeDefinition)?.pass || 0.2, warn: (scorecard.max_drawdown as GradeDefinition)?.warn || 0.4, dir: -1, higher_is_better: false, label: 'Max drawdown' },
    winrate: { pass: (scorecard.winrate as GradeDefinition)?.pass || 0.45, warn: (scorecard.winrate as GradeDefinition)?.warn || 0.35, dir: 1, higher_is_better: true, label: 'Win rate' },
    trades: { pass: (scorecard.trades as GradeDefinition)?.pass || 100, warn: (scorecard.trades as GradeDefinition)?.warn || 30, dir: 1, higher_is_better: true, label: 'Trades' },
    worst_trade: { pass: (scorecard.worst_trade as GradeDefinition)?.pass || -0.15, warn: (scorecard.worst_trade as GradeDefinition)?.warn || -0.25, dir: 1, higher_is_better: true, label: 'Worst trade' }
  }
  return base
}

export function saveGradeFactors(factors: Record<string, GradeFactor>): void {
  try { localStorage.setItem('gradeFactors', JSON.stringify(factors)) } catch { /* ignore */ }
}

export function scoreRowTuned(row: Record<string, unknown>, factors: Record<string, GradeFactor>): number {
  return gradedScore(row, factors)
}

function gradedScore(row: Record<string, unknown>, factors: Record<string, GradeDefinition | GradeFactor>): number {
  let s = 0
  let cnt = 0
  for (const k of Object.keys(factors)) {
    const v = row[k] as number | undefined
    if (v === undefined || v === null) continue
    const f = factors[k]
    const dir = (f as GradeDefinition | GradeFactor).dir || ((f as GradeFactor).higher_is_better ? 1 : -1)
    const pass = (f as GradeDefinition | GradeFactor).pass
    const warn = (f as GradeDefinition | GradeFactor).warn
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
