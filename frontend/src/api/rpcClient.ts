import { request } from './shared'

const DEV_PROXY_PREFIX = '/api/rpc'

function resolveUrl(path: string): string {
  const baseUrl = import.meta.env.VITE_RPC_API_URL || 'http://localhost:8080'
  if (import.meta.env.DEV && path.charAt(0) === '/') {
    return `${DEV_PROXY_PREFIX}${path}`
  }
  if (!import.meta.env.DEV && path.charAt(0) === '/') {
    return baseUrl + path
  }
  return path
}

export const rpcApi = {
  get: (url: string, config?: Record<string, unknown>) =>
    request(resolveUrl(url), { method: 'GET', params: (config?.params as Record<string, unknown>) || undefined }),
  post: (url: string, body?: unknown) =>
    request(resolveUrl(url), { method: 'POST', body }),
  delete: (url: string) =>
    request(resolveUrl(url), { method: 'DELETE' }),
  patch: (url: string, body?: unknown) =>
    request(resolveUrl(url), { method: 'PATCH', body }),
}

export function setRpcToken(token: string) {
  localStorage.setItem('rpc_api_token', token)
}

export function clearRpcToken() {
  localStorage.removeItem('rpc_api_token')
}
