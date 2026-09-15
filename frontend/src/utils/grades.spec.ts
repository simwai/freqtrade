import { describe, it, expect } from 'vitest'
import { scoreStrategy, gradeFromScore } from './grades'
describe('scoreStrategy', () => {
  it('perfect row yields 1', () => {
    const row = { sortino: 2, calmar: 2, profit_factor: 2, max_drawdown: 0.1, winrate: 0.6, trades: 200, worst_trade: -0.1 }
    expect(scoreStrategy(row)).toBe(1)
  })
  it('all warn yields 0.5', () => {
    const row = { sortino: 0.5, calmar: 0.5, profit_factor: 1.1, max_drawdown: 0.3, winrate: 0.4, trades: 50, worst_trade: -0.2 }
    expect(scoreStrategy(row)).toBe(0.5)
  })
  it('all fail yields 0', () => {
    const row = { sortino: 0.1, calmar: 0.1, profit_factor: 0.5, max_drawdown: 0.5, winrate: 0.2, trades: 10, worst_trade: -0.3 }
    expect(scoreStrategy(row)).toBe(0)
  })
  it('missing metrics skipped', () => {
    const row = { sortino: 2 }
    expect(scoreStrategy(row)).toBe(1)
  })
  it('grade boundaries', () => {
    expect(gradeFromScore(0.85)).toBe('A')
    expect(gradeFromScore(0.65)).toBe('B')
    expect(gradeFromScore(0.45)).toBe('C')
    expect(gradeFromScore(0.25)).toBe('D')
    expect(gradeFromScore(0.15)).toBe('na')
  })
})
