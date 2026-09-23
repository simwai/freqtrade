import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { StrategyRow, BacktestRow, BenchmarkRow, HyperoptRow, WalkforwardRow, TradeRunRow, StrategyDetailResponse } from '../types/trade'

export const useStrategyDetailStore = defineStore('strategyDetail', {
  state: () => ({
    canonical: null as StrategyRow | null,
    backtests: [] as BacktestRow[],
    benchmarks: [] as BenchmarkRow[],
    hyperopt: [] as HyperoptRow[],
    walkforward: [] as WalkforwardRow[],
    tradeRuns: [] as TradeRunRow[],
    scorecard: {} as Record<string, unknown>,
    propSpec: {} as Record<string, unknown>,
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
        const { data } = await api.get<StrategyDetailResponse>(`/api/strategy/${encodeURIComponent(name)}/detail`)
        this.canonical = data.canonical || null
        this.backtests = (data.backtests || []) as BacktestRow[]
        this.benchmarks = (data.benchmarks || []) as BenchmarkRow[]
        this.hyperopt = (data.hyperopt || []) as HyperoptRow[]
        this.walkforward = (data.walkforward || []) as WalkforwardRow[]
        this.tradeRuns = (data.trade_runs || []) as TradeRunRow[]
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