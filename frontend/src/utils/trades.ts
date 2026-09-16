export interface CompactTrade {
  p: string; s: number; t: string; e: string; o: string; c: string;
  or: number; cr: number; mn: number; mx: number; am: number;
  sa: number; lev: number; pr: number; pa: number; d: number;
  sl: number; slr: number; isl: number; islr: number;
  fo: number; fc: number; px?: number[][]
}
export const EXIT_PAL: Record<string, string> = {
  roi: '#00d4aa', trailing: '#ffd60a',
  stop_loss: '#ff4757', liquidation: '#ff4757',
  signal: '#00d4aa', force: '#ff4757',
  delist: '#ff4757', exit_signal: '#00d4aa',
  unknown: '#a89fc4'
}
export function tradeMs(s: string): number {
  const v = String(s).replace(' ', 'T')
  if (/[Z+]/.test(v.slice(-6))) {
    return Date.parse(v)
  }
  return Date.parse(v + 'Z')
}
export function tlBisect(times: number[], ms: number): number {
  let lo = 0, hi = times.length - 1
  if (ms <= times[0]) return 0
  if (ms >= times[hi]) return hi
  while (lo < hi - 1) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= ms) lo = mid; else hi = mid
  }
  return lo
}
export function tmSuperSmoother(p: number[]): number[] {
  const n = p.length
  if (n < 5) return p.slice()
  const period = Math.max(3, Math.min(10, Math.round(n / 3)))
  const a1 = Math.exp(-1.414 * Math.PI / period)
  const b1 = 2 * a1 * Math.cos(1.414 * Math.PI / period)
  const c2 = b1, c3 = -a1 * a1, c1 = 1 - c2 - c3
  const out = p.slice()
  for (let i = 2; i < n; i++) {
    out[i] = c1 * (p[i] + p[i - 1]) / 2 + c2 * out[i - 1] + c3 * out[i - 2]
  }
  return out
}
export function tpPriceForTrade(t: CompactTrade, roi: any): number | null {
  if (!roi) return null
  const minutes = Math.max(0, Math.floor((t.d || 0) / 60))
  const keys = Object.keys(roi).map((k: string) => Number(k)).filter((n: number) => Number.isFinite(n)).sort((a: number, b: number) => a - b)
  if (!keys.length) return null
  let chosen = keys[0]
  for (const k of keys) { if (k <= minutes) chosen = k; else break }
  const target = Number(roi[String(chosen)] || 0)
  if (target <= 0) return null
  const rate = Number(t.or)
  if (!Number.isFinite(rate) || rate <= 0) return null
  return t.s ? rate * (1 - target) : rate * (1 + target)
}
export const MARK = { entLong: '#00d4aa', entShort: '#ff4757', exit: '#ffd60a', win: '#00d4aa', loss: '#ff4757' }
export function tlExitColor(t: CompactTrade, style?: string, mc?: any): string {
  const st = style || (typeof localStorage !== 'undefined' ? localStorage.getItem('tlExitStyle') || 'by_reason' : 'by_reason')
  if (st === 'single') return (mc || MARK).exit
  if (st === 'win_loss') return (t.pr || 0) >= 0 ? (mc || MARK).win : (mc || MARK).loss
  const key = String(t.e || '').toLowerCase()
  return (EXIT_PAL as any)[key] || EXIT_PAL.unknown
}
export function getContrastColor(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16)
  return 0.299 * r + 0.587 * g + 0.114 * b > 128 ? '#1b1628' : '#e9e4f5'
}
export function markerItem(_params: any, api: any): any {
  const p = api.coord([api.value(0), api.value(1)])
  const kind = api.value(2), color = api.value(3), txt = api.value(4)
  const s = 7
  if (kind === 0) return { type: 'polygon', shape: { points: [[p[0], p[1]], [p[0] - s, p[1] + s * 1.7], [p[0] + s, p[1] + s * 1.7]] }, style: { fill: color } }
  if (kind === 1) return { type: 'polygon', shape: { points: [[p[0], p[1]], [p[0] - s, p[1] - s * 1.7], [p[0] + s, p[1] - s * 1.7]] }, style: { fill: color } }
  return {
    type: 'circle', shape: { cx: p[0], cy: p[1], r: 5 },
    style: { fill: color, stroke: '#1b1628', lineWidth: 1 },
    textContent: { style: { text: txt, fill: getContrastColor(color), fontSize: 10, fontWeight: 600 } },
    textConfig: { position: kind === 2 ? 'top' : 'bottom', distance: 4 }
  }
}

