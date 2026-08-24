"""build_report.py — generate user_data/analysis/dashboard.html from results.db.

Reads the SQLite database produced by ingest_results.py and writes a single
self-contained HTML dashboard (no server, no build step) using CDN
Tailwind CSS + Apache ECharts with a dark + lavender flexbox theme.

Layout is tabbed:
  Dashboard | Strategies | History | Benchmark | Walk-Forward | Hyperopt | Trades | Lab

Every strategy gets ONE canonical grade (from its latest benchmark run, else
latest backtest run). Clicking a strategy opens a detail view with the full
scorecard breakdown, every run, trades, hyperopt and walk-forward data.

Usage:
    python user_data/scripts/build_report.py [--db user_data/analysis/results.db]
                                             [--out user_data/analysis/dashboard.html]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

USER_DATA = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = USER_DATA / "analysis"

# ---------------------------------------------------------------- scorecard ---

SCORECARD = {
    "sortino": {"pass": 1.0, "warn": 0.3, "higher_is_better": True, "label": "Sortino"},
    "calmar": {"pass": 1.0, "warn": 0.3, "higher_is_better": True, "label": "Calmar"},
    "profit_factor": {"pass": 1.2, "warn": 1.0, "higher_is_better": True, "label": "Profit factor"},
    "max_drawdown_account": {"pass": 0.2, "warn": 0.4, "higher_is_better": False, "label": "Max drawdown"},
    "winrate": {"pass": 0.45, "warn": 0.35, "higher_is_better": True, "label": "Win rate"},
    "total_trades": {"pass": 100, "warn": 30, "higher_is_better": True, "label": "Trades"},
}

GRADE_EXPLANATION = {
    "A": "5+ metrics pass, none fail",
    "B": "at least 3 metrics pass",
    "C": "exactly 1 metric fails",
    "D": "2 or more metrics fail",
}


def grade_value(value, spec):
    if value is None:
        return "na"
    if spec["higher_is_better"]:
        if value >= spec["pass"]:
            return "pass"
        if value >= spec["warn"]:
            return "warn"
        return "fail"
    if value <= spec["pass"]:
        return "pass"
    if value <= spec["warn"]:
        return "warn"
    return "fail"


def overall_grade(grades: list[str]) -> str:
    counts = {g: grades.count(g) for g in ("pass", "warn", "fail", "na")}
    if counts["fail"] >= 2:
        return "D"
    if counts["fail"] == 1:
        return "C"
    if counts["pass"] >= 5 and counts["fail"] == 0:
        return "A"
    if counts["pass"] >= 3:
        return "B"
    return "C"


def score_strategy(row: dict) -> dict:
    """Compute a scorecard for a single backtest/benchmark row."""
    grades = {}
    for key, spec in SCORECARD.items():
        grades[key] = grade_value(row.get(key), spec)
    grade_list = list(grades.values())
    return {
        "grade": overall_grade(grade_list),
        "grades": grades,
        "pass_count": grade_list.count("pass"),
        "warn_count": grade_list.count("warn"),
        "fail_count": grade_list.count("fail"),
    }


# ------------------------------------------------------------------- queries ---

def load_data(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row

    def with_score(rows):
        out = []
        for r in rows:
            d = dict(r)
            d["score"] = score_strategy(d)
            out.append(d)
        return out

    backtests = with_score(conn.execute(
        """SELECT b.*, s.status, s.notes
           FROM backtests b
           LEFT JOIN strategies s ON s.name = b.strategy
           ORDER BY b.strategy, b.run_time"""
    ).fetchall())
    benchmarks = with_score(conn.execute(
        "SELECT * FROM benchmarks ORDER BY strategy, run_time"
    ).fetchall())
    hyperopt = [dict(r) for r in conn.execute(
        "SELECT * FROM hyperopt ORDER BY strategy, run_time"
    )]
    walkforward = [dict(r) for r in conn.execute(
        "SELECT * FROM walkforward ORDER BY strategy, run_time"
    )]
    strategies = [dict(r) for r in conn.execute(
        "SELECT * FROM strategies ORDER BY name"
    )]
    return {
        "backtests": backtests,
        "benchmarks": benchmarks,
        "hyperopt": hyperopt,
        "walkforward": walkforward,
        "strategies": strategies,
        "trade_runs": trade_runs(conn),
    }


# compact key mapping for trade export (keeps JSON small)
TRADE_KEYS = {
    "pair": "p", "is_short": "s", "enter_tag": "t", "exit_reason": "e",
    "open_date": "o", "close_date": "c", "open_rate": "or", "close_rate": "cr",
    "min_rate": "mn", "max_rate": "mx", "amount": "am", "stake_amount": "sa",
    "leverage": "lev", "profit_ratio": "pr", "profit_abs": "pa",
    "trade_duration": "d", "stop_loss_abs": "sl", "stop_loss_ratio": "slr",
    "initial_stop_loss_abs": "isl", "initial_stop_loss_ratio": "islr",
    "fee_open": "fo", "fee_close": "fc",
}


def trade_runs(conn: sqlite3.Connection) -> list[dict]:
    """List of (strategy, source) combos that have trades, newest first."""
    conn.row_factory = sqlite3.Row
    runs = [dict(r) for r in conn.execute(
        """SELECT t.strategy, t.source, COUNT(*) AS n_trades,
                  MAX(b.run_time) AS run_time
           FROM trades t
           LEFT JOIN backtests b ON b.strategy = t.strategy AND b.source = t.source
           GROUP BY t.strategy, t.source
           ORDER BY run_time DESC, t.strategy"""
    )]
    for r in runs:
        r["key"] = run_key(r["strategy"], r["source"])
    return runs


def compact_trade(t: dict) -> dict:
    out = {}
    for k, short in TRADE_KEYS.items():
        v = t.get(k)
        if isinstance(v, bool):
            v = int(v)
        out[short] = v
    return out


def export_trade_files(conn: sqlite3.Connection, out_dir: Path) -> int:
    """Write one compact JSON per (strategy, source) into out_dir/trades/.

    Returns number of files written.
    """
    conn.row_factory = sqlite3.Row
    td = out_dir / "trades"
    td.mkdir(parents=True, exist_ok=True)
    written = 0
    for run in trade_runs(conn):
        rows = conn.execute(
            """SELECT * FROM trades WHERE strategy=? AND source=? ORDER BY close_date""",
            (run["strategy"], run["source"]),
        ).fetchall()
        payload = {
            "strategy": run["strategy"],
            "source": run["source"],
            "n": len(rows),
            "trades": [compact_trade(dict(r)) for r in rows],
        }
        fname = run_key(run["strategy"], run["source"]) + ".json"
        (td / fname).write_text(json.dumps(payload), encoding="utf-8")
        written += 1
    return written


def run_key(strategy: str, source: str) -> str:
    """Filesystem-safe key for a (strategy, source) run."""
    safe = source.replace(".json", "").replace(".zip", "").replace("backtest-result-", "")
    return f"{strategy}__{safe}"


def canonical_per_strategy(data: dict) -> list[dict]:
    """One canonical row per strategy: latest benchmark run, else latest backtest.

    The canonical row defines the strategy's single grade shown across the UI.
    """
    canonical: dict[str, dict] = {}
    # benchmarks preferred (apples-to-apples)
    for row in data["benchmarks"]:
        name = row["strategy"]
        if name not in canonical or (row["run_time"] or "") > (canonical[name].get("run_time") or ""):
            r = dict(row)
            r["basis"] = "benchmark"
            canonical[name] = r
    for row in data["backtests"]:
        name = row["strategy"]
        cur = canonical.get(name)
        if cur is None or ((row["run_time"] or "") > (cur.get("run_time") or "") and cur.get("basis") != "benchmark"):
            r = dict(row)
            r["basis"] = "backtest"
            canonical[name] = r
    out = sorted(
        canonical.values(),
        key=lambda r: (r["score"]["grade"], -(r.get("profit_total") or 0)),
    )
    return out


def history_series(data: dict) -> dict:
    """Per-strategy time series for profit and sortino charts."""
    series = {}
    for row in data["backtests"]:
        name = row["strategy"]
        rt = row["run_time"]
        if not rt:
            continue
        s = series.setdefault(name, {"dates": [], "profit": [], "sortino": [], "trades": []})
        s["dates"].append(rt[:10])
        s["profit"].append(round(row.get("profit_total") or 0.0, 4))
        s["sortino"].append(round(row.get("sortino") or 0.0, 2))
        s["trades"].append(row.get("total_trades") or 0)
    return {k: v for k, v in series.items() if len(v["dates"]) >= 2}


def benchmark_bars(data: dict) -> list[dict]:
    """Latest benchmark run per strategy for the compare bar chart."""
    latest: dict[str, dict] = {}
    for row in data["benchmarks"]:
        name = row["strategy"]
        if name not in latest or (row["run_time"] or "") > (latest[name].get("run_time") or ""):
            latest[name] = row
    return sorted(
        (dict(r) for r in latest.values()),
        key=lambda r: -(r.get("sortino") or 0),
    )


# ------------------------------------------------------------------ html css ---

CSS = """
:root {
  --bg: #131020;
  --bg-soft: #1b1628;
  --card: #201a30;
  --card-hover: #2a2240;
  --border: #2f2745;
  --text: #e9e4f5;
  --text-dim: #a89fc4;
  --text-faint: #6f668c;
  --lavender: #c4b5fd;
  --lavender-deep: #a78bfa;
  --lavender-ink: #6d5bd0;
  --accent: #b39df7;
  --good: #6ee7a8;
  --warn: #fbbf24;
  --bad: #f87171;
  --na: #8b83a5;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
body { display: flex; flex-direction: column; min-height: 100vh; }
a { color: var(--lavender); text-decoration: none; }
header { background: var(--bg-soft); border-bottom: 1px solid var(--border);
  padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; }
header .logo { display: flex; align-items: center; gap: 12px; }
header .dot { width: 12px; height: 12px; border-radius: 50%;
  background: var(--lavender-deep); box-shadow: 0 0 12px var(--lavender); }
header h1 { font-size: 18px; margin: 0; font-weight: 600; letter-spacing: .3px; }
header .sub { color: var(--text-faint); font-size: 12px; }

/* tabs */
.tabs { display: flex; gap: 4px; flex-wrap: wrap; padding: 10px 24px;
  background: var(--bg-soft); border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 40; }
.tabs button { background: transparent; border: 1px solid transparent; color: var(--text-dim);
  padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; }
.tabs button:hover { color: var(--lavender); background: var(--card-hover); }
.tabs button.active { background: var(--lavender-ink); color: #fff; }

main { flex: 1; width: 100%; max-width: 1500px; margin: 0 auto; padding: 24px; }
.tab { display: none; flex-direction: column; gap: 24px; }
.tab.active { display: flex; }
section { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.section-head { display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; }
.section-head h2 { margin: 0; font-size: 16px; font-weight: 600; color: var(--lavender); }
.section-head .hint { color: var(--text-faint); font-size: 12px; }

/* stat cards */
.stats { display: flex; gap: 14px; flex-wrap: wrap; }
.stat { flex: 1 1 170px; background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 16px 18px; display: flex; flex-direction: column; gap: 4px; }
.stat .k { color: var(--text-faint); font-size: 12px; text-transform: uppercase; letter-spacing: .6px; }
.stat .v { font-size: 24px; font-weight: 600; color: var(--lavender); }
.stat .v.good { color: var(--good); }
.stat .v.bad { color: var(--bad); }

/* cards */
.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 18px; display: flex; flex-direction: column; gap: 12px; }
.card:hover { border-color: var(--lavender-ink); }

/* tables */
.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px;
  position: relative; scrollbar-width: thin; scrollbar-color: #3a3254 var(--bg-soft);
  overscroll-behavior-inline: contain; }
.table-wrap::-webkit-scrollbar { height: 10px; }
.table-wrap::-webkit-scrollbar-track { background: var(--bg-soft); }
.table-wrap::-webkit-scrollbar-thumb { background: #3a3254; border-radius: 8px; border: 2px solid var(--bg-soft); }
.table-wrap::-webkit-scrollbar-thumb:hover { background: var(--lavender-ink); }
.table-wrap::before, .table-wrap::after { content: ''; position: absolute; top: 0; bottom: 10px;
  width: 28px; pointer-events: none; opacity: 0; transition: opacity .15s ease; z-index: 5; }
.table-wrap::before { left: 0; border-radius: 12px 0 0 0;
  background: linear-gradient(to right, rgba(19, 16, 32, .92), rgba(19, 16, 32, 0)); }
.table-wrap::after { right: 0; border-radius: 0 12px 0 0;
  background: linear-gradient(to left, rgba(19, 16, 32, .92), rgba(19, 16, 32, 0)); }
.table-wrap.has-overflow.scroll-left::before { opacity: 1; }
.table-wrap.has-overflow.scroll-right::after { opacity: 1; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
thead th { background: var(--bg-soft); color: var(--lavender); font-weight: 600;
  text-align: left; padding: 10px 12px; white-space: nowrap; cursor: pointer; user-select: none; }
thead th:hover { color: var(--accent); }
thead th .arrow { color: var(--lavender-deep); font-size: 10px; margin-left: 4px; opacity: .7; }
tbody td { padding: 8px 12px; border-top: 1px solid var(--border); white-space: nowrap; }
tbody tr:hover { background: var(--card-hover); }
td.num, th.num { text-align: right; }
.clickable { cursor: pointer; }
.clickable:hover { color: var(--lavender-deep); }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 11px;
  font-weight: 600; }
.pill.pass { background: rgba(110,231,168,.12); color: var(--good); }
.pill.warn { background: rgba(251,191,36,.12); color: var(--warn); }
.pill.fail { background: rgba(248,113,113,.14); color: var(--bad); }
.pill.na { background: rgba(139,131,165,.12); color: var(--na); }
.pill.gA { background: rgba(110,231,168,.15); color: var(--good); }
.pill.gB { background: rgba(163,157,247,.15); color: var(--lavender); }
.pill.gC { background: rgba(251,191,36,.14); color: var(--warn); }
.pill.gD { background: rgba(248,113,113,.15); color: var(--bad); }
.pill.gF { background: rgba(248,113,113,.25); color: var(--bad); }
.status { font-size: 11px; padding: 2px 10px; border-radius: 999px; border: 1px solid var(--border);
  color: var(--text-dim); }
.status.active { color: var(--good); border-color: rgba(110,231,168,.4); }
.status.experimental { color: var(--warn); border-color: rgba(251,191,36,.4); }
.status.retired { color: var(--na); }

/* charts */
.charts { display: flex; gap: 16px; flex-wrap: wrap; min-width: 0; }
.chart-box { flex: 1 1 460px; min-width: 0; background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 12px; }
.chart { width: 100%; height: 320px; min-width: 0; }
.chart canvas { max-width: 100%; }

/* controls */
.controls { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.controls input, .controls select { background: var(--bg-soft); border: 1px solid var(--border);
  color: var(--text); border-radius: 8px; padding: 7px 12px; font-size: 13px; outline: none; }
.controls input:focus, .controls select:focus { border-color: var(--lavender-ink); }
.controls label { color: var(--text-dim); font-size: 13px; }
.btn { background: var(--bg-soft); border: 1px solid var(--border); color: var(--lavender);
  border-radius: 8px; padding: 7px 14px; font-size: 13px; cursor: pointer; font-weight: 500; }
.btn:hover { border-color: var(--lavender-ink); background: var(--card-hover); }
.btn.primary { background: var(--lavender-ink); color: #fff; border-color: var(--lavender-ink); }
.btn.primary:hover { background: #7c6cd6; }
.btn.compact { padding: 5px 12px; font-size: 12px; border-radius: 6px; }

/* lab strategy editor */
select.statusSel {
  appearance: none; -webkit-appearance: none; -moz-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'%3E%3Cpath d='M2 3h6l-3 4z' fill='%23a89fc4'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 10px center; background-size: 10px;
  background-color: var(--bg-soft);
  border: 1px solid var(--border); border-radius: 8px;
  color: var(--text-dim); padding: 6px 30px 6px 12px; font-size: 13px; font-weight: 500;
  font-family: inherit; cursor: pointer; outline: none; min-width: 132px;
  transition: border-color .15s ease, box-shadow .15s ease;
}
select.statusSel:hover { border-color: var(--lavender-ink); }
select.statusSel:focus-visible { border-color: var(--lavender-ink); box-shadow: 0 0 0 3px rgba(109, 91, 208, .18); }
select.statusSel option { background: var(--bg-soft); color: var(--text); }
select.statusSel.active { color: var(--good); }
select.statusSel.experimental { color: var(--warn); }
select.statusSel.retired { color: var(--na); }

.notesInput {
  background: var(--bg-soft); border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 6px 10px; font-size: 13px; font-family: inherit; outline: none;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.notesInput:focus-visible { border-color: var(--lavender-ink); box-shadow: 0 0 0 3px rgba(109, 91, 208, .18); }
.notesInput::placeholder { color: var(--text-faint); }

footer { padding: 16px 24px; color: var(--text-faint); font-size: 12px;
  border-top: 1px solid var(--border); background: var(--bg-soft); }

.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--text-dim); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

/* grade explanation */
.grade-grid { display: flex; gap: 12px; flex-wrap: wrap; }
.grade-cell { flex: 1 1 150px; background: var(--bg-soft); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px; text-align: center; }
.grade-cell .big { font-size: 26px; font-weight: 700; }

/* strategy detail */
#strategy-detail { display: none; }
#strategy-detail.active { display: flex; flex-direction: column; gap: 24px; }
.detail-head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.detail-head .name { font-size: 22px; font-weight: 700; }
.metric-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.metric-card { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 12px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
.metric-card .mk { color: var(--text-faint); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }
.metric-card .mv { font-size: 18px; font-weight: 600; }
.basis-badge { font-size: 11px; color: var(--text-faint); border: 1px solid var(--border);
  padding: 2px 10px; border-radius: 999px; }
.hidden { display: none !important; }
.bad { color: var(--bad); }

/* responsive */
@media (max-width: 768px) {
  main { padding: 14px; }
  .tabs { padding: 8px 10px; }
  .tabs button { padding: 7px 12px; font-size: 12px; }
  header { padding: 12px 14px; flex-wrap: wrap; gap: 8px; }
  header h1 { font-size: 16px; }
  .stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .stat { padding: 12px 14px; }
  .stat .v { font-size: 20px; }
  .charts { gap: 12px; }
  .chart-box { flex: 1 1 100%; }
  .metric-row { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
  .grade-grid { gap: 8px; }
  .grade-cell { flex: 1 1 40%; padding: 10px; }
  .controls { gap: 8px; }
  .controls input, .controls select, .btn { width: 100%; }
  .controls label { width: 100%; display: flex; flex-direction: column; gap: 4px; }
  #histSelect { min-width: 0 !important; width: 100%; }
  #benchStrategies, #benchRange, #benchTf { min-width: 0 !important; width: 100%; }
  #tradeRun { min-width: 0 !important; width: 100%; }
  .section-head { flex-direction: column; align-items: flex-start; }
  .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  table { min-width: 640px; }
  .detail-head { gap: 10px; }
  .detail-head .name { font-size: 18px; }
}
@media (max-width: 480px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .grade-cell { flex: 1 1 100%; }
  .tabs button { padding: 6px 10px; font-size: 11px; }
  .chart { height: 260px; }
}
"""

# ------------------------------------------------------------------ JS --------

JS = r"""
const state = { tab: 'dashboard', strategy: null, query: '', status: 'all' };
const tradeCache = {};

function $(id) { return document.getElementById(id); }
function pill(cls, txt) { return `<span class="pill ${cls}">${txt}</span>`; }
function fmt(v, d=3) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!isFinite(n)) return '—';
  return n.toLocaleString('en-US', {maximumFractionDigits: d});
}
function gradePill(g) { return pill('g'+g, g); }
function statusPill(s) {
  if (!s) s = 'active';
  const map = {active:'active', experimental:'experimental', retired:'retired'};
  return `<span class="status ${map[s]||'active'}">${s}</span>`;
}
function pct(v) { return v===null||v===undefined ? '—' : (v*100).toFixed(1)+'%'; }
function esc(s) { return String(s==null?'':s).replace(/[&<>"']/g, c => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

/* ---------- tabs ---------- */
function showTab(name) {
  state.tab = name;
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === 'tab-' + name));
  if (name === 'dashboard') renderDashboard();
  if (name === 'strategies') renderStrategies();
  if (name === 'history') renderHistory();
  if (name === 'benchmark') renderBenchmark();
  if (name === 'walkforward') renderWalkForward();
  if (name === 'hyperopt') renderHyperopt();
  if (name === 'trades') renderTradesTab();
  if (name === 'lab') renderLab();
  window.dispatchEvent(new Event('resize'));
}

/* ---------- table scroll indicators ---------- */
function updateTableScroll(wrap) {
  if (!wrap) return;
  const hasOverflow = wrap.scrollWidth > wrap.clientWidth + 1;
  wrap.classList.toggle('has-overflow', hasOverflow);
  if (!hasOverflow) { wrap.classList.remove('scroll-left', 'scroll-right'); return; }
  wrap.classList.toggle('scroll-left', wrap.scrollLeft > 2);
  wrap.classList.toggle('scroll-right', wrap.scrollLeft < wrap.scrollWidth - wrap.clientWidth - 2);
}
function updateAllTableScrolls() { document.querySelectorAll('.table-wrap').forEach(updateTableScroll); }
document.addEventListener('scroll', e => {
  const wrap = e.target.closest ? e.target.closest('.table-wrap') : null;
  if (wrap) updateTableScroll(wrap);
}, true);
window.addEventListener('resize', updateAllTableScrolls);

/* ---------- sortable table ---------- */
function makeSortable(tableEl) {
  updateTableScroll(tableEl.closest('.table-wrap'));
  tableEl.querySelectorAll('thead th').forEach(th => {
    th.addEventListener('click', () => {
      const idx = [...th.parentNode.children].indexOf(th);
      const tbody = tableEl.querySelector('tbody');
      document.querySelectorAll('thead th .arrow', tableEl).forEach(a => a.remove());
      tableEl.querySelectorAll('thead th').forEach(h => { const a = h.querySelector('.arrow'); if (a) a.remove(); });
      const asc = th.dataset.asc !== '1';
      const rows = [...tbody.rows].sort((a,b) => {
        let av = a.cells[idx].dataset.val, bv = b.cells[idx].dataset.val;
        if (av === undefined && bv === undefined) return 0;
        if (av === '' || av === undefined) av = '-inf';
        if (bv === '' || bv === undefined) bv = '-inf';
        const an = Number(av), bn = Number(bv);
        const useNum = !isNaN(an) && !isNaN(bn) && av !== '-inf' && bv !== '-inf';
        let r = useNum ? (an - bn) : String(av).localeCompare(String(bv));
        return asc ? r : -r;
      });
      rows.forEach(r => tbody.appendChild(r));
      th.dataset.asc = asc ? '1' : '0';
      const arrow = document.createElement('span');
      arrow.className = 'arrow';
      arrow.textContent = asc ? '\u25B2' : '\u25BC';
      th.appendChild(arrow);
    });
  });
}

function stratLink(name) {
  return `<a class="clickable" onclick="openStrategy('${esc(name)}')">${esc(name)}</a>`;
}

/* ---------- dashboard ---------- */
function renderDashboard() {
  const rows = LAB.canonical;
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr>
    <th>Strategy</th><th class="num">Grade</th><th class="num">Profit%</th>
    <th class="num">Sortino</th><th class="num">Calmar</th><th class="num">PF</th>
    <th class="num">MaxDD</th><th class="num">Win%</th><th class="num">Trades</th>
    <th>Basis</th><th>Run</th>
  </tr></thead><tbody>` + rows.map(r => {
    const prof = (r.profit_total||0)*100;
    return `<tr>
      <td>${stratLink(r.strategy)} ${statusPill(r.status)}</td>
      <td class="num" data-val="${r.score.grade}">${gradePill(r.score.grade)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt(prof,1)}%</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td>
      <td class="num" data-val="${r.calmar||0}">${fmt(r.calmar)}</td>
      <td class="num" data-val="${r.profit_factor||0}">${fmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.max_drawdown_account||0}">${pct(r.max_drawdown_account)}</td>
      <td class="num" data-val="${r.winrate||0}">${pct(r.winrate)}</td>
      <td class="num" data-val="${r.total_trades||0}">${fmt(r.total_trades,0)}</td>
      <td data-val="${r.basis||''}">${pill(r.basis==='benchmark'?'pass':'na', r.basis||'')}</td>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,10))}</td>
    </tr>`;
  }).join('') + '</tbody>';
  const wrap = $('dashboardTable');
  wrap.innerHTML = '';
  wrap.appendChild(t);
  makeSortable(t);

  // what to improve next
  const worst = rows.filter(r => r.score.grade !== 'A').slice(0, 6);
  const wl = $('improveList');
  wl.innerHTML = worst.map(r => {
    const fails = Object.entries(r.score.grades)
      .filter(([k,g]) => g === 'fail').map(([k]) => LAB.scorecard[k].label).join(', ');
    const warns = Object.entries(r.score.grades)
      .filter(([k,g]) => g === 'warn').map(([k]) => LAB.scorecard[k].label).join(', ');
    let focus = fails ? '<b class="bad">' + fails + '</b>' : '';
    if (warns) focus += (focus ? ' + ' : '') + warns;
    return `<div class="metric-card" style="cursor:pointer" onclick="openStrategy('${esc(r.strategy)}')">
      <div class="mk">${esc(r.strategy)} — ${gradePill(r.score.grade)}</div>
      <div class="mv">${focus || '—'}</div>
    </div>`;
  }).join('');
}

/* ---------- strategies ---------- */
function renderStrategies() {
  let rows = LAB.canonical;
  const q = state.query.toLowerCase();
  rows = rows.filter(r => !q || r.strategy.toLowerCase().includes(q));
  if (state.status !== 'all') rows = rows.filter(r => (r.status||'active') === state.status);
  rows.sort((a,b) => (a.strategy||'').localeCompare(b.strategy||''));
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr>
    <th>Strategy</th><th>Status</th><th class="num">Grade</th><th class="num">Trades</th>
    <th class="num">Profit%</th><th class="num">PF</th><th class="num">Sortino</th>
    <th class="num">Calmar</th><th class="num">MaxDD</th><th>Basis</th><th>Run</th>
  </tr></thead><tbody>` + rows.map(r => {
    return `<tr>
      <td>${stratLink(r.strategy)}</td>
      <td data-val="${r.status||'active'}">${statusPill(r.status)}</td>
      <td class="num" data-val="${r.score.grade}">${gradePill(r.score.grade)}</td>
      <td class="num" data-val="${r.total_trades||0}">${fmt(r.total_trades,0)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt((r.profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.profit_factor||0}">${fmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td>
      <td class="num" data-val="${r.calmar||0}">${fmt(r.calmar)}</td>
      <td class="num" data-val="${r.max_drawdown_account||0}">${pct(r.max_drawdown_account)}</td>
      <td data-val="${r.basis||''}">${r.basis||''}</td>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,10))}</td>
    </tr>`;
  }).join('') + '</tbody>';
  const wrap = $('strategiesTable');
  wrap.innerHTML = '';
  wrap.appendChild(t);
  makeSortable(t);
}

function applyFilters() {
  state.query = $('q').value;
  state.status = $('status').value;
  renderStrategies();
}

/* ---------- strategy detail ---------- */
function openStrategy(name) {
  state.strategy = name;
  const canon = LAB.canonical.find(r => r.strategy === name);
  const allRuns = LAB.backtests.filter(r => r.strategy === name).sort((a,b) =>
    (b.run_time||'').localeCompare(a.run_time||''));
  const benches = LAB.benchmarks.filter(r => r.strategy === name);
  const hos = LAB.hyperopt.filter(r => r.strategy === name);
  const wfs = LAB.walkforward.filter(r => r.strategy === name);

  const head = $('detailHead');
  head.innerHTML = `
    <button class="btn" onclick="closeStrategy()">← Back</button>
    <div>
      <div class="detail-head">
        <span class="name">${esc(name)}</span>
        ${canon ? gradePill(canon.score.grade) : ''}
        ${statusPill(canon ? canon.status : '')}
        <span class="basis-badge">grade basis: ${canon ? canon.basis : '—'}</span>
      </div>
      <div class="hint">${canon ? esc((canon.notes||'') + (canon.notes?' · ':'')) : ''}${canon ? canon.score.pass_count+' pass, '+canon.score.warn_count+' warn, '+canon.score.fail_count+' fail' : ''}</div>
    </div>`;

  // metric cards
  const metrics = $('detailMetrics');
  metrics.innerHTML = (canon ? [
    ['Profit', fmt((canon.profit_total||0)*100,1)+'%', canon.profit_total>=0?'good':'bad'],
    ['Sortino', fmt(canon.sortino), ''], ['Calmar', fmt(canon.calmar), ''],
    ['Profit factor', fmt(canon.profit_factor), ''], ['Max drawdown', pct(canon.max_drawdown_account), ''],
    ['Win rate', pct(canon.winrate), ''], ['Trades', fmt(canon.total_trades,0), ''],
    ['Holding avg', canon.holding_avg_s ? fmt(canon.holding_avg_s/3600,1)+'h' : '—', ''],
  ].map(([k,v,c]) => `<div class="metric-card"><span class="mk">${k}</span><span class="mv ${c}">${v}</span></div>`).join('')
  : '<p class="hint">No backtest data for this strategy.</p>');

  // scorecard breakdown
  const sb = $('detailScorecard');
  if (canon) {
    sb.innerHTML = `<table><thead><tr><th>Metric</th><th class="num">Value</th>
      <th>Status</th><th class="num">Pass ≥</th><th class="num">Warn ≥</th></tr></thead><tbody>` +
      Object.entries(LAB.scorecard).map(([k, spec]) => {
        const v = canon[k];
        const g = canon.score.grades[k];
        let shown = fmt(v);
        if (k==='winrate'||k==='max_drawdown_account') shown = pct(v);
        if (k==='total_trades') shown = fmt(v,0);
        const passStr = k==='max_drawdown_account' ? `≤ ${pct(spec.pass)}` : (k==='total_trades' ? fmt(spec.pass,0) : fmt(spec.pass));
        const warnStr = k==='max_drawdown_account' ? `≤ ${pct(spec.warn)}` : (k==='total_trades' ? fmt(spec.warn,0) : fmt(spec.warn));
        return `<tr><td>${spec.label}</td><td class="num">${shown}</td>
          <td>${pill(g,g)}</td><td class="num">${passStr}</td><td class="num">${warnStr}</td></tr>`;
      }).join('') + '</tbody></table>';
  } else sb.innerHTML = '<p class="hint">No scorecard.</p>';

  // all runs
  const rt = document.createElement('table');
  rt.innerHTML = `<thead><tr><th>Run</th><th class="num">Grade</th><th class="num">Profit%</th>
    <th class="num">Trades</th><th class="num">PF</th><th class="num">Sortino</th>
    <th class="num">MaxDD</th><th>TF</th><th>Source</th></tr></thead><tbody>` +
    allRuns.map(r => `<tr>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,16))}</td>
      <td class="num" data-val="${r.score.grade}">${gradePill(r.score.grade)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt((r.profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.total_trades||0}">${fmt(r.total_trades,0)}</td>
      <td class="num" data-val="${r.profit_factor||0}">${fmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td>
      <td class="num" data-val="${r.max_drawdown_account||0}">${pct(r.max_drawdown_account)}</td>
      <td data-val="${r.timeframe||''}">${esc(r.timeframe||'')}</td>
      <td data-val="${r.source||''}" title="${esc(r.source)}">${esc((r.source||'').slice(-28))}</td>
    </tr>`).join('') + '</tbody>';
  const rtWrap = $('detailRuns');
  rtWrap.innerHTML = '';
  rtWrap.appendChild(rt);
  makeSortable(rt);

  // benchmark + hyperopt + wf
  const bt = benches.length ? benches.map(r => `<tr>
      <td>${esc((r.run_time||'').slice(0,10))}</td><td class="num">${gradePill(r.score.grade)}</td>
      <td class="num">${fmt((r.profit_total||0)*100,1)}%</td><td class="num">${fmt(r.sortino)}</td>
      <td class="num">${fmt(r.profit_factor)}</td></tr>`).join('')
    : '<tr><td colspan="5" class="hint">No benchmark runs.</td></tr>';
  $('detailBench').innerHTML = `<table><thead><tr><th>Run</th><th class="num">Grade</th><th class="num">Profit%</th><th class="num">Sortino</th><th class="num">PF</th></tr></thead><tbody>${bt}</tbody></table>`;

  const ht = hos.length ? hos.slice(0, 8).map(r => `<tr>
      <td>${esc((r.run_time||'').slice(0,10))}</td><td class="num">${fmt(r.epochs,0)}</td>
      <td class="num">${fmt(r.best_loss,2)}</td><td class="num">${fmt((r.best_profit_total||0)*100,1)}%</td>
      <td class="num">${fmt(r.best_sortino)}</td></tr>`).join('')
    : '<tr><td colspan="5" class="hint">No hyperopt runs.</td></tr>';
  $('detailHyperopt').innerHTML = `<table><thead><tr><th>Run</th><th class="num">Epochs</th><th class="num">Best loss</th><th class="num">Best profit</th><th class="num">Best sortino</th></tr></thead><tbody>${ht}</tbody></table>`;

  const wt = wfs.length ? wfs.map(r => `<tr>
      <td>${esc((r.run_id||'').slice(0,16))}</td><td class="num">${fmt(r.n_windows,0)}</td>
      <td class="num">${r.profitable_windows}/${r.n_windows}</td>
      <td class="num">${fmt(r.oos_profit_abs)}</td><td class="num">${fmt(r.avg_oos_sortino)}</td></tr>`).join('')
    : '<tr><td colspan="5" class="hint">No walk-forward runs.</td></tr>';
  $('detailWF').innerHTML = `<table><thead><tr><th>Run</th><th class="num">Windows</th><th class="num">Profitable</th><th class="num">OOS profit</th><th class="num">Avg sortino</th></tr></thead><tbody>${wt}</tbody></table>`;

  $('strategy-detail').classList.add('active');
  $('mainContent').classList.add('hidden');
  window.scrollTo(0, 0);
  updateAllTableScrolls();

  // trades: use latest run of this strategy
  const run = LAB.trade_runs.find(r => r.strategy === name);
  if (run) {
    const key = run.key;
    $('detailTradesStatus').textContent = `Loading trades for ${run.source} (${run.n_trades})…`;
    const load = (data) => {
      $('detailTradesStatus').textContent = '';
      // defer to next frame so the flex layout has applied and echarts sees real width
      requestAnimationFrame(() => {
        renderEquity(data.trades, 'detailEquityChart', '_detailEquityChart');
        renderProfitHist(data.trades, 'detailHistChart', '_detailHistChart');
        renderTradeTable(data, $('detailTradesTable'));
        // echarts can read a stale pre-layout size; force resize once laid out
        setTimeout(() => {
          if (window._detailEquityChart) window._detailEquityChart.resize();
          if (window._detailHistChart) window._detailHistChart.resize();
        }, 30);
      });
    };
    if (tradeCache[key]) load(tradeCache[key]);
    else if (LAB.embedded_trades && LAB.embedded_trades.key === key) { tradeCache[key] = LAB.embedded_trades; load(LAB.embedded_trades); }
    else fetch(`trades/${encodeURIComponent(key)}.json`).then(r => r.ok ? r.json() : null)
      .then(d => { if (d) { tradeCache[key] = d; load(d); } else $('detailTradesStatus').textContent = 'Trades unavailable (use lab.py serve).'; });
  } else $('detailTradesStatus').textContent = 'No trades for this strategy.';
}

function closeStrategy() {
  state.strategy = null;
  $('strategy-detail').classList.remove('active');
  $('mainContent').classList.remove('hidden');
  showTab(state.tab);
}

/* ---------- history ---------- */
function histOptions() {
  const sel = $('histSelect');
  const chosen = [...sel.options].filter(o => o.selected).map(o => o.value);
  if (chosen.includes('__top')) {
    return Object.entries(LAB.history).sort((a,b) => b[1].dates.length - a[1].dates.length)
      .slice(0, 8).map(([name]) => name);
  }
  if (chosen.includes('__all')) return Object.keys(LAB.history);
  return chosen.filter(v => !v.startsWith('__'));
}
function populateHistSelect() {
  const sel = $('histSelect');
  Object.entries(LAB.history).sort((a,b) => b[1].dates.length - a[1].dates.length)
    .forEach(([name]) => { const o = document.createElement('option'); o.value = name; o.textContent = name; sel.appendChild(o); });
}
function histSelectAll() { const s=$('histSelect'); [...s.options].forEach(o=>o.selected=true); renderHistory(); }
function histSelectTop() {
  const s=$('histSelect'); [...s.options].forEach(o=>o.selected=false);
  Object.entries(LAB.history).sort((a,b)=>b[1].dates.length-a[1].dates.length).slice(0,8)
    .forEach(([name])=>{ const o=[...s.options].find(x=>x.value===name); if(o)o.selected=true; });
  renderHistory();
}
function histClear() { const s=$('histSelect'); [...s.options].forEach(o=>o.selected=false); renderHistory(); }

function renderHistory() {
  const names = histOptions();
  const useLog = $('logScale').checked;
  const series = names.map(name => ({
    name, type: 'line', smooth: true, showSymbol: false,
    data: LAB.history[name].dates.map((d,i) => { let v = LAB.history[name].profit[i]; if (useLog && v<=0) v=null; return [d,v]; })
  }));
  const c1 = echarts.init($('historyChart'));
  c1.setOption({ backgroundColor:'transparent',
    tooltip:{trigger:'axis', valueFormatter:v=>(v*100).toFixed(1)+'%'},
    legend:{textStyle:{color:'#a89fc4'},type:'scroll',top:0},
    grid:{left:70,right:20,top:40,bottom:40},
    xAxis:{type:'category',axisLabel:{color:'#a89fc4'},axisLine:{lineStyle:{color:'#2f2745'}}},
    yAxis: useLog ? {type:'log',logBase:10,axisLabel:{color:'#a89fc4',formatter:v=>v===0?'0':(v*100).toFixed(0)+'%'},splitLine:{lineStyle:{color:'#241d36'}}}
                 : {type:'value',axisLabel:{color:'#a89fc4',formatter:v=>(v*100).toFixed(0)+'%'},splitLine:{lineStyle:{color:'#241d36'}}},
    dataZoom:[{type:'inside'},{type:'slider',height:14,bottom:6}], series });
  window._historyChart = c1;

  const s2 = names.map(name => ({
    name, type:'line', smooth:true, showSymbol:false,
    data: LAB.history[name].dates.map((d,i)=>[d, LAB.history[name].sortino[i]])
  }));
  const c2 = echarts.init($('sortinoChart'));
  c2.setOption({ backgroundColor:'transparent', tooltip:{trigger:'axis'},
    legend:{textStyle:{color:'#a89fc4'},type:'scroll',top:0},
    grid:{left:60,right:20,top:40,bottom:40},
    xAxis:{type:'category',axisLabel:{color:'#a89fc4'},axisLine:{lineStyle:{color:'#2f2745'}}},
    yAxis:{type:'value',axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}},
    dataZoom:[{type:'inside'},{type:'slider',height:14,bottom:6}], series: s2 });
  window._sortinoChart = c2;
}

/* ---------- benchmark ---------- */
function renderBenchmark() {
  const el = $('benchChart');
  const rows = LAB.benchmarks;
  if (!rows.length) { $('benchHint').textContent = 'No benchmark runs yet. Use the Lab tab to run one.'; el.style.display='none'; return; }
  $('benchHint').textContent = ''; el.style.display='';
  const metric = $('benchMetric').value;
  const useLog = $('benchLog').checked;
  const value = r => r[metric] === null || r[metric] === undefined ? 0 : Number(r[metric]);
  const c = echarts.init(el);
  c.setOption({ backgroundColor:'transparent', tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
    grid:{left:110,right:30,top:20,bottom:40},
    xAxis: useLog ? {type:'log',logBase:10,axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}}
                  : {type:'value',axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}},
    yAxis:{type:'category',data:rows.map(r=>r.strategy),axisLabel:{color:'#a89fc4'}},
    series:[{ name:metric, type:'bar',
      data: rows.map(r=>{ const v=value(r);
        let color = metric==='max_drawdown_account' ? (v<=0.2?'#6ee7a8':v<=0.4?'#fbbf24':'#f87171')
          : (v>=1?'#6ee7a8':v>=0.3?'#fbbf24':'#f87171');
        return {value:v,itemStyle:{color}}; }) }] });
  window._benchChart = c;
}

