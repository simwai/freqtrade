import { api } from '../api/client'

export async function checkFreshness(): Promise<unknown> {
  const { data } = await api.get('/api/freshness')
  return data
}

export async function triggerRefresh(): Promise<unknown> {
  const { data } = await api.post('/api/refresh', {})
  return data
}

let inFlight = false
let timer: ReturnType<typeof setTimeout> | null = null
let staleFailCount = 0
let backoffUntil = 0
const BACKOFF_CAP_MS = 1800000
const INTERVAL_MS = 180000

export async function ensureFresh(onStale: () => void): Promise<unknown> {
  if (inFlight) return null
  inFlight = true
  try {
    const d = await checkFreshness()
    if (d && (d as { stale?: boolean }).stale) onStale()
    return d
  } catch (e) {
    console.error('Freshness check error:', e)
    throw e
  } finally {
    inFlight = false
  }
}

export function startFreshnessLoop(onStale: () => void) {
  if (timer) return
  timer = setInterval(() => {
    if (document.hidden) return
    if (Date.now() < backoffUntil) return
    ensureFresh(() => {
      Promise.resolve()
        .then(() => onStale())
        .then(() => { staleFailCount = 0; backoffUntil = 0 })
        .catch(() => {
          staleFailCount += 1
          backoffUntil = Date.now() + Math.min(60000 * 2 ** staleFailCount, BACKOFF_CAP_MS)
        })
    })
  }, INTERVAL_MS)
}

export function onVisible(fn: () => void) {
  document.addEventListener('visibilitychange', () => { if (!document.hidden) fn() })
}
