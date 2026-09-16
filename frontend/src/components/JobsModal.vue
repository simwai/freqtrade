<template>
  <div>
    <button class="jobs-btn" v-on:click="open = true" :title="activeCount ? activeCount + ' active job' + (activeCount > 1 ? 's' : '') : 'Background jobs'" aria-label="Background jobs">
      Jobs <span v-if="activeCount" class="jobs-badge">{{ activeCount }}</span>
    </button>

    <div v-if="open" class="drawer-overlay" v-on:click="open = false"></div>
    <div v-if="open" class="drawer" role="dialog" aria-label="Background jobs">
      <div class="drawer-header">
        <h2>Jobs</h2>
        <span class="sub">{{ activeCount ? activeCount + ' active' : totalCount ? totalCount + ' total' : '' }}</span>
        <button class="close-btn" v-on:click="open = false" aria-label="Close jobs">×</button>
      </div>

      <div class="drawer-content">
        <div class="form-row">
          <button class="btn-secondary btn-sm" v-on:click="loadJobs">Refresh</button>
        </div>

        <h3>Active</h3>
        <div v-if="!active.length" class="hint">No active jobs.</div>
        <div v-for="[id, j] in active" :key="id" class="job-row">
          <div class="job-main">
            <span :class="statusClass(j.status)">{{ j.status }}</span>
            <span class="job-id">{{ id }}</span>
            <span class="hint">{{ j.name || '' }}{{ j.step ? ' · step ' + j.step : '' }}{{ j.code != null ? ' · exit ' + j.code : '' }}</span>
          </div>
          <div class="job-actions">
            <button class="btn-secondary btn-sm" v-on:click="viewLog(String(id))">View log</button>
            <button v-if="j.status === 'running'" class="btn-secondary btn-sm" v-on:click="jobAction(String(id), 'pause')">Pause</button>
            <button v-if="j.status === 'paused'" class="btn-secondary btn-sm" v-on:click="jobAction(String(id), 'resume')">Resume</button>
            <button v-if="j.status === 'running' || j.status === 'paused' || j.status === 'queued'" class="btn-secondary btn-sm" v-on:click="jobAction(String(id), 'stop')">Stop</button>
            <button v-if="j.status === 'error' || j.status === 'done' || j.status === 'stopped'" class="btn-secondary btn-sm" v-on:click="dismiss(String(id))">Dismiss</button>
          </div>
          <div v-if="j.status === 'error' && excerpt(j)" class="job-excerpt">{{ excerpt(j) }}</div>
        </div>

        <h3>Recent</h3>
        <div v-if="!recent.length" class="hint">No recent finished jobs.</div>
        <div v-for="[id, j] in recent" :key="id" class="job-row">
          <div class="job-main">
            <span :class="statusClass(j.status)">{{ j.status }}</span>
            <span class="job-id">{{ id }}</span>
            <span class="hint">{{ j.name || '' }}</span>
          </div>
          <div class="job-actions">
            <button class="btn-secondary btn-sm" v-on:click="viewLog(String(id))">View log</button>
            <button class="btn-secondary btn-sm" v-on:click="dismiss(String(id))">Dismiss</button>
          </div>
        </div>

        <div v-if="logJob" class="log-panel card">
          <div class="log-header">
            <h4>Log {{ logJob }}</h4>
            <button class="btn-secondary btn-sm" v-on:click="closeLog">Close</button>
          </div>
          <pre class="code-block">{{ logText }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { api } from '../api/client'

const open = ref(false)
const jobs = ref<Record<string, any>>({})
const logJob = ref('')
const logText = ref('')
const dismissed = ref([] as string[])
let pollTimer: any = null
let escHandler: any = null

const entries = computed(() => Object.entries(jobs.value).filter(([id]) => !dismissed.value.includes(id)).sort((a, b) => ((b[1] as any).created || 0) - ((a[1] as any).created || 0)))
const active = computed(() => entries.value.filter(([, j]) => ['running', 'paused', 'queued'].includes((j as any).status)))
const recent = computed(() => entries.value.filter(([, j]) => ['error', 'done', 'stopped', 'skipped'].includes((j as any).status)).slice(0, 20))
const activeCount = computed(() => active.value.length)
const totalCount = computed(() => entries.value.length)

async function loadJobs() {
  try {
    const { data } = await api.get('/api/jobs')
    jobs.value = data || {}
  } catch (e) { jobs.value = {} }
}

async function jobAction(id: string, action: string) {
  await api.post('/api/jobs/' + id + '/' + action, {})
  await loadJobs()
}

async function viewLog(id: string) {
  logJob.value = id
  logText.value = 'Loading...'
  const { data } = await api.get('/api/jobs/' + id + '/log', { params: { tail: 6000 } })
  logText.value = data.log || ''
}

function closeLog() {
  logJob.value = ''
  logText.value = ''
}

function dismiss(id: string) {
  if (!dismissed.value.includes(id)) dismissed.value.push(id)
}

function excerpt(j: any) {
  const log = (j.log || '').split('\n').filter((l: string) => l.trim())
  if (log.length) return log[log.length - 1].slice(-220)
  if (j.error) return String(j.error).slice(-220)
  return ''
}

function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'running' || sl === 'done') return 'status active'
  if (sl === 'error') return 'status retired'
  if (sl === 'paused' || sl === 'queued') return 'status experimental'
  return 'status'
}

onMounted(loadJobs)

watch(open, (v) => {
  if (v) {
    loadJobs()
    if (!pollTimer) pollTimer = setInterval(() => { if (!document.hidden) loadJobs() }, 10000)
    escHandler = (e: KeyboardEvent) => { if (e.key === 'Escape') open.value = false }
    document.addEventListener('keydown', escHandler)
  } else {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    if (escHandler) { document.removeEventListener('keydown', escHandler); escHandler = null }
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (escHandler) document.removeEventListener('keydown', escHandler)
})
defineExpose({ loadJobs })
</script>

<style scoped>
.jobs-btn { position: relative; background: var(--card-hover); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 12px; }
.jobs-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; border-radius: 999px; background: var(--lavender-ink); color: #fff; font-size: 11px; padding: 0 5px; margin-left: 6px; }
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 99; }
.drawer { position: fixed; right: 0; top: 0; bottom: 0; width: 460px; max-width: 100vw; background: var(--card); border-left: 1px solid var(--border); z-index: 100; display: flex; flex-direction: column; }
.drawer-header { display: flex; align-items: center; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.drawer-header h2 { margin: 0; font-size: 16px; }
.drawer-header .sub { color: var(--text-dim); font-size: 12px; }
.close-btn { margin-left: auto; background: transparent; border: none; color: var(--text-dim); font-size: 22px; cursor: pointer; }
.drawer-content { flex: 1; overflow-y: auto; padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.job-row { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 8px; }
.job-main { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.job-id { font-family: monospace; font-size: 11px; color: var(--text-dim); }
.job-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.hint { color: var(--text-faint); font-size: 12px; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.log-panel { margin-top: 8px; }
.code-block { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; overflow: auto; max-height: 300px; font-size: 11px; white-space: pre-wrap; }
</style>
