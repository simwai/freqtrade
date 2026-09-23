import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { TradeRunRow, StrategyDetailResponse } from '../types/trade'

export const useTradeRunsStore = defineStore('tradeRuns', {
  state: () => ({
    items: [] as TradeRunRow[],
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
        // Trade runs are fetched per-strategy via fetchByStrategy
        // fetchAll now just initializes the store
        this.items = []
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchByStrategy(name: string) {
      const { data } = await api.get<StrategyDetailResponse>(`/api/strategy/${encodeURIComponent(name)}/detail`)
      this.items = data.trade_runs || []
    },
  },
})