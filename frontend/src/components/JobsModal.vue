<template>
  <div>
    <!-- Trigger Button - Fixed at top-right -->
    <button 
      v-if="!open" 
      class="jobs-trigger-btn" 
      @click="open = true" 
      :title="activeCount ? activeCount + ' active job' + (activeCount > 1 ? 's' : '') : 'Background jobs'" 
      aria-label="Background jobs"
      :class="{ 'has-active': activeCount > 0 }"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="9"></rect>
        <rect x="14" y="3" width="7" height="5"></rect>
        <rect x="14" y="12" width="7" height="9"></rect>
        <rect x="3" y="16" width="7" height="5"></rect>
      </svg>
      <span v-if="activeCount" class="jobs-trigger-badge">{{ activeCount > 9 ? '9+' : activeCount }}</span>
    </button>

    <!-- Centered Modal -->
    <Teleport to="body">
      <div v-if="open" class="modal-overlay" @click.self="close">
        <div class="modal" role="dialog" aria-label="Background jobs" aria-modal="true">
          <div class="modal-header">
            <h2>Background Jobs</h2>
            <span class="sub">{{ activeCount ? activeCount + ' active' : totalCount ? totalCount + ' total' : '' }}</span>
            <button class="modal-close" @click="close" aria-label="Close jobs">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <div class="modal-toolbar">
              <UButton variant="ghost" size="sm" @click="loadJobs" :loading="loading">
                <template #leading>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'animate-spin': loading }">
                    <path d="M23 4v6h-6"></path>
                    <path d="M1 20v-6h6"></path>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                  </svg>
                </template>
                Refresh
              </UButton>
              <div class="spacer" />
              <span class="hint" v-if="dismissedCount"> {{ dismissedCount }} dismissed </span>
            </div>

            <!-- Active Jobs -->
            <div class="job-section">
              <h3>Active</h3>
              <div v-if="!active.length" class="empty-state">
                <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <rect x="3" y="3" width="7" height="9"></rect>
                  <rect x="14" y="3" width="7" height="5"></rect>
                  <rect x="14" y="12" width="7" height="9"></rect>
                  <rect x="3" y="16" width="7" height="5"></rect>
                </svg>
                <p>No active jobs</p>
              </div>
              <div v-else class="job-list">
                <div v-for="[id, j] in active" :key="id" class="job-row">
                  <div class="job-main">
                    <span class="status-badge" :class="statusBadgeClass(j.status)">{{ j.status }}</span>
                    <span class="job-id">{{ id }}</span>
                    <span class="hint">{{ j.name || '' }}{{ j.step ? ' · step ' + j.step : '' }}{{ j.code != null ? ' · exit ' + j.code : '' }}</span>
                  </div>
                  <div class="job-actions">
                    <UButton size="sm" variant="ghost" @click="viewLog(String(id))">
                      <template #leading>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                          <polyline points="14 2 14 8 20 8"></polyline>
                          <line x1="16" y1="13" x2="8" y2="13"></line>
                          <line x1="16" y1="17" x2="8" y2="17"></line>
                          <polyline points="10 9 9 9 8 9"></polyline>
                        </svg>
                      </template>
                      Log
                    </UButton>
                    <UButton v-if="j.status === 'running'" size="sm" variant="ghost" @click="jobAction(String(id), 'pause')">Pause</UButton>
                    <UButton v-if="j.status === 'paused'" size="sm" variant="ghost" @click="jobAction(String(id), 'resume')">Resume</UButton>
                    <UButton v-if="j.status === 'running' || j.status === 'paused' || j.status === 'queued'" size="sm" variant="ghost" color="error" @click="jobAction(String(id), 'stop')">Stop</UButton>
                    <UButton v-if="j.status === 'error' || j.status === 'done' || j.status === 'stopped'" size="sm" variant="ghost" @click="dismiss(String(id))">Dismiss</UButton>
                  </div>
                  <div v-if="j.status === 'error' && excerpt(j)" class="job-excerpt">{{ excerpt(j) }}</div>
                </div>
              </div>
            </div>

            <!-- Recent Jobs -->
            <div class="job-section">
              <h3>Recent</h3>
              <div v-if="!recent.length" class="empty-state">
                <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <rect x="3" y="3" width="7" height="9"></rect>
                  <rect x="14" y="3" width="7" height="5"></rect>
                  <rect x="14" y="12" width="7" height="9"></rect>
                  <rect x="3" y="16" width="7" height="5"></rect>
                </svg>
                <p>No recent finished jobs</p>
              </div>
              <div v-else class="job-list">
                <div v-for="[id, j] in recent" :key="id" class="job-row">
                  <div class="job-main">
                    <span class="status-badge" :class="statusBadgeClass(j.status)">{{ j.status }}</span>
                    <span class="job-id">{{ id }}</span>
                    <span class="hint">{{ j.name || '' }}</span>
                  </div>
                  <div class="job-actions">
                    <UButton size="sm" variant="ghost" @click="viewLog(String(id))">
                      <template #leading>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                          <polyline points="14 2 14 8 20 8"></polyline>
                          <line x1="16" y1="13" x2="8" y2="13"></line>
                          <line x1="16" y1="17" x2="8" y2="17"></line>
                          <polyline points="10 9 9 9 8 9"></polyline>
                        </svg>
                      </template>
                      Log
                    </UButton>
                    <UButton size="sm" variant="ghost" @click="dismiss(String(id))">Dismiss</UButton>
                  </div>
                </div>
              </div>
            </div>

            <!-- Log Panel -->
            <div v-if="logJob" class="log-panel">
              <div class="log-header">
                <h4>Log {{ logJob }}</h4>
                <div class="log-header-actions">
                  <UButton size="sm" variant="ghost" @click="viewLog(logJob)">Refresh</UButton>
                  <UButton size="sm" variant="ghost" @click="closeLog">Close</UButton>
                </div>
              </div>
              <pre class="code-block">{{ logText }}</pre>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
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
const loading = ref(false)
let pollTimer: any = null

