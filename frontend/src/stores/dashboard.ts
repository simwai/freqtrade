import { defineStore } from 'pinia'
import { api } from '../api/client'

export interface StrategyRow {
  strategy: string
  status: string
  score?: { grade: string; grades?: Record<string, string> }
  profit_total: number
  total_trades: number
  sortino: number
  calmar: number
  profit_factor: number
  max_drawdown_account: number
  prop_firms?: Record<string, unknown>
  propPass?: number
  winrate: number
  basis: string
  timerange: string
  run_time: string
  source?: string
}

interface DataResponse {
  canonical: StrategyRow[]
  backtests: unknown[]
  benchmarks: unknown[]
  hyperopt: unknown[]
  walkforward: unknown[]
  strategies: StrategyRow[]
  trade_runs: unknown[]
  history: Record<string, unknown>
  scorecard: Record<string, unknown>
  prop_firms_spec?: Record<string, unknown>
  configs: Record<string, unknown>
  current_code?: Record<string, unknown>
  current_code_set?: Record<string, unknown>
  snapshot_paths?: Record<string, unknown>
  snapshot_combined?: Record<string, unknown>
  snapshot_files?: Record<string, unknown>
  backtest_configs?: Record<string, unknown>
}

export const useDashboardStore = defineStore('dashboard', {
  state: () => ({
    canonical: [] as StrategyRow[],
    backtests: [] as unknown[],
    benchmarks: [] as unknown[],
    hyperopt: [] as unknown[],
    walkforward: [] as unknown[],
    strategies: [] as StrategyRow[],
    trade_runs: [] as unknown[],
    history: {} as Record<string, unknown>,
    scorecard: {} as Record<string, unknown>,
    propSpec: {} as Record<string, unknown>,
    configs: {} as Record<string, unknown>,
    currentCode: {} as Record<string, unknown>,
    currentCodeSet: {} as Record<string, unknown>,
    snapshotPaths: {} as Record<string, unknown>,
    snapshotCombined: {} as Record<string, unknown>,
    snapshotFiles: {} as Record<string, unknown>,
    backtestConfigs: {} as Record<string, unknown>,
    loading: false,
    error: null as string | null
  }),
  actions: {
    async fetchAll(force = false) {
      if (!force && this.canonical.length) {
        this.loading = false
        this.error = null
        return
      }
      await this.fetchFullData()
    },
    async fetchFullData() {
      this.loading = true
      this.error = null
      try {
        const { data } = await api.get('/api/data')
        const d = data as DataResponse
        this.canonical = d.canonical || []
        this.backtests = d.backtests || []
        this.benchmarks = d.benchmarks || []
        this.hyperopt = d.hyperopt || []
        this.walkforward = d.walkforward || []
        this.strategies = d.strategies || []
        this.trade_runs = d.trade_runs || []
        this.history = d.history || {}
        this.scorecard = d.scorecard || {}
        this.propSpec = d.prop_firms_spec || {}
        this.configs = d.configs || {}
        this.currentCode = d.current_code || {}
        this.currentCodeSet = d.current_code_set || {}
        this.snapshotPaths = d.snapshot_paths || {}
        this.snapshotCombined = d.snapshot_combined || {}
        this.snapshotFiles = d.snapshot_files || {}
        this.backtestConfigs = d.backtest_configs || {}
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
