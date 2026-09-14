import { describe, it, expect } from 'vitest'
import { corrClass, ratioClass } from './pills'
describe('corrClass', () => {
  it('pass below -0.2', () => { expect(corrClass(-0.5)).toBe('pass') })
  it('fail above 0.2', () => { expect(corrClass(0.5)).toBe('fail') })
  it('warn between', () => { expect(corrClass(0)).toBe('warn') })
  it('boundary -0.2 is warn', () => { expect(corrClass(-0.2)).toBe('warn') })
  it('boundary 0.2 is warn', () => { expect(corrClass(0.2)).toBe('warn') })
})
describe('ratioClass', () => {
  it('pass at 0.6', () => { expect(ratioClass(0.6)).toBe('pass') })
  it('warn at 0.4', () => { expect(ratioClass(0.4)).toBe('warn') })
  it('fail below', () => { expect(ratioClass(0.2)).toBe('fail') })
})