const entries = computed(() => Object.entries(jobs.value).filter(([id]) => !dismissed.value.includes(id)).sort((a, b) => ((b[1] as any).created || 0) - ((a[1] as any).created || 0)))
const active = computed(() => entries.value.filter(([, j]) => ['running', 'paused', 'queued'].includes((j as any).status)))
const recent = computed(() => entries.value.filter(([, j]) => ['error', 'done', 'stopped', 'skipped'].includes((j as any).status)).slice(0, 20))
const activeCount = computed(() => active.value.length)
const totalCount = computed(() => entries.value.length)
const dismissedCount = computed(() => dismissed.value.length)

async function loadJobs() {
  loading.value = true
  try {
    const { data } = await api.get('/api/jobs')
    jobs.value = data || {}
  } catch (e) { jobs.value = {} } finally { loading.value = false }
}

async function jobAction(id: string, action: string) {
  await api.post('/api/jobs/' + id + '/' + action, {})
  await loadJobs()
}

async function viewLog(id: string) {
  logJob.value = id
  logText.value = 'Loading...'
  const { data } = await api.get<{ log: string }>('/api/jobs/' + id + '/log', { params: { tail: 6000 } })
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

function statusBadgeClass(s: string) {
  if (!s) return ''
  const sl = s.toLowerCase()
  if (sl === 'running' || sl === 'done') return 'status-active'
  if (sl === 'error') return 'status-error'
  if (sl === 'paused' || sl === 'queued') return 'status-warning'
  return ''
}

function close() {
  open.value = false
}

watch(open, (v) => {
  if (v) {
    loadJobs()
    if (!pollTimer) pollTimer = setInterval(() => { if (!document.hidden) loadJobs() }, 10000)
    document.addEventListener('keydown', escHandler)
  } else {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    document.removeEventListener('keydown', escHandler)
  }
})

function escHandler(e: KeyboardEvent) { if (e.key === 'Escape') close() }

onMounted(loadJobs)
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

defineExpose({ loadJobs })
</script>

<style scoped>
/* Trigger Button - Fixed Top Right */
.jobs-trigger-btn {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  background: var(--color-panel);
  border: 1px solid var(--color-panel-border);
  border-radius: var(--radius-lg);
  color: var(--color-text);
  cursor: pointer;
  box-shadow: var(--shadow-lg);
  transition: all var(--transition-base);
}
.jobs-trigger-btn:hover { background: var(--color-bg-hover); border-color: var(--color-border); transform: translateY(-1px); }
.jobs-trigger-btn:focus-visible { box-shadow: var(--shadow-lg), var(--shadow-focus); }
.jobs-trigger-btn.has-active { background: var(--color-accent-bg); border-color: var(--color-accent-border); }
.jobs-trigger-btn.has-active svg { color: var(--color-accent); }
.jobs-trigger-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-pnl-negative);
  color: white;
  font-size: 10px;
  font-weight: 600;
  border-radius: 9999px;
  padding: 0 5px;
}

