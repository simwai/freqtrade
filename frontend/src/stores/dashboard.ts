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

export interface BacktestRow {
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
  loss_function?: string
  spaces?: string
  train_days?: number
  test_days?: number
  step_days?: number
  n_windows?: number
  profitable_windows?: number
  epochs?: number
  config_hash?: string
  config_json?: string
  code_hash?: string
  trading_mode?: string
  timeframe?: string
  [key: string]: unknown
}

export interface BenchmarkRow {
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
  loss_function?: string
  spaces?: string
  epochs?: number
  config_hash?: string
  config_json?: string
  code_hash?: string
  trading_mode?: string
  timeframe?: string
  [key: string]: unknown
}

export interface HyperoptRow {
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
  loss_function?: string
  spaces?: string
  epochs?: number
  config_hash?: string
  config_json?: string
  code_hash?: string
  trading_mode?: string
  timeframe?: string
  best_loss?: number
  random_state?: number
  jobs?: number
  min_trades?: number
  [key: string]: unknown
}

export interface WalkforwardRow {
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
  loss_function?: string
  spaces?: string
  epochs?: number
  train_days?: number
  test_days?: number
  step_days?: number
  n_windows?: number
  profitable_windows?: number
  config_hash?: string
  config_json?: string
  code_hash?: string
  trading_mode?: string
  timeframe?: string
  [key: string]: unknown
}

export interface TradeRunRow {
  key: string
  strategy: string
  source: string
  n_trades: number
  run_time: string
  [key: string]: unknown
}

export interface HistoryData {
  dates: string[]
  profit: number[]
  sortino: number[]
  calmar: number[]
  profit_factor: number[]
  max_drawdown: number[]
  winrate: number[]
  trades: number[]
  [key: string]: unknown
}

interface DataResponse {
  canonical: StrategyRow[]
  backtests: BacktestRow[]
  benchmarks: BenchmarkRow[]
  hyperopt: HyperoptRow[]
  walkforward: WalkforwardRow[]
  strategies: StrategyRow[]
  trade_runs: TradeRunRow[]
  history: Record<string, HistoryData>
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
    backtests: [] as BacktestRow[],
    benchmarks: [] as BenchmarkRow[],
    hyperopt: [] as HyperoptRow[],
    walkforward: [] as WalkforwardRow[],
    strategies: [] as StrategyRow[],
    trade_runs: [] as TradeRunRow[],
    history: {} as Record<string, HistoryData>,
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
