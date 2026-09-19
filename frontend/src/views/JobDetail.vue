<template>
  <section>
    <div class="section-head">
      <router-link to="/lab" class="back-link">← Back to Lab</router-link>
      <h2>Job Detail {{ jobId }}</h2>
      <span :class="statusClass(jobStatus)">{{ jobStatus || 'unknown' }}</span>
      <span v-if="isStreaming" class="status active ml-2">LIVE</span>
    </div>

    <InlineStatus v-if="jobStatusMsg" :type="jobStatusMsg.type" :title="jobStatusMsg.title" :message="jobStatusMsg.message" :duration="5000" />

    <div v-if="loading" class="card">
      <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
        <span class="ml-3 text-muted">Loading job details...</span>
      </div>
    </div>
    <div v-else-if="error" class="card" style="color: var(--bad);">
      <div class="flex items-center gap-3">
        <UIcon name="i-lucide-alert-circle" class="text-error" size="20" />
        <div>
          <p class="font-medium">{{ error }}</p>
          <UButton size="sm" variant="outline" @click="loadJob">Retry</UButton>
        </div>
      </div>
    </div>
    <div v-else class="card">
      <div class="job-meta">
        <div class="meta-row">
          <span class="meta-label">Job ID</span>
          <span class="meta-value font-mono">{{ jobId }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Name</span>
          <span class="meta-value">{{ jobMeta.name || '—' }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Created</span>
          <span class="meta-value">{{ formatTime(jobMeta.created) }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Started</span>
          <span class="meta-value">{{ jobMeta.started_at ? formatTime(jobMeta.started_at) : '—' }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Finished</span>
          <span class="meta-value">{{ jobMeta.finished ? formatTime(jobMeta.finished) : '—' }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Command</span>
          <span class="meta-value font-mono text-xs">{{ jobMeta.cmd || '—' }}</span>
        </div>
        <div class="meta-row" v-if="jobMeta.mode">
          <span class="meta-label">Mode</span>
          <span class="meta-value">{{ jobMeta.mode }}</span>
        </div>
        <div class="meta-row" v-if="jobMeta.strategy">
          <span class="meta-label">Strategy</span>
          <span class="meta-value">{{ jobMeta.strategy }}</span>
        </div>
      </div>

      <div v-if="Object.keys(progressTasks).length" class="card mt-4">
        <h3>Progress Tasks</h3>
        <div class="progress-tasks">
          <div v-for="(task, taskId) in progressTasks" :key="taskId" class="progress-task">
            <div class="progress-task-header">
              <span class="font-mono">{{ task.description }}</span>
              <span v-if="task.total > 0" class="text-muted">{{ task.progress }} / {{ task.total }}</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: task.total > 0 ? (task.progress / task.total * 100) + '%' : '0%' }"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="card mt-4">
        <div class="section-head">
          <h3>Log</h3>
          <div class="controls">
            <UButton size="xs" variant="ghost" @click="toggleStream" :disabled="isStreaming && !canReconnect">
              {{ isStreaming ? 'Disconnect' : (jobStatus === 'running' ? 'Reconnect' : 'Connect') }}
            </UButton>
            <UButton size="xs" variant="ghost" @click="loadFullLog">Load Full Log</UButton>
            <UButton size="xs" variant="ghost" @click="clearLog">Clear</UButton>
          </div>
        </div>
        <div v-if="progressTasks && Object.keys(progressTasks).length" class="progress-summary mb-2">
          <div v-for="(task, taskId) in progressTasks" :key="taskId" class="progress-task-summary">
            <span class="font-mono text-xs">{{ task.description }}</span>
            <span v-if="task.total > 0" class="text-muted">{{ task.progress }} / {{ task.total }}</span>
            <div class="progress-bar-sm">
              <div class="progress-fill" :style="{ width: task.total > 0 ? (task.progress / task.total * 100) + '%' : '0%' }"></div>
            </div>
          </div>
        </div>
        <pre class="code-block" ref="logContainer">{{ logText }}</pre>
      </div>

      <div class="card mt-4">
        <h3>Actions</h3>
        <div class="flex gap-2 flex-wrap">
          <UButton v-if="jobStatus === 'running'" variant="ghost" @click="jobAction('pause')">Pause</UButton>
          <UButton v-if="jobStatus === 'paused'" variant="ghost" @click="jobAction('resume')">Resume</UButton>
          <UButton v-if="jobStatus === 'running' || jobStatus === 'paused' || jobStatus === 'queued'" color="error" variant="ghost" @click="confirmStop">Stop</UButton>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { useJobLogStream } from '../composables/useEventSource'
import InlineStatus from '../components/InlineStatus.vue'

const route = useRoute()
const router = useRouter()
const { confirm } = useConfirmDialog()

// Inline status state (replaces toast)
const jobStatusMsg = ref<{ type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string } | null>(null)

function showJobStatus(type: 'success' | 'error' | 'warning' | 'info', title: string, message?: string) {
  jobStatusMsg.value = { type, title, message }
  setTimeout(() => { jobStatusMsg.value = null }, 5000)
}

const jobId = route.params.id as string
const loading = ref(true)
const error = ref('')
const jobMeta = ref<any>({})
const logText = ref('')

// SSE-based job log streaming
const { logLines, isStreaming, jobStatus, progressTasks, start: startStream, stop: stopStream, getLogText } = useJobLogStream(jobId)

const canReconnect = computed(() => jobStatus.value === 'running' && !isStreaming.value)

async function loadJob() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/api/jobs/' + jobId)
    jobMeta.value = data
    // Start streaming if job is running
    if (data.status === 'running') {
      startStream()
    } else {
      // Load existing log for non-running jobs
      const { data: logData } = await api.get('/api/jobs/' + jobId + '/log', { params: { tail: 6000 } })
      logText.value = logData.log || ''
    }
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
}

async function loadFullLog() {
  try {
    const { data } = await api.get('/api/jobs/' + jobId + '/log')
    logText.value = data.log || ''
  } catch (e) {
    showJobStatus('error', 'Failed to load full log')
  }
}

function clearLog() {
  logText.value = ''
  stopStream()
  logLines.value = []
}

function toggleStream() {
  if (isStreaming.value) {
    stopStream()
  } else {
    startStream()
  }
}

async function jobAction(action: string) {
  try {
    await api.post('/api/jobs/' + jobId + '/' + action, {})
    await loadJob()
  } catch (e) {
    showJobStatus('error', 'Job action failed', 'Could not ' + action + ' job.')
  }
}

async function confirmStop() {
  const confirmed = await confirm({
    title: 'Stop job',
    description: 'Stop job ' + jobId + '? A running backtest or optimization will be terminated.',
    confirmLabel: 'Stop job',
    color: 'error'
  })
  if (!confirmed) return
  await jobAction('stop')
}

function formatTime(ts: number) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
}

function statusClass(s: string) {
  if (!s) return 'status'
  const sl = s.toLowerCase()
  if (sl === 'running') return 'status active'
  if (sl === 'done') return 'status active'
  if (sl === 'error') return 'status retired'
  if (sl === 'paused') return 'status experimental'
  if (sl === 'queued') return 'status experimental'
  if (sl === 'stopped') return 'status'
  if (sl === 'skipped') return 'status'
  return 'status'
}

// Auto-scroll log container
const logContainer = ref<HTMLElement | null>(null)
let lastLogLength = 0
const autoScroll = () => {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

// Watch logLines for auto-scroll when streaming
import { watch } from 'vue'
watch(() => logLines.value.length, (newLen) => {
  if (isStreaming.value && newLen > lastLogLength) {
    nextTick(autoScroll)
  }
  lastLogLength = newLen
})

onMounted(async () => {
  await loadJob()
})

onUnmounted(() => {
  stopStream()
})
</script>

<style scoped>
.back-link { color: var(--text-dim); font-size: 13px; text-decoration: none; }
.back-link:hover { color: var(--lavender); }
.job-meta { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin-bottom: 16px; }
.meta-row { display: flex; flex-direction: column; gap: 2px; }
.meta-label { font-size: 11px; color: var(--text-dim); }
.meta-value { font-size: 13px; }
.progress-tasks { display: flex; flex-direction: column; gap: 8px; }
.progress-task { display: flex; flex-direction: column; gap: 4px; }
.progress-task-header { display: flex; justify-content: space-between; font-size: 12px; }
.progress-bar { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--primary); border-radius: 3px; transition: width 0.3s; }
.progress-summary { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
.progress-task-summary { display: flex; flex-direction: column; gap: 2px; font-size: 11px; }
.progress-bar-sm { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
.controls { display: flex; gap: 8px; }
</style>
