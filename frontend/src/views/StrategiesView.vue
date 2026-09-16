<template>
  <section>
    <div class="section-head">
      <h2>Strategies</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else>
      <div class="card filters">
        <input v-model="query" placeholder="filter strategies" class="filter-input" />
        <select v-model="statusFilter" class="filter-select">
          <option value="all">all statuses</option>
          <option value="active">active</option>
          <option value="experimental">experimental</option>
          <option value="retired">retired</option>
        </select>
      </div>

      <div class="table-wrap table-stack">
        <div class="thead-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" v-on:click="sortBy('strategy')">Name <span class="arrow" v-if="sortKey==='strategy'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('status')">Status <span class="arrow" v-if="sortKey==='status'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('score.grade')">Grade <span class="arrow" v-if="sortKey==='score.grade'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('profit_total')">Profit% <span class="arrow" v-if="sortKey==='profit_total'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('profit_factor')">PF <span class="arrow" v-if="sortKey==='profit_factor'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('sortino')">Sortino <span class="arrow" v-if="sortKey==='sortino'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('calmar')">Calmar <span class="arrow" v-if="sortKey==='calmar'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('max_drawdown_account')">MaxDD <span class="arrow" v-if="sortKey==='max_drawdown_account'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('propPass')">Prop <span class="arrow" v-if="sortKey==='propPass'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('n_backtests')">Backtests <span class="arrow" v-if="sortKey==='n_backtests'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" class="num" v-on:click="sortBy('n_trades')">Trades <span class="arrow" v-if="sortKey==='n_trades'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('basis')">Basis <span class="arrow" v-if="sortKey==='basis'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('timerange')">Range <span class="arrow" v-if="sortKey==='timerange'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('run_time')">Run <span class="arrow" v-if="sortKey==='run_time'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th></th>
              </tr>
            </thead>
          </table>
        </div>
        <div class="table-wrap">
          <table>
            <tbody>
              <tr v-for="s in sortedRows" :key="s.strategy" v-on:click="openStrategy(s.strategy)" v-on:keydown.enter="openStrategy(s.strategy)" tabindex="0" role="button" :aria-label="'Open ' + s.strategy">
                <td>{{ s.strategy }}</td>
                <td><span :class="statusClass(s.status)">{{ s.status }}</span></td>
                <td><span :class="gradePill(s.score?.grade)">{{ s.score?.grade || '?' }}</span></td>
                <td class="num">{{ fmtProfitPct(s.profit_total) }}</td>
                <td class="num">{{ fmt3(s.profit_factor) }}</td>
                <td class="num">{{ fmt3(s.sortino) }}</td>
                <td class="num">{{ fmt3(s.calmar) }}</td>
                <td class="num">{{ fmtPct(s.max_drawdown_account) }}</td>
                <td class="num"><span :title="propTitle(s)">{{ propText(s) }}</span></td>
                <td class="num">{{ s.n_backtests }}</td>
                <td class="num">{{ s.n_trades }}</td>
                <td :title="basisTooltip(s)">{{ basisLabel(s) }}</td>
                <td style="font-size:12px;color:var(--text-dim)">{{ s.timerange || '' }}</td>
                <td>{{ (s.run_time || '').slice(0, 10) }}</td>
                <td><button class="btn-secondary btn-sm" v-on:click.stop="startEdit(s)">Edit</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="editName" class="card edit-panel">
        <h3>Edit {{ editName }}</h3>
        <label class="edit-field">Status <select v-model="editStatus"><option>active</option><option>experimental</option><option>retired</option></select></label>
        <label class="edit-field">Notes <input v-model="editNotes" placeholder="notes" /></label>
        <div class="edit-actions">
          <button class="btn-primary" v-on:click="saveEdit">Save</button>
          <button class="btn-secondary" v-on:click="cancelEdit">Cancel</button>
        </div>
        <div v-if="editMsg" class="edit-msg">{{ editMsg }}</div>
      </div>

      <StrategyDrawer v-if="selected" :name="selected" v-on:close="selected = ''" />
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { api } from '../api/client'
import StrategyDrawer from '../components/StrategyDrawer.vue'

const store = useDashboardStore()
const selected = ref('')
const editName = ref('')
const editStatus = ref('active')
const editNotes = ref('')
const editMsg = ref('')
const sortKey = ref('strategy')
const sortAsc = ref(true)
const query = ref('')
const statusFilter = ref('all')

