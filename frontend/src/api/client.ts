import { request } from './shared'

export const api = {
  get: (url: string, config?: Record<string, unknown>) =>
    request(url, { method: 'GET', params: (config?.params as Record<string, unknown>) || undefined }),
  post: (url: string, body?: unknown) =>
    request(url, { method: 'POST', body }),
}
