# SESSION STATE
<!-- Auto-written by active persona. Do not edit manually. -->

## Meta
session_id: 2026-08-27T19-05-00Z-dashfix
active_persona: BabaDev
current_phase: CLOSED
prior_phase: PATCH
planning_mode: NONE
execution_mode: DIRECT
mode_reason: iterative dashboard feature work with live verification; low blast radius
mode_override: none
session_start: 2026-08-27T17:20:00Z(approx)
last_updated: 2026-08-28T15:30:00Z
session_end: CLOSED at user request

## Target
repo: M:\Documents\Programming\Python\freqtrade
scope: Strategy Lab dashboard (user_data) – inverted timestamps on charts
language: Python (embedded JS template)

## Current Task
target: user_data/analysis/dashboard.html + user_data/scripts/build_report.py (JS template)
size: S
definition_of_done:
- timestamp-bearing charts render chronologically regardless of payload order
- fix survives report rebuilds (template + generated html in sync)
- verified live via Playwright (server on 127.0.0.1:8099)

## Findings
- rendering was faithful to payload order (proven by asc/desc screenshot test); user-visible inversion came from payloads arriving newest-first (stale cached trade JSON / straggler runs)
- all current data layers (SQL ORDER BY close_date, trades/*.json, LAB blob) verified ascending
- dashboard.html is generated from build_report.py template - fixing HTML alone would be wiped on rebuild, both edited identically

## Phase Skips
- DOCS/REVIEW: diagnosis done empirically (grep + live page inspection); rubric applied inline
- PATCH plan gate: user pre-approved via "feel free to see it yourself" + build-mode switch

## Verification
diff_inspected: true (exact 3-change delta confirmed via git diff)
checks_run: [
  "python -m py_compile scripts/build_report.py -> OK",
  "ruff check scripts/build_report.py -> 226 findings, identical to pre-edit baseline (0 new; template noise pre-existing)",
  "Playwright real render: equity asc 2025-06-03 -> 2025-08-25",
  "Playwright adversarial: reversed payload still renders ascending",
  "Playwright history profit+sortino: 8/8 series ascending",
  "screenshot equity-fixed.png visual check"
]
results: PASS

## Edited Files
- user_data/scripts/build_report.py (renderEquity chronological sort + cumsum in sorted order; renderHistory rewritten: time axis, no smoothing, lttb sampling, connectNulls, y-axis scale, guarded tooltips, connected chart groups; LAB.built build stamp; 2x trades fetch cache-busted with ?v=LAB.built; logScale default on)
- user_data/analysis/dashboard.html (regenerated from template via build_report.py run at 19:36)

## Community indicators + spacing (user request 2026-08-28)
- server.py: /api/indicators (curated registry, 17 entries) + /api/indicator?name&pair&timeframe&trading_mode&start&end - computes overlays with the USER'S OWN indicators_pandas_ta functions over the shared feather cache (_candle_frame helper extracted, _candles_payload refactored onto it); NaN->null JSON-safe
- dashboard: sample SMA/EMA/BB/VWAP machinery REMOVED; Indicators dropdown populated from /api/indicators; tlIndAdd fetches server series and renders per scale ('price' overlay on main chart, 'own' -> new synced oscillator pane below the main chart with two-way visible-range sync); chips per instance with remove
- spacing: .tl-mount flex layout with gap, chart-box padding, 360px main + 110px osc panes
- side-tracks verified working (longs->under 82pts, shorts->over; GKD run 4 longs/2 shorts -> under 5 / over 4); user's "not fixed" likely stale page - hard refresh needed
- wavetrend value -366.7 in flat Sep window is a data artifact (CI normalization on tiny mean deviation) - rendering correct
- verification: /api/indicators list + wavetrend payload live, osc pane + chips + side-aware tracks + SL segments on osc=final screenshots, console clean

## Auto-scale, indicators, SL lines, strict tracks (user request 2026-08-28)
- Fit button per Trade map mount (price autoScale + timeScale.fitContent); fit-on-load via inst.fitted flag (reset on run/pair change) wired into all candle-load paths
- TA indicators: client-computed SMA 20 / EMA 50 / BB 20/2 / VWAP rendered as native LWC line series (LWC has no built-ins; community bundles are bundler-only, so math is local); Indicators "+ add" select per mount, active set persisted (localStorage tlInds) and synced across all mounts via removable chips
- initial stop loss drawn as dashed red segments per trade span (isl, fallback sl); wide pseudo-stops (slr < -35%) skipped to protect the price scale; legend swatch added
- strict entry-exit tracks (approved plan): hilo tracks only within [entryIdx, exitIdx] candle bounds + body-based offsets (min/max of open/close) so tracks never trail wicks or bleed into flat periods; side-aware: long trades under the price, short trades above
- duplication resolved/verified: build_report.py holds exactly ONE trade map implementation (mountTradeMap factory; old ECharts renderer grep-count 0); dashboard.html contains a copy by design - it is a GENERATED artifact overwritten by every rebuild, never edit it directly
- verification: final-all.png (BB + volume + markers + tracks + chips), zoom merge 8928->9330 candles stable span, Fit button restores full range, indicators add/remove across both mounts, console clean
- note: user browser tab and my test tab share the browser - verification screenshots may race with user navigation

## lightweight-charts rewrite (user request 2026-08-28)
- Trade map ported from ECharts custom series to lightweight-charts v4.2 (CDN standalone): candlestick + volume histogram (secondary scale) + native bar markers (entry arrowUp/arrowDown, exit circle with profit% label) + track line series
- REUSABLE BLOCK: mountTradeMap(mountId) factory injects controls+chart+legend+tooltip and registers itself in _tlInstances; Trades tab (tm-tab) and strategy detail (tm-detail) are two mounts of the same component; shared Candles/Markers/Tracks presets via class-based selects persisted in localStorage; _tmTab/_tmDetail instances; tlUpdate() re-renders all on preset change; autoSize handles resize (removed from manual resize list)
- tracks in hilo ("Beside candles"): line series along lows*0.975 / highs*1.025 per trade span; rate mode ("At trade rates"): win/loss line series at open->close rates with whitespace gaps
- offline fallback: pseudo-candles synthesized from trade rates when /api/candles unavailable
- bugs fixed during port: tlTradeTime helper missing; loadSeq/zoomSeq shared counter let visible-range events cancel the initial candle fetch (split counters); getVisibleRange() returns from/to as Number objects, not {time} - NaN params poisoned merge filters and wiped candles (NaN guard + span clamp added); buildTracks emitted bare y-values instead of [ts,y] pairs on the time axis
- perf: canvas engine - 3-9k candles + 500 markers pan/zoom fluidly; zoom refetch merges finer buckets over stable full-span base (cap 20k)
- verification: lwc-final2.png / lwc-zoom2.png - candles 8928->9330 after zoom merge, 242 markers, volume follows, span stable, tracks hug price, console clean (only stale-tab 8099 noise)

## Tracks + dark tooltips (user request 2026-08-28)
- hilo mode reworked: no more diagonal entry-exit line; two track polylines hug the price instead - one stepping along candle lows (2.5% under, entry-long cyan) and one along highs (2.5% over, entry-short pink) across each trade span; markers only in custom series (value[9] flags hilo)
- zoom-refetch architecture fixed: zoomed fetch used to REPLACE the candle series, collapsing the axis extent and cascading bogus refetches (Dec 8-9 window bug); now finer candles are MERGED into the zoomed window over the stable full-range base (cap 15k), zoom-out restores coarse, appliedZoom key guards re-entry
- dark tooltips: echarts.registerTheme('lab') with #1b1628 panel, #2f2745 border, #e9e4f5 text, shadow, rounded corners, themed axis pointer; all echarts.init call sites routed through initChart() helper
- verification: tracks-final.png (fine candles merged, tracks follow price through the 10-08 crash, markers below/above), dark-tooltip.png (equity axis tooltip themed), 3880 merged candles full-span preserved, trackUnder/Over 69+69, console clean
- test server note: instances keep dying (user workflow collisions) - now running agent-own instance on port 8098; user must restart their 8099 server to pick up volume-capable /api/candles

## Candlesticks round 2 (user request 2026-08-28)
- split single Colors dropdown into Candles + Markers dropdowns (independent registries TL_CANDLE_PRESETS / TL_MARKER_PRESETS, localStorage tlCandlePreset / tlMarkerPreset)
- new presets: Mint & Rajah (mint #aaf0d1 up / rajah #f5a45c down, cyan/pink entries) and Cyan & Pink (cyan #22d3ee / pink #f472b6)
- Position dropdown: markers "On price" (default) or "Above/below candles" (entry 2.5% under candle low, exit 2.5% over high via tlBisect nearest-candle lookup; falls back to on-price until candles load)
- volume: /api/candles now ships [ts,o,h,l,c,vol] (downsampled buckets sum volume); Trade map renders violet volume bars on hidden secondary y-axis (max*6 so bars hug bottom)
- BUG fixed: candle itemStyle used tlColors() (marker registry, no up/down keys) after the preset split -> undefined colors -> invisible candles; candle series now uses tlCandleColors(); tooltip win/loss colors follow marker preset
- BUG fixed: buildData briefly mapped trade times to candle indices on a time axis (axis collapsed to 1978) - x stays timestamp, bisect only for high/low lookup
- verification: final-mint-hilo.png (Mint & Rajah + hilo + volume, BigZ06AtrSl ETH/USDC), volDataN=2996, itemStyle confirmed mint, presets persisted, console clean

## Candlesticks + color presets (user request 2026-08-28)
- blocker found: the running server process predated the /api/candles route in server.py (added by concurrent edits) -> 404; restarted server on 8099, candles now render (2996 buckets on full range)
- added zoom-triggered candle refetch (debounced 450ms, window-keyed cache capped at ~60, _tlSeq staleness guard) so zooming reveals progressively finer buckets
- color presets for Trade map: Lab (default) / TradingView / Classic / Ghost (dim candles, trades pop) - candle up/down + win/loss + entry long/short colors; exit-reason palette unchanged
- "Colors:" select in Trades tab and strategy detail; choice persisted in localStorage (key tlPreset), both selects kept in sync, legend entry swatches update live
- verification: screenshots preset-tv.png / preset-ghost.png (BigZ06AtrSl ETH/USDC), localStorage persisted, console clean, block lint-clean
- NOTE: build_report.py + server.py keep receiving concurrent external edits (prop-firm section, rowDrill) - all preserved

## Trade map feature (user request 2026-08-28)
- new "Trade map" chart per run in Trades tab + strategy detail: custom ECharts series rendering entry triangle (up=long cyan, down=short violet), exit dot colored by exit reason family (roi/trailing/stop+liq/signal/force/other), entry-to-exit segment colored win/loss, item tooltip with pair, side, tags, dates, rates, profit, duration
- controls: pair selector (ordered by trade count) + exit-reason filter; independent instances for Trades tab (_timelineChart) and detail (_timelineChartD); added to window resize list
- data: compact trade records only (no OHLCV) - chart stays serverless-capable; Date.parse with space->T normalization
- verification: rebuilt report (3903 KB), live test on BigZ06AtrSl: 121 trades rendered for ETH/USDC, 9 pairs / 4 exit reasons in selectors, stop_loss filter 121->62, pair switch ETH->BTC 60 trades, detail instance renders, console clean, screenshot trade-map-view2.png
- lint: net +0 new findings from my block (all lines <=100; built line uses astimezone() for DTZ005)
- NOTE: build_report.py received concurrent external edits mid-session (rowDrill hyperopt feature) - preserved untouched, verified my changes coexist

## History tab follow-up (user: "looks terrible")
- ROOT CAUSE of the original "inverted timestamps": history charts used a category axis whose order is inferred from first-encounter across series - different strategies' run dates appended out of order, scrambling/inverting the axis and producing zigzag lines
- fix: xAxis type 'time' (+ hideOverlap, {yyyy}-{MM}-{dd} labels); smooth:false (smooth:true fabricated overshoot peaks on sparse run data); sampling lttb; connectNulls for log-scale gaps; value axes scale:true; sortino tooltip null guard; profit+sortino zoom synced via echarts.connect; log scale default on (profit spans 3+ orders of magnitude)
- verification: before/after screenshots (history-before.png / history-after.png); all series time-ascending; xAxis type=time; groups synced; console clean; ruff back at 226 baseline after splitting the two cache-busted fetch lines

## BigZ06AtrSl follow-up (user-reported example)
- could NOT reproduce: all BigZ06AtrSl trades/*.json payloads ascending; Trades tab + strategy-detail equity both render asc 2024-01-03 -> 2025-12-31 (screenshots bigz06atrsl-check.png, bigz06atrsl-detail.png, bigz06atrsl-final.png)
- conclusion: user browser served stale cached HTML/trade JSON; hardened with LAB.built cache-busting so trade payloads refetch on every report rebuild
- report rebuilt: dashboard 2621 KB, built=2026-08-27 19:22:04, 321 trade files re-exported

## Commit/Push Gate
decision: NOT COMMITTED - user declined/no answer after repeated asks; session ends with work in the working tree
- stageable: user_data/scripts/build_report.py, user_data/scripts/server.py (both modified, uncommitted)
- gitignored (generated): user_data/analysis/dashboard.html - template in build_report.py is the source of truth
- to commit later: git add user_data/scripts/build_report.py user_data/scripts/server.py && git commit -m "feat: lab dashboard trade map on lightweight-charts + ordering/track/indicator fixes"
- suggested commit message: feat: lab dashboard trade map on lightweight-charts + ordering/track/indicator fixes
- push targets: origin + *-mirror remotes per module 33 (none configured check pending)

## Cleanup at close
- diagnostic screenshots removed from repo root (equity-*.png, bigz06*.png, trade-map*.png, history-*.png, candles-*.png, tracks-*.png, dark-tooltip.png, preset-*.png, mint-rajah*.png, osc-pane.png, reuse-tab.png, final-all.png, ind-final.png, lwc-*.png)
- test server on port 8098 left RUNNING intentionally (serves the fixed dashboard); kill via Get-NetTCPConnection -LocalPort 8098 or restart with lab.py serve