/* Modal Overlay */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

/* Modal */
.modal {
  width: 100%;
  max-width: 720px;
  max-height: 90vh;
  background: var(--color-panel);
  border: 1px solid var(--color-panel-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: slideUp 0.2s ease-out;
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-panel-border);
  background: var(--color-bg-elevated);
}
.modal-header h2 { margin: 0; font-size: var(--text-lg); font-weight: 600; }
.modal-header .sub { color: var(--color-text-muted); font-size: var(--text-sm); }
.modal-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.modal-close:hover { background: var(--color-bg-hover); color: var(--color-text); }

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.modal-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-panel-border);
}
.modal-toolbar .spacer { flex: 1; }

.job-section { display: flex; flex-direction: column; gap: 12px; }
.job-section h3 { margin: 0; font-size: var(--text-sm); font-weight: 600; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.05em; }

.job-list { display: flex; flex-direction: column; gap: 10px; }

.job-row {
  border: 1px solid var(--color-panel-border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--color-bg-elevated);
  transition: border-color var(--transition-fast);
}
.job-row:hover { border-color: var(--color-border); }

.job-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: var(--text-xs);
  font-weight: 600;
  border-radius: var(--radius-pill);
  font-family: var(--font-sans);
  text-transform: capitalize;
}
.status-active { background: rgba(16,185,129,0.15); color: var(--color-pnl-positive); border: 1px solid rgba(16,185,129,0.3); }
.status-error { background: rgba(239,68,68,0.15); color: var(--color-pnl-negative); border: 1px solid rgba(239,68,68,0.3); }
.status-warning { background: rgba(245,158,11,0.15); color: var(--color-warning); border: 1px solid rgba(245,158,11,0.3); }

.job-id { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--color-text-muted); }

.job-actions { display: flex; gap: 6px; flex-wrap: wrap; }

.job-excerpt {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 8px 10px;
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--color-text-dim);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60px;
  overflow: auto;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  text-align: center;
  color: var(--color-text-faint);
  border: 1px dashed var(--color-panel-border);
  border-radius: var(--radius-lg);
}
.empty-icon { width: 40px; height: 40px; opacity: 0.3; margin-bottom: 12px; }
.empty-state p { margin: 0; font-size: var(--text-sm); }

/* Log Panel */
.log-panel {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-panel-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-panel-border);
}
.log-header h4 { margin: 0; font-size: var(--text-sm); font-weight: 600; }
.log-header-actions { display: flex; gap: 8px; }
.code-block {
  background: var(--color-bg);
  border: none;
  border-radius: 0;
  padding: 16px;
  overflow: auto;
  max-height: 400px;
  font-size: var(--text-xs);
  line-height: 1.6;
  font-family: var(--font-mono);
  color: var(--color-text-dim);
  white-space: pre-wrap;
  word-break: break-word;
}

/* Responsive */
@media (max-width: 768px) {
  .modal { max-height: 95vh; max-width: calc(100vw - 16px); margin: 8px; }
  .modal-body { padding: 16px; }
  .jobs-trigger-btn { top: 12px; right: 12px; width: 40px; height: 40px; }
}
@media (max-width: 480px) {
  .modal-header { padding: 12px 16px; }
  .modal-body { padding: 12px; }
  .job-row { padding: 12px; }
  .job-main { flex-direction: column; align-items: flex-start; gap: 8px; }
  .job-actions { width: 100%; justify-content: flex-start; }
}
</style>