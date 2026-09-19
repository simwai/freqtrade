import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { CompactTrade } from '../utils/trades'

export const useTradesStore = defineStore('trades', {
  state: () => ({
    key: '' as string,
    items: [] as CompactTrade[],
    total: 0,
    limit: 500,
    offset: 0,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async load(key: string, limit = 500, offset = 0) {
      this.loading = true
      this.error = null
      this.key = key
      this.limit = limit
      this.offset = offset
      try {
        const { data } = await api.get(`/api/trades/${encodeURIComponent(key)}`, {
          params: { limit, offset }
        })
        this.items = data.trades || []
        this.total = data.total || 0
        this.limit = data.limit || limit
        this.offset = data.offset || offset
      } catch (e) {
        this.error = String(e)
        this.items = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },
    async nextPage() {
      if (this.offset + this.limit < this.total) {
        await this.load(this.key, this.limit, this.offset + this.limit)
      }
    },
    async prevPage() {
      if (this.offset > 0) {
        await this.load(this.key, this.limit, Math.max(0, this.offset - this.limit))
      }
    },
    async goToPage(page: number) {
      const offset = (page - 1) * this.limit
      if (offset >= 0 && offset < this.total) {
        await this.load(this.key, this.limit, offset)
      }
    },
    clear() {
      this.key = ''
      this.items = []
      this.total = 0
      this.offset = 0
    },
  },
})
