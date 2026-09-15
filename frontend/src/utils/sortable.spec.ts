import { describe, it, expect } from 'vitest'
import { compareCells } from './sortable'
describe('compareCells', () => {
  it('numeric both sides', () => {
    expect(compareCells('2', '10', true) < 0).toBe(true)
    expect(compareCells('2', '10', false) > 0).toBe(true)
  })
  it('empty sorts last ascending', () => {
    expect(compareCells('', '5', true) > 0).toBe(true)
    expect(compareCells('5', '', true) < 0).toBe(true)
  })
  it('strings compare', () => {
    expect(compareCells('b', 'a', true) > 0).toBe(true)
  })
})
