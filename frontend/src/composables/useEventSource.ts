import { ref, onUnmounted, type Ref } from 'vue'
import type { SseEvent, JobProgressTask } from '../api/schemas'

interface UseEventSourceOptions {
  url: string
  onMessage?: (event: SseEvent) => void
  onOpen?: () => void
  onError?: (error: Event) => void
  reconnect?: boolean
  maxRetries?: number
  retryDelay?: number
}

interface UseEventSourceReturn {
  isConnected: Ref<boolean>
  lastEvent: Ref<SseEvent | null>
  error: Ref<Event | null>
  retryCount: Ref<number>
  close: () => void
  reconnect: () => void
}

export function useEventSource(options: UseEventSourceOptions): UseEventSourceReturn {
  const {
    url,
    onMessage,
    onOpen,
    onError,
    reconnect = true,
    maxRetries = 5,
    retryDelay = 1000,
  } = options

  const isConnected = ref(false)
  const lastEvent = ref<SseEvent | null>(null)
  const error = ref<Event | null>(null)
  const retryCount = ref(0)
  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  const connect = () => {
    if (eventSource) {
      eventSource.close()
    }

    // Add auth token if available
    const token = import.meta.env.VITE_RPC_API_TOKEN || localStorage.getItem('rpc_api_token')
    let fullUrl = url
    if (token) {
      fullUrl += (fullUrl.includes('?') ? '&' : '?') + `token=${encodeURIComponent(token)}`
    }

    eventSource = new EventSource(fullUrl)

    eventSource.onopen = () => {
      isConnected.value = true
      retryCount.value = 0
      error.value = null
      onOpen?.()
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const sseEvent: SseEvent = {
          type: data.type as SseEvent['type'],
          data: data.data,
        }
        lastEvent.value = sseEvent
        onMessage?.(sseEvent)
      } catch (e) {
        console.warn('Failed to parse SSE message:', event.data)
      }
    }

    eventSource.onerror = (err) => {
      isConnected.value = false
      error.value = err
      onError?.(err)

      if (reconnect && retryCount.value < maxRetries) {
        const delay = retryDelay * Math.pow(2, retryCount.value)
        retryCount.value++
        reconnectTimer = setTimeout(() => {
          connect()
        }, delay)
      } else if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }
  }

  const close = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    isConnected.value = false
  }

  const manualReconnect = () => {
    retryCount.value = 0
    connect()
  }

  // Initial connection
  connect()

  // Cleanup on unmount
  onUnmounted(() => {
    close()
  })

  return {
    isConnected,
    lastEvent,
    error,
    retryCount,
    close,
    reconnect: manualReconnect,
  }
}

// Specialized hook for job log streaming
export function useJobLogStream(jobIdRef: string | Ref<string>, baseUrl: string = '/api/jobs') {
  const logLines = ref<string[]>([])
  const isStreaming = ref(false)
  const jobStatus = ref<'queued' | 'running' | 'paused' | 'done' | 'error' | null>(null)
  const progressTasks = ref<Record<string, JobProgressTask>>({})

  let eventSource: ReturnType<typeof useEventSource> | null = null

  const start = (jobId?: string) => {
    const id = jobId || (typeof jobIdRef === 'string' ? jobIdRef : jobIdRef.value)
    if (!id) return
    logLines.value = []
    isStreaming.value = true
    jobStatus.value = 'running'

    eventSource = useEventSource({
      url: `${baseUrl}/${id}/logs/stream`,
      onOpen: () => {
        isStreaming.value = true
      },
      onMessage: (event) => {
        if (event.type === 'log') {
          logLines.value.push(event.data)
          // Keep last 10000 lines
          if (logLines.value.length > 10000) {
            logLines.value = logLines.value.slice(-10000)
          }
        } else if (event.type === 'progress') {
          progressTasks.value = event.data.progress_tasks
        } else if (event.type === 'status') {
          if (event.data.finished) {
            isStreaming.value = false
            jobStatus.value = event.data.status === 'done' ? 'done' : 'error'
            eventSource?.close()
          }
        }
      },
      onError: () => {
        isStreaming.value = false
      },
      reconnect: true,
      maxRetries: 10,
    })
  }

  const stop = () => {
    eventSource?.close()
    eventSource = null
    isStreaming.value = false
  }

  const getLogText = (tail?: number) => {
    const lines = tail ? logLines.value.slice(-tail) : logLines.value
    return lines.join('\n')
  }

  onUnmounted(() => {
    stop()
  })

  return {
    logLines,
    isStreaming,
    jobStatus,
    progressTasks,
    start,
    stop,
    getLogText,
  }
}