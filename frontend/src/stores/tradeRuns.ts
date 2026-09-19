import { defineStore } from 'pinia'
import { api } from '../api/client'

interface TradeRun {
  name: string
  status: string
  strategy: string
  [key: string]: unknown
}

export const useTradeRunsStore = defineStore('tradeRuns', {
  state: () => ({
    items: [] as TradeRun[],
    loading: false,
    error: null as string | null,
  }),
  getters: {
    filtered: (state) => state.items,
  },
  actions: {
    async fetchAll() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/api/data')
        const d = data as { trade_runs?: TradeRun[] }
        this.items = d.trade_runs || []
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchByStrategy(name: string) {
      const { data } = await api.get(`/api/strategy/${encodeURIComponent(name)}/detail`)
      this.items = (data as { trade_runs?: TradeRun[] }).trade_runs || []
    },
  },
})
