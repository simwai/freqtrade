import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useStrategyDetailStore = defineStore('strategyDetail', {
  state: () => ({
    canonical: null as any | null,
    backtests: [] as any[],
    benchmarks: [] as any[],
    hyperopt: [] as any[],
    walkforward: [] as any[],
    tradeRuns: [] as any[],
    scorecard: {} as Record<string, any>,
    propSpec: {} as Record<string, any>,
    loading: false,
    error: null as string | null,
    currentName: '' as string,
  }),
  actions: {
    async load(name: string) {
      if (this.currentName === name && this.canonical) {
        this.loading = false
        this.error = null
        return
      }
      this.loading = true
      this.error = null
      this.currentName = name
      try {
        const { data } = await api.get(`/api/strategy/${encodeURIComponent(name)}/detail`)
        this.canonical = data.canonical || null
        this.backtests = data.backtests || []
        this.benchmarks = data.benchmarks || []
        this.hyperopt = data.hyperopt || []
        this.walkforward = data.walkforward || []
        this.tradeRuns = data.trade_runs || []
        this.scorecard = data.scorecard || {}
        this.propSpec = data.prop_firms_spec || {}
      } catch (e) {
        this.error = String(e)
        this.canonical = null
      } finally {
        this.loading = false
      }
    },
    clear() {
      this.canonical = null
      this.backtests = []
      this.benchmarks = []
      this.hyperopt = []
      this.walkforward = []
      this.tradeRuns = []
      this.currentName = ''
    },
  },
})
