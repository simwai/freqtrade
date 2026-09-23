// TypeScript schemas for RPC API Server endpoints
// Based on freqtrade/rpc/api_server/api_analysis.py, api_backtest.py, api_schemas.py

// ============================================================================
// Recursive Analysis
// ============================================================================

export interface RecursiveAnalysisRequest {
  strategy: string
  timeframe?: string
  timeframe_detail?: string
  timerange?: string
  startup_candles?: number
  recursive_strategy_search?: boolean
  [key: string]: any
}

export interface RecursiveAnalysisResponse {
  status: 'running' | 'ended' | 'error'
  running: boolean
  status_msg: string
  job_id?: string
  result?: RecursiveAnalysisResult
}

export interface RecursiveAnalysisResult {
  strategy: string
  startup_candles: number
  strategy_scc: string[]
  results: Record<string, Record<string, number>>
  // results[indicator][candle] = diff
}

export interface SccGraphData {
  nodes: SccNode[]
  edges: SccEdge[]
}

export interface SccNode {
  id: string
  label: string
  startup_candles: number
  indicators: string[]
}

export interface SccEdge {
  source: string
  target: string
  weight: number
}

// ============================================================================
// Lookahead Analysis
// ============================================================================

export interface LookaheadAnalysisRequest {
  strategy: string
  timeframe?: string
  timeframe_detail?: string
  timerange?: string
  lookahead_window?: number
  [key: string]: any
}

export interface LookaheadAnalysisResponse {
  status: 'running' | 'ended' | 'error'
  running: boolean
  status_msg: string
  job_id?: string
  result?: LookaheadAnalysisResult
}

export interface LookaheadAnalysisResult {
  strategy: string
  has_bias: boolean
  total_signals: number
  biased_entry_signals: number
  biased_exit_signals: number
  biased_indicators: string[]
}

// ============================================================================
// Backtest History
// ============================================================================

export interface BacktestHistoryEntry {
  filename: string
  strategy: string
  date: string
  profit_total: number
  profit_pct: number
  trades: number
  max_drawdown: number
  sortino: number
  calmar: number
  profit_factor: number
  notes?: string
}

export interface BacktestResult {
  metadata: Record<string, any>
  strategy: Record<string, any>
  strategy_comparison: any[]
}

export interface BacktestMarketChange {
  columns: string[]
  data: number[][]
  length: number
}

export interface WalletHistoryResponse {
  columns: string[]
  data: number[][]
  length: number
  capture_start_ts: number
}

export interface BacktestMetadataUpdate {
  notes: string
}

// ============================================================================
// Job Progress (for SSE)
// ============================================================================

export interface JobProgressTask {
  progress: number
  total: number
  description: string
}

export interface JobStatus {
  job_id: string
  name: string
  status: 'queued' | 'running' | 'paused' | 'done' | 'error' | 'stopped' | 'skipped'
  created: number
  finished?: number
  pid?: number
  cmd?: string
  step?: string
  step_cmd?: string
  progress?: number
  progress_tasks?: Record<string, JobProgressTask>
  error?: string
  log?: string
  log_full_len?: number
  mode?: string
  strategy?: string
}

// ============================================================================
// SSE Event Types
// ============================================================================

export interface SseLogEvent {
  type: 'log'
  data: string
}

export interface SseProgressEvent {
  type: 'progress'
  data: {
    job_id: string
    step: string
    progress: number
    progress_tasks: Record<string, JobProgressTask>
  }
}

export interface SseStatusEvent {
  type: 'status'
  data: {
    job_id: string
    status: string
    finished: boolean
  }
}

export type SseEvent = SseLogEvent | SseProgressEvent | SseStatusEvent