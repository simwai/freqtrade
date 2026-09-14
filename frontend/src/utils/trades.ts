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
export function tlExitColor(t: CompactTrade): string {
  const key = String(t.e || '').toLowerCase()
  return (EXIT_PAL as any)[key] || EXIT_PAL.unknown
}
export function markerItem(params: any, api: any): any {
  const p = api.coord([api.value(0), api.value(1)])
  const kind = api.value(2), color = api.value(3), txt = api.value(4)
  const s = 7
  if (kind === 0) return { type: 'polygon', shape: { points: [[p[0], p[1]], [p[0] - s, p[1] + s * 1.7], [p[0] + s, p[1] + s * 1.7]] }, style: { fill: color } }
  if (kind === 1) return { type: 'polygon', shape: { points: [[p[0], p[1]], [p[0] - s, p[1] - s * 1.7], [p[0] + s, p[1] - s * 1.7]] }, style: { fill: color } }
  return { type: 'circle', shape: { cx: p[0], cy: p[1], r: 5 }, style: { fill: color } }
}
