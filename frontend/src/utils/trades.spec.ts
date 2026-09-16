import { describe, it, expect } from 'vitest'
import { tpPriceForTrade, tmSuperSmoother, tlBisect, tlExitColor, getContrastColor, candleColors, markerColors, markMode, exitStyle, tlTfMs, TL_CANDLE_PRESETS, TL_MARKER_PRESETS, MARK } from './trades'
import type { CompactTrade } from './trades'
function mk(over: any): CompactTrade {
  const base: any = { p: 'X', s: 0, t: '', e: 'roi', o: '', c: '', or: 100, cr: 110, mn: 0, mx: 0, am: 1, sa: 100, lev: 1, pr: 0.1, pa: 10, d: 3600, sl: 90, slr: 0, isl: 0, islr: 0, fo: 0, fc: 0 }
  for (const k of Object.keys(over)) base[k] = over[k]
  return base as CompactTrade
}
describe('tpPriceForTrade', () => {
  it('long target', () => { expect(tpPriceForTrade(mk({}), { '60': 0.05 })).toBe(105) })
  it('short target', () => { expect(tpPriceForTrade(mk({ s: 1 }), { '60': 0.05 })).toBe(95) })
  it('null roi', () => { expect(tpPriceForTrade(mk({}), null)).toBe(null) })
  it('zero target', () => { expect(tpPriceForTrade(mk({}), { '60': 0 })).toBe(null) })
})
describe('tlBisect', () => {
  it('clamps and bisects', () => {
    expect(tlBisect([10, 20, 30], 5)).toBe(0)
    expect(tlBisect([10, 20, 30], 35)).toBe(2)
    expect(tlBisect([10, 20, 30], 20)).toBe(1)
  })
})
describe('tmSuperSmoother', () => {
  it('copies short input', () => { expect(tmSuperSmoother([1, 2])).toEqual([1, 2]) })
  it('keeps length', () => { expect(tmSuperSmoother([1, 2, 3, 4, 5, 6]).length).toBe(6) })
})
describe('tlExitColor', () => {
  it('maps reasons', () => {
    expect(tlExitColor(mk({ e: 'roi' }))).toBe('#00d4aa')
    expect(tlExitColor(mk({ e: 'stop_loss' }))).toBe('#ff4757')
    expect(tlExitColor(mk({ e: 'zzz' }))).toBe('#a89fc4')
  })
  it('supports win_loss and single styles', () => {
    expect(tlExitColor(mk({ pr: 0.1 }), 'win_loss', MARK)).toBe(MARK.win)
    expect(tlExitColor(mk({ pr: -0.1 }), 'win_loss', MARK)).toBe(MARK.loss)
    expect(tlExitColor(mk({ e: 'roi' }), 'single', MARK)).toBe(MARK.exit)
  })
})
describe('getContrastColor', () => {
  it('picks dark text on light fills', () => { expect(getContrastColor('#ffffff')).toBe('#1b1628') })
  it('picks light text on dark fills', () => { expect(getContrastColor('#000000')).toBe('#e9e4f5') })
})
describe('presets', () => {
  it('exposes six candle and six marker presets', () => {
    expect(Object.keys(TL_CANDLE_PRESETS).length).toBe(6)
    expect(Object.keys(TL_MARKER_PRESETS).length).toBe(6)
  })
  it('falls back to lab defaults', () => {
    expect(candleColors().name).toBe('Lab (default)')
    expect(markerColors().name).toBe('Lab (default)')
    expect(markMode()).toBe('rate')
    expect(exitStyle()).toBe('by_reason')
  })
})
describe('tlTfMs', () => {
  it('parses timeframe strings', () => {
    expect(tlTfMs('5m')).toBe(300000)
    expect(tlTfMs('1h')).toBe(3600000)
    expect(tlTfMs('1d')).toBe(86400000)
    expect(tlTfMs('nope')).toBe(null)
  })
})
