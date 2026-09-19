import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useTradeRunsStore = defineStore('tradeRuns', {
  state: () => ({
    items: [] as any[],
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
        const { data } = await api.get('/api/strategies/summary')
        // Extract trade runs from the canonical data
        // We'll need to get the full data to get trade_runs
        const { data: fullData } = await api.get('/api/data')
        this.items = fullData.trade_runs || []
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchByStrategy(name: string) {
      const { data } = await api.get(`/api/strategy/${encodeURIComponent(name)}/detail`)
      this.items = data.trade_runs || []
    },
  },
})