/* ---------- walk-forward ---------- */
function renderWalkForward() {
  const rows = LAB.walkforward;
  if (!rows.length) { $('wf').innerHTML = '<p class="hint">No walk-forward results ingested yet.</p>'; return; }
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr><th>Strategy</th><th class="num">Run</th><th class="num">Windows</th>
    <th class="num">Profitable</th><th class="num">OOS Trades</th><th class="num">OOS Profit</th>
    <th class="num">Avg Sortino</th><th class="num">Avg PF</th></tr></thead><tbody>` +
    rows.map(r => {
      const ratio = r.n_windows ? (r.profitable_windows / r.n_windows) : 0;
      return `<tr>
        <td>${stratLink(r.strategy)}</td>
        <td class="num" data-val="${r.run_id||''}">${esc((r.run_id||'').slice(0,16))}</td>
        <td class="num" data-val="${r.n_windows||0}">${fmt(r.n_windows,0)}</td>
        <td class="num" data-val="${ratio}">${pill(ratio>=0.6?'pass':ratio>=0.4?'warn':'fail', `${r.profitable_windows}/${r.n_windows}`)}</td>
        <td class="num" data-val="${r.oos_trades||0}">${fmt(r.oos_trades,0)}</td>
        <td class="num" data-val="${r.oos_profit_abs||0}">${fmt(r.oos_profit_abs)}</td>
        <td class="num" data-val="${r.avg_oos_sortino||0}">${fmt(r.avg_oos_sortino)}</td>
        <td class="num" data-val="${r.avg_oos_profit_factor||0}">${fmt(r.avg_oos_profit_factor)}</td>
      </tr>`;
    }).join('') + '</tbody>';
  const wrap = $('wf'); wrap.innerHTML=''; wrap.appendChild(t); makeSortable(t);
}

/* ---------- hyperopt ---------- */
function renderHyperopt() {
  const rows = LAB.hyperopt;
  if (!rows.length) { $('ho').innerHTML = '<p class="hint">No hyperopt results ingested yet.</p>'; return; }
  rows.sort((a,b)=>(b.epochs||0)-(a.epochs||0));
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr><th>Strategy</th><th class="num">Epochs</th><th class="num">Best Loss</th>
    <th class="num">Best Profit</th><th class="num">Best Sortino</th><th class="num">Best PF</th><th>Run</th></tr></thead><tbody>` +
    rows.slice(0,40).map(r => `<tr>
      <td>${stratLink(r.strategy)}</td>
      <td class="num" data-val="${r.epochs||0}">${fmt(r.epochs,0)}</td>
      <td class="num" data-val="${r.best_loss||0}">${fmt(r.best_loss,2)}</td>
      <td class="num" data-val="${r.best_profit_total||0}">${fmt((r.best_profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.best_sortino||0}">${fmt(r.best_sortino)}</td>
      <td class="num" data-val="${r.best_profit_factor||0}">${fmt(r.best_profit_factor)}</td>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,16))}</td>
    </tr>`).join('') + '</tbody>';
  const wrap = $('ho'); wrap.innerHTML=''; wrap.appendChild(t); makeSortable(t);
}

