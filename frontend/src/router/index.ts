import { createRouter, createWebHistory } from "vue-router"
import DashboardView from "../views/DashboardView.vue"
import StrategiesView from "../views/StrategiesView.vue"
import BenchmarkView from "../views/BenchmarkView.vue"
import HistoryView from "../views/HistoryView.vue"
import TradeView from "../views/TradeView.vue"
import LabView from "../views/LabView.vue"
import StrategyDetail from "../views/StrategyDetail.vue"

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    { path: "/dashboard", component: DashboardView },
    { path: "/strategies", component: StrategiesView },
    { path: "/benchmark", component: BenchmarkView },
    { path: "/history", component: HistoryView },
    { path: "/trades", component: TradeView },
    { path: "/lab", component: LabView },
    { path: "/strategies/:name", component: StrategyDetail }
  ]
})
