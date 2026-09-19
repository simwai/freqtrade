import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useStrategiesStore = defineStore('strategies', {
  state: () => ({
    items: [] as any[],
    backtests: [] as any[],
    benchmarks: [] as any[],
    loading: false,
    error: null as string | null,
    scorecard: {} as Record<string, any>,
    propSpec: {} as Record<string, any>,
  }),
  getters: {
    filtered: (state) => state.items,
  },
  actions: {
    async fetchAll(force = false) {
      if (!force && this.items.length) {
        this.loading = false
        this.error = null
        return
      }
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/api/strategies/summary')
        this.items = data || []
        // Extract scorecard and propSpec from first item if available
        if (this.items.length && this.items[0].score) {
          this.scorecard = this.items[0].score
        }
        if (this.items.length && this.items[0].prop_firms) {
          this.propSpec = this.items[0].prop_firms
        }
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchFullData() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/api/data')
        this.backtests = data.backtests || []
        this.benchmarks = data.benchmarks || []
        this.items = data.canonical || []
        if (this.items.length && this.items[0].score) {
          this.scorecard = this.items[0].score
        }
        if (this.items.length && this.items[0].prop_firms) {
          this.propSpec = this.items[0].prop_firms
        }
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchOne(name: string) {
      const { data } = await api.get(`/api/strategy/${encodeURIComponent(name)}/summary`)
      return data
    },
  },
})
