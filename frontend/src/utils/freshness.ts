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
let staleFailCount = 0
let backoffUntil = 0
const BACKOFF_CAP_MS = 1800000
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
  timer = setInterval(() => {
    if (document.hidden) return
    // Back off refresh attempts while the backend keeps failing so a wedged
    // server is not hammered with a new report-refresh job every cycle.
    if (Date.now() < backoffUntil) return
    ensureFresh(() => {
      // NOTE: Auto-refresh removed. onStale now only notifies UI.
      // User must manually click "Refresh" button to trigger rebuild.
      Promise.resolve()
        .then(() => onStale())
        .then(() => { staleFailCount = 0; backoffUntil = 0 })
        .catch(() => {
          staleFailCount += 1
          backoffUntil = Date.now() + Math.min(60000 * 2 ** staleFailCount, BACKOFF_CAP_MS)
        })
    })
  }, 180000)
}
export function onVisible(fn: () => void) {
  document.addEventListener('visibilitychange', () => { if (!document.hidden) fn() })
}
