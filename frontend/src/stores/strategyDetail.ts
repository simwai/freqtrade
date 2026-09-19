import { defineStore } from 'pinia'
import { api } from '../api/client'

interface StrategyDetail {
  strategy: string
  status: string
  score?: { grade: string }
  profit_total?: number
  sortino?: number
  calmar?: number
  profit_factor?: number
  max_drawdown_account?: number
  prop_firms?: Record<string, unknown>
  basis: string
  timerange: string
  run_time: string
  source?: string
  notes?: string
}

interface StrategyDetailState {
  canonical: StrategyDetail | null
  backtests: unknown[]
  benchmarks: unknown[]
  hyperopt: unknown[]
  walkforward: unknown[]
  tradeRuns: unknown[]
  scorecard: Record<string, unknown>
  propSpec: Record<string, unknown>
  loading: boolean
  error: string | null
  currentName: string
}

export const useStrategyDetailStore = defineStore('strategyDetail', {
  state: (): StrategyDetailState => ({
    canonical: null,
    backtests: [] as unknown[],
    benchmarks: [] as unknown[],
    hyperopt: [] as unknown[],
    walkforward: [] as unknown[],
    tradeRuns: [] as unknown[],
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
        const { data } = await api.get(`/api/strategy/${encodeURIComponent(name)}/detail`)
        const d = data as { canonical?: StrategyDetail; backtests?: unknown[]; benchmarks?: unknown[]; hyperopt?: unknown[]; walkforward?: unknown[]; trade_runs?: unknown[]; scorecard?: Record<string, unknown>; prop_firms_spec?: Record<string, unknown> }
        this.canonical = d.canonical || null
        this.backtests = d.backtests || []
        this.benchmarks = d.benchmarks || []
        this.hyperopt = d.hyperopt || []
        this.walkforward = d.walkforward || []
        this.tradeRuns = d.trade_runs || []
        this.scorecard = d.scorecard || {}
        this.propSpec = d.prop_firms_spec || {}
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
