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

from datetime import datetime  # noqa: E402

# ---------------------------------------------------------------- scorecard ---

SCORECARD = {
    "sortino": {"pass": 1.0, "warn": 0.3, "higher_is_better": True, "label": "Sortino"},
    "calmar": {"pass": 1.0, "warn": 0.3, "higher_is_better": True, "label": "Calmar"},
    "profit_factor": {"pass": 1.2, "warn": 1.0, "higher_is_better": True, "label": "Profit factor"},
    "max_drawdown_account": {"pass": 0.2, "warn": 0.4, "higher_is_better": False, "label": "Max drawdown"},
    "winrate": {"pass": 0.45, "warn": 0.35, "higher_is_better": True, "label": "Win rate"},
    "total_trades": {"pass": 100, "warn": 30, "higher_is_better": True, "label": "Trades"},
    "worst_trade": {"pass": -0.08, "warn": -0.15, "higher_is_better": True, "label": "Worst trade"},
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


# ------------------------------------------------------- derived + recommendations ---

def _compute_derived(trades: list[dict]) -> dict:
    """Compute streaks, payoff, MFE/MAE, capture from a list of trades sorted by close_date."""
    if not trades:
        return {
            "max_win_streak": None, "max_loss_streak": None,
            "avg_mfe": None, "avg_mae": None,
            "payoff_ratio": None, "avg_win": None, "avg_loss": None,
            "avg_profit": None, "capture_ratio": None,
            "worst_trade": None, "worst_trade_pair": None,
        }
    max_win = max_loss = cur_win = cur_loss = 0
    win_vals: list[float] = []
    loss_vals: list[float] = []
    mfe_vals: list[float] = []
    mae_vals: list[float] = []
    profit_vals: list[float] = []
    worst_pr: float | None = None
    worst_pair: str | None = None
    for t in trades:
        pr = t.get("profit_ratio")
        try:
            pr = float(pr) if pr is not None else 0.0
        except (TypeError, ValueError):
            pr = 0.0
        profit_vals.append(pr)
        if worst_pr is None or pr < worst_pr:
            worst_pr = pr
            worst_pair = t.get("pair")
        is_win = pr > 0
        if is_win:
            cur_win += 1
            cur_loss = 0
            max_win = max(max_win, cur_win)
            win_vals.append(pr)
        else:
            cur_loss += 1
            cur_win = 0
            max_loss = max(max_loss, cur_loss)
            loss_vals.append(pr)
        open_r = t.get("open_rate")
        max_r = t.get("max_rate")
        min_r = t.get("min_rate")
        is_short = t.get("is_short")
        try:
            open_r = float(open_r) if open_r is not None else None
            max_r = float(max_r) if max_r is not None else None
            min_r = float(min_r) if min_r is not None else None
        except (TypeError, ValueError):
            continue
        if open_r and max_r and min_r and open_r != 0:
            if is_short:
                mfe = (open_r - min_r) / open_r
                mae = (max_r - open_r) / open_r
            else:
                mfe = (max_r - open_r) / open_r
                mae = (open_r - min_r) / open_r
            # clamp to reasonable 0..5
            if -1 < mfe < 5 and -1 < mae < 5:
                mfe_vals.append(mfe)
                mae_vals.append(mae)
    avg_mfe = sum(mfe_vals) / len(mfe_vals) if mfe_vals else None
    avg_mae = sum(mae_vals) / len(mae_vals) if mae_vals else None
    avg_win = sum(win_vals) / len(win_vals) if win_vals else None
    avg_loss = sum(loss_vals) / len(loss_vals) if loss_vals else None
    avg_profit = sum(profit_vals) / len(profit_vals) if profit_vals else None
    payoff = abs(avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0) else None
    capture = None
    if avg_profit is not None and avg_mfe not in (None, 0):
        try:
            capture = avg_profit / avg_mfe
        except ZeroDivisionError:
            capture = None
    return {
        "max_win_streak": max_win if trades else None,
        "max_loss_streak": max_loss if trades else None,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "payoff_ratio": payoff,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_profit": avg_profit,
        "capture_ratio": capture,
        "worst_trade": worst_pr if trades else None,
        "worst_trade_pair": worst_pair,
    }


def _enrich_with_derived(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Attach derived metrics (streaks, MFE/MAE, worst trade) in-place (keyed by strategy/source)."""
    if not rows:
        return
    # Build map (strategy, source) -> list[trade dict]
    conn.row_factory = sqlite3.Row
    # Fetch all trades once, then group. 530k rows is fine (<10MB).
    try:
        all_trades = conn.execute(
            """SELECT strategy, source, pair, profit_ratio, open_rate, max_rate, min_rate, is_short, trade_duration, close_date
               FROM trades ORDER BY strategy, source, close_date"""
        ).fetchall()
    except sqlite3.OperationalError:
        all_trades = []
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in all_trades:
        key = (r["strategy"], r["source"])
        grouped.setdefault(key, []).append(dict(r))
    for row in rows:
        key = (row.get("strategy"), row.get("source"))
        trades = grouped.get(key, [])
        derived = _compute_derived(trades)
        row.update(derived)


def build_recommendations(row: dict) -> list[dict]:
    """Generic actionable recommendations based on graded + derived metrics."""
    recs: list[dict] = []

    def add(level: str, title: str, detail: str):
        recs.append({"level": level, "title": title, "detail": detail})

    total = row.get("total_trades")
    pf = row.get("profit_factor")
    winrate = row.get("winrate")
    dd = row.get("max_drawdown_account")
    sortino = row.get("sortino")
    calmar = row.get("calmar")
    expectancy = row.get("expectancy")
    sqn = row.get("sqn")
    tpd = row.get("trades_per_day")
    holding = row.get("holding_avg_s")
    wh = row.get("winner_holding_avg_s")
    lh = row.get("loser_holding_avg_s")
    max_loss_streak = row.get("max_loss_streak")
    payoff = row.get("payoff_ratio")
    avg_mfe = row.get("avg_mfe")
    avg_mae = row.get("avg_mae")
    capture = row.get("capture_ratio")
    timeframe = row.get("timeframe")

    # 1. Statistical significance
    if total is not None:
        if total < 30:
            add("fail", "Too few trades", "n<30 is not significant. Widen entry, lower filters, or extend timerange (>6 months).")
        elif total < 100:
            add("warn", "Few trades", "n<100 — results are fragile. Test longer period or more pairs before live.")

    # 2. Profit factor
    if pf is not None:
        if pf < 1.0:
            add("fail", "Losing after fees", f"PF {pf:.2f} <1.0 — strategy destroys capital. Tighten exits / avoid noisy pairs.")
        elif pf < 1.2:
            add("warn", "Thin edge", f"PF {pf:.2f} <1.2 — barely profitable after slippage. Improve exit.")

    # 3. Winrate / payoff interaction
    if winrate is not None and payoff is not None:
        if winrate > 0.70 and payoff < 1.0:
            add("warn", "High WR but payoff <1", f"WR {winrate*100:.1f}% looks good but avg win {(row.get('avg_win') or 0)*100:.2f}% < avg loss {abs((row.get('avg_loss') or 0)*100):.2f}%. Winners tiny — loosen ROI or trailing.")
        elif winrate < 0.35 and (pf or 0) < 1.2:
            add("warn", "Low winrate", f"WR {winrate*100:.1f}% — entry is near coin-flip. Add trend/volume filter.")
    elif winrate is not None and winrate < 0.35:
        add("warn", "Low winrate", f"WR {winrate*100:.1f}% — needs filter improvement.")

    # 4. Drawdown
    if dd is not None:
        if dd > 0.40:
            add("fail", "Drawdown too high", f"MaxDD {dd*100:.1f}% >40% — position sizing / stop is broken. Reduce stake, add max-drawdown pause.")
        elif dd > 0.20:
            add("warn", "High drawdown", f"MaxDD {dd*100:.1f}% >20% — consider tighter stop or reducing max_open_trades.")

    # 5. Risk-adjusted
    if sortino is not None and sortino < 0.3:
        add("warn", "Poor Sortino", f"Sortino {sortino:.2f} <0.3 — return does not compensate for downside volatility.")
    if calmar is not None and calmar < 0.3:
        add("warn", "Poor Calmar", f"Calmar {calmar:.2f} <0.3 — return vs drawdown is weak.")
    if row.get("sortino") is not None and row.get("calmar") is not None and sortino < 0.3 and calmar < 0.3:
        add("fail", "Risk-adjusted weak", "Both Sortino & Calmar <0.3 — edge doesn't survive volatility. Likely overfit.")

    # 6. Expectancy / SQN
    if expectancy is not None and expectancy <= 0:
        add("fail", "Negative expectancy", f"Expectancy {expectancy:.4f} ≤0 — loses per trade on average. Overfit or fee drag.")
    if sqn is not None:
        if sqn < 1.0:
            add("warn", "Low SQN", f"SQN {sqn:.2f} <1.0 — system quality poor (Van Tharp <1.6 = poor).")
        elif sqn < 1.6:
            add("info", "Mediocre SQN", f"SQN {sqn:.2f} <1.6 — average system, needs more edge.")

    # 7. Activity
    if tpd is not None:
        if tpd > 8:
            add("warn", "Overtrading", f"{tpd:.1f} trades/day — fees/slippage & delisting risk. Add cooldown / filter.")
        elif tpd < 0.2:
            add("info", "Low activity", f"{tpd:.2f} trades/day — may miss regimes. Test more pairs or lower timeframe.")

    # 8. Holding time
    if holding is not None and timeframe:
        # 5m -> expected holding hours, if >48h warn
        if timeframe == "5m" and holding > 172800:
            add("info", "Holding >> timeframe", f"Avg holding {holding/3600:.1f}h on 5m — mismatch. Consider higher TF or review exit.")
        if timeframe == "1d" and holding and holding < 86400:
            add("info", "Short holding on daily", "Avg hold <1d on 1d TF — noisy.")

    # 9. Winner vs loser holding
    if wh is not None and lh is not None and wh and lh:
        if lh > wh * 2:
            add("warn", "Holding losers too long", f"Losers {lh/3600:.1f}h vs winners {wh/3600:.1f}h — loss aversion. Add time-stop or tighten SL.")
        elif wh > lh * 3:
            add("info", "Winners held long", "Winners 3× longer than losers — good, but check trailing is not too loose.")

    # 10. Loss streak
    if max_loss_streak is not None:
        if max_loss_streak >= 8:
            add("fail", f"Loss streak {max_loss_streak}", "8+ consecutive losses — sizing risk. Add regime filter / pause after N losses.")
        elif max_loss_streak >= 5:
            add("warn", f"Loss streak {max_loss_streak}", "5+ consecutive losses — check if streak clusters in bear/bull regimes.")

    # 11. Payoff
    if payoff is not None:
        if payoff < 1.0:
            add("warn", f"Payoff {payoff:.2f} <1", f"Avg win {(row.get('avg_win') or 0)*100:.2f}% < |avg loss| {abs((row.get('avg_loss') or 0)*100):.2f}% — improve R:R.")
        elif payoff > 3 and (winrate or 0) < 0.40:
            add("info", "Lottery payoff", f"Payoff {payoff:.2f} with WR {(winrate or 0)*100:.1f}% — high variance, needs many trades to converge.")

    # 12. MFE capture
    if capture is not None and avg_mfe is not None:
        if capture < 0.20:
            add("warn", f"Low capture {capture*100:.0f}% of MFE", f"Avg profit {(row.get('avg_profit') or 0)*100:.2f}% vs avg MFE {avg_mfe*100:.2f}% — exits too early. Loosen ROI/trailing.")
        elif capture < 0.35 and (payoff or 0) < 1.5:
            add("info", "Leaving money on table", f"Capturing only {capture*100:.0f}% of MFE — test trailing stop.")

    # 13. MAE vs MFE — stop placement hint
    if avg_mae is not None and avg_mfe is not None:
        if avg_mae > avg_mfe * 0.9:
            add("warn", "Adverse ≈ favorable", f"Avg MAE {avg_mae*100:.2f}% ≈ MFE {avg_mfe*100:.2f}% — entries are tossed, no edge.")

    # 14. Outlier single-trade loss
    worst_trade = row.get("worst_trade")
    if worst_trade is not None:
        wpair = row.get("worst_trade_pair") or "?"
        wpct = abs(worst_trade) * 100
        if worst_trade <= -0.50:
            add("fail", f"Outlier loss −{wpct:.0f}%",
                f"Worst trade {worst_trade*100:.1f}% on {wpair} — a single trade wiped out ~{wpct:.0f}% of stake. Stop/sizing broken; cap risk per trade.")
        elif worst_trade <= -0.15:
            add("warn", f"Large single loss −{wpct:.0f}%",
                f"Worst trade {worst_trade*100:.1f}% on {wpair} — one outlier distorts the grade. Tighten SL or reduce stake on that pair.")

    # 15. Positive but fragile
    if not recs and row.get("score", {}).get("grade") == "A":
        add("good", "Well balanced", "5+ metrics pass, no fail. Check walk-forward OOS next.")

    # Cap to 8 most severe
    order = {"fail": 0, "warn": 1, "info": 2, "good": 3}
    recs.sort(key=lambda r: order.get(r["level"], 9))
    return recs[:8]


# ------------------------------------------------------------------- queries ---

def load_data(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row

    def score_and_recommend(rows):
        out = []
        for r in rows:
            d = dict(r)
            d["score"] = score_strategy(d)
            d["recommendations"] = build_recommendations(d)
            out.append(d)
        return out

    backtests = conn.execute(
        """SELECT b.*, s.status, s.notes
           FROM backtests b
           LEFT JOIN strategies s ON s.name = b.strategy
           ORDER BY b.strategy, b.run_time"""
    ).fetchall()
    benchmarks = conn.execute(
        "SELECT * FROM benchmarks ORDER BY strategy, run_time"
    ).fetchall()
    # derived metrics must be attached before scoring so worst_trade feeds the grade
    backtests = [dict(r) for r in backtests]
    benchmarks = [dict(r) for r in benchmarks]
    _enrich_with_derived(conn, backtests)
    _enrich_with_derived(conn, benchmarks)
    backtests = score_and_recommend(backtests)
    benchmarks = score_and_recommend(benchmarks)
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


def collect_extras(conn: sqlite3.Connection | None) -> dict:
    """Provenance data for the UI: deduped configs, current-code hashes, snapshot index.

    configs       {hash: parsed config}   – embedded once per unique config
    current_code  {strategy: sha1}        – hash of the .py at report build time
    snapshot_paths{hash: {path, mtime}}   – where/when a snapshot was captured
    """
    extras = {"configs": {}, "current_code": {}, "snapshot_paths": {}}
    if conn is None:
        return extras
    conn.row_factory = sqlite3.Row
    try:
        for r in conn.execute("SELECT hash, size FROM configs"):
            extras["configs"][r["hash"]] = {"__size": r["size"]}
        # parse lazily per hash below to keep memory bounded
        for h in list(extras["configs"]):
            raw = conn.execute("SELECT config_json FROM configs WHERE hash=?", (h,)).fetchone()[0]
            try:
                extras["configs"][h] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                extras["configs"][h] = {"_raw": str(raw)[:20000] if raw else None}
    except sqlite3.OperationalError:
        pass
    try:
        # current file hashes: recompute from disk so offline staleness badges work
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ft_metrics import find_strategy_file, sha1_text

        user_data = ANALYSIS_DIR.parent
        names = {r["strategy"] for r in conn.execute(
            "SELECT DISTINCT name AS strategy FROM strategies")}
        for name in sorted(names):
            f = find_strategy_file(user_data, name)
            if f is None:
                continue
            try:
                extras["current_code"][name] = sha1_text(f.read_text(encoding="utf-8"))
            except OSError:
                continue
    except sqlite3.OperationalError:
        pass
    try:
        for r in conn.execute(
            "SELECT hash, path, mtime FROM strategy_snapshots"
        ):
            extras["snapshot_paths"][r["hash"]] = {
                "path": r["path"],
                "mtime": datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M") if r["mtime"] else None,
            }
    except (sqlite3.OperationalError, ValueError, OSError, TypeError):
        pass
    return extras


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

/* top scrollbar under the table header (header strip stays put, synced to the body scroll) */
.table-stack { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; min-width: 0; }
.table-stack .thead-scroll { overflow-x: auto; overflow-y: hidden; background: var(--bg-soft);
  scrollbar-width: thin; scrollbar-color: #3a3254 var(--bg-soft); overscroll-behavior-inline: contain;
  -webkit-overflow-scrolling: touch; border-bottom: 1px solid var(--border); }
.table-stack .thead-scroll::-webkit-scrollbar { height: 10px; }
.table-stack .thead-scroll::-webkit-scrollbar-track { background: var(--bg-soft); }
.table-stack .thead-scroll::-webkit-scrollbar-thumb { background: #3a3254; border-radius: 8px; border: 2px solid var(--bg-soft); }
.table-stack .thead-scroll::-webkit-scrollbar-thumb:hover { background: var(--lavender-ink); }
.table-stack .table-wrap { border: 0; border-radius: 0; }
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

/* lab date range */
input[type="date"] { color-scheme: dark; }
.daterange { display: flex; align-items: center; background: var(--bg-soft);
  border: 1px solid var(--border); border-radius: 8px;
  transition: border-color .15s ease, box-shadow .15s ease; }

.daterange:hover { border-color: #3d3358; }
.daterange:focus-within { border-color: var(--lavender-ink);
  box-shadow: 0 0 0 3px rgba(109, 91, 208, .18); }
.daterange > label { display: flex; align-items: center; gap: 6px; color: var(--text-dim);
  font-size: 13px; padding: 0 2px 0 10px; white-space: nowrap; cursor: pointer; }
.daterange input[type="date"] { background: transparent; border: 0; color: var(--text);
  padding: 7px 2px 7px 0; width: 128px; font-family: inherit; font-size: 13px; outline: none; }
.daterange input[type="date"]::-webkit-calendar-picker-indicator { cursor: pointer; opacity: .6;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a89fc4' stroke-width='2' stroke-linecap='round'%3E%3Crect x='3' y='5' width='18' height='16' rx='2'/%3E%3Cpath d='M16 3v4M8 3v4M3 11h18'/%3E%3C/svg%3E"); }
.daterange input[type="date"]:hover::-webkit-calendar-picker-indicator,
.daterange input[type="date"]:focus::-webkit-calendar-picker-indicator { opacity: 1; }
.dr-sep { color: var(--text-faint); font-size: 12px; padding: 0 2px; user-select: none; }

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

/* run drawer */
#drawerBackdrop { position: fixed; inset: 0; background: rgba(10, 7, 20, .55);
  opacity: 0; pointer-events: none; transition: opacity .2s ease; z-index: 60; }
#drawerBackdrop.open { opacity: 1; pointer-events: auto; }
#drawer { position: fixed; top: 0; right: 0; height: 100vh; width: min(720px, 100vw);
  background: var(--bg-soft); border-left: 1px solid var(--border);
  transform: translateX(102%); transition: transform .22s ease; z-index: 70;
  display: flex; flex-direction: column; box-shadow: -18px 0 40px rgba(0,0,0,.4); }
#drawer.open { transform: translateX(0); }
.drawer-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 16px 18px 10px; border-bottom: 1px solid var(--border); }
.drawer-head .name { font-size: 18px; font-weight: 700; }
.drawer-head .grow { flex: 1; }
.drawer-tabs { display: flex; gap: 4px; padding: 8px 14px 0; flex-wrap: wrap;
  border-bottom: 1px solid var(--border); background: var(--bg); }
.drawer-tabs button { background: transparent; border: 1px solid transparent; border-bottom: 0;
  color: var(--text-dim); padding: 7px 14px; border-radius: 8px 8px 0 0; cursor: pointer;
  font-size: 13px; font-weight: 500; }
.drawer-tabs button:hover { color: var(--lavender); }
.drawer-tabs button.active { background: var(--card); color: #fff;
  border-color: var(--border); }
.drawer-body { flex: 1; overflow-y: auto; padding: 16px 18px; background: var(--card);
  display: flex; flex-direction: column; gap: 14px; }
.drawer-pane { display: none; flex-direction: column; gap: 12px; }
.drawer-pane.active { display: flex; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 18px; font-size: 13px; }
.kv .k { color: var(--text-faint); }
.kv .v { color: var(--text); word-break: break-all; }
pre.codeblock { background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; font-size: 12px; line-height: 1.5; overflow: auto; max-height: 55vh;
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, "Cascadia Code", Consolas, monospace; color: var(--text-dim); }
details.paramsBlock { background: var(--bg-soft); border: 1px solid var(--border);
  border-radius: 10px; padding: 8px 12px; }
details.paramsBlock summary { cursor: pointer; color: var(--lavender); font-size: 13px;
  font-weight: 600; user-select: none; }
details.paramsBlock[open] summary { margin-bottom: 8px; }

/* responsive */
@media (max-width: 768px) {
  main { padding: 14px; }
  .tabs { padding: 8px 10px; }
  .tabs button { padding: 7px 12px; font-size: 12px; }
  header { padding: 12px 14px; flex-wrap: wrap; gap: 8px; }
  header h1 { font-size: 16px; }
  #drawer { width: 100vw; border-left: 0; }
  .drawer-body { padding: 12px; }
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
  #runStrategy, #runMode, #runTf, #runEpochs, #runLoss, #runSpaces,
  #runJobs, #runRandomState, #runMinTrades, #runAnalyzePerEpoch, #runDisableExport, #runPrintAll,
  #runTrain, #runTest, #runStep, #runWfMinTrades, #runWfMaxDD, #runConfig { min-width: 0 !important; width: 100%; }
  .daterange { width: 100%; }
  .daterange > label { flex: 1; min-width: 0; flex-direction: column;
    align-items: flex-start; gap: 4px; }
  .daterange input[type="date"] { min-width: 0 !important; width: 100%; }
  .dr-sep { display: none; }
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
function showTab(name, fromHash) {
  state.tab = name;
  // tabs are always authoritative: close an open strategy detail overlay first
  if ($('strategy-detail').classList.contains('active')) {
    $('strategy-detail').classList.remove('active');
    $('mainContent').classList.remove('hidden');
    state.strategy = null;
  }
  closeDrawer();
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
  if (!fromHash) setHash();
  window.scrollTo(0, 0);
  window.dispatchEvent(new Event('resize'));
  tryPendingSplits();
}

/* ---------- url hash routing (#t=tab / #s=strategy) ---------- */
function setHash() {
  const h = state.strategy ? '#s=' + encodeURIComponent(state.strategy)
                           : '#t=' + encodeURIComponent(state.tab);
  if (location.hash !== h) history.pushState(null, '', h);
}
function applyFromHash() {
  const h = decodeURIComponent((location.hash || '').replace(/^#/, ''));
  if (h.startsWith('s=')) { openStrategy(h.slice(2), true); return; }
  const tab = h.startsWith('t=') ? h.slice(2) : 'dashboard';
  showTab(TABS.includes(tab) ? tab : 'dashboard', true);
}
const TABS = ['dashboard','strategies','history','benchmark','walkforward','hyperopt','trades','lab'];
window.addEventListener('popstate', applyFromHash);

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
  return `<a class="clickable" data-strategy="${esc(name)}" onclick="openStrategy(this.dataset.strategy)">${esc(name)}</a>`;
}
function drawerBtn(kind, r) {
  const s = esc(r.strategy || ''), src = esc(r.source || '');
  return `<button class="btn compact" title="config & code for this run" data-kind="${esc(kind)}" data-strategy="${s}" data-source="${src}"
    onclick="openDrawer({kind:this.dataset.kind,strategy:this.dataset.strategy,source:this.dataset.source})">{ }</button>`;
}

/* ---------- top scrollbar under the header ---------- */
// After a table is rendered, lift its <thead> into a header-only table inside a
// thin scroll strip above the body. Column widths are frozen with table-layout:
// fixed + a measured colgroup so header and body stay aligned, and the two
// scroll areas (header strip + body) are synced so the header follows the data.
const pendingSplits = [];
function splitTableScroll(tableEl) {
  const wrap = tableEl.closest('.table-wrap');
  const thead = tableEl.querySelector('thead');
  if (!wrap || !thead) return;
  const stack = wrap.closest('.table-stack');
  let headScroll = stack ? stack.querySelector('.thead-scroll') : null;
  const widths = [...thead.querySelectorAll('th')].map(th => th.offsetWidth);
  if (!widths.length || widths.some(w => w <= 0)) {
    // table not laid out yet (hidden tab/detail) — retry once it becomes visible
    if (!pendingSplits.includes(tableEl)) pendingSplits.push(tableEl);
    return;
  }

  const colgroup = document.createElement('colgroup');
  widths.forEach(w => { const c = document.createElement('col'); c.style.width = w + 'px'; colgroup.appendChild(c); });
  tableEl.insertBefore(colgroup.cloneNode(true), tableEl.firstChild);
  tableEl.style.tableLayout = 'fixed';
  tableEl.removeChild(thead);

  let headTable;
  if (stack && headScroll) {
    headTable = document.createElement('table');
  } else {
    const s = document.createElement('div');
    s.className = 'table-stack';
    headScroll = document.createElement('div');
    headScroll.className = 'thead-scroll';
    const parent = wrap.parentNode;
    parent.insertBefore(s, wrap);
    s.appendChild(headScroll);
    s.appendChild(wrap);
    const sync = (a, b) => a.addEventListener('scroll', () => { b.scrollLeft = a.scrollLeft; }, { passive: true });
    sync(wrap, headScroll);
    sync(headScroll, wrap);
    headTable = document.createElement('table');
  }
  headTable.appendChild(thead.cloneNode(true));
  headTable.insertBefore(colgroup.cloneNode(true), headTable.firstChild);
  headTable.style.tableLayout = 'fixed';
  headScroll.innerHTML = '';
  headScroll.appendChild(headTable);

  attachSort(headTable, tableEl);
  updateTableScroll(wrap);
}

function tryPendingSplits() {
  for (let i = pendingSplits.length - 1; i >= 0; i--) {
    const t = pendingSplits[i];
    if (!t.isConnected || !t.querySelector('thead')) { pendingSplits.splice(i, 1); continue; }
    const widths = [...t.querySelectorAll('thead th')].map(th => th.offsetWidth);
    if (widths.length && !widths.some(w => w <= 0)) {
      pendingSplits.splice(i, 1);
      splitTableScroll(t);
    }
  }
}

function attachSort(headTable, bodyTable) {
  const wrap = bodyTable.closest('.table-wrap');
  const tbody = bodyTable.querySelector('tbody');
  if (!tbody) return;
  headTable.querySelectorAll('thead th').forEach(th => {
    th.addEventListener('click', () => {
      const idx = [...th.parentNode.children].indexOf(th);
      headTable.querySelectorAll('thead th').forEach(h => { const a = h.querySelector('.arrow'); if (a) a.remove(); });
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
      updateTableScroll(wrap);
    });
  });
}

function setupTableSplitter() {
  const obs = new MutationObserver(muts => {
    muts.forEach(m => m.addedNodes.forEach(n => {
      if (!n || n.nodeType !== 1) return;
      const tables = n.matches && n.matches('table') ? [n] : (n.querySelectorAll ? [...n.querySelectorAll('table')] : []);
      tables.forEach(t => { if (!t.closest('.thead-scroll')) splitTableScroll(t); });
    }));
  });
  obs.observe(document.body, { childList: true, subtree: true });
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
    return `<div class="metric-card" style="cursor:pointer" data-strategy="${esc(r.strategy)}" onclick="openStrategy(this.dataset.strategy)">
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
    <th class="num">Calmar</th><th class="num">MaxDD</th><th>Basis</th><th>Run</th><th></th>
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
      <td>${drawerBtn(r.basis === 'benchmark' ? 'benchmark' : 'backtest', r)}</td>
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
function openStrategy(name, fromHash) {
  state.strategy = name;
  // show the detail pane before populating its tables so column widths can be measured
  $('strategy-detail').classList.add('active');
  $('mainContent').classList.add('hidden');
  closeDrawer();
  const canon = LAB.canonical.find(r => r.strategy === name);
  const allRuns = LAB.backtests.filter(r => r.strategy === name).sort((a,b) =>
    (b.run_time||'').localeCompare(a.run_time||''));
  const benches = LAB.benchmarks.filter(r => r.strategy === name);
  const hos = LAB.hyperopt.filter(r => r.strategy === name);
  const wfs = LAB.walkforward.filter(r => r.strategy === name);

  const head = $('detailHead');
  const canonCode = canon ? { hash: canon.code_hash, verified: canon.code_verified } : null;
  head.innerHTML = `
    <button class="btn" onclick="closeStrategy()">← Back</button>
    <div>
      <div class="detail-head">
        <span class="name">${esc(name)}</span>
        ${canon ? gradePill(canon.score.grade) : ''}
        ${statusPill(canon ? canon.status : '')}
        <span class="basis-badge">grade basis: ${canon ? canon.basis : '—'}</span>
        ${codeBadge(name, canonCode)}
        ${canon ? `<button class="btn compact" data-kind="${esc(canon.basis === 'benchmark' ? 'benchmark' : 'backtest')}" data-strategy="${esc(name)}" data-source="${esc(canon.source)}" onclick="openDrawer({kind:this.dataset.kind,strategy:this.dataset.strategy,source:this.dataset.source})">{ } config &amp; code</button>` : ''}
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
        if (k==='winrate'||k==='max_drawdown_account'||k==='worst_trade') shown = pct(v);
        if (k==='total_trades') shown = fmt(v,0);
        const isPctMetric = k==='max_drawdown_account'||k==='worst_trade';
        const passStr = isPctMetric ? `≤ ${pct(spec.pass)}` : (k==='total_trades' ? fmt(spec.pass,0) : fmt(spec.pass));
        const warnStr = isPctMetric ? `≤ ${pct(spec.warn)}` : (k==='total_trades' ? fmt(spec.warn,0) : fmt(spec.warn));
        return `<tr><td>${spec.label}</td><td class="num">${shown}</td>
          <td>${pill(g,g)}</td><td class="num">${passStr}</td><td class="num">${warnStr}</td></tr>`;
      }).join('') + '</tbody></table>';
  } else sb.innerHTML = '<p class="hint">No scorecard.</p>';

  // diagnostics + recommendations
  const diag = $('detailDiagnostics');
  const recWrap = $('detailRecommendations');
  if (canon) {
    const avgMfe = canon.avg_mfe != null ? (canon.avg_mfe*100).toFixed(2)+'%' : '—';
    const avgMae = canon.avg_mae != null ? (canon.avg_mae*100).toFixed(2)+'%' : '—';
    const payoff = canon.payoff_ratio != null ? fmt(canon.payoff_ratio) : '—';
    const capture = canon.capture_ratio != null ? (canon.capture_ratio*100).toFixed(0)+'%' : '—';
    const wStreak = canon.max_win_streak ?? '—';
    const lStreak = canon.max_loss_streak ?? '—';
    const avgWin = canon.avg_win != null ? (canon.avg_win*100).toFixed(2)+'%' : '—';
    const avgLoss = canon.avg_loss != null ? (canon.avg_loss*100).toFixed(2)+'%' : '—';
    const worstTrade = canon.worst_trade != null ? (canon.worst_trade*100).toFixed(2)+'%' : '—';
    diag.innerHTML = [
      ['Max loss streak', fmt(lStreak,0), (canon.max_loss_streak||0) >=8 ? 'bad' : (canon.max_loss_streak||0) >=5 ? 'warn' : ''],
      ['Max win streak', fmt(wStreak,0), ''],
      ['Payoff (avg win/loss)', payoff, (canon.payoff_ratio!=null && canon.payoff_ratio <1 ? 'bad' : '')],
      ['Avg MFE', avgMfe, ''], ['Avg MAE', avgMae, ''],
      ['Capture of MFE', capture, (canon.capture_ratio!=null && canon.capture_ratio <0.25 ? 'bad' : '')],
      ['Avg win', avgWin, ''], ['Avg loss', avgLoss, ''],
      ['Worst trade' + (canon.worst_trade_pair ? ` · ${esc(canon.worst_trade_pair)}` : ''), worstTrade, ((canon.worst_trade ?? 0) <= -0.15 ? 'bad' : '')],
    ].map(([k,v,c]) => `<div class="metric-card"><span class="mk">${k}</span><span class="mv ${c}">${v}</span></div>`).join('');
    const recs = canon.recommendations || [];
    if (!recs.length) recWrap.innerHTML = '<p class="hint">No recommendations — well balanced.</p>';
    else recWrap.innerHTML = recs.map(r => {
      const cls = r.level==='fail'?'fail':r.level==='warn'?'warn':r.level==='good'?'pass':'na';
      return `<div style="background:var(--bg-soft);border:1px solid var(--border);border-radius:10px;padding:10px 14px;display:flex;gap:10px;align-items:flex-start"><span style="flex-shrink:0">${pill(cls, r.level)}</span><div><b>${esc(r.title)}</b><div class="hint" style="margin-top:2px">${esc(r.detail)}</div></div></div>`;
    }).join('');
  } else {
    diag.innerHTML = '<p class="hint">No diagnostics.</p>';
    recWrap.innerHTML = '';
  }

  // all runs
  const rt = document.createElement('table');
  rt.innerHTML = `<thead><tr><th>Run</th><th class="num">Grade</th><th class="num">Profit%</th>
    <th class="num">Trades</th><th class="num">PF</th><th class="num">Sortino</th>
    <th class="num">MaxDD</th><th>TF</th><th>Source</th><th></th></tr></thead><tbody>` +
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
      <td>${drawerBtn('backtest', r)}</td>
    </tr>`).join('') + '</tbody>';
  const rtWrap = $('detailRuns');
  rtWrap.innerHTML = '';
  rtWrap.appendChild(rt);
  makeSortable(rt);

  // benchmark + hyperopt + wf
  const bt = benches.length ? benches.map(r => `<tr>
      <td>${esc((r.run_time||'').slice(0,10))}</td><td class="num">${gradePill(r.score.grade)}</td>
      <td class="num">${fmt((r.profit_total||0)*100,1)}%</td><td class="num">${fmt(r.sortino)}</td>
      <td class="num">${fmt(r.profit_factor)}</td><td>${drawerBtn('benchmark', r)}</td></tr>`).join('')
    : '<tr><td colspan="6" class="hint">No benchmark runs.</td></tr>';
  $('detailBench').innerHTML = `<table><thead><tr><th>Run</th><th class="num">Grade</th><th class="num">Profit%</th><th class="num">Sortino</th><th class="num">PF</th><th></th></tr></thead><tbody>${bt}</tbody></table>`;

  const ht = hos.length ? hos.slice(0, 8).map(r => `<tr>
      <td>${esc((r.run_time||'').slice(0,10))}</td><td class="num">${fmt(r.epochs,0)}</td>
      <td class="num">${fmt(r.best_loss,2)}</td><td class="num">${fmt((r.best_profit_total||0)*100,1)}%</td>
      <td class="num">${fmt(r.best_sortino)}</td><td>${drawerBtn('hyperopt', r)}</td></tr>`).join('')
    : '<tr><td colspan="6" class="hint">No hyperopt runs.</td></tr>';
  $('detailHyperopt').innerHTML = `<table><thead><tr><th>Run</th><th class="num">Epochs</th><th class="num">Best loss</th><th class="num">Best profit</th><th class="num">Best sortino</th><th></th></tr></thead><tbody>${ht}</tbody></table>`;

  const wt = wfs.length ? wfs.map(r => `<tr>
      <td>${esc((r.run_id||'').slice(0,16))}</td><td class="num">${fmt(r.n_windows,0)}</td>
      <td class="num">${r.profitable_windows}/${r.n_windows}</td>
      <td class="num">${fmt(r.oos_profit_abs)}</td><td class="num">${fmt(r.avg_oos_sortino)}</td>
      <td>${drawerBtn('walkforward', r)}</td></tr>`).join('')
    : '<tr><td colspan="6" class="hint">No walk-forward runs.</td></tr>';
  $('detailWF').innerHTML = `<table><thead><tr><th>Run</th><th class="num">Windows</th><th class="num">Profitable</th><th class="num">OOS profit</th><th class="num">Avg sortino</th><th></th></tr></thead><tbody>${wt}</tbody></table>`;

  $('strategy-detail').classList.add('active');
  $('mainContent').classList.add('hidden');
  if (!fromHash) setHash();
  window.scrollTo(0, 0);
  updateAllTableScrolls();
  tryPendingSplits();

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
  tryPendingSplits();
}

/* ---------- run provenance: badges + drawer ---------- */
function codeBadge(strategy, info) {
  if (!info || !info.hash) return pill('na', 'code unknown');
  const cur = (LAB.current_code || {})[strategy];
  if (!cur) return pill('na', 'no .py on disk');
  if (cur === info.hash) return pill(info.verified ? 'pass' : 'warn', info.verified ? 'code current' : 'code current*');
  return pill('fail', 'code changed since run');
}
function findRun(kind, strategy, source) {
  const pool = kind === 'benchmark' ? LAB.benchmarks
    : kind === 'hyperopt' ? LAB.hyperopt
    : kind === 'walkforward' ? LAB.walkforward : LAB.backtests;
  return (pool || []).find(r => r.strategy === strategy && r.source === source) ||
         (pool || []).find(r => r.source === source);
}
const drawerState = { open: false, ctx: null, tab: 'overview' };
const DRAWER_TABS = ['overview', 'config', 'code', 'params'];
function openDrawer(ctx, tab) {
  drawerState.ctx = ctx;
  drawerState.open = true;
  drawerState.tab = tab || 'overview';
  $('drawer').classList.add('open');
  $('drawerBackdrop').classList.add('open');
  renderDrawer();
}
function closeDrawer() {
  drawerState.open = false;
  drawerState.ctx = null;
  const d = $('drawer');
  if (!d) return;
  d.classList.remove('open');
  $('drawerBackdrop').classList.remove('open');
}
function escAttr(s) { return esc(s).replace(/`/g, '&#96;'); }
function drawerTabBtn(t) {
  return `<button data-dtab="${t}" class="${drawerState.tab === t ? 'active' : ''}"
    onclick="drawerState.tab='${t}';renderDrawer()">${t[0].toUpperCase() + t.slice(1)}</button>`;
}
function renderDrawer() {
  const ctx = drawerState.ctx;
  const body = $('drawerBody');
  const head = document.querySelector('#drawer .drawer-head');
  if (!ctx) { body.innerHTML = ''; head.innerHTML = ''; return; }
  const r = findRun(ctx.kind, ctx.strategy, ctx.source) || {};
  const tabs = ['overview', 'config', 'code'];
  if (ctx.kind === 'hyperopt') tabs.push('params');
  head.innerHTML = `
    <span class="name">${esc(ctx.strategy)}</span>
    ${pill(ctx.kind === 'benchmark' ? 'pass' : 'na', ctx.kind)}
    <span class="hint">${esc((ctx.source || '').slice(-40))}</span>
    <span class="grow"></span>
    <button class="btn compact" onclick="closeDrawer()">✕ Close</button>`;
  document.querySelector('#drawer .drawer-tabs').innerHTML = tabs.map(drawerTabBtn).join('');
  body.innerHTML = tabs.map(t =>
    `<div class="drawer-pane ${drawerState.tab === t ? 'active' : ''}" id="dpane-${t}">${drawerPane(t, r)}</div>`
  ).join('');
}
function drawerPane(t, r) {
  if (t === 'overview') return paneOverview(r);
  if (t === 'config') return paneConfig(r);
  if (t === 'code') return paneCode(r);
  if (t === 'params') return paneParams(r);
  return '';
}
function paneOverview(r) {
  const rows = [
    ['Strategy', esc(r.strategy || '')],
    ['Kind', esc(drawerState.ctx.kind)],
    ['Source', `<code>${esc(r.source || '')}</code>`],
    ['Run time', esc(r.run_time || '—')],
    ['Timeframe', esc(r.timeframe || '—')],
    ['Timerange', esc(r.timerange || '—')],
    ['Pairs', fmt(r.pair_count, 0)],
    ['Stake currency', esc(r.stake_currency || '—')],
    ['Trading mode', esc(r.trading_mode || '—')],
    ['Profit total', r.profit_total != null ? pct(r.profit_total) : '—'],
    ['Trades / winrate', `${fmt(r.total_trades, 0)} / ${pct(r.winrate)}`],
    ['Sortino / Calmar', `${fmt(r.sortino)} / ${fmt(r.calmar)}`],
    ['Max drawdown', pct(r.max_drawdown_account)],
  ];
  if (r.loss_function) rows.push(['Loss function', esc(r.loss_function)]);
  if (r.spaces) rows.push(['Spaces', esc(r.spaces)]);
  if (r.train_days) rows.push(['WF windows', `${fmt(r.n_windows,0)} (${r.profitable_windows ?? '—'} profitable)`]);
  if (r.epochs) rows.push(['Epochs', fmt(r.epochs, 0)]);
  return `<div class="kv">${rows.map(([k, v]) => `<span class="k">${k}</span><span class="v">${v}</span>`).join('')}</div>`;
}
function configFor(r) {
  if (r && r.config_hash && LAB.configs && LAB.configs[r.config_hash]) {
    return { hash: r.config_hash, obj: LAB.configs[r.config_hash] };
  }
  return null;
}
function paneConfig(r) {
  const c = configFor(r);
  if (!c) {
    let hint = 'No config captured for this run.';
    if (drawerState.ctx.kind === 'backtest' && !r.config_hash)
      hint += ' Plain-JSON backtests predate provenance capture; re-run or benchmark to link one.';
    if (drawerState.ctx.kind !== 'backtest' && drawerState.ctx.kind !== 'benchmark')
      hint += ' Hyperopt/walk-forward configs are linked when launched from the Lab.';
    return `<p class="hint">${hint}</p>`;
  }
  return `
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="btn compact" onclick="copyText(JSON.stringify(LAB.configs['${escAttr(c.hash)}'],null,2))">Copy JSON</button>
      <a class="btn compact" download="config_${escAttr(c.hash.slice(0, 8))}.json"
         href="data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(c.obj, null, 2))}">Download</a>
      <span class="hint">hash ${esc(c.hash.slice(0, 12))}…</span>
    </div>
    <pre class="codeblock">${esc(JSON.stringify(c.obj, null, 2))}</pre>`;
}
let _codeCache = {};
function codeText(hash) { return _codeCache[hash] || ''; }
function loadCodeInto(hash, elId) {
  const el = $(elId);
  fetch('/api/strategy/file?hash=' + encodeURIComponent(hash))
    .then(r => r.ok ? r.text() : Promise.reject(r.status))
    .then(txt => {
      _codeCache[hash] = txt;
      el.innerHTML = `<pre class="codeblock" id="codePre-${escAttr(hash).slice(0,8)}">${esc(txt.length > 120000 ? txt.slice(0, 120000) + '\n… (truncated preview)' : txt)}</pre>
        <button class="btn compact" onclick="copyText(codeText('${escAttr(hash)}'))">Copy code</button>`;
    })
    .catch(() => { el.innerHTML = '<p class="hint">Snapshot viewer needs the server (lab.py serve).</p>'; });
}
function paneCode(r) {
  const strategy = drawerState.ctx.strategy;
  const badge = codeBadge(strategy, { hash: r.code_hash, verified: r.code_verified });
  if (!r.code_hash) return `<p class="hint">No code snapshot for this run.</p>`;
  const meta = (LAB.snapshot_paths || {})[r.code_hash];
  const isCurrent = (LAB.current_code || {})[strategy] === r.code_hash;
  const curPath = meta && meta.path;
  return `
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      ${badge}
      <span class="hint">snapshot ${esc(r.code_hash.slice(0, 12))}…${meta && meta.mtime ? ' · ' + esc(meta.mtime) : ''}${curPath ? ' · <code>' + esc(curPath) + '</code>' : ''}</span>
    </div>
    ${isCurrent ? '' : '<p class="hint bad">The current .py file differs from this snapshot — metrics below reflect the old code.</p>'}
    <div id="dcode-viewer"><button class="btn compact" onclick="loadCodeInto('${escAttr(r.code_hash)}','dcode-viewer')">View snapshot source</button> <span class="hint">(loads via server)</span></div>`;
}
function paneParams(r) {
  if (drawerState.ctx.kind !== 'hyperopt') return '<p class="hint">Params apply to hyperopt runs.</p>';
  let params = null;
  try { params = r.best_params ? JSON.parse(r.best_params) : null; } catch (e) { params = null; }
  const metaRows = [
    ['Loss function', esc(r.loss_function || '—')],
    ['Spaces', esc(r.spaces || '—')],
    ['Epochs', fmt(r.epochs, 0)],
    ['Best loss', fmt(r.best_loss, 4)],
    ['Random state', fmt(r.random_state, 0)],
    ['Jobs', fmt(r.jobs, 0)],
    ['Min trades', fmt(r.min_trades, 0)],
  ].map(([k, v]) => `<span class="k">${k}</span><span class="v">${v}</span>`).join('');
  return `<div class="kv">${metaRows}</div>`
    + (params
      ? `<details class="paramsBlock" open><summary>Best epoch params</summary><pre class="codeblock">${esc(JSON.stringify(params, null, 2))}</pre></details>`
      : '<p class="hint">No best_params stored (re-run ingest).</p>');
}
function copyText(txt) {
  (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject())
    .then(() => {})
    .catch(() => {
      const ta = document.createElement('textarea');
      ta.value = txt; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (e) {}
      ta.remove();
    });
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
  // one bar per strategy: latest benchmark run wins
  const latest = {};
  rows.forEach(r => {
    const cur = latest[r.strategy];
    if (!cur || (r.run_time||'') > (cur.run_time||'')) latest[r.strategy] = r;
  });
  const shown = Object.values(latest).sort((a,b) => -(Number(a.sortino||0) - Number(b.sortino||0)));
  $('benchHint').textContent = ''; el.style.display='';
  const metric = $('benchMetric').value;
  const useLog = $('benchLog').checked;
  const value = r => r[metric] === null || r[metric] === undefined ? 0 : Number(r[metric]);
  const c = echarts.init(el);
  c.setOption({ backgroundColor:'transparent', tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
    grid:{left:110,right:30,top:20,bottom:40},
    xAxis: useLog ? {type:'log',logBase:10,axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}}
                  : {type:'value',axisLabel:{color:'#a89fc4'},splitLine:{lineStyle:{color:'#241d36'}}},
    yAxis:{type:'category',data:shown.map(r=>r.strategy),axisLabel:{color:'#a89fc4'}},
    series:[{ name:metric, type:'bar',
      data: shown.map(r=>{ const v=value(r);
        let color = metric==='max_drawdown_account' ? (v<=0.2?'#6ee7a8':v<=0.4?'#fbbf24':'#f87171')
          : (v>=1?'#6ee7a8':v>=0.3?'#fbbf24':'#f87171');
        return {value:v,itemStyle:{color}}; }) }] });
  window._benchChart = c;
}

/* ---------- walk-forward ---------- */
let wfSelected = null;
function renderWalkForward() {
  const rows = LAB.walkforward;
  if (!rows.length) { $('wf').innerHTML = '<p class="hint">No walk-forward results ingested yet.</p>'; return; }
  const q = ($('wfFilter') ? $('wfFilter').value.toLowerCase() : '');
  let filtered = rows.filter(r => !q || (r.strategy||'').toLowerCase().includes(q) || (r.run_id||'').toLowerCase().includes(q));
  filtered.sort((a,b)=>(b.run_time||'').localeCompare(a.run_time||''));
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr><th>Strategy</th><th class="num">Run</th><th class="num">Windows</th>
    <th class="num">Profitable</th><th class="num">OOS Trades</th><th class="num">OOS Profit</th>
    <th class="num">Avg Sortino</th><th class="num">Avg PF</th><th>Loss</th><th>Detail</th></tr></thead><tbody>` +
    filtered.slice(0,80).map(r => {
      const ratio = r.n_windows ? (r.profitable_windows / r.n_windows) : 0;
      const sel = wfSelected===r.source ? ' style="background:var(--card-hover)"' : '';
      return `<tr${sel}>
        <td>${stratLink(r.strategy)}</td>
        <td class="num" data-val="${r.run_id||''}" title="${esc(r.source||'')}">${esc((r.run_id||r.source||'').slice(0,18))}</td>
        <td class="num" data-val="${r.n_windows||0}">${fmt(r.n_windows,0)}</td>
        <td class="num" data-val="${ratio}">${pill(ratio>=0.6?'pass':ratio>=0.4?'warn':'fail', `${r.profitable_windows}/${r.n_windows}`)}</td>
        <td class="num" data-val="${r.oos_trades||0}">${fmt(r.oos_trades,0)}</td>
        <td class="num" data-val="${r.oos_profit_abs||0}">${fmt(r.oos_profit_abs)}</td>
        <td class="num" data-val="${r.avg_oos_sortino||0}">${fmt(r.avg_oos_sortino)}</td>
        <td class="num" data-val="${r.avg_oos_profit_factor||0}">${fmt(r.avg_oos_profit_factor)}</td>
        <td data-val="${r.loss_function||''}">${esc(r.loss_function||'')}</td>
        <td style="white-space:nowrap"><button class="btn compact" data-source="${esc(r.source)}" onclick="loadWFDetail(this.dataset.source)">Windows</button> ${drawerBtn('walkforward', r)}</td>
      </tr>`;
    }).join('') + '</tbody>';
  const wrap = $('wf'); wrap.innerHTML=''; wrap.appendChild(t); makeSortable(t);
  if ($('wfCount')) $('wfCount').textContent = `${filtered.length}/${rows.length} runs`;
}
function renderWFDetailFromWindows(r, wins, el) {
  const chartId = 'wfSpark';
  el.innerHTML = `<div class="card"><div class="section-head"><h2>OOS per window — ${esc(r.strategy)} · ${esc((r.run_id||'').slice(0,16))}</h2><span class="hint">${wins.length} windows · ${r.train_days}/${r.test_days}/${r.step_days} d</span></div><div id="${chartId}" class="chart" style="height:200px"></div><div class="table-wrap"><div id="wfWinTable"></div></div></div>`;
  setTimeout(()=>{
    try {
      const c = echarts.init($(chartId));
      const x = wins.map((_,i)=>'W'+(i+1));
      const y = wins.map(w=>w.oos_profit_abs||0);
      c.setOption({backgroundColor:'transparent', tooltip:{trigger:'axis'}, grid:{left:50,right:20,top:20,bottom:30}, xAxis:{type:'category',data:x,axisLabel:{color:'#a89fc4'}}, yAxis:{type:'value',axisLabel:{color:'#a89fc4'}}, series:[{type:'bar',data:y.map(v=>({value:v,itemStyle:{color:v>=0?'#6ee7a8':'#f87171'}}))},{type:'line',data:y,smooth:true,lineStyle:{color:'#c4b5fd'}}]});
      window._wfChart=c;
    } catch(e){}
  },60);
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr><th>#</th><th>Test range</th><th class="num">Trades</th><th class="num">Profit</th><th class="num">Win%</th><th class="num">Sortino</th><th class="num">PF</th><th class="num">DD</th></tr></thead><tbody>` +
    wins.map((w,i)=>`<tr><td>${i+1}</td><td>${esc(w.test_range||'')}</td><td class="num">${fmt(w.oos_trades,0)}</td><td class="num">${fmt(w.oos_profit_abs)}</td><td class="num">${pct(w.oos_winrate)}</td><td class="num">${fmt(w.oos_sortino)}</td><td class="num">${fmt(w.oos_pf)}</td><td class="num">${pct(w.oos_dd)}</td></tr>`).join('') + '</tbody>';
  $('wfWinTable').appendChild(t); makeSortable(t);
}
function loadWFDetail(source) {
  wfSelected = source;
  renderWalkForward();
  const el = $('wfDetail');
  if (!el) return;
  el.innerHTML = '<p class="hint">Loading windows for '+esc(source.slice(-40))+'…</p>';
  const local = (LAB.walkforward||[]).find(r=>r.source===source);
  if (local && local.windows_json) {
    try {
      const wins = JSON.parse(local.windows_json);
      if (wins && wins.length) { renderWFDetailFromWindows(local, wins, el); return; }
    } catch(e) {}
  }
  fetch('/api/walkforward?source='+encodeURIComponent(source)).then(r=>r.json()).then(d=>{
    const rows = d.rows||[];
    if (!rows.length) { el.innerHTML='<p class="hint">No detail.</p>'; return; }
    const r = rows[0];
    const wins = r.windows || [];
    if (!wins.length) { el.innerHTML='<p class="hint">No windows_json (re-ingest).</p>'; return; }
    renderWFDetailFromWindows(r, wins, el);
  }).catch(()=>{ el.innerHTML='<p class="hint">Failed to load (need server).</p>'; });
}

/* ---------- hyperopt ---------- */
let hoSelected = null;
let hoSort = {col:'loss', asc:true};
let hoMinTrades = 0;
function renderHyperopt() {
  const rows = LAB.hyperopt;
  if (!rows.length) { $('ho').innerHTML = '<p class="hint">No hyperopt results ingested yet.</p>'; return; }
  const q = ($('hoFilter') ? $('hoFilter').value.toLowerCase() : '');
  const minT = hoMinTrades;
  let filtered = rows.filter(r => {
    if (minT && (r.best_trades||0) < minT) return false;
    if (!q) return true;
    return (r.strategy||'').toLowerCase().includes(q) || (r.source||'').toLowerCase().includes(q) || (r.loss_function||'').toLowerCase().includes(q);
  });
  filtered.sort((a,b)=>(b.epochs||0)-(a.epochs||0));
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr><th>Strategy</th><th class="num">Epochs</th><th class="num">Best Loss</th>
    <th class="num">Best Profit</th><th class="num">Best Sortino</th><th class="num">Best PF</th><th class="num">Trades</th><th>Loss</th><th>Spaces</th><th>Run</th><th></th></tr></thead><tbody>` +
    filtered.slice(0,60).map(r => `<tr${hoSelected===r.source?' style="background:var(--card-hover)"':''}>
      <td>${stratLink(r.strategy)}</td>
      <td class="num" data-val="${r.epochs||0}">${fmt(r.epochs,0)}</td>
      <td class="num" data-val="${r.best_loss||0}">${fmt(r.best_loss,2)}</td>
      <td class="num" data-val="${r.best_profit_total||0}">${fmt((r.best_profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.best_sortino||0}">${fmt(r.best_sortino)}</td>
      <td class="num" data-val="${r.best_profit_factor||0}">${fmt(r.best_profit_factor)}</td>
      <td class="num" data-val="${r.best_trades||0}">${fmt(r.best_trades,0)}</td>
      <td data-val="${r.loss_function||''}" title="${esc(r.spaces||'')}">${esc((r.loss_function||'').replace('HyperOptLoss',''))}</td>
      <td data-val="${r.spaces||''}">${esc((r.spaces||'').slice(0,18))}</td>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,16))}</td>
      <td style="white-space:nowrap"><button class="btn compact" data-source="${esc(r.source)}" onclick="loadHOEpochs(this.dataset.source)">Drill</button> ${drawerBtn('hyperopt', r)}</td>
    </tr>`).join('') + '</tbody>';
  const wrap = $('ho'); wrap.innerHTML=''; wrap.appendChild(t); makeSortable(t);
  if ($('hoCount')) $('hoCount').textContent = `${filtered.length}/${rows.length} runs`;
  if ($('hoFiles')) fetch('/api/hyperopt/files').then(r=>r.json()).then(f=>{ $('hoFiles').innerHTML = f.slice(0,8).map(x=>`<option value="${esc(x.source)}">${esc(x.source)} (${(x.size/1e6).toFixed(1)} MB)</option>`).join(''); }).catch(()=>{});
}
function loadHOEpochs(source) {
  hoSelected=source;
  renderHyperopt();
  const el = $('hoDetail');
  if (!el) return;
  el.innerHTML = '<p class="hint">Loading epochs for '+esc(source.slice(-40))+'… (up to 200 sorted by loss)</p>';
  const limit = ($('hoLimit')? Number($('hoLimit').value)||200 : 200);
  fetch('/api/hyperopt?source='+encodeURIComponent(source)+'&limit='+limit).then(r=>r.json()).then(d=>{
    if (d.error) { el.innerHTML='<p class="hint bad">'+esc(d.error)+'</p>'; return; }
    const recs = d.records||[];
    const corr = d.corr||{};
    if (!recs.length) { el.innerHTML='<p class="hint">No epochs.</p>'; return; }
    // inline best-params glance (from the ingested hyperopt row, works offline)
    let inlineParams = '';
    const hoRow = (LAB.hyperopt||[]).find(x => x.source === d.source);
    if (hoRow && hoRow.best_params) {
      try {
        const bp = JSON.parse(hoRow.best_params);
        inlineParams = `<details class="paramsBlock"><summary>Best epoch params — ${esc(hoRow.loss_function||'')} · loss ${fmt(hoRow.best_loss,4)}</summary><pre class="codeblock">${esc(JSON.stringify(bp,null,2))}</pre></details>`;
      } catch(e) {}
    }
    let corrHtml = Object.keys(corr).length ? '<div class="card" style="padding:10px"><div class="hint">Correlation with loss (lower loss = better). Negative = good for sortino/calmar/PF.</div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">'+Object.entries(corr).map(([k,v])=>`<span class="pill ${v< -0.2 ? 'pass' : v>0.2 ? 'fail' : 'warn'}">${esc(k)} ${v>0?'+':''}${v.toFixed(2)}</span>`).join('')+'</div></div>' : '';
    const t = document.createElement('table');
    // compute sortable
    const head = `<thead><tr><th class="num">Epoch</th><th class="num">Loss</th><th class="num">Trades</th><th class="num">Profit%</th><th class="num">Sortino</th><th class="num">Calmar</th><th class="num">PF</th><th class="num">SQN</th><th class="num">DD</th><th class="num">MAE%</th><th class="num">ExitEff</th><th>Best?</th></tr></thead>`;
    const rows = recs.map(r=>`<tr>
      <td class="num" data-val="${r.epoch||0}">${fmt(r.epoch,0)}</td>
      <td class="num" data-val="${r.loss||0}">${fmt(r.loss,4)}</td>
      <td class="num" data-val="${r.trades||0}">${fmt(r.trades,0)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt((r.profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td>
      <td class="num" data-val="${r.calmar||0}">${fmt(r.calmar)}</td>
      <td class="num" data-val="${r.profit_factor||0}">${fmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.sqn||0}">${fmt(r.sqn)}</td>
      <td class="num" data-val="${r.max_drawdown||0}">${pct(r.max_drawdown)}</td>
      <td class="num" data-val="${r.mae||0}">${fmt((r.mae||0)*100,2)}%</td>
      <td class="num" data-val="${r.exit_eff||0}">${fmt((r.exit_eff||0)*100,0)}%</td>
      <td>${r.best?pill('pass','best'): r.init?pill('na','init'):''}</td>
    </tr>`).join('');
    t.innerHTML = head + '<tbody>' + rows + '</tbody>';
    const chartId = 'hoScatter';
    el.innerHTML = corrHtml + inlineParams + `<div class="card"><div class="section-head"><h2>Epochs — ${esc(d.source)} (${recs.length}/${d.count})</h2><span class="hint">sorted by loss asc · MAE/exit_eff from embedded trades</span></div><div id="${chartId}" class="chart" style="height:220px"></div><div class="table-wrap"></div><div class="hint" style="margin-top:8px">Tip: use Min trades filter to cull noise; compare Top loss vs Top sortino/calmar before trusting a loss function. Use <code>python user_data/scripts/analyze_hyperopt.py --results user_data/hyperopt_results/${esc(d.source)} --top 15</code> for full CLI table.</div></div>`;
    el.querySelector('.table-wrap').appendChild(t); makeSortable(t);
    setTimeout(()=>{
      try {
        const c = echarts.init($(chartId));
        const pts = recs.map(r=>[r.loss, r.sortino]);
        c.setOption({backgroundColor:'transparent', tooltip:{trigger:'item', formatter:p=>`loss ${p.value[0].toFixed(4)}<br/>sortino ${p.value[1]}`}, grid:{left:50,right:20,top:20,bottom:30}, xAxis:{type:'value',name:'loss',nameTextStyle:{color:'#a89fc4'},axisLabel:{color:'#a89fc4'}}, yAxis:{type:'value',name:'sortino',axisLabel:{color:'#a89fc4'}}, series:[{type:'scatter',data:pts, symbolSize:6, itemStyle:{color:'#c4b5fd'}}]});
        window._hoChart=c;
      } catch(e){}
    },60);
  }).catch(()=>{ el.innerHTML='<p class="hint">Failed (need server with /api/hyperopt).</p>'; });
}
function hoApplyFilter() { const v = $('hoMinTrades'); hoMinTrades = v ? (Number(v.value)||0) : 0; renderHyperopt(); }


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
        <td class="num" data-val="${td.pr||0}">${pill(prof>=0?'pass':'fail', (prof<=-0.15?'⚠ ':'')+prof.toFixed(2)+'%')}</td>
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
function updateRunFields() {
  const mode = $('runMode').value;
  document.querySelectorAll('[data-runfield]').forEach(el => {
    el.classList.toggle('hidden', !el.dataset.runfield.split(' ').includes(mode));
  });
}
function defaultRunRange() {
  let min = '20220101', max = '20240101';
  (LAB.backtests || []).forEach(r => {
    const m = /^(\d{8})-(\d{8})$/.exec(r.timerange || '');
    if (m) { if (m[1] < min) min = m[1]; if (m[2] > max) max = m[2]; }
  });
  const fmt = s => s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8);
  $('runStart').value = fmt(min);
  $('runEnd').value = fmt(max);
}
function loadLosses() {
  fetch('/api/losses').then(r => r.json()).then(d => {
    const dl = $('lossList');
    (d.losses || []).forEach(l => { const o = document.createElement('option'); o.value = l; dl.appendChild(o); });
  }).catch(() => {});
}
function labRun() {
  const strategy = $('runStrategy').value;
  if (!strategy) { $('jobStatus').textContent = 'Pick a strategy first.'; return; }
  const start = ($('runStart').value || '').replace(/-/g, '');
  const end = ($('runEnd').value || '').replace(/-/g, '');
  const mode = $('runMode').value;
  const body = {
    mode,
    strategy,
    timerange: (start && end) ? start + '-' + end : '',
    timeframe: $('runTf').value,
    config: $('runConfig').value.trim(),
    rebuild: $('runRebuild').checked,
  };
  if (mode === 'hyperopt' || mode === 'walkforward') {
    body.epochs = Number($('runEpochs').value) || 100;
    body.loss = $('runLoss').value.trim() || 'SharpeHyperOptLossDaily';
    const spaces = $('runSpaces').value.split(/\s+/).map(s=>s.trim()).filter(Boolean);
    if (spaces.length) body.spaces = spaces;
    const jobs = $('runJobs').value.trim();
    if (jobs !== '') body.jobs = Number(jobs);
    const seed = $('runRandomState').value.trim();
    if (seed !== '') body.random_state = Number(seed);
    const mt = $('runMinTrades').value.trim();
    if (mt !== '') body.min_trades = Number(mt);
    if ($('runAnalyzePerEpoch').checked) body.analyze_per_epoch = true;
  }
  if (mode === 'hyperopt') {
    if ($('runDisableExport').checked) body.disable_param_export = true;
    if ($('runPrintAll').checked) body.print_all = true;
  }
  if (mode === 'walkforward') {
    body.train_days = Number($('runTrain').value) || 90;
    body.test_days = Number($('runTest').value) || 7;
    body.step_days = Number($('runStep').value) || 7;
    const wfmt = $('runWfMinTrades').value.trim();
    if (wfmt !== '') body.wf_min_trades = Number(wfmt);
    const wfdd = $('runWfMaxDD').value.trim();
    if (wfdd !== '') body.wf_max_drawdown = Number(wfdd);
  }
  $('jobStatus').textContent = `Running ${mode} for ${strategy} (${body.timerange || 'all data'})…`;
  fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r => r.json()).then(() => { jobTimer = setInterval(() => { pollJobs(); }, 1500); })
    .catch(e => { $('jobStatus').textContent = 'Run failed: ' + e; });
}
function renderLab() {
  // strategy status editor
  fetch('/api/strategies').then(r=>r.json()).then(list => {
    const sel = $('runStrategy');
    sel.innerHTML = '<option value="">(choose…)</option>';
    list.forEach(s => { const o = document.createElement('option'); o.value = s.name; o.textContent = s.name; sel.appendChild(o); });
    $('runHint').textContent = 'Auto config: user_data/config_<strategy>.json if it exists, else config_benchmark.json. Override with the Config field.';
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
        <td><button class="btn compact" data-name="${esc(s.name)}" onclick="saveStrategy(this.dataset.name)">Save</button></td>
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
  setupTableSplitter();
  document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); } });
  populateHistSelect();
  populateTradeRunSelect();
  renderDashboard();
  renderLab();
  updateRunFields();
  defaultRunRange();
  loadLosses();

  // resize charts when the viewport changes
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      ['_historyChart','_sortinoChart','_benchChart','_equityChart','_profitHistChart',
       '_detailEquityChart','_detailHistChart'].forEach(k => {
        if (window[k]) window[k].resize();
      });
      updateAllTableScrolls();
      tryPendingSplits();
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
          <div><b style="color:var(--lavender)">Worst trade</b> ≥ −8% pass · ≥ −15% warn · below flags outlier trades</div>
        </div>
        <div class="hint">Each strategy shows ONE grade from its most recent benchmark run (else latest backtest). A single extreme losing trade (e.g. −15% or worse) flags the Worst trade metric; a −50% outlier also raises a fail recommendation. Click a strategy for the full breakdown and every run.</div>
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
        <span class="hint">profitable windows / total = OOS consistency · click Windows for per-window OOS</span></div>
      <div class="controls">
        <input id="wfFilter" type="text" placeholder="Filter strategy/run..." oninput="renderWalkForward()" style="min-width:220px">
        <span id="wfCount" class="hint"></span>
        <button class="btn" onclick="loadWFDetail(wfSelected||LAB.walkforward[0]?.source||'')">Load latest</button>
      </div>
      <div class="table-wrap"><div id="wf"></div></div>
      <div id="wfDetail" style="display:flex;flex-direction:column;gap:12px"></div>
    </section>
  </div>

  <!-- ============ HYPEROPT ============ -->
  <div class="tab" id="tab-hyperopt">
    <section>
      <div class="section-head"><h2>Hyperopt</h2>
        <span class="hint">best epoch per run · Drill loads top 200 epochs sorted by loss (MAE/exit_eff + corr)</span></div>
      <div class="controls">
        <input id="hoFilter" type="text" placeholder="Filter strategy/loss..." oninput="renderHyperopt()" style="min-width:200px">
        <label>Min trades <input id="hoMinTrades" type="number" value="0" style="width:80px" oninput="hoApplyFilter()"></label>
        <label>Limit <select id="hoLimit" onchange="hoSelected&&loadHOEpochs(hoSelected)"><option value="100">100</option><option value="200" selected>200</option><option value="500">500</option></select></label>
        <select id="hoFiles" style="min-width:200px" onchange="if(this.value) loadHOEpochs(this.value)"><option value="">(pick .fthypt)</option></select>
        <span id="hoCount" class="hint"></span>
      </div>
      <div class="table-wrap"><div id="ho"></div></div>
      <div id="hoDetail" style="display:flex;flex-direction:column;gap:12px;margin-top:8px"></div>
      <p class="hint">Full analysis offline: <code>python user_data/scripts/analyze_hyperopt.py --results user_data/hyperopt_results/strategy_X.fthypt --top 15 --best-params 5</code></p>
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
      <div class="section-head"><h2>Run strategy</h2>
        <span class="hint">backtest / hyperopt / walk-forward for one strategy — requires the web server (lab.py serve)</span></div>
      <div class="card">
        <div class="controls">
          <label>Strategy:
            <select id="runStrategy"><option value="">(choose…)</option></select>
          </label>
          <label>Run:
            <select id="runMode" onchange="updateRunFields()">
              <option value="backtest">Backtest</option>
              <option value="hyperopt">Hyperopt</option>
              <option value="walkforward">Walk-Forward</option>
            </select>
          </label>
          <div class="daterange">
            <label>From: <input id="runStart" type="date"></label>
            <span class="dr-sep" aria-hidden="true">→</span>
            <label>To: <input id="runEnd" type="date"></label>
          </div>
          <label>TF: <input id="runTf" type="text" value="5m" style="width:70px"></label>
          <label data-runfield="hyperopt walkforward" class="hidden">Epochs:
            <input id="runEpochs" type="number" value="100" style="width:90px"></label>
          <label data-runfield="hyperopt walkforward" class="hidden">Loss:
            <input id="runLoss" list="lossList" value="SharpeHyperOptLossDaily">
            <datalist id="lossList"></datalist></label>
          <label data-runfield="hyperopt walkforward" class="hidden">Spaces:
            <input id="runSpaces" value="buy sell roi stoploss trailing" style="min-width:200px"></label>
          <label data-runfield="hyperopt walkforward" class="hidden">Jobs:
            <input id="runJobs" type="number" placeholder="-1" style="width:70px"></label>
          <label data-runfield="hyperopt walkforward" class="hidden">Seed:
            <input id="runRandomState" type="number" placeholder="auto" style="width:90px"></label>
          <label data-runfield="hyperopt walkforward" class="hidden">MinTr:
            <input id="runMinTrades" type="number" placeholder="1" style="width:70px"></label>
          <label data-runfield="hyperopt walkforward" class="hidden"><input type="checkbox" id="runAnalyzePerEpoch"> per-epoch</label>
          <label data-runfield="hyperopt" class="hidden"><input type="checkbox" id="runDisableExport"> no export</label>
          <label data-runfield="hyperopt" class="hidden"><input type="checkbox" id="runPrintAll"> print-all</label>
          <label data-runfield="walkforward" class="hidden">Train d:
            <input id="runTrain" type="number" value="90" style="width:80px"></label>
          <label data-runfield="walkforward" class="hidden">Test d:
            <input id="runTest" type="number" value="7" style="width:70px"></label>
          <label data-runfield="walkforward" class="hidden">Step d:
            <input id="runStep" type="number" value="7" style="width:70px"></label>
          <label data-runfield="walkforward" class="hidden">WF minTr:
            <input id="runWfMinTrades" type="number" placeholder="0" style="width:70px"></label>
          <label data-runfield="walkforward" class="hidden">WF maxDD:
            <input id="runWfMaxDD" type="number" step="0.01" placeholder="0.25" style="width:80px"></label>
          <label>Config: <input id="runConfig" type="text" placeholder="auto (optional)" style="min-width:180px"></label>
          <label><input type="checkbox" id="runRebuild" checked> Rebuild report when done</label>
          <button class="btn primary" onclick="labRun()">▶ Run</button>
          <button class="btn" onclick="labRefresh()">↻ Refresh data</button>
          <button class="btn" onclick="labReport()">Rebuild report</button>
        </div>
        <div id="runHint" class="hint"></div>
        <div id="jobStatus" class="hint">Idle.</div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Benchmark (apples-to-apples)</h2>
        <span class="hint">every strategy on the shared benchmark config</span></div>
      <div class="card">
        <div class="controls">
          <button class="btn" onclick="labBench()">Run benchmark</button>
          <label>Strategies: <input id="benchStrategies" type="text" placeholder="comma separated (empty = all)" style="min-width:220px"></label>
          <label>Range: <input id="benchRange" type="text" value="20230101-20240101" style="width:150px"></label>
          <label>TF: <input id="benchTf" type="text" value="5m" style="width:70px"></label>
        </div>
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
    <div class="section-head"><h2>Diagnostics</h2>
      <span class="hint">streaks, MFE/MAE, payoff & capture — from trade history</span></div>
    <div class="metric-row" id="detailDiagnostics"></div>
    <div id="detailRecommendations" style="display:flex;flex-direction:column;gap:8px"></div>
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

<!-- ============ RUN DRAWER ============ -->
<div id="drawerBackdrop" onclick="closeDrawer()"></div>
<aside id="drawer" aria-hidden="true">
  <div class="drawer-head"></div>
  <div class="drawer-tabs"></div>
  <div class="drawer-body" id="drawerBody"></div>
</aside>

<footer>Strategy Lab · results.db → dashboard.html · ingest_results.py · benchmark_runner.py · build_report.py · server.py</footer>

<script>
const LAB = {data_placeholder};
{js}
init();
applyFromHash();
</script>
</body>
</html>
"""


def build_html(data: dict, conn: sqlite3.Connection | None = None) -> str:
    canonical = canonical_per_strategy(data)
    history = history_series(data)

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

    extras = collect_extras(conn)

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
        "scorecard": SCORECARD,
        "configs": extras["configs"],
        "current_code": extras["current_code"],
        "snapshot_paths": extras["snapshot_paths"],
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
