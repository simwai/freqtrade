<template>
  <div class="drawer-overlay" v-on:click="close"></div>
  <div class="drawer">
    <div class="drawer-header">
      <h2>{{ strategy.strategy }}</h2>
      <span class="grade-pill" :class="gradePill(strategy.score?.grade)">{{ strategy.score?.grade || '?' }}</span>
      <button class="close-btn" v-on:click="close">×</button>
    </div>
    <div class="drawer-tabs">
      <button :class="{ active: tab === 'overview' }" v-on:click="tab = 'overview'">Overview</button>
      <button :class="{ active: tab === 'code' }" v-on:click="tab = 'code'">Code</button>
      <button :class="{ active: tab === 'config' }" v-on:click="tab = 'config'">Config</button>
      <button :class="{ active: tab === 'params' }" v-on:click="tab = 'params'">Params</button>
      <button :class="{ active: tab === 'prop' }" v-on:click="tab = 'prop'">Prop</button>
    </div>

    <div v-if="tab === 'overview'" class="drawer-content">
      <table class="drawer-table">
        <tbody>
          <tr v-for="(g, k) in strategy.score?.grades" :key="k">
            <td>{{ k }}</td>
            <td>{{ g }}</td>
          </tr>
        </tbody>
      </table>
      <h3>Recent runs</h3>
      <ul class="runs-list">
        <li v-for="r in runs" :key="r.source">
          <span>{{ r.source }}</span>
          <span class="num" :class="profitClass(r.profit_total)">{{ fmtNum(r.profit_total) }}</span>
        </li>
      </ul>
    </div>

    <div v-if="tab === 'code'" class="drawer-content">
      <div class="code-header">
        <button v-on:click="loadCode" class="btn-secondary">Load code</button>
      </div>
      <pre class="code-block">{{ codeText || 'Click Load code to fetch strategy source' }}</pre>
    </div>

    <div v-if="tab === 'config'" class="drawer-content">
      <table class="drawer-table">
        <tbody>
          <tr v-for="row in configRows" :key="row.k">
            <td>{{ row.k }}</td>
            <td>{{ row.v }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="tab === 'params'" class="drawer-content">
      <pre class="code-block">{{ paramsText || 'No tuned params yet' }}</pre>
    </div>

    <div v-if="tab === 'prop'" class="drawer-content">
      <div v-if="propRows.length">
        <div v-for="row in propRows" :key="row.k" class="prop-row">
          <span>{{ row.label }}</span>
          <span :class="verdictClass(row.verdict)">{{ row.verdict }}</span>
        </div>
      </div>
      <div v-else class="empty-state">No prop evaluations.</div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'

const props = defineProps<{ name: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const store = useDashboardStore()
const tab = ref('overview')
const codeText = ref('')
const strategy = computed(() => store.canonical.find((s: any) => s.strategy === props.name) || { strategy: props.name, score: { grade: '?', grades: {} } })
const runs = computed(() => store.backtests.filter((b: any) => b.strategy === props.name).slice(0, 10))

const configRows = computed(() => {
  const raw = (strategy.value as any).config_json
  if (!raw) return []
  let cfg: any = {}
  try { cfg = JSON.parse(raw) } catch (e) { return [] }
  const keys = ['stake_currency', 'stake_amount', 'max_open_trades', 'timeframe', 'trading_mode', 'margin_mode', 'minimal_roi', 'stoploss', 'trailing_stop', 'exchange', 'pair_whitelist', 'dry_run', 'dry_run_wallet']
  return keys.filter((k) => cfg[k] !== undefined).map((k) => ({ k: k, v: typeof cfg[k] === 'object' ? JSON.stringify(cfg[k]) : String(cfg[k]) }))
})

const propRows = computed(() => {
  const pf = (strategy.value as any).prop_firms
  if (!pf) return []
  return Object.keys(pf).map((k) => ({ k: k, verdict: pf[k].verdict, label: (store.propSpec[k] && store.propSpec[k].label) || k }))
})

const paramsText = computed(() => {
  const raw = (strategy.value as any).best_params || (strategy.value as any).params_json
  if (!raw) return ''
  try { return JSON.stringify(typeof raw === 'string' ? JSON.parse(raw) : raw, null, 2) } catch (e) { return String(raw) }
})

async function loadCode() {
  const h = (strategy.value as any).code_hash
  if (!h) { codeText.value = 'no snapshot hash'; return }
  const { data } = await api.get('/api/strategy/file', { params: { hash: h } })
  codeText.value = typeof data === 'string' ? data : JSON.stringify(data)
}
function close() { emit('close') }
function gradePill(g: string) {
  if (!g || g === '—') return 'pill gna'
  if (g === 'A') return 'pill gA'
  if (g === 'B') return 'pill gB'
  if (g === 'C') return 'pill gC'
  if (g === 'D') return 'pill gD'
  if (g === 'F') return 'pill gF'
  return 'pill gna'
}
function verdictClass(v: string) {
  if (!v) return 'status'
  const vl = v.toLowerCase()
  if (vl.includes('pass')) return 'status active'
  if (vl.includes('fail')) return 'status retired'
  return 'status'
}
function profitClass(v: number) { if (!v) return ''; return v > 0 ? 'good' : v < 0 ? 'bad' : '' }
function fmtNum(v: number) { return v ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—' }
</script>

<style scoped>
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 99; }
.drawer { position: fixed; right: 0; top: 0; bottom: 0; width: 420px; max-width: 100vw; background: var(--card); border-left: 1px solid var(--border); z-index: 100; display: flex; flex-direction: column; box-shadow: -8px 0 24px rgba(0,0,0,.4); }
.drawer-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.drawer-header h2 { margin: 0; font-size: 16px; font-weight: 600; }
.grade-pill { font-size: 12px; font-weight: 600; }
.close-btn { background: transparent; border: none; color: var(--text-dim); font-size: 22px; cursor: pointer; line-height: 1; padding: 0 4px; }
.close-btn:hover { color: var(--bad); }
.drawer-tabs { display: flex; gap: 4px; padding: 8px 16px; background: var(--bg-soft); border-bottom: 1px solid var(--border); }
.drawer-tabs button { background: transparent; border: 1px solid transparent; color: var(--text-dim); padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 500; }
.drawer-tabs button:hover { color: var(--lavender); background: var(--card-hover); }
.drawer-tabs button.active { background: var(--lavender-ink); color: #fff; }
.drawer-content { flex: 1; overflow-y: auto; padding: 16px 18px; display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.drawer-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.drawer-table td { padding: 6px 8px; border-top: 1px solid var(--border); }
.drawer-table td:first-child { color: var(--text-dim); width: 40%; }
.drawer-table td:last-child { text-align: right; font-family: monospace; }
.runs-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.runs-list li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 8px; background: var(--bg-soft); border-radius: 8px; font-size: 12px; }
.runs-list li .num { font-family: monospace; white-space: nowrap; }
.code-header { margin-bottom: 8px; }
.code-block { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; overflow: auto; max-height: 300px; font-size: 11px; line-height: 1.5; color: var(--text-dim); white-space: pre-wrap; word-break: break-word; }
.prop-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); }
.prop-row:last-child { border-bottom: none; }
.prop-row span:first-child { color: var(--text-dim); font-size: 12px; }
.empty-state { color: var(--text-faint); font-size: 12px; }
</style>