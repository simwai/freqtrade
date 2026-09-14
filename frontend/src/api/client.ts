const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8088'
const TIMEOUT_MS = 120000
async function request(path: string, init: any = {}): Promise<any> {
  const params = init.params || {}
  let url = path
  const keys = Object.keys(params)
  if (keys.length) {
    const qs = new URLSearchParams()
    for (const k of keys) {
      const v = params[k]
      if (v !== undefined && v !== null) qs.append(k, String(v))
    }
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  if (url.charAt(0) === '/') url = BASE_URL + url
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(url, { method: init.method || 'GET', headers: { 'Content-Type': 'application/json' }, body: init.body, signal: ctrl.signal })
  } catch (e) {
    console.error('API error:', e)
    throw e
  } finally {
    clearTimeout(t)
  }
  if (!res.ok) {
    const err = new Error('API error ' + res.status)
    console.error('API error:', err)
    throw err
  }
  const data = await res.json().catch(() => null)
  return { data: data }
}
export const api = {
  get: (url: string, config?: any) => request(url, { method: 'GET', params: config ? config.params : undefined }),
  post: (url: string, body?: any) => request(url, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}
