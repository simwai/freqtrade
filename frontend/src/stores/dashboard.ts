import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useDashboardStore = defineStore('dashboard', {
  state: () => ({
    canonical: [] as any[],
    backtests: [] as any[],
    benchmarks: [] as any[],
    hyperopt: [] as any[],
    walkforward: [] as any[],
    strategies: [] as any[],
    trade_runs: [] as any[],
    history: {} as Record<string, any>,
    scorecard: {} as Record<string, any>,
    propSpec: {} as Record<string, any>,
    configs: {} as Record<string, any>,
    currentCode: {} as Record<string, any>,
    currentCodeSet: {} as Record<string, any>,
    snapshotPaths: {} as Record<string, any>,
    snapshotCombined: {} as Record<string, any>,
    snapshotFiles: {} as Record<string, any>,
    backtestConfigs: {} as Record<string, any>,
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
        this.propSpec = data.prop_firms_spec || {}
        this.configs = data.configs || {}
        this.currentCode = data.current_code || {}
        this.currentCodeSet = data.current_code_set || {}
        this.snapshotPaths = data.snapshot_paths || {}
        this.snapshotCombined = data.snapshot_combined || {}
        this.snapshotFiles = data.snapshot_files || {}
        this.backtestConfigs = data.backtest_configs || {}
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
