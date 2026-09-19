const BASE_URL = import.meta.env.VITE_RPC_API_URL || 'http://localhost:8080'
const TIMEOUT_MS = 300000

// In dev mode, use Vite proxy path; in prod, use direct URL
const DEV_PROXY_PREFIX = '/api/rpc'

function getAuthHeader(): Record<string, string> {
  const token = import.meta.env.VITE_RPC_API_TOKEN || localStorage.getItem('rpc_api_token')
  if (token) {
    return { 'Authorization': `Bearer ${token}` }
  }
  // Fallback: check for basic auth in env
  const basic = import.meta.env.VITE_RPC_API_BASIC
  if (basic) {
    return { 'Authorization': `Basic ${basic}` }
  }
  return {}
}

function resolveUrl(path: string): string {
  if (import.meta.env.DEV && path.charAt(0) === '/') {
    return `${DEV_PROXY_PREFIX}${path}`
  }
  if (!import.meta.env.DEV && path.charAt(0) === '/') {
    return BASE_URL + path
  }
  return path
}

async function request(path: string, init: any = {}): Promise<any> {
  const params = init.params || {}
  let url = resolveUrl(path)
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
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(url, {
      method: init.method || 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader(),
      },
      body: init.body,
      signal: ctrl.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw e
    }
    console.error('RPC API error:', e)
    throw e
  } finally {
    clearTimeout(t)
  }
  if (!res.ok) {
    const err = new Error('RPC API error ' + res.status)
    ;(err as any).status = res.status
    throw err
  }
  const data = await res.clone().json().catch(() => res.text())
  return { data: data }
}

export const rpcApi = {
  get: (url: string, config?: any) => request(url, { method: 'GET', params: config ? config.params : undefined }),
  post: (url: string, body?: any) => request(url, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: (url: string) => request(url, { method: 'DELETE' }),
  patch: (url: string, body?: any) => request(url, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
}

export function setRpcToken(token: string) {
  localStorage.setItem('rpc_api_token', token)
}

export function clearRpcToken() {
  localStorage.removeItem('rpc_api_token')
}