/* ---------- trades ---------- */
function populateTradeRunSelect() {
  const sel = $('tradeRun'); sel.innerHTML='';
  LAB.trade_runs.forEach(r => {
    const o = document.createElement('option'); o.value = r.key;
    o.textContent = `${r.strategy} — ${r.source} (${r.n_trades} trades${r.run_time?' · '+(r.run_time||'').slice(0,16):''})`;
    sel.appendChild(o);
  });
}
function loadTradeRun() {
  const sel = $('tradeRun'), status = $('tradeStatus');
  if (!sel.value) return;
  const key = sel.value;
  status.textContent = 'Loading…';
  if (tradeCache[key]) { renderTrades(tradeCache[key]); status.textContent=''; return; }
  if (LAB.embedded_trades && LAB.embedded_trades.key === key) {
    tradeCache[key] = LAB.embedded_trades; renderTrades(LAB.embedded_trades); status.textContent=''; return;
  }
  fetch(`trades/${encodeURIComponent(key)}.json`).then(r => r.ok ? r.json() : Promise.reject())
    .then(d => { tradeCache[key]=d; renderTrades(d); status.textContent=''; })
    .catch(() => { status.textContent = 'Could not load trades — open via lab.py serve.'; });
}
function renderTradesTab() { if (!LAB.trade_runs.length) { $('trades').innerHTML = '<p class="hint">No trades ingested.</p>'; return; } loadTradeRun(); }
function tradeSide(t) { return t.s ? 'short' : 'long'; }
function renderTrades(data) {
  renderEquity(data.trades);
  renderProfitHist(data.trades);
  renderTradeTable(data, $('tradesTable'));
}
function renderEquity(trades, elId, storeKey) {
  elId = elId || 'equityChart';
  storeKey = storeKey || '_equityChart';
  const c = echarts.init($(elId));
  let cum = 0;
  const points = [];
  trades.forEach(t => { cum += (t.pa||0); if (t.c) points.push([t.c, Math.round(cum*100)/100]); });
  c.setOption({ backgroundColor:'transparent', tooltip:{trigger:'axis',valueFormatter:v=>v.toLocaleString('en-US',{maximumFractionDigits:0})},
    grid:{left:70,right:20,top:30,bottom:40},
    xAxis:{type:'category',axisLabel:{color:'#a89fc4'},axisLine:{lineStyle:{color:'#2f2745'}}},
    yAxis:{type:'value',axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}},
    dataZoom:[{type:'inside'},{type:'slider',height:14,bottom:6}],
    series:[{name:'Cumulative profit',type:'line',showSymbol:false,data:points,lineStyle:{color:'#c4b5fd',width:2},areaStyle:{color:'rgba(196,181,253,0.12)'}}] });
  window[storeKey] = c;
  // echarts can read a stale size when the container just became visible
  if (c.getWidth() < 50) setTimeout(() => c.resize(), 50);
}
function renderProfitHist(trades, elId, storeKey) {
  elId = elId || 'profitHistChart';
  storeKey = storeKey || '_profitHistChart';
  const c = echarts.init($(elId));
  const profits = trades.map(t=>t.pr).filter(v=>v!==null&&v!==undefined);
  if (!profits.length) { c.clear(); return; }
  const min = Math.min(...profits), max = Math.max(...profits), bins = 40, width = (max-min)||1;
  const counts = new Array(bins).fill(0);
  profits.forEach(v => { let i = Math.floor((v-min)/width*bins); if (i===bins) i=bins-1; counts[i]++; });
  const labels = counts.map((_,i)=>{ const lo=min+i*width/bins, hi=lo+width/bins; return ((lo+hi)/2*100).toFixed(1)+'%'; });
  c.setOption({ backgroundColor:'transparent', tooltip:{trigger:'axis'},
    grid:{left:50,right:16,top:30,bottom:40},
    xAxis:{type:'category',data:labels,axisLabel:{color:'#a89fc4',rotate:45},axisLine:{lineStyle:{color:'#2f2745'}}},
    yAxis:{type:'value',axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}},
    series:[{name:'Trades',type:'bar',data:counts,itemStyle:{color:'#a78bfa'}}] });
  window[storeKey] = c;
  if (c.getWidth() < 50) setTimeout(() => c.resize(), 50);
}
function renderTradeTable(data, wrapEl) {
  const trades = data.trades || [];
  const rows = trades.slice(0, 500);
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr><th>Pair</th><th>Side</th><th>Enter tag</th><th>Exit reason</th>
    <th>Open</th><th>Close</th><th class="num">Open rate</th><th class="num">Close rate</th>
    <th class="num">Profit%</th><th class="num">Profit abs</th><th class="num">Stop loss</th>
    <th class="num">SL%</th><th class="num">Duration</th></tr></thead><tbody>` +
    rows.map(td => {
      const prof = (td.pr||0)*100;
      return `<tr>
        <td><b>${esc(td.p)}</b></td><td>${esc(tradeSide(td))}</td><td>${esc(td.t||'')}</td>
        <td>${esc(td.e||'')}</td>
        <td data-val="${td.o||''}">${esc((td.o||'').slice(0,16))}</td>
        <td data-val="${td.c||''}">${esc((td.c||'').slice(0,16))}</td>
        <td class="num" data-val="${td.or||0}">${fmt(td.or)}</td>
        <td class="num" data-val="${td.cr||0}">${fmt(td.cr)}</td>
        <td class="num" data-val="${td.pr||0}">${pill(prof>=0?'pass':'fail', prof.toFixed(2)+'%')}</td>
        <td class="num" data-val="${td.pa||0}">${fmt(td.pa)}</td>
        <td class="num" data-val="${td.sl||0}">${fmt(td.sl)}</td>
        <td class="num" data-val="${td.slr||0}">${fmt((td.slr||0)*100,1)}%</td>
        <td class="num" data-val="${td.d||0}">${td.d?Math.floor(td.d/3600)+'h'+Math.round((td.d%3600)/60)+'m':'—'}</td>
      </tr>`;
    }).join('') + '</tbody>';
  wrapEl.innerHTML = '';
  const hint = document.createElement('p'); hint.className='hint';
  hint.textContent = `Showing ${Math.min(500,trades.length)} of ${trades.length} trades for ${data.strategy}`;
  wrapEl.appendChild(hint); wrapEl.appendChild(t); makeSortable(t);
}

/* ---------- lab ---------- */
let jobTimer = null;
function pollJobs() {
  fetch('/api/jobs').then(r => r.json()).then(jobs => {
    const entries = Object.entries(jobs);
    const st = $('jobStatus');
    if (!entries.length) { st.innerHTML = 'Idle.'; return; }
    const lines = entries.slice(0, 4).map(([id, j]) => {
      const cls = j.status === 'done' ? 'pass' : j.status === 'error' ? 'fail' : 'warn';
      return `<div>${pill(cls, j.status)} <b>${esc(id)}</b> — ${esc(j.log.slice(-200))}</div>`;
    }).join('');
    st.innerHTML = lines;
    const running = entries.some(([,j]) => j.status === 'running');
    if (!running && jobTimer) { clearInterval(jobTimer); jobTimer = null; }
  }).catch(() => {});
}
function labRefresh() {
  $('jobStatus').innerHTML = 'Starting ingest + report…';
  fetch('/api/refresh', {method:'POST'}).then(r=>r.json()).then(() => {
    jobTimer = setInterval(() => { pollJobs(); }, 1500);
  });
}
function labReport() {
  $('jobStatus').innerHTML = 'Rebuilding report…';
  fetch('/api/report', {method:'POST'}).then(r=>r.json()).then(() => {
    jobTimer = setInterval(() => { pollJobs(); }, 1500);
  });
}
function labBench() {
  const strategies = $('benchStrategies').value.split(',').map(s=>s.trim()).filter(Boolean);
  const body = { timerange: $('benchRange').value, timeframe: $('benchTf').value, strategies };
  $('jobStatus').innerHTML = 'Running benchmark…';
  fetch('/api/bench', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r=>r.json()).then(() => { jobTimer = setInterval(() => { pollJobs(); }, 1500); });
}
function renderLab() {
  // strategy status editor
  fetch('/api/strategies').then(r=>r.json()).then(list => {
    const wrap = $('strategyEditor');
    if (!list.length) { wrap.innerHTML = '<p class="hint">No strategies registered.</p>'; return; }
    const t = document.createElement('table');
    t.innerHTML = `<thead><tr><th>Strategy</th><th>Status</th><th class="num">Backtests</th><th class="num">Trades</th><th>Notes</th><th></th></tr></thead><tbody>` +
      list.map(s => `<tr>
        <td><b>${esc(s.name)}</b></td>
        <td><select class="statusSel ${esc(s.status||'active')}" data-name="${esc(s.name)}" onchange="this.className='statusSel '+this.value">
            ${['active','experimental','retired'].map(o=>`<option ${s.status===o?'selected':''}>${o}</option>`).join('')}
          </select></td>
        <td class="num">${fmt(s.n_backtests,0)}</td>
        <td class="num">${fmt(s.n_trades,0)}</td>
        <td><input class="notesInput" data-name="${esc(s.name)}" value="${esc(s.notes||'')}" placeholder="notes"></td>
        <td><button class="btn compact" onclick="saveStrategy('${esc(s.name)}')">Save</button></td>
      </tr>`).join('') + '</tbody>';
    wrap.innerHTML = '';
    wrap.appendChild(t);
    makeSortable(t);
  });
}
function saveStrategy(name) {
  const sel = document.querySelector(`.statusSel[data-name="${CSS.escape(name)}"]`);
  const notes = document.querySelector(`.notesInput[data-name="${CSS.escape(name)}"]`);
  const body = { name, status: sel ? sel.value : 'active', notes: notes ? notes.value : '' };
  fetch('/api/strategies', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r=>r.json()).then(() => { $('jobStatus').textContent = `Saved ${name} -> ${body.status}`; })
    .catch(e => $('jobStatus').textContent = 'Save failed: ' + e);
}

/* ---------- init ---------- */
function init() {
  document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  populateHistSelect();
  populateTradeRunSelect();
  renderDashboard();
  renderLab();

  // resize charts when the viewport changes
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      ['_historyChart','_sortinoChart','_benchChart','_equityChart','_profitHistChart',
       '_detailEquityChart','_detailHistChart'].forEach(k => {
        if (window[k]) window[k].resize();
      });
    }, 150);
  });
}
"""

# --------------------------------------------------------------- html template

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Lab — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<style>{css}</style>
</head>
<body>
<header>
  <div class="logo"><span class="dot"></span>
    <div>
      <h1>Strategy Lab</h1>
      <div class="sub">freqtrade strategy overview · {generated}</div>
    </div>
  </div>
</header>

<div class="tabs">
  <button data-tab="dashboard" class="active">Dashboard</button>
  <button data-tab="strategies">Strategies</button>
  <button data-tab="history">History</button>
  <button data-tab="benchmark">Benchmark</button>
  <button data-tab="walkforward">Walk-Forward</button>
  <button data-tab="hyperopt">Hyperopt</button>
  <button data-tab="trades">Trades</button>
  <button data-tab="lab">Lab</button>
</div>

<main id="mainContent">

  <!-- ============ DASHBOARD ============ -->
  <div class="tab active" id="tab-dashboard">
    <section>
      <div class="stats">
        <div class="stat"><span class="k">Strategies</span><span class="v">{n_strategies}</span></div>
        <div class="stat"><span class="k">Backtest runs</span><span class="v">{n_backtests}</span></div>
        <div class="stat"><span class="k">Hyperopt runs</span><span class="v">{n_hyperopt}</span></div>
        <div class="stat"><span class="k">Walk-forward runs</span><span class="v">{n_walkforward}</span></div>
        <div class="stat"><span class="k">Benchmark runs</span><span class="v">{n_benchmarks}</span></div>
        <div class="stat"><span class="k">Trades</span><span class="v">{n_trades}</span></div>
      </div>
    </section>

    <section>
      <div class="section-head"><h2>How grades are calculated</h2>
        <span class="hint">each metric → pass / warn / fail against fixed thresholds · grade from those</span></div>
      <div class="grade-grid">
        <div class="grade-cell"><span class="big" style="color:var(--good)">A</span><div class="hint">5+ pass, 0 fail</div></div>
        <div class="grade-cell"><span class="big" style="color:var(--lavender)">B</span><div class="hint">3+ pass</div></div>
        <div class="grade-cell"><span class="big" style="color:var(--warn)">C</span><div class="hint">1 fail</div></div>
        <div class="grade-cell"><span class="big" style="color:var(--bad)">D</span><div class="hint">2+ fail</div></div>
      </div>
      <div class="card">
        <div style="display:flex;flex-wrap:wrap;gap:18px;font-size:13px;color:var(--text-dim)">
          <div><b style="color:var(--lavender)">Sortino</b> ≥ 1.0 pass · ≥ 0.3 warn</div>
          <div><b style="color:var(--lavender)">Calmar</b> ≥ 1.0 pass · ≥ 0.3 warn</div>
          <div><b style="color:var(--lavender)">Profit factor</b> ≥ 1.2 pass · ≥ 1.0 warn</div>
          <div><b style="color:var(--lavender)">Max drawdown</b> ≤ 20% pass · ≤ 40% warn</div>
          <div><b style="color:var(--lavender)">Win rate</b> ≥ 45% pass · ≥ 35% warn</div>
          <div><b style="color:var(--lavender)">Trades</b> ≥ 100 pass · ≥ 30 warn</div>
        </div>
        <div class="hint">Each strategy shows ONE grade from its most recent benchmark run (else latest backtest). Click a strategy for the full breakdown and every run.</div>
      </div>
    </section>

    <section>
      <div class="section-head"><h2>What to improve next</h2>
        <span class="hint">strategies below grade A · click to open</span></div>
      <div class="metric-row" id="improveList"></div>
    </section>

    <section>
      <div class="section-head"><h2>All strategies</h2>
        <span class="hint">click a name for details · sort by clicking headers</span></div>
      <div class="table-wrap"><div id="dashboardTable"></div></div>
    </section>
  </div>

  <!-- ============ STRATEGIES ============ -->
  <div class="tab" id="tab-strategies">
    <section>
      <div class="section-head"><h2>Strategies</h2>
        <span class="hint">registry + latest results per strategy</span></div>
      <div class="controls">
        <input id="q" type="text" placeholder="Filter strategy..." oninput="applyFilters()">
        <select id="status" onchange="applyFilters()">
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="experimental">Experimental</option>
          <option value="retired">Retired</option>
        </select>
      </div>
      <div class="table-wrap"><div id="strategiesTable"></div></div>
    </section>
  </div>

  <!-- ============ HISTORY ============ -->
  <div class="tab" id="tab-history">
    <section>
      <div class="section-head"><h2>History</h2>
        <span class="hint">profit &amp; sortino per strategy over all runs</span></div>
      <div class="controls">
        <label><input type="checkbox" id="logScale" onchange="renderHistory()"> Profit % (log scale)</label>
        <select id="histSelect" size="1" multiple style="min-width:260px" onchange="renderHistory()">
          <option value="__top" selected>Top by run count</option>
          <option value="__all">All</option>
        </select>
        <button class="btn" onclick="histSelectAll()">Select all</button>
        <button class="btn" onclick="histSelectTop()">Top 8</button>
        <button class="btn" onclick="histClear()">Clear</button>
      </div>
      <div class="charts">
        <div class="chart-box"><div id="historyChart" class="chart"></div></div>
        <div class="chart-box"><div id="sortinoChart" class="chart"></div></div>
      </div>
    </section>
  </div>

  <!-- ============ BENCHMARK ============ -->
  <div class="tab" id="tab-benchmark">
    <section>
      <div class="section-head"><h2>Benchmark (apples-to-apples)</h2>
        <span class="hint">every strategy on the shared benchmark config</span></div>
      <div class="controls">
        <label>Metric:
          <select id="benchMetric" onchange="renderBenchmark()">
            <option value="sortino">Sortino</option>
            <option value="profit_total">Total Profit</option>
            <option value="calmar">Calmar</option>
            <option value="profit_factor">Profit Factor</option>
            <option value="max_drawdown_account">Max Drawdown</option>
          </select>
        </label>
        <label><input type="checkbox" id="benchLog" onchange="renderBenchmark()"> Log scale</label>
      </div>
      <div class="chart-box"><p id="benchHint" class="hint"></p><div id="benchChart" class="chart" style="height:380px"></div></div>
    </section>
  </div>

  <!-- ============ WALK-FORWARD ============ -->
  <div class="tab" id="tab-walkforward">
    <section>
      <div class="section-head"><h2>Walk-Forward (out-of-sample)</h2>
        <span class="hint">profitable windows / total = OOS consistency</span></div>
      <div class="table-wrap"><div id="wf"></div></div>
    </section>
  </div>

  <!-- ============ HYPEROPT ============ -->
  <div class="tab" id="tab-hyperopt">
    <section>
      <div class="section-head"><h2>Hyperopt</h2>
        <span class="hint">best epoch per run</span></div>
      <div class="table-wrap"><div id="ho"></div></div>
    </section>
  </div>

  <!-- ============ TRADES ============ -->
  <div class="tab" id="tab-trades">
    <section>
      <div class="section-head"><h2>Trades</h2>
        <span class="hint">equity curve, profit distribution &amp; per-trade detail (SL/TP, exit reason). Use <b>lab.py serve</b> to browse all runs.</span></div>
      <div class="controls">
        <label>Run:
          <select id="tradeRun" onchange="loadTradeRun()" style="min-width:360px"></select>
        </label>
        <button class="btn" onclick="loadTradeRun()">Load</button>
        <span id="tradeStatus" class="hint"></span>
      </div>
      <div class="charts">
        <div class="chart-box"><div id="equityChart" class="chart"></div></div>
        <div class="chart-box"><div id="profitHistChart" class="chart"></div></div>
      </div>
      <div class="table-wrap"><div id="tradesTable"></div></div>
    </section>
  </div>

  <!-- ============ LAB ============ -->
  <div class="tab" id="tab-lab">
    <section>
      <div class="section-head"><h2>Lab</h2>
        <span class="hint">run everything from here — requires the web server (lab.py serve)</span></div>
      <div class="card">
        <div class="controls">
          <button class="btn primary" onclick="labRefresh()">↻ Refresh data</button>
          <button class="btn" onclick="labReport()">Rebuild report</button>
          <button class="btn" onclick="labBench()">Run benchmark</button>
          <label>Strategies: <input id="benchStrategies" type="text" placeholder="comma separated (empty = all)" style="min-width:220px"></label>
          <label>Range: <input id="benchRange" type="text" value="20230101-20240101" style="width:150px"></label>
          <label>TF: <input id="benchTf" type="text" value="5m" style="width:70px"></label>
        </div>
        <div id="jobStatus" class="hint">Idle.</div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Strategy status</h2>
        <span class="hint">active / experimental / retired + notes (stored in DB)</span></div>
      <div class="table-wrap"><div id="strategyEditor"></div></div>
    </section>
  </div>

</main>

<!-- ============ STRATEGY DETAIL ============ -->
<main id="strategy-detail">
  <section>
    <div id="detailHead"></div>
  </section>
  <section>
    <div class="section-head"><h2>Latest run</h2></div>
    <div class="metric-row" id="detailMetrics"></div>
  </section>
  <section>
    <div class="section-head"><h2>Scorecard breakdown</h2>
      <span class="hint">why this grade — each metric vs its threshold</span></div>
    <div class="table-wrap"><div id="detailScorecard"></div></div>
  </section>
  <section>
    <div class="section-head"><h2>All backtest runs</h2></div>
    <div class="table-wrap"><div id="detailRuns"></div></div>
  </section>
  <section>
    <div class="section-head"><h2>Benchmark runs</h2></div>
    <div class="table-wrap"><div id="detailBench"></div></div>
  </section>
  <section>
    <div class="section-head"><h2>Hyperopt runs</h2></div>
    <div class="table-wrap"><div id="detailHyperopt"></div></div>
  </section>
  <section>
    <div class="section-head"><h2>Walk-forward runs</h2></div>
    <div class="table-wrap"><div id="detailWF"></div></div>
  </section>
  <section>
    <div class="section-head"><h2>Latest trades</h2><span class="hint" id="detailTradesStatus"></span></div>
    <div class="charts">
      <div class="chart-box"><div id="detailEquityChart" class="chart"></div></div>
      <div class="chart-box"><div id="detailHistChart" class="chart"></div></div>
    </div>
    <div class="table-wrap"><div id="detailTradesTable"></div></div>
  </section>
</main>

<footer>Strategy Lab · results.db → dashboard.html · ingest_results.py · benchmark_runner.py · build_report.py · server.py</footer>

<script>
const LAB = {data_placeholder};
{js}
init();
showTab('dashboard');
</script>
</body>
</html>
"""


def build_html(data: dict, conn: sqlite3.Connection | None = None) -> str:
    canonical = canonical_per_strategy(data)
    history = history_series(data)
    benchmarks = benchmark_bars(data)
    from datetime import datetime

    # embed the most recent run's trades so the section works without a server
    embedded_trades = None
    if conn is not None:
        runs = trade_runs(conn)
        if runs:
            top = runs[0]
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM trades WHERE strategy=? AND source=?
                   ORDER BY close_date LIMIT 2000""",
                (top["strategy"], top["source"]),
            ).fetchall()
            embedded_trades = {
                "key": top["key"],
                "strategy": top["strategy"],
                "source": top["source"],
                "n": top["n_trades"],
                "trades": [compact_trade(dict(r)) for r in rows],
            }

    lab = {
        "canonical": canonical,
        "latest": canonical,
        "backtests": data["backtests"],
        "benchmarks": data["benchmarks"],
        "history": history,
        "walkforward": data["walkforward"],
        "hyperopt": data["hyperopt"],
        "strategies": data["strategies"],
        "trade_runs": data["trade_runs"],
        "embedded_trades": embedded_trades,
        "scorecard": {k: {kk: vv for kk, vv in v.items() if kk != "label"} for k, v in SCORECARD.items()},
    }

    html = HTML_TEMPLATE
    html = html.replace("{css}", CSS)
    html = html.replace("{js}", JS)
    html = html.replace("{data_placeholder}", json.dumps(lab, default=str))
    html = html.replace("{generated}", datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = html.replace("{n_strategies}", str(len({r["strategy"] for r in data["backtests"]})))
    html = html.replace("{n_backtests}", str(len(data["backtests"])))
    html = html.replace("{n_hyperopt}", str(len(data["hyperopt"])))
    html = html.replace("{n_walkforward}", str(len(data["walkforward"])))
    html = html.replace("{n_benchmarks}", str(len(data["benchmarks"])))
    html = html.replace("{n_trades}", str(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]) if conn else "0")
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description="Build dashboard.html from results.db")
    ap.add_argument("--db", default=str(ANALYSIS_DIR / "results.db"))
    ap.add_argument("--out", default=str(ANALYSIS_DIR / "dashboard.html"))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    data = load_data(conn)

    n_files = export_trade_files(conn, ANALYSIS_DIR)
    print(f"Trade files exported: {n_files}")

    html = build_html(data, conn)
    conn.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Dashboard written to {args.out} ({Path(args.out).stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
