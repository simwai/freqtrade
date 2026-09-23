import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { StrategyRow, BacktestRow, BenchmarkRow, HyperoptRow, WalkforwardRow, HistoryData } from '../types/trade'

export const useStrategiesStore = defineStore('strategies', {
  state: () => ({
    items: [] as StrategyRow[],
    canonical: [] as StrategyRow[],
    backtests: [] as BacktestRow[],
    benchmarks: [] as BenchmarkRow[],
    hyperopt: [] as HyperoptRow[],
    walkforward: [] as WalkforwardRow[],
    history: {} as Record<string, HistoryData>,
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
        const { data } = await api.get<StrategyRow[]>('/api/strategies/summary')
        this.items = data || []
        this.canonical = data || []
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
        const { data: summary } = await api.get<StrategyRow[]>('/api/strategies/summary')
        this.canonical = summary || []
        this.items = summary || []
        if (summary?.length && summary[0].score) {
          this.scorecard = summary[0].score
        }
        if (summary?.length && summary[0].prop_firms) {
          this.propSpec = summary[0].prop_firms
        }
        const [hyperoptRaw, walkforwardRaw] = await Promise.all([
          api.get<HyperoptRow[]>('/api/hyperopt').catch(() => ({ data: [] })),
          api.get<WalkforwardRow[]>('/api/walkforward').catch(() => ({ data: [] })),
        ])
        this.hyperopt = hyperoptRaw.data || []
        this.walkforward = walkforwardRaw.data || []
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchOne(name: string) {
      const { data } = await api.get<StrategyRow>(`/api/strategy/${encodeURIComponent(name)}/summary`)
      return data
    },
  },
})