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
  notes?: string
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

interface StrategiesState {
  items: StrategyRow[]
  backtests: any[]
  benchmarks: any[]
  loading: boolean
  error: string | null
  scorecard: Record<string, unknown>
  propSpec: Record<string, unknown>
}

export const useStrategiesStore = defineStore('strategies', {
  state: (): StrategiesState => ({
    items: [] as StrategyRow[],
    backtests: [] as any[],
    benchmarks: [] as any[],
    loading: false,
    error: null as string | null,
    scorecard: {} as Record<string, unknown>,
    propSpec: {} as Record<string, unknown>,
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
        this.items = (data as StrategyRow[]) || []
        if (this.items.length && this.items[0].score) {
          this.scorecard = this.items[0].score as Record<string, unknown>
        }
        if (this.items.length && this.items[0].prop_firms) {
          this.propSpec = this.items[0].prop_firms as Record<string, unknown>
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
        const d = data as { backtests?: any[]; benchmarks?: any[]; canonical?: any[]; scorecard?: Record<string, unknown>; prop_firms?: Record<string, unknown> }
        this.backtests = d.backtests || []
        this.benchmarks = d.benchmarks || []
        this.items = d.canonical || []
        if (this.items.length && this.items[0].score) {
          this.scorecard = this.items[0].score as Record<string, unknown>
        }
        if (this.items.length && this.items[0].prop_firms) {
          this.propSpec = this.items[0].prop_firms as Record<string, unknown>
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
