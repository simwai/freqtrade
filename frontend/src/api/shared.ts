const TIMEOUT_MS = 300000

interface RequestOptions {
  method?: string
  params?: Record<string, unknown>
  body?: unknown
  headers?: Record<string, string>
}

async function request(path: string, init: RequestOptions = {}): Promise<{ data: unknown }> {
  const { method = 'GET', params, body, headers = {} } = init
  let url = path
  const keys = Object.keys(params || {})
  if (keys.length) {
    const qs = new URLSearchParams()
    for (const k of keys) {
      const v = (params || {})[k]
      if (v !== undefined && v !== null) qs.append(k, String(v))
    }
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw e
    }
    console.error('API error:', e)
    throw e
  } finally {
    clearTimeout(t)
  }
  if (!res.ok) {
    const err = new Error('API error ' + res.status)
    throw err
  }
  const data = await res.clone().json().catch(() => res.text())
  return { data }
}

export { request, TIMEOUT_MS }
export type { RequestOptions }
