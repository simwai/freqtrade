import { createRouter, createWebHistory } from "vue-router"
import DashboardView from "../views/DashboardView.vue"
import StrategiesView from "../views/StrategiesView.vue"
import BenchmarkView from "../views/BenchmarkView.vue"
import HistoryView from "../views/HistoryView.vue"
import TradeView from "../views/TradeView.vue"
import LabView from "../views/LabView.vue"
import HyperoptView from "../views/HyperoptView.vue"
import WalkForwardView from "../views/WalkForwardView.vue"
import DryRunView from "../views/DryRunView.vue"
import StrategyDetail from "../views/StrategyDetail.vue"
import TradeDetail from "../views/TradeDetail.vue"
import JobDetail from "../views/JobDetail.vue"
import BacktestHistoryView from "../views/BacktestHistoryView.vue"
import RecursiveAnalysisView from "../views/RecursiveAnalysisView.vue"
import LookaheadAnalysisView from "../views/LookaheadAnalysisView.vue"

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    { path: "/dashboard", component: DashboardView },
    { path: "/strategies", component: StrategiesView },
    { path: "/benchmark", component: BenchmarkView },
    { path: "/lab", component: LabView },
    { path: "/lab/jobs/:id", component: JobDetail },
    { path: "/backtest/history", component: BacktestHistoryView },
    { path: "/analysis/recursive", component: RecursiveAnalysisView },
    { path: "/analysis/lookahead", component: LookaheadAnalysisView },
    { path: "/hyperopt", component: HyperoptView },
    { path: "/walkforward", component: WalkForwardView },
    { path: "/dryrun", component: DryRunView },
    { path: "/history", component: HistoryView },
    { path: "/trades", component: TradeView },
    { path: "/trades/:key", component: TradeDetail },
    { path: "/strategies/:name", component: StrategyDetail }
  ]
})
