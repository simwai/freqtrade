<template>
  <div class="drawer-overlay" v-on:click="close"></div>
  <div class="drawer" role="dialog" aria-label="Run details">
    <div class="drawer-header">
      <h2>{{ title }}</h2>
      <span v-if="runKind" class="grade-pill" :class="kindPill(runKind)">{{ runKind }}</span>
      <span v-else class="grade-pill" :class="gradePill(strategy.score?.grade)">{{ strategy.score?.grade || '?' }}</span>
      <button class="close-btn" v-on:click="close" aria-label="Close details">×</button>
    </div>
    <div class="drawer-tabs">
      <button :class="{ active: tab === 'overview' }" v-on:click="tab = 'overview'">Overview</button>
      <button :class="{ active: tab === 'code' }" v-on:click="tab = 'code'">Code</button>
      <button :class="{ active: tab === 'config' }" v-on:click="tab = 'config'">Config</button>
      <button v-if="showParams" :class="{ active: tab === 'params' }" v-on:click="tab = 'params'">Params</button>
      <button :class="{ active: tab === 'prop' }" v-on:click="tab = 'prop'">Prop</button>
    </div>

    <div v-if="tab === 'overview'" class="drawer-content">
      <div v-if="run" class="kv">
        <div v-for="row in runOverview" :key="row.k" class="kv-row"><span class="k">{{ row.k }}</span><span class="v">{{ row.v }}</span></div>
      </div>
      <template v-else>
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
      </template>
    </div>

    <div v-if="tab === 'code'" class="drawer-content">
      <div class="code-sub">{{ codeBadgeText() }}</div>
      <div v-if="codeFiles.length > 1" class="file-chips">
        <span class="hint">Files ({{ codeFiles.length }}):</span>
        <button v-for="(f, i) in codeFiles" :key="f.path" class="btn-secondary btn-sm" :class="{ primary: i === codeFileIdx }" v-on:click="selectCodeFile(i)">{{ shortName(f.path) }}</button>
      </div>
      <div class="code-header">
        <button v-on:click="loadCode" class="btn-secondary">Load code</button>
        <button v-if="codeText" v-on:click="copyCode" class="btn-secondary">Copy</button>
      </div>
      <pre class="code-block">{{ codeText || 'Click Load code to fetch strategy source' }}</pre>
    </div>

    <div v-if="tab === 'config'" class="drawer-content">
      <div v-if="linkedConfig">
        <div class="code-header">
          <button v-on:click="copyConfig" class="btn-secondary">Copy JSON</button>
          <a class="btn-secondary" :download="'config_' + linkedConfig.hash.slice(0, 8) + '.json'" :href="configDownloadUrl()">Download</a>
          <span class="hint">hash {{ linkedConfig.hash.slice(0, 12) }}…</span>
        </div>
        <pre class="code-block">{{ linkedConfig.text }}</pre>
      </div>
      <table v-else class="drawer-table">
        <tbody>
          <tr v-for="row in configRows" :key="row.k">
            <td>{{ row.k }}</td>
            <td>{{ row.v }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!linkedConfig && !configRows.length" class="hint">No config captured for this run.</p>
    </div>

    <div v-if="tab === 'params'" class="drawer-content">
      <div class="kv">
        <div v-for="row in paramsMeta" :key="row.k" class="kv-row"><span class="k">{{ row.k }}</span><span class="v">{{ row.v }}</span></div>
      </div>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'

const props = defineProps<{ name: string, runKind?: string, runSource?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const store = useDashboardStore()
const tab = ref('overview')
const codeText = ref('')
const codeFileIdx = ref(0)
const strategy = computed(() => store.canonical.find((s: any) => s.strategy === props.name) || { strategy: props.name, score: { grade: '?', grades: {} } })
const runs = computed(() => store.backtests.filter((b: any) => b.strategy === props.name).slice(0, 10))

const runKind = computed(() => props.runKind || '')
const run = computed(() => {
  if (!props.runKind || !props.runSource) return null
  const pool = props.runKind === 'benchmark' ? store.benchmarks
    : props.runKind === 'hyperopt' ? store.hyperopt
    : props.runKind === 'walkforward' ? store.walkforward : store.backtests
  return (pool as any[]).find((r: any) => r.strategy === props.name && r.source === props.runSource)
    || (pool as any[]).find((r: any) => r.source === props.runSource) || null
})

const showParams = computed(() => runKind.value === 'hyperopt' || !!(strategy.value as any).best_params || !!(strategy.value as any).params_json)
const title = computed(() => run.value ? props.name + ' · ' + runKind.value : (strategy.value as any).strategy || props.name)

const runOverview = computed(() => {
  const r: any = run.value
  if (!r) return []
  const rows = [
    { k: 'Strategy', v: r.strategy || '' },
    { k: 'Kind', v: runKind.value },
    { k: 'Source', v: r.source || '' },
    { k: 'Run time', v: r.run_time || '—' },
    { k: 'Timeframe', v: r.timeframe || '—' },
    { k: 'Timerange', v: r.timerange || '—' },
    { k: 'Trading mode', v: r.trading_mode || '—' },
    { k: 'Profit total', v: r.profit_total != null ? (r.profit_total * 100).toFixed(1) + '%' : '—' },
    { k: 'Trades / winrate', v: (r.total_trades || 0) + ' / ' + (r.winrate != null ? (r.winrate * 100).toFixed(1) + '%' : '—') },
    { k: 'Sortino / Calmar', v: fmt3(r.sortino) + ' / ' + fmt3(r.calmar) },
    { k: 'Max drawdown', v: r.max_drawdown_account != null ? (r.max_drawdown_account * 100).toFixed(1) + '%' : '—' }
  ]
  if (r.loss_function) rows.push({ k: 'Loss function', v: r.loss_function })
  if (r.spaces) rows.push({ k: 'Spaces', v: r.spaces })
  if (r.train_days) rows.push({ k: 'WF windows', v: (r.n_windows || 0) + ' (' + (r.profitable_windows ?? '—') + ' profitable)' })
  if (r.epochs) rows.push({ k: 'Epochs', v: String(r.epochs) })
  return rows
})

const configRows = computed(() => {
  const src: any = run.value || strategy.value
  const raw = src.config_json
  if (!raw) return []
  let cfg: any = {}
  try { cfg = JSON.parse(raw) } catch (e) { return [] }
  const keys = ['stake_currency', 'stake_amount', 'max_open_trades', 'timeframe', 'trading_mode', 'margin_mode', 'minimal_roi', 'stoploss', 'trailing_stop', 'exchange', 'pair_whitelist', 'dry_run', 'dry_run_wallet']
  return keys.filter((k) => cfg[k] !== undefined).map((k) => ({ k: k, v: typeof cfg[k] === 'object' ? JSON.stringify(cfg[k]) : String(cfg[k]) }))
})

const linkedConfig = computed(() => {
  const r: any = run.value
  const hash = r?.config_hash
  const obj = hash ? store.configs[hash] : null
  if (!hash || !obj) return null
  return { hash: hash, text: JSON.stringify(obj, null, 2) }
})

function configDownloadUrl() {
  if (!linkedConfig.value) return ''
  return 'data:application/json;charset=utf-8,' + encodeURIComponent(linkedConfig.value.text)
}

function copyText(txt: string) {
  if (navigator.clipboard) navigator.clipboard.writeText(txt).catch(() => {})
  else {
    const ta = document.createElement('textarea')
    ta.value = txt
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch (e) {}
    ta.remove()
  }
}

function copyConfig() { if (linkedConfig.value) copyText(linkedConfig.value.text) }
function copyCode() { if (codeText.value) copyText(codeText.value) }

const codeFiles = computed((): any[] => {
  const r: any = run.value || strategy.value
  const hash = r?.code_hash
  if (!hash) return []
  return store.snapshotFiles[hash] || []
})

function shortName(p: string) { return (p || '').split(/[\\/]/).pop() || p }
function selectCodeFile(i: number) { codeFileIdx.value = i; loadCode() }

async function loadCode() {
  const r: any = run.value || strategy.value
  const h = r?.code_hash
  if (!h) { codeText.value = 'no snapshot hash'; return }
  const files = codeFiles.value
  const file = files.length > 1 ? files[Math.min(codeFileIdx.value, files.length - 1)].path : ''
  let url = '/api/strategy/file'
  const params: any = { hash: h }
  if (file) params.file = file
  try {
    const { data } = await api.get(url, { params: params })
    const txt = typeof data === 'string' ? data : JSON.stringify(data)
    codeText.value = txt.length > 120000 ? txt.slice(0, 120000) + '\n… (truncated preview)' : txt
  } catch (e) { codeText.value = 'Snapshot viewer needs the server (lab.py serve).' }
}

function codeBadgeText() {
  const r: any = run.value || strategy.value
  const hash = r?.code_hash
  if (!hash) return 'code unknown'
  const setSnap = store.snapshotCombined[hash]
  const setCur = store.currentCodeSet[props.name]
  if (setSnap && setCur) return setSnap === setCur ? 'code current' : 'code changed since run'
  const cur = store.currentCode[props.name]
  if (!cur) return 'no .py on disk'
  return cur === hash ? 'code current' : 'code changed since run'
}

const propRows = computed(() => {
  const src: any = run.value && (run.value as any).prop_firms ? run.value : strategy.value
  const pf = (src as any).prop_firms
  if (!pf) return []
  return Object.keys(pf).map((k) => ({ k: k, verdict: pf[k].verdict, label: (store.propSpec[k] && store.propSpec[k].label) || k }))
})

const paramsMeta = computed(() => {
  const r: any = run.value || {}
  return [
    { k: 'Loss function', v: r.loss_function || '—' },
    { k: 'Spaces', v: r.spaces || '—' },
    { k: 'Epochs', v: r.epochs != null ? String(r.epochs) : '—' },
    { k: 'Best loss', v: r.best_loss != null ? Number(r.best_loss).toFixed(4) : '—' },
    { k: 'Random state', v: r.random_state != null ? String(r.random_state) : '—' },
    { k: 'Jobs', v: r.jobs != null ? String(r.jobs) : '—' },
    { k: 'Min trades', v: r.min_trades != null ? String(r.min_trades) : '—' }
  ]
})

const paramsText = computed(() => {
  const r: any = run.value || strategy.value
  const raw = r?.best_params || r?.params_json
  if (!raw) return ''
  try { return JSON.stringify(typeof raw === 'string' ? JSON.parse(raw) : raw, null, 2) } catch (e) { return String(raw) }
})

function close() { emit('close') }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }
onMounted(() => { document.addEventListener('keydown', onKey) })
onUnmounted(() => { document.removeEventListener('keydown', onKey) })
function kindPill(k: string) { return k === 'benchmark' ? 'pill gA' : 'pill gna' }
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
function fmt3(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 })
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
.kv { display: flex; flex-direction: column; }
.kv-row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 8px; border-top: 1px solid var(--border); font-size: 12px; }
.kv-row .k { color: var(--text-dim); }
.kv-row .v { font-family: monospace; text-align: right; word-break: break-all; }
.code-sub { font-size: 12px; color: var(--text-dim); }
.code-header { margin-bottom: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.code-block { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; overflow: auto; max-height: 300px; font-size: 11px; line-height: 1.5; color: var(--text-dim); white-space: pre-wrap; word-break: break-word; }
.file-chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.file-chips .primary { background: var(--lavender-ink); color: #fff; }
.prop-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); }
.prop-row:last-child { border-bottom: none; }
.prop-row span:first-child { color: var(--text-dim); font-size: 12px; }
.empty-state { color: var(--text-faint); font-size: 12px; }
.hint { color: var(--text-faint); font-size: 12px; }
</style>
