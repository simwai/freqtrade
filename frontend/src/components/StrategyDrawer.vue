<template>
  <div v-on:click="close"></div>
  <div>
    <button v-on:click="close">Close</button>
    <h2>{{ strategy.strategy }}</h2>
    <div>Grade: {{ strategy.score.grade }}</div>
    <div>
      <button v-on:click="tab = 'overview'">Overview</button>
      <button v-on:click="tab = 'code'">Code</button>
      <button v-on:click="tab = 'config'">Config</button>
      <button v-on:click="tab = 'prop'">Prop</button>
    </div>
    <div v-if="tab === 'overview'">
      <table v-sortable>
        <tr v-for="(g, k) in strategy.score.grades" :key="k">
          <td>{{ k }}</td><td>{{ g }}</td>
        </tr>
      </table>
      <h3>Recent runs</h3>
      <ul>
        <li v-for="r in runs" :key="r.source">{{ r.source }} {{ r.profit_total }}</li>
      </ul>
    </div>
    <div v-if="tab === 'code'">
      <button v-on:click="loadCode">Load code</button>
      <pre>{{ codeText }}</pre>
    </div>
    <div v-if="tab === 'config'">
      <table>
        <tr v-for="row in configRows" :key="row.k">
          <td>{{ row.k }}</td><td>{{ row.v }}</td>
        </tr>
      </table>
    </div>
    <div v-if="tab === 'prop'">
      <div v-for="row in propRows" :key="row.k">{{ row.label }}: {{ row.verdict }}</div>
      <div v-if="!propRows.length">No prop evaluations.</div>
    </div>
  </div>
</template>
<script setup lang='ts'>
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
async function loadCode() {
  const h = (strategy.value as any).code_hash
  if (!h) { codeText.value = 'no snapshot hash'; return }
  const { data } = await api.get('/api/strategy/file', { params: { hash: h } })
  codeText.value = typeof data === 'string' ? data : JSON.stringify(data)
}
function close() {
  emit('close')
}
</script>
