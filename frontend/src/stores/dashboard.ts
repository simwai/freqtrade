import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useDashboardStore = defineStore('dashboard', {
  state: () => ({
    canonical: [],
    backtests: [],
    benchmarks: [],
    hyperopt: [],
    walkforward: [],
    strategies: [],
    trade_runs: [],
    history: {},
    scorecard: {},
    loading: false,
    error: null as string | null
  }),
  actions: {
    async fetchAll(force = false) {
      if (force == false) {
        if (this.canonical.length) return
      }
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/api/data')
        this.canonical = data.canonical || []
        this.backtests = data.backtests || []
        this.benchmarks = data.benchmarks || []
        this.hyperopt = data.hyperopt || []
        this.walkforward = data.walkforward || []
        this.history = data.history || {}
        this.strategies = data.strategies || []
        this.trade_runs = data.trade_runs || []
        this.scorecard = data.scorecard || {}
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchJobs() {
      const { data } = await api.get('/api/jobs')
      return data
    }
  }
})