const rows = computed(() => store.canonical.map((c: any) => {
  const reg = store.strategies.find((r: any) => r.name === c.strategy)
  let nb = 0
  let nt = 0
  if (reg) {
    nb = reg.n_backtests || 0
    nt = reg.n_trades || 0
  }
  return { strategy: c.strategy, status: c.status || 'active', score: c.score, profit_total: c.profit_total, profit_factor: c.profit_factor, sortino: c.sortino, calmar: c.calmar, max_drawdown_account: c.max_drawdown_account, prop_firms: c.prop_firms, source: c.source, run_time: c.run_time, timerange: c.timerange, basis: c.basis || '', n_backtests: nb, n_trades: nt, notes: c.notes || '' }
}).filter((r: any) => {
  const q = query.value.toLowerCase()
  if (q && !(r.strategy || '').toLowerCase().includes(q)) return false
  if (statusFilter.value !== 'all' && (r.status || 'active') !== statusFilter.value) return false
  return true
}))

const sortedRows = computed(() => {
  const arr = [...rows.value]
  arr.sort((a: any, b: any) => {
    let av = sortKey.value === 'propPass' ? propPassCount(a) : sortKey.value.split('.').reduce((o: any, k: string) => o?.[k], a)
    let bv = sortKey.value === 'propPass' ? propPassCount(b) : sortKey.value.split('.').reduce((o: any, k: string) => o?.[k], b)
    if (av === undefined && bv === undefined) return 0
    if (av === '' || av === undefined || av === null) return sortAsc.value ? 1 : -1
    if (bv === '' || bv === undefined || bv === null) return sortAsc.value ? -1 : 1
    const an = Number(av), bn = Number(bv)
    const useNum = !isNaN(an) && !isNaN(bn)
    const r = useNum ? an - bn : String(av).localeCompare(String(bv))
    return sortAsc.value ? r : -r
  })
  return arr
})

function sortBy(key: string) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = true }
}
function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'active') return 'status active'
  if (sl === 'experimental') return 'status experimental'
  if (sl === 'retired') return 'status retired'
  return 'status'
}
function gradePill(g: string) {
  if (!g || g === '—') return 'pill gna'
  if (g === 'A') return 'pill gA'
  if (g === 'B') return 'pill gB'
  if (g === 'C') return 'pill gC'
  if (g === 'D') return 'pill gD'
  if (g === 'F') return 'pill gF'
  return 'pill gna'
}
function startEdit(s: any) {
  editName.value = s.strategy
  editStatus.value = s.status
  editNotes.value = s.notes || ''
  editMsg.value = ''
}
function fmt3(v: number) { return v === null || v === undefined ? '—' : Number(v).toFixed(3) }
function fmtPct(v: number) { return v ? (v * 100).toFixed(1) + '%' : '—' }
function fmtProfitPct(v: number) { return v === null || v === undefined ? '—' : ((v || 0) * 100).toFixed(1) + '%' }
function basisLabel(r: any) {
  if (r.basis === 'registry') return 'no runs yet'
  return r.basis === 'benchmark' ? 'benchmark (fallback)' : 'last backtest'
}
function basisTooltip(r: any) {
  if (r.basis === 'registry') return 'registered in the strategies table; no backtest or benchmark ingested yet'
  return 'metrics from ' + (r.basis === 'benchmark' ? 'benchmark' : 'backtest') + ' run ' + (r.source || '?') + ' · ' + (r.run_time || '?')
}
function propPassCount(r: any) {
  const pf = r.prop_firms
  if (!pf) return -1
  const vals = Object.values(pf) as any[]
  if (vals.every((p: any) => p.verdict === 'na')) return -1
  return vals.filter((p: any) => p.verdict === 'pass').length
}
function propText(r: any) {
  const pf = r.prop_firms
  if (!pf) return '—'
  const keys = Object.keys(pf)
  if (!keys.some((k) => (pf as any)[k].verdict !== 'na')) return '—'
  return keys.filter((k) => (pf as any)[k].verdict === 'pass').length + '/' + keys.length
}
function propTitle(r: any) {
  const pf = r.prop_firms
  if (!pf) return ''
  const keys = Object.keys(pf)
  const failed = keys.filter((k) => (pf as any)[k].verdict === 'fail').map((k) => store.propSpec[k]?.label || k)
  return failed.length ? 'failed: ' + failed.join(', ') : 'all programs pass'
}
function cancelEdit() { editName.value = '' }
async function saveEdit() {
  await api.post('/api/strategies', { name: editName.value, status: editStatus.value, notes: editNotes.value })
  editMsg.value = 'saved'
  await store.fetchAll(true)
}
function openStrategy(name: string) { selected.value = name }

onMounted(() => { store.fetchAll() })
</script>

<style scoped>
.edit-panel { margin-top: 16px; padding: 16px; }
.edit-panel h3 { margin: 0 0 12px; font-size: 14px; }
.edit-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); margin-bottom: 12px; }
.edit-field select, .edit-field input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--text);
  font-size: 13px;
}
.edit-actions { display: flex; gap: 8px; margin-top: 8px; }
.edit-msg { color: var(--good); font-size: 12px; margin-top: 8px; }
</style>