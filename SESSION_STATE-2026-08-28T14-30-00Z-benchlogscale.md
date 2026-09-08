# SESSION STATE
<!-- Auto-written by active persona. Do not edit manually. -->

## Meta
session_id: 2026-08-28T14-30-00Z-benchlogscale
active_persona: BabaDev
current_phase: CLOSED
prior_phase: PATCH
planning_mode: STRUCTURED
execution_mode: DIRECT
mode_reason: localized JS template fix in build_report.py + dashboard.html regen; round 2 re-opened by user report "still not looking good"; session closed after commit+push
mode_override: user pre-approved PLAN ("approved") -> HANDOFF -> BUILD
session_start: 2026-08-28T14:25:00Z(approx)
last_updated: 2026-08-28T17:40:00Z

## Target
repo: M:\Documents\Programming\Python\freqtrade
scope: Strategy Lab dashboard benchmark tab - log scale toggle widens chart and removes axis; round 2: chart still visually broken after dispose fix
language: Python (embedded JS template) + generated HTML

## Round 1 (dispose leak) - fixed earlier this session
- ROOT CAUSE 1: every ECharts init re-initialized without dispose(); leaked canvases stacked and tracked by the resize listener -> "widening"
- fix: dispose-before-init guard at all 7 initChart() call sites (lines 1995, 2011, 2147→2196, 2319, 2439, 2497, 2518), idiom matches reloadLab
- verified: width invariant across toggles, previousInstance.isDisposed()=true

## Round 2 (user: "still not looking good") - found via Playwright visual inspection
Three additional defects visible in the boxplot rewrite of renderBenchmark:
1. ROOT CAUSE 2 (swapped coordinates): median-diamond and run-dot scatter series encoded [categoryIndex, value] but the axes are x=value / y=category - markers rendered at x=0..72 and y=-1999px (off-screen). convertToPixel probe proved it: medianPixel y=-1999 vs boxMedianPixel y=417.
   - fix: swapped to [value, i + jitter]; tooltip indices p.data[1] -> p.data[0]
2. ROOT CAUSE 3 (sentinel -100): freqtrade/data/metrics.py:308 emits sortino=-100 when down_stdev==0; 58 of 381 runs carried it, plus 32 zeros and real values down to -785 - the boxplot quartiles were dominated by sentinels and the axis spanned -900..600 hiding all useful resolution
   - fix: filter v !== -100 from sortino values + display entries; drop strategies whose values are ALL sentinel (73 -> 68 rows); hint count now reflects displayed rows
3. ROOT CAUSE 4 (fixed height): 73 rows crammed into 460px = ~6px per row, labels unreadable
   - fix: dynamic height 26px/row + 90, min 380 -> 1858px for 68 rows
4. Log scale: log axis cannot display <=0 values; sortino/PF/profit data always contains zeros/negatives so log either broke or showed garbage
   - fix: effectiveUseLog falls back to linear with hint "log scale off: values <=0 cannot be shown on a log axis"; xAxis gains scale:true on the linear branch

## Current Task
target: user_data/scripts/build_report.py + user_data/analysis/dashboard.html (regen)
size: M
status: CLOSED
definition_of_done:
- toggling #benchLog in benchmark tab no longer widens the chart canvas
- toggling #benchLog no longer leaves an old chart underneath (the "scale disappears" symptom)
- same fix applies to #logScale (History tab) - chart width invariant on toggle
- fix survives report rebuilds (template + generated html in sync)
- dispose-before-init pattern used uniformly across all 8 ECharts init sites (idiom matches reloadLab at line 3087-3091)
- zero new ruff findings

## Findings
- ROOT CAUSE: every ECharts init in build_report.py re-initializes on every render without first calling dispose() on the prior instance
- the leaked canvas remains in the DOM and is tracked by the global resize listener, producing a double-canvas whose total width exceeds .chart-box - this is the "widening" symptom
- the "scale disappears" symptom is the old chart's axes still rendering underneath the new chart's data layer
- 8 init sites: renderHistory (2 charts), renderBenchmark, renderWFDetailFromWindows, loadHOEpochs, renderEquity, renderProfitHist, renderTradeTimeline (via storeKey)
- reloadLab at line 3087-3091 already uses the correct `if (window[k] && window[k].dispose) { try { window[k].dispose(); } catch (e) {} }` idiom - we extend this idiom to all 8 init sites
- dashboard.html is generated from build_report.py template - fixing HTML alone would be wiped on rebuild; template is the source of truth