export interface CandlePreset { name: string, up: string, upB: string, down: string, downB: string }
export const TL_CANDLE_PRESETS: Record<string, CandlePreset> = {
  lab: { name: 'Lab (default)', up: 'rgba(0,212,170,0.45)', upB: '#00d4aa', down: 'rgba(255,71,87,0.45)', downB: '#ff4757' },
  tv: { name: 'TradingView', up: 'rgba(38,166,154,0.9)', upB: '#26a69a', down: 'rgba(239,83,80,0.9)', downB: '#ef5350' },
  classic: { name: 'Classic', up: 'rgba(16,185,129,0.95)', upB: '#10b981', down: 'rgba(239,68,68,0.95)', downB: '#ef4444' },
  ghost: { name: 'Ghost (dim)', up: 'rgba(0,212,170,0.22)', upB: '#00d4aa', down: 'rgba(255,71,87,0.10)', downB: '#ff4757' },
  mint: { name: 'Mint & Rajah', up: 'rgba(0,255,136,0.85)', upB: '#00ff88', down: 'rgba(255,51,102,0.85)', downB: '#ff3366' },
  cyanpink: { name: 'Cyan & Pink', up: 'rgba(0,255,255,0.85)', upB: '#00ffff', down: 'rgba(255,0,127,0.85)', downB: '#ff007f' }
}
export interface MarkerPreset { name: string, win: string, loss: string, entLong: string, entShort: string, exit: string }
export const TL_MARKER_PRESETS: Record<string, MarkerPreset> = {
  lab: { name: 'Lab (default)', win: '#00d4aa', loss: '#ff4757', entLong: '#00d4aa', entShort: '#ff4757', exit: '#ffd60a' },
  tv: { name: 'TradingView', win: '#26a69a', loss: '#ef5350', entLong: '#26a69a', entShort: '#ef5350', exit: '#ffd60a' },
  classic: { name: 'Classic', win: '#10b981', loss: '#ef4444', entLong: '#10b981', entShort: '#ef4444', exit: '#ffd60a' },
  ghost: { name: 'Ghost (dim)', win: '#00d4aa', loss: '#ff4757', entLong: '#00d4aa', entShort: '#ff4757', exit: '#ffd60a' },
  mint: { name: 'Mint & Rajah', win: '#00ff88', loss: '#ff3366', entLong: '#00ff88', entShort: '#ff3366', exit: '#ffff00' },
  cyanpink: { name: 'Cyan & Pink', win: '#00ffff', loss: '#ff007f', entLong: '#00ffff', entShort: '#ff007f', exit: '#ffcc00' }
}
function stored(key: string, fallback: string): string {
  try { return localStorage.getItem(key) || fallback } catch (e) { return fallback }
}
export function candleColors(): CandlePreset {
  return TL_CANDLE_PRESETS[stored('tlCandlePreset', 'lab')] || TL_CANDLE_PRESETS.lab
}
export function markerColors(): MarkerPreset {
  return TL_MARKER_PRESETS[stored('tlMarkerPreset', 'lab')] || TL_MARKER_PRESETS.lab
}
export function markMode(): string {
  return stored('tlMark', 'rate') === 'hilo' ? 'hilo' : 'rate'
}
export function exitStyle(): string {
  const v = stored('tlExitStyle', 'by_reason')
  return v === 'single' || v === 'win_loss' ? v : 'by_reason'
}
export function persistPreset(kind: string, value: string): void {
  const key = kind === 'candle' ? 'tlCandlePreset' : kind === 'marker' ? 'tlMarkerPreset' : kind === 'mark' ? 'tlMark' : 'tlExitStyle'
  try { localStorage.setItem(key, value) } catch (e) {}
}
export function tlTfMs(tf: string): number | null {
  const m = /^(\d+)\s*([mhd])$/i.exec(String(tf || '').trim())
  if (!m) return null
  return Number(m[1]) * ({ m: 60e3, h: 3600e3, d: 86400e3 } as any)[m[2].toLowerCase()]
}
