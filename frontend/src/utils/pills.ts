export function corrClass(v: number): string {
  if (v < -0.2) return 'pass'
  if (v > 0.2) return 'fail'
  return 'warn'
}
export function ratioClass(ratio: number): string {
  if (ratio >= 0.6) return 'pass'
  if (ratio >= 0.4) return 'warn'
  return 'fail'
}
