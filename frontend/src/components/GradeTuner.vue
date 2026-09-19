<template>
  <div class="grade-tuner card">
    <div class="tuner-head">
      <h3>Grade Tuner</h3>
      <button class="btn-secondary btn-sm" v-on:click="open = !open" :aria-expanded="open">{{ open ? 'Hide' : 'Show' }}</button>
    </div>
    <div v-if="open">
    <div class="tuner-inputs">
      <label>Min Profit <input type="number" step="any" :value="minProfit" v-on:input="$emit('update:minProfit', ($event.target as HTMLInputElement).valueAsNumber || 0)" /></label>
      <label>Min Trades <input type="number" :value="minTrades" v-on:input="$emit('update:minTrades', ($event.target as HTMLInputElement).valueAsNumber || 0)" /></label>
    </div>
    <table class="factors-table">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Pass</th>
          <th>Warn</th>
          <th><UTooltip text="Whether a higher value is better (e.g. profit) or a lower value is better (e.g. drawdown)."><span class="tip">Direction</span></UTooltip></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(spec, key) in factors" :key="key">
          <td>{{ spec.label || key }}</td>
          <td><input type="number" step="any" v-model.number="factors[key].pass" /></td>
          <td><input type="number" step="any" v-model.number="factors[key].warn" /></td>
          <td>{{ spec.higher_is_better ? 'higher better' : 'lower better' }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="tuner-actions">
      <button v-on:click="apply" class="btn-primary">Apply</button>
      <button v-on:click="resetFactors" class="btn-secondary">Reset</button>
    </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useStrategiesStore } from '../stores/strategies'
import { useStrategyDetailStore } from '../stores/strategyDetail'
import { activeGradeFactors, saveGradeFactors, scoreRowTuned } from '../utils/grades'
defineProps<{ minProfit: number, minTrades: number, scorecard?: Record<string, any>, canonical?: any[], backtests?: any[], benchmarks?: any[] }>()
const emit = defineEmits<{ (e: 'update:minProfit', v: number): void, (e: 'update:minTrades', v: number): void, (e: 'retune'): void }>()
const strategiesStore = useStrategiesStore()
const strategyDetailStore = useStrategyDetailStore()
const factors = ref<Record<string, any>>({})
const err = ref('')
const open = ref(true)

function loadFactors() {
  const sc = props.scorecard || strategiesStore.scorecard || strategyDetailStore.scorecard || {}
  factors.value = activeGradeFactors(sc)
}
function retune() {
  const sc = activeGradeFactors(props.scorecard || strategiesStore.scorecard || strategyDetailStore.scorecard || {})
  const canonical = props.canonical || strategiesStore.items || []
  const backtests = props.backtests || strategyDetailStore.backtests || []
  const benchmarks = props.benchmarks || strategyDetailStore.benchmarks || []
  canonical.concat(backtests).concat(benchmarks).forEach((r: any) => { r.score = scoreRowTuned(r, sc) })
  emit('retune')
}
function apply() {
  for (const k of Object.keys(factors.value)) {
    const f = factors.value[k]
    if (!Number.isFinite(Number(f.pass)) || !Number.isFinite(Number(f.warn))) {
      err.value = 'Bad number in row ' + k + '.'
      return
    }
    f.pass = Number(f.pass); f.warn = Number(f.warn)
  }
  err.value = ''
  saveGradeFactors(factors.value)
  retune()
}
function resetFactors() {
  try { localStorage.removeItem('gradeFactors') } catch (e) {}
  loadFactors()
  retune()
}
onMounted(loadFactors)
watch(() => props.scorecard, loadFactors, { immediate: false })
watch(() => strategiesStore.scorecard, loadFactors, { immediate: false })
watch(() => strategyDetailStore.scorecard, loadFactors, { immediate: false })
</script>

<style scoped>
.grade-tuner { padding: 16px; }
.tip { border-bottom: 1px dotted var(--text-faint); cursor: help; }
.tuner-inputs { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
.tuner-inputs label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.tuner-inputs input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
}
.factors-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.factors-table th {
  background: var(--bg-soft);
  color: var(--lavender);
  font-weight: 600;
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
.factors-table td { padding: 6px 10px; border-top: 1px solid var(--border); }
.factors-table input {
  width: 80px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 8px;
  color: var(--text);
  font-size: 12px;
}
.err { color: var(--bad); font-size: 12px; margin: 8px 0; }
.tuner-actions { display: flex; gap: 8px; margin-top: 12px; }
.btn-primary, .btn-secondary {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn-primary { background: var(--lavender-ink); color: #fff; }
.btn-primary:hover { background: #5b4ac5; }
.btn-secondary { background: var(--card-hover); color: var(--text); border-color: var(--border); }
.btn-secondary:hover { background: var(--card); }
</style>
