# SESSION STATE
<!-- Auto-written by active persona. Do not edit manually. -->

## Meta
session_id: 2026-08-30T10-40-00Z-echartstm
active_persona: BabaSensei (CHECKLIST/DOCS/REVIEW/PLAN) -> BabaDev (PATCH)
current_phase: CLOSED
prior_phase: PATCH
planning_mode: NONE
execution_mode: STRUCTURED (plan) -> DIRECT-equivalent build after explicit user go
mode_reason: library migration with confirmed plan; user commanded implementation
session_start: 2026-08-30T10-15:00Z(approx)
last_updated: 2026-08-30T10:55:00Z

## Target
repo: M:\Documents\Programming\Python\freqtrade
scope: Trade map charting library migration lightweight-charts v4.2 -> ECharts 5
language: Python (embedded JS template in build_report.py)

## Findings
- diCharts (user's original request) API-verified from dist type defs: NO marker API, NO custom line series (only sma/ema/bollinger), NO range events, panes limited to rsi/macd/volume, WebGPU-only main chart, 2-star/1-contributor dist-only repo -> user accepted recommendation to re-port to ECharts instead (decision: A)
- ECharts 5 already loaded in page; 'lab' dark theme registered (initChart helper)
- Old LWC bug confirmed live: preset setters called undefined inst.paint() -> TypeError, presets never repainted (user's "markers broken" symptom)
- Old LWC bug: empty-view branch of tlRender omitted slSer -> stale dashed SL lines

## Current Task
target: user_data/scripts/build_report.py (trade map block + CDN + resize)
size: M
definition_of_done: all LWC machinery replaced by ECharts; both bugs fixed; live Playwright verification of markers/tracks/zoom-merge/panes/tooltip/presets - MET

## Implementation (PATCH)
- tmBaseSeries(): 8 stable slots (candlestick, volume bar on hidden yAxis max*6, under/over/rateWin/rateLoss/SL line series with null breaks, custom series markers) - setOption(..., {replaceMerge:['series']})
- tmMarkerItem(): custom renderItem - up-triangle (long entry below), down-triangle (short entry above), exit circle with profit% textContent (kinds 0-3)
- native axis tooltip via tmTooltipFormatter (candle OHLC + active trades, win/loss colors); removed hand-rolled .tl-tip
- panes: separate ECharts instances joined by chart.group + echarts.connect (native two-way sync replaces tlSyncFrom/_tlSyncing/_tlPaneHold/tlIndSyncPanes); pane dataZoom non-interactive (relay-driven)
- tlZoomFetch: reads dataZoom startValue/endValue or start/end percent from getOption(); merge/coarse logic and 20k cap preserved
- tlFit: dispatchAction dataZoom 0-100; resize list extended to trade-map instances + pane charts
- fixes by construction: inst.paint defined (preset change repaints); empty-view path rebuilds ALL series incl SL
- pseudo-candle fallback now ms-consistent (tradeMs); tlTradeTime removed (dead)

## Phase Skips
- none material; DOCS run inline during CHECKLIST (diCharts API evidence)

## Verification
diff_inspected: true (git diff reviewed; user_data/ is gitignored so no git-visible diff)
checks_run: [
  "python -m py_compile user_data/scripts/build_report.py -> OK",
  "ruff check -> 288 findings on HEAD and working tree alike (0 new; baseline drifted from concurrent external edits)",
  "rebuild: dashboard.html 7247 KB regenerated",
  "Playwright live (server.py --port 8098): candles 2969 + volume render; markers 72 (36 trades x2) correct sides/colors; hilo tracks 89 pts + SL 107 pts; preset change TV -> no error, swatch+repaint OK (old bug gone)",
  "zoom dispatch -> merge 2969->5096 candles, full span preserved; second zoom -> 7668, span preserved",
  "WaveTrend pane added: 2 series/207k pts, zoom pinned == main; main zoom relayed to pane via connect",
  "native tooltip shows themed OHLC; Fit restores 0-100; chip x disposes pane",
  "console: only pre-existing favicon 404; NO 'Value is null' (LWC bug class eliminated)"
]
results: PASS

## Edited Files
- user_data/scripts/build_report.py (trade map block rewritten L~2804-3350 region: tmMarkerItem/tmBaseSeries/tmTooltipFormatter/mountTradeMap/tlRender/tlPaint/tlFit/tlMakePane/tlIndRefresh/tlIndAdd/tlIndRemove/tlIndMove/tlIndDropAll/tlZoomFetch; removed tlTooltip/tlSyncFrom/tlPaneHold/tlIndSyncPanes/_tlSyncing/tlTradeTime; CSS comment; LWC CDN tag removed; resize list extended)
- user_data/analysis/dashboard.html (regenerated artifact; gitignored)

## Commit/Push Gate
decision: NOTHING TO COMMIT - user_data/ is gitignored (line 7); template + generated html intentionally untracked
- if user ever wants it tracked: git add -f user_data/scripts/build_report.py (not recommended; repo policy)
- no remotes touched

## Cleanup at close
- diagnostic screenshots deleted (echarts-tm-*.png)
- test server RUNNING on port 8098 (agent-started, serves the migrated build); kill via Get-NetTCPConnection -LocalPort 8098

## Open follow-ups
- second mount (strategy detail tm-detail) uses the same factory - verified by construction, not separately screenshotted
- LWC CDN removal means dashboard.html has zero lightweight-charts references (grep-verified)

## Follow-up round 2 (user reports: y axis wrong, SL line never shown, dead server)
- ROOT CAUSE y-axis: dataZoom filterMode 'none' pinned the y scale to the FULL data extent (0-140 for SOL) - LWC autoScale-equivalent missing. Fix: filterMode 'filter' on main + pane dataZooms -> every axis rescales to the visible window
- ROOT CAUSE SL invisible: HoffmanIRB run trades carry pseudo initial stops (isl=0.27 for $26 SOL entry, islr=-0.99); old guard checked t.slr (final SL rate) so garbage isl passed and drew at 0.27 (off-screen). Fix: rate check on the SELECTED value (|rate|>0.35 -> fall back t.sl/t.slr, skip if that is wide too)
- ROOT CAUSE SL sub-pixel: trades last 5-20 min -> entry-exit span < 1px. Fix: pad each SL segment to >=0.8% of the visible window (~10px at any zoom), centered on the trade; SL width 1->2
- yAxis position 'right' added (main + panes) - labels were clipped at grid.left=10 (LWC had right price scale)
- debug note: pixel scans must scale by devicePixelRatio (1.25 here) - convertToPixel returns CSS px, canvas is 1593px for 1275 CSS px; null entries in a setOption series merge array COMPACT indices (poisoned two early tests)
- verification: pixel scan found 69 exact rgba(248,113,113) SL hits at converted coords; y axis 19-28 in zoomed window; console clean; ruff 288 = baseline (0 new); py_compile OK; report rebuilt 7237 KB
- 8098 server died twice mid-session (unexplained, no logs captured); restarted each time - if it dies again, wrap with file logging before chasing chart bugs

## Follow-up round 3: partial exits + Super Smoother tracks
- freqtrade core needs NO change: backtest results already carry per-trade orders[] (verified); the drop happens in our ingest/export
- ingest_results.py: trades.orders_json TEXT column (schema + additive migration), _orders_json() keeps [order_filled_date, safe_price, filled, ft_is_entry] only when >2 orders; _ingest_trade_row() helper backfills orders_json on re-ingest via UPDATE (INSERT OR IGNORE alone would never upgrade old rows)
- build_report.py: _fill_ms() (ISO->epoch ms, UTC-naive fallback) + compact_trade() exports fills as "px": [[ms, price, amt, isEntry]...] only when >2 fills (keeps JSON small)
- JS tlPaint: when t.px present, one marker per fill - entry triangles per DCA fill, exit circles per partial exit, profit% label ONLY on the final exit fill; fallback to old 2-marker shape otherwise
- tmSuperSmoother(): Ehlers 2-pole Super Smoother, period = clamp(3,10, len/3); hilo tracks now collect per-trade segments (underSegs/overSegs), smoothed, then joined with null breaks
- verified: synthetic 4-fill trade renders 2 triangles + 2 dots + label on final fill (Playwright); smoother called 114x/repaint, overPts 726 for shorts-only run; under-track visibly smooth in screenshot; console clean; py_compile OK; ruff 288+18 = baselines (0 new); DB column added via open_db migration
- note: existing 647k DB rows have orders_json NULL (no strategy uses partials today, 0 trades >2 orders across last 15 runs); backfill happens automatically on next re-ingest of a file containing partial trades
- synthetic test trade was page-local only (tradeCache mutation), not persisted