## Phase Skips
- DOCS/REVIEW: done inline at PLAN time (H1-H12 + S1-S13 rubric applied; reviewer verdict APPROVED)
- PATCH plan gate: user pre-approved with "approved" message; HANDOFF recorded; transition to PATCH

## Verification
diff_inspected: true (round 1: 7 dispose guards; round 2: coordinate swap + sentinel filter + dynamic height + log fallback in renderBenchmark)
checks_run: [
  "python -m py_compile user_data/scripts/build_report.py -> OK",
  "ruff check -> remaining E501s in my region all pre-existing over-limit lines; my added en-dashes (RUF001) removed; my long comments/returns wrapped; 0 new findings from clean lines",
  "convertToPixel probe: median marker y was -1999px (off-screen) before fix; box median at y=417 -> proves coordinate swap",
  "data probe: 58/381 sortino values are sentinel -100; 32 zeros; min -785.7 -> proves sentinel distortion",
  "rebuild via server /api/report (direct python run blocked: sqlite database is locked by server); built stamp advances (16:41:45) with template changes present (logNote, rawBoxData)",
  "Playwright visual: linear mode renders correctly - rows spaced, diamonds on median values, dots on run values (screenshot page-2026-08-28T14-43-18-194Z.png)",
  "Playwright log toggle: falls back to linear with explanatory hint, xAxisType stays 'value', 1 canvas, height 1858px",
  "Playwright metric switch + tooltip hover: no console errors (only pre-existing /api/configs 404)",
  "round 1 checks (dispose proof, width invariance) re-validated in round 2 rebuild: canvases=1 after toggle"
]
results: PASS

## Edited Files
- user_data/scripts/build_report.py (MODIFIED, gitignored: user_data/; round 1: 7 dispose guards; round 2: renderBenchmark coordinate swap [value,idx], sortino sentinel -100 filter, dynamic height, log fallback with hint, tooltip index fix; NOTE: file receives concurrent external edits - line count grew 3974->4276 during session)
- user_data/analysis/dashboard.html (REGENERATED via server /api/report, gitignored: user_data/analysis/; built=2026-08-28 16:41:45)

## Commit/Push Gate
decision: CLOSED - pushed. Session edits (build_report.py, dashboard.html) are gitignored; committed pending repo work in 5 commits:
- f8db899ac chore: update Baba agent workflow, claude adapters and system modules (incl. codespell fix unparsable in 19-session-state.txt)
- fa18f2220 feat(walkforward): delete re-computable hyperopt ticker cache per window
- eff349a3a test(hoffman): add vol-regime guard tests and feature profiler (fixed flake8/mypy/ruff hook findings: narrowed blind except, int coercions, groups annotation, unused noqas, long lines)
- 01b916b54 test: add benchmark chart self-checks and NFI guard sweep driver (fixed F401/E402/E501; both self-checks re-run PASS)
- 7b39edd86 test(pine): add structure regime oscillator state machine tests (20/20 pass; codespell trough->swing-low rephrase)
push: origin 7b39edd86..b57fa66c6 OK (second push); azure-mirror OK; gitlab-mirror up-to-date (same backend as origin); upstream NOT pushed (public freqtrade repo)
final commit: b57fa66c6 feat(profile): add SMMA/EMA dual-MA convergence gate to hoffman profiler (concurrent-session work, landed mid-close; ruff/format/py_compile clean, check_bench_math PASS)
tracked tree: CLEAN at close
late sweep at user close request: 0c2a52680 feat(profile): swap convergence gate for EMA pullback confirmation + tests (concurrent work; ruff/format clean, hoffman tests 48/48 pass; pushed origin + azure-mirror)
note: a concurrent process is actively iterating on hoffman profiler/strategy work; any drift after close belongs to that session
deliberately not committed: root-level verification PNGs, stray "=" file, strategy_lib/loss_streak_lock.py (package retired in HEAD), SESSION_STATE files, gitignored user_data/
concurrent activity note: tests/strategy/test_components_pine.py was modified mid-session by another process; verified 20/20 tests pass before committing
