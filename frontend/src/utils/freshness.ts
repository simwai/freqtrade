import { api } from '../api/client'
export async function checkFreshness(): Promise<any> {
  const { data } = await api.get('/api/freshness')
  return data
}
export async function triggerRefresh(): Promise<any> {
  const { data } = await api.post('/api/refresh', {})
  return data
}
let inFlight = false
let timer: any = null
export async function ensureFresh(onStale: () => void): Promise<any> {
  if (inFlight) return null
  inFlight = true
  try {
    const d = await checkFreshness()
    if (d && d.stale) onStale()
    return d
  } catch (e) { return null }
  finally { inFlight = false }
}
export function startFreshnessLoop(onStale: () => void) {
  if (timer) return
  timer = setInterval(() => { if (!document.hidden) ensureFresh(onStale) }, 180000)
}
export function onVisible(fn: () => void) {
  document.addEventListener('visibilitychange', () => { if (!document.hidden) fn() })
}
