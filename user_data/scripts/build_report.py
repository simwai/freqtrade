"""build_report.py — generate user_data/analysis/dashboard.html from results.db.

Reads the SQLite database produced by ingest_results.py and writes a single
self-contained HTML dashboard (no server, no build step) using CDN
Tailwind CSS + Apache ECharts with a dark + lavender flexbox theme.

Layout is tabbed:
  Dashboard | Strategies | History | Benchmark | Walk-Forward | Hyperopt | Trades | Lab

Every strategy gets ONE canonical grade (from its latest own-config backtest
run; the benchmark is comparison-only and seeds the grade only for strategies
with no backtest runs). Clicking a strategy opens a detail view with the full
scorecard breakdown, every run, trades, hyperopt and walk-forward data.

Usage:
    python user_data/scripts/build_report.py [--db user_data/analysis/results.db]
                                              [--out user_data/analysis/dashboard.html]
"""

from __future__ import annotations

import argparse
import calendar
import json
import sqlite3
import zipfile
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


USER_DATA = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = USER_DATA / "analysis"

# ---------------------------------------------------------------- scorecard ---

# Outlier thresholds – tuned for futures variance (single-wick sensitivity reduction).
# -15% pass keeps the user's requested band; -25% warn and -60% fail are materially looser
# than the original -8%/-15%/-50% so one liquidation wick does not dominate the grade.
WORST_TRADE_PASS: float = -0.15
WORST_TRADE_WARN: float = -0.25
WORST_TRADE_FAIL: float = -0.60
WORST_TRADE_ROBUST_K: int = 3

SCORECARD = {
    "sortino": {"pass": 1.0, "warn": 0.3, "higher_is_better": True, "label": "Sortino"},
    "calmar": {"pass": 1.0, "warn": 0.3, "higher_is_better": True, "label": "Calmar"},
    "profit_factor": {"pass": 1.2, "warn": 1.0, "higher_is_better": True, "label": "Profit factor"},
    "max_drawdown_account": {"pass": 0.2, "warn": 0.4, "higher_is_better": False, "label": "Max drawdown"},
    "winrate": {"pass": 0.45, "warn": 0.35, "higher_is_better": True, "label": "Win rate"},
    "total_trades": {"pass": 100, "warn": 30, "higher_is_better": True, "label": "Trades"},
    "worst_trade": {"pass": WORST_TRADE_PASS, "warn": WORST_TRADE_WARN, "higher_is_better": True, "label": "Worst trade"},
}

GRADE_EXPLANATION = {
    "A": "5+ metrics pass, none fail",
    "B": "at least 3 metrics pass",
    "C": "exactly 1 metric fails",
    "D": "2 or more metrics fail",
}


def grade_value(value: float | None, spec: dict) -> str:
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
    if counts["pass"] + counts["warn"] + counts["fail"] == 0:
        return "na"
    if counts["fail"] >= 2:
        return "D"
    if counts["fail"] == 1:
        return "C"
    if counts["pass"] >= 5 and counts["fail"] == 0:
        return "A"
    if counts["pass"] >= 3:
        return "B"
    return "C"


def _demote_sole_worst_trade_fail(grades: dict[str, str]) -> list[str]:
    """Desensitization carve-out: a sole worst_trade fail is demoted to warn.

    One wick should not force grade C/D when the other 6 metrics are clean.
    """
    lst = list(grades.values())
    if lst.count("fail") == 1 and grades.get("worst_trade") == "fail":
        return [("warn" if k == "worst_trade" else g) for k, g in grades.items()]
    return lst


def score_strategy(row: dict) -> dict:
    """Compute a scorecard for a single backtest/benchmark row."""
    grades: dict[str, str] = {}
    for key, spec in SCORECARD.items():
        grades[key] = grade_value(row.get(key), spec)
    # A 0-trade run has no evidence - grade na rather than a wall of fake fails
    if not row.get("total_trades"):
        grades = {k: "na" for k in grades}
    # counts and grade both come from the demoted list so display stays consistent
    counted = _demote_sole_worst_trade_fail(grades)
    return {
        "grade": overall_grade(counted),
        "grades": grades,
        "pass_count": counted.count("pass"),
        "warn_count": counted.count("warn"),
        "fail_count": counted.count("fail"),
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
    worst_candidates: list[tuple[float, str | None]] = []
    for t in trades:
        pr = t.get("profit_ratio")
        try:
            pr = float(pr) if pr is not None else 0.0
        except (TypeError, ValueError):
            pr = 0.0
        profit_vals.append(pr)
        worst_candidates.append((pr, t.get("pair")))
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
    # robust worst_trade – desensitized to a single wick (averages worst K)
    worst_trade_robust: float | None = worst_pr
    worst_trade_raw: float | None = worst_pr
    worst_pair_robust: str | None = worst_pair
    if trades and worst_candidates:
        n = len(worst_candidates)
        if n >= 20:
            worst_candidates.sort(key=lambda x: x[0])
            k = min(WORST_TRADE_ROBUST_K, n)
            # average of k worst; keeps -15% threshold meaningful without single-outlier dominance
            worst_slice = [p for p, _ in worst_candidates[:k]]
            worst_trade_robust = sum(worst_slice) / len(worst_slice) if worst_slice else worst_pr
            # pair stays as the single worst for traceability
            worst_pair_robust = worst_candidates[0][1]
        else:
            worst_trade_robust = worst_pr
            worst_pair_robust = worst_pair
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
        "worst_trade": worst_trade_robust if trades else None,
        "worst_trade_pair": worst_pair_robust,
        "worst_trade_raw": worst_trade_raw if trades else None,
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
            """SELECT strategy, source, pair, profit_ratio, open_rate, max_rate, min_rate,
                      is_short, trade_duration, close_date, open_date, profit_abs, amount
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
        pf = evaluate_prop_firms(row, _compute_prop_metrics(trades, _initial_balance(row)))
        row["prop_firms"] = pf
        row["prop_pass"] = sum(1 for p in pf.values() if p["verdict"] == "pass") if pf else 0


def build_recommendations(row: dict) -> list[dict]:
    """Generic actionable recommendations based on graded + derived metrics."""
    # A 0-trade run carries no signal - zeroed metrics would read as failures
    if not row.get("total_trades"):
        return []
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

    # 14. Outlier trade loss – uses desensitized thresholds (-15%/-25%/-60%)
    worst_trade = row.get("worst_trade")
    if worst_trade is not None:
        wpair = row.get("worst_trade_pair") or "?"
        wpct = abs(worst_trade) * 100
        raw = row.get("worst_trade_raw")
        raw_hint = f" (raw worst {raw*100:.1f}%)" if isinstance(raw, (int, float)) and raw != worst_trade else ""
        if worst_trade <= WORST_TRADE_FAIL:
            add("fail", f"Outlier loss −{wpct:.0f}%",
                f"Worst trade {worst_trade*100:.1f}% on {wpair}{raw_hint} — a trade wiped out ~{wpct:.0f}% of stake. Stop/sizing broken; cap risk per trade.")
        elif worst_trade <= WORST_TRADE_WARN:
            add("warn", f"Large single loss −{wpct:.0f}%",
                f"Worst trade {worst_trade*100:.1f}% on {wpair}{raw_hint} — one outlier distorts the grade. Tighten SL or reduce stake on that pair.")

    # 15. Positive but fragile
    if not recs and row.get("score", {}).get("grade") == "A":
        add("good", "Well balanced", "5+ metrics pass, no fail. Check walk-forward OOS next.")

    # Cap to 8 most severe
    order = {"fail": 0, "warn": 1, "info": 2, "good": 3}
    recs.sort(key=lambda r: order.get(r["level"], 9))
    return recs[:8]


# ------------------------------------------------------- prop firm checks ---

# Daily-DD basis variants: FTMO-style resets the reference at CE(S)T midnight,
# Hyro-style trails the intraday high-water mark.
DD_MIDNIGHT_BALANCE = "midnight_balance"
DD_TRAILING_INTRADAY_HIGH = "trailing_intraday_high"

PROP_FIRMS = {
    "ftmo_challenge": {
        "label": "FTMO-Ch", "profit_target": 0.10, "max_daily_loss": 0.05,
        "max_drawdown": 0.10, "min_trading_days": 4, "daily_dd_basis": DD_MIDNIGHT_BALANCE,
    },
    "ftmo_verification": {
        "label": "FTMO-Vf", "profit_target": 0.05, "max_daily_loss": 0.05,
        "max_drawdown": 0.10, "min_trading_days": 4, "daily_dd_basis": DD_MIDNIGHT_BALANCE,
    },
    "kraken_advanced": {
        "label": "KR-Adv", "profit_target": 0.09, "max_daily_loss": 0.03,
        "max_drawdown": 0.03, "min_trading_days": 0, "daily_dd_basis": DD_MIDNIGHT_BALANCE,
    },
    "kraken_intermediate": {
        "label": "KR-Int", "profit_target": 0.12, "max_daily_loss": 0.03,
        "max_drawdown": 0.05, "min_trading_days": 0, "daily_dd_basis": DD_MIDNIGHT_BALANCE,
    },
    "kraken_starter": {
        "label": "KR-Strt", "profit_target": 0.10, "max_daily_loss": 0.03,
        "max_drawdown": 0.06, "min_trading_days": 0, "daily_dd_basis": DD_MIDNIGHT_BALANCE,
    },
    "hyro_standard": {
        "label": "HYRO", "profit_target": 0.10, "max_daily_loss": 0.04,
        "max_drawdown": 0.06, "min_trading_days": 0, "daily_dd_basis": DD_TRAILING_INTRADAY_HIGH,
    },
}

try:
    _PRAGUE = ZoneInfo("Europe/Prague")
except (KeyError, ImportError, OSError):  # pragma: no cover - Windows without tzdata
    _PRAGUE = None


def _eu_dst_active(dt_utc: datetime) -> bool:
    """EU DST rule: last Sunday of March 01:00 UTC to last Sunday of October 01:00 UTC."""
    year = dt_utc.year

    def last_sunday(month: int) -> datetime:
        d = datetime(year, month, calendar.monthrange(year, month)[1], 1, tzinfo=timezone.utc)
        while d.weekday() != 6:
            d -= timedelta(days=1)
        return d

    return last_sunday(3) <= dt_utc < last_sunday(10)


def _prague_date(dt_utc: datetime) -> date:
    if _PRAGUE is not None:
        return dt_utc.astimezone(_PRAGUE).date()
    offset = timedelta(hours=2 if _eu_dst_active(dt_utc) else 1)
    return (dt_utc + offset).date()


def _parse_utc(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _initial_balance(row: dict) -> float | None:
    v = row.get("dry_run_wallet")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return float(v)
    pt, pta = row.get("profit_total"), row.get("profit_total_abs")
    if (isinstance(pt, (int, float)) and isinstance(pta, (int, float))
            and not isinstance(pt, bool) and pt > 0):
        return float(pta) / float(pt)
    return None


def _excursion_loss(t: dict, open_rate: float, amount: float) -> float:
    """Worst-case adverse price excursion of an open trade, as absolute PnL."""
    try:
        if t.get("is_short"):
            mx = t.get("max_rate")
            if mx is not None:
                return max(0.0, (float(mx) - open_rate) * amount)
        else:
            mn = t.get("min_rate")
            if mn is not None:
                return max(0.0, (open_rate - float(mn)) * amount)
    except (TypeError, ValueError):
        pass
    return 0.0


def _parse_trade(t: dict) -> dict | None:
    close = _parse_utc(t.get("close_date"))
    if close is None:
        return None
    try:
        pa = float(t.get("profit_abs") or 0.0)
    except (TypeError, ValueError):
        return None
    open_dt = _parse_utc(t.get("open_date"))
    excursion = 0.0
    try:
        open_rate = float(t.get("open_rate") or 0.0)
        amount = float(t.get("amount") or 0.0)
    except (TypeError, ValueError):
        open_rate, amount = 0.0, 0.0
    if open_dt is not None and open_rate > 0 and amount > 0:
        excursion = _excursion_loss(t, open_rate, amount)
    return {"open": open_dt, "close": close, "pa": pa, "exc": excursion}


def _daily_losses(events: list[tuple[datetime, float]],
                  realized: list[tuple[datetime, float]],
                  initial_balance: float) -> tuple[float, float]:
    """Worst daily loss per basis (fraction of initial balance) over CE(S)T days.

    midnight_balance: day's worst equity vs balance at the preceding midnight;
    trailing_intraday_high: day's worst equity vs the running intraday high.
    """
    day_events: dict[date, list[tuple[datetime, float]]] = {}
    for dt, e in events:
        day_events.setdefault(_prague_date(dt), []).append((dt, e))
    worst_mid = 0.0
    worst_trail_day = 0.0
    ri = 0
    balance = initial_balance
    for d in sorted(day_events):
        while ri < len(realized) and _prague_date(realized[ri][0]) < d:
            balance = realized[ri][1]
            ri += 1
        evs = day_events[d]
        min_e = min(e for _, e in evs)
        worst_mid = max(worst_mid, (balance - min_e) / initial_balance)
        day_hwm = evs[0][1]
        for _, e in evs:
            day_hwm = max(day_hwm, e)
            worst_trail_day = max(worst_trail_day, (day_hwm - e) / initial_balance)
    return worst_mid, worst_trail_day


def _compute_prop_metrics(trades: list[dict], initial_balance: float | None) -> dict | None:
    """Reconstruct an equity event stream from closed trades for prop-firm checks.

    simplify: backtest trade rows have no mark-to-market ticks - open-trade
    excursions are approximated conservatively from min/max rate at open time;
    upgrade path: ingest per-bar equity curves from the backtest output.
    """
    if not trades or not initial_balance or initial_balance <= 0:
        return None
    clean = [p for p in (_parse_trade(t) for t in trades) if p is not None]
    if not clean:
        return None
    clean.sort(key=lambda t: t["close"])
    closes = [t["close"] for t in clean]
    prefix = [0.0]
    for t in clean:
        prefix.append(prefix[-1] + t["pa"])

    # chronological equity events: conservative open-time dips + realized closes
    events: list[tuple[datetime, float]] = []
    for t in clean:
        if t["open"] is not None and t["exc"] > 0:
            n_before = bisect_left(closes, t["open"])
            events.append((t["open"], initial_balance + prefix[n_before] - t["exc"]))
    realized: list[tuple[datetime, float]] = []
    eq = initial_balance
    for t in clean:
        eq += t["pa"]
        realized.append((t["close"], eq))
    events.extend(realized)
    events.sort(key=lambda e: e[0])

    hwm = initial_balance
    dd_trail = 0.0
    dd_initial = 0.0
    for _, e in events:
        hwm = max(hwm, e)
        dd_trail = max(dd_trail, (hwm - e) / initial_balance)
        dd_initial = max(dd_initial, (initial_balance - e) / initial_balance)

    worst_mid, worst_trail_day = _daily_losses(events, realized, initial_balance)

    trading_days = len({_prague_date(dt) for dt, _ in realized})
    day_final: dict[date, float] = {}
    for dt, e in realized:
        day_final[_prague_date(dt)] = e
    daily_realized = [
        {"d": d.isoformat(), "r": day_final[d] / initial_balance - 1.0}
        for d in sorted(day_final)
    ]
    return {
        "worst_daily_loss": {
            DD_MIDNIGHT_BALANCE: worst_mid,
            DD_TRAILING_INTRADAY_HIGH: worst_trail_day,
        },
        "max_dd_from_initial": dd_initial,
        "max_dd_trailing_hwm": dd_trail,
        "trading_days": trading_days,
        "daily_realized": daily_realized,
    }


def _pf_check(name: str, value: float | None, limit: float, status: str,
              fmt: str = "pct", info: int | None = None) -> dict:
    return {"name": name, "value": value, "limit": limit,
            "status": status, "fmt": fmt, "info": info}


def evaluate_prop_firms(row: dict, pm: dict | None) -> dict | None:
    """Verdicts of every PROP_FIRMS program against one run's metrics."""
    out: dict = {}
    profit = row.get("profit_total")
    for key, spec in PROP_FIRMS.items():
        basis = spec["daily_dd_basis"]
        daily_name = ("Daily loss (midnight balance)" if basis == DD_MIDNIGHT_BALANCE
                      else "Daily loss (trading HWM)")
        dd_name = ("Max DD (from initial)" if basis == DD_MIDNIGHT_BALANCE
                   else "Max DD (trailing HWM)")
        if pm is None or profit is None:
            checks = [
                _pf_check("Profit target", None, spec["profit_target"], "na"),
                _pf_check(daily_name, None, spec["max_daily_loss"], "na"),
                _pf_check(dd_name, None, spec["max_drawdown"], "na"),
                _pf_check("Trading days", None, spec["min_trading_days"], "na", fmt="int"),
            ]
        else:
            dtd = next((i + 1 for i, d in enumerate(pm["daily_realized"])
                        if d["r"] >= spec["profit_target"]), None)
            daily_loss = pm["worst_daily_loss"][basis]
            max_dd = (pm["max_dd_from_initial"] if basis == DD_MIDNIGHT_BALANCE
                      else pm["max_dd_trailing_hwm"])
            days = pm["trading_days"]
            min_days = spec["min_trading_days"]
            checks = [
                _pf_check("Profit target", profit, spec["profit_target"],
                          "pass" if profit >= spec["profit_target"] else "fail", info=dtd),
                _pf_check(daily_name, daily_loss, spec["max_daily_loss"],
                          "fail" if daily_loss >= spec["max_daily_loss"] else "pass"),
                _pf_check(dd_name, max_dd, spec["max_drawdown"],
                          "fail" if max_dd >= spec["max_drawdown"] else "pass"),
                _pf_check("Trading days", days, min_days,
                          "na" if min_days == 0 else ("pass" if days >= min_days else "fail"),
                          fmt="int"),
            ]
        statuses = [c["status"] for c in checks]
        if "fail" in statuses:
            verdict = "fail"
        elif "na" in statuses and "pass" not in statuses:
            verdict = "na"
        else:
            verdict = "pass"
        out[key] = {"label": spec["label"], "verdict": verdict, "checks": checks}
    return out


# ------------------------------------------------------------------- queries ---

def load_data(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row

    def score_and_recommend(rows: list[dict]) -> list[dict]:
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


def _fill_ms(d: str) -> int | None:
    """Parse an order fill date (UTC-naive or tz-aware) to epoch ms."""
    s = str(d).replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def compact_trade(t: dict) -> dict:
    out = {}
    for k, short in TRADE_KEYS.items():
        v = t.get(k)
        if isinstance(v, bool):
            v = int(v)
        out[short] = v
    # per-order fills for partial exits / DCA: [ms, price, amount, is_entry]
    oj = t.get("orders_json")
    if oj:
        try:
            fills = json.loads(oj)
        except (ValueError, TypeError):
            fills = None
        if fills:
            px = []
            for d, price, amt, ent in fills:
                ms = _fill_ms(d) if d else None
                if ms is None or price is None:
                    continue
                px.append([ms, price, amt, int(bool(ent))])
            if len(px) > 2:
                out["px"] = px
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
    """One canonical row per strategy, seeded from the `strategies` registry so
    a strategy that has never been ingested still appears in the UI as a
    registry stub (basis="registry", no metrics, no grade). When runs exist, the
    latest own-config backtest wins, else the latest benchmark, else the
    registry stub.

    The canonical row defines the strategy's single grade shown across the UI.
    Benchmarks are a shared-config comparison, not a strategy's own record -
    a 0-trade transplant must not override a healthy backtest. Registry stubs
    are last-resort rows so the Lab editor (the registry's source of truth)
    and the Dashboard (a projection of it) never disagree about which
    strategies exist.
    """
    canonical: dict[str, dict] = {}
    for row in data["backtests"]:
        name = row["strategy"]
        cur = canonical.get(name)
        if cur is None or (row["run_time"] or "") > (cur.get("run_time") or ""):
            r = dict(row)
            r["basis"] = "backtest"
            canonical[name] = r
    # benchmark fallback: strategies that only exist as benchmark runs
    for row in data["benchmarks"]:
        name = row["strategy"]
        if name in canonical:
            continue
        r = dict(row)
        r["basis"] = "benchmark"
        canonical[name] = r
    # registry fallback: every strategy the registry knows about, even if it
    # has never been ingested; carries status + notes for the Lab editor's
    # single source of truth.
    for row in data.get("strategies", []):
        name = row["name"]
        if name in canonical:
            # promote status/notes from the registry onto the existing row
            canonical[name]["status"] = row.get("status") or canonical[name].get("status") or "active"
            canonical[name]["notes"] = row.get("notes") or canonical[name].get("notes") or ""
            continue
        stub = {
            "strategy": name,
            "status": row.get("status") or "active",
            "notes": row.get("notes") or "",
            "basis": "registry",
            "run_time": None,
            "source": None,
            "timerange": None,
            "profit_total": None,
            "sortino": None,
            "calmar": None,
            "profit_factor": None,
            "max_drawdown_account": None,
            "winrate": None,
            "total_trades": None,
            "prop_firms": None,
            "score": {"grade": "—", "grades": {}, "score": 0},
            "recommendations": [],
        }
        canonical[name] = stub
    out = sorted(
        canonical.values(),
        key=lambda r: (
            # registry stubs sort last so they never lead the table
            0 if r.get("basis") in ("backtest", "benchmark") else 1,
            (r.get("score") or {}).get("grade", "—"),
            -(r.get("profit_total") or 0),
        ),
    )
    return out


def history_series(data: dict) -> dict:
    """Per-strategy time series for the per-strategy history charts."""
    series = {}
    for row in data["backtests"]:
        name = row["strategy"]
        rt = row["run_time"]
        if not rt:
            continue
        s = series.setdefault(name, {
            "dates": [], "profit": [], "sortino": [], "trades": [],
            "calmar": [], "profit_factor": [], "max_drawdown": [], "winrate": [],
        })
        s["dates"].append(rt[:10])
        s["profit"].append(round(row.get("profit_total") or 0.0, 4))
        s["sortino"].append(round(row.get("sortino") or 0.0, 2))
        s["trades"].append(row.get("total_trades") or 0)
        s["calmar"].append(round(row.get("calmar") or 0.0, 2))
        s["profit_factor"].append(round(row.get("profit_factor") or 0.0, 3))
        s["max_drawdown"].append(round(row.get("max_drawdown_account") or 0.0, 4))
        s["winrate"].append(round(row.get("winrate") or 0.0, 4))
    return {k: v for k, v in series.items() if len(v["dates"]) >= 2}


def collect_extras(conn: sqlite3.Connection | None) -> dict:
    """Provenance data for the UI: deduped configs, current-code hashes, snapshot index.

    configs            {hash: parsed config}      – embedded once per unique config
    current_code       {strategy: sha1}            – hash of the strategy .py at report build time
    current_code_set   {strategy: sha1}            – combined hash of strategy + all local imports
    snapshot_paths     {hash: {path, mtime}}       – where/when a snapshot was captured
    snapshot_combined  {hash: sha1}                – combined hash captured with the snapshot
    snapshot_files     {hash: [{path, is_main}, …]} – files in the snapshot (main + deps)
    """
    extras = {"configs": {}, "current_code": {}, "current_code_set": {},
              "snapshot_paths": {}, "snapshot_combined": {}, "snapshot_files": {}}
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
        from ft_metrics import current_code_set_hash, find_strategy_file, sha1_text

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
            try:
                extras["current_code_set"][name] = current_code_set_hash(user_data, name)
            except (OSError, SyntaxError):
                continue
    except sqlite3.OperationalError:
        pass
    try:
        for r in conn.execute(
            "SELECT hash, path, mtime, combined_hash FROM strategy_snapshots"
        ):
            extras["snapshot_paths"][r["hash"]] = {
                "path": r["path"],
                "mtime": datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M") if r["mtime"] else None,
            }
            if r["combined_hash"]:
                extras["snapshot_combined"][r["hash"]] = r["combined_hash"]
    except (sqlite3.OperationalError, ValueError, OSError, TypeError):
        pass
    # per-snapshot dep file list (metadata only — source loaded on demand)
    try:
        rows = conn.execute(
            "SELECT s.hash, s.path AS main_path, f.path AS dep_path"
            " FROM strategy_snapshots s"
            " LEFT JOIN strategy_snapshot_files f ON f.hash = s.hash"
            " ORDER BY s.hash, f.path"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    current_hash: str | None = None
    bucket: list[dict] = []
    def flush():
        if current_hash is None:
            return
        extras["snapshot_files"].setdefault(current_hash, bucket)
    for r in rows:
        if r["hash"] != current_hash:
            flush()
            current_hash = r["hash"]
            bucket = [{"path": r["main_path"], "is_main": True}]
        if r["dep_path"]:
            bucket.append({"path": r["dep_path"], "is_main": False})
    flush()
    return extras


def discover_losses(user_data_dir: Path | None = None) -> list[str]:
    """Discover all available hyperopt loss class names without hardcoding.

    Tries the resolver first (builtin + user_data/hyperopts customs), falls back to
    a filesystem scan that parses class names from hyperopt_loss_*.py and
    user_data/hyperopts/*.py. Seeds from HYPEROPT_LOSS_BUILTIN plus the alias
    DefaultHyperOptLoss so offline builds stay complete. Sorted, deduplicated.
    """
    import re

    seed: set[str] = set()
    try:
        from freqtrade.constants import HYPEROPT_LOSS_BUILTIN as _builtin  # type: ignore

        seed.update(_builtin)
        seed.add("DefaultHyperOptLoss")
    except Exception:  # noqa: BLE001
        pass

    # try resolver (authoritative when freqtrade imports work)
    try:
        from freqtrade.resolvers.hyperopt_resolver import HyperOptLossResolver  # type: ignore

        ud = user_data_dir or USER_DATA
        objs = HyperOptLossResolver.search_all_objects(
            {"user_data_dir": ud}, enum_failed=False
        )
        found = {o["name"] for o in objs if o.get("name") and o["name"] != "IHyperOptLoss"}
        if found:
            seed.update(found)
            return sorted(n for n in seed if n != "IHyperOptLoss")
    except Exception:  # noqa: BLE001
        pass

    # filesystem fallback
    pat = re.compile(r"class\s+(\w+HyperOptLoss\w*)\s*\(")
    builtin_dir = Path(__file__).resolve().parents[2] / "freqtrade" / "optimize" / "hyperopt_loss"
    if builtin_dir.is_dir():
        for p in builtin_dir.glob("hyperopt_loss_*.py"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in pat.finditer(text):
                n = m.group(1)
                if n != "IHyperOptLoss":
                    seed.add(n)
    ud = user_data_dir or USER_DATA
    custom_dir = Path(ud) / "hyperopts"
    if custom_dir.is_dir():
        for p in custom_dir.glob("*.py"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in pat.finditer(text):
                n = m.group(1)
                if n != "IHyperOptLoss":
                    seed.add(n)
    return sorted(n for n in seed if n != "IHyperOptLoss")


def extract_backtest_configs(user_data: Path, backtests: list[dict]) -> dict[str, dict]:
    """Extract backtest configs from zip files for each strategy.

    Returns a dict mapping strategy_name -> relevant config subset.
    """
    backtest_results_dir = user_data / "backtest_results"
    if not backtest_results_dir.is_dir():
        return {}

    # Relevant config keys to display (keep JSON small)
    RELEVANT_KEYS = {
        "stake_currency", "stake_amount", "max_open_trades",
        "timeframe", "trading_mode", "margin_mode",
        "minimal_roi", "stoploss", "trailing_stop",
        "trailing_stop_positive", "trailing_stop_positive_offset",
        "trailing_only_offset_is_reached",
        "exchange", "pair_whitelist", "pair_blacklist",
        "dry_run", "dry_run_wallet", "available_capital",
        "entry_pricing", "exit_pricing", "order_types",
        "unfilledtimeout", "use_custom_stoploss",
        "process_only_new_candles", "cancel_open_orders_on_exit",
        "position_adjustment_enable", "max_entry_position_adjustment",
        "amend_last_stake_amount", "last_stake_amount_min_ratio",
        "tradable_balance_ratio", "fiat_display_currency",
    }

    configs = {}
    seen_strategies = set()

    for bt in backtests:
        strategy = bt.get("strategy")
        source = bt.get("source")
        if not strategy or not source:
            continue

        # Skip if we already have config for this strategy (use latest run)
        if strategy in seen_strategies:
            continue

        # Source is typically like "backtest-result-2022-12-08_19-11-00.json"
        # Zip file is the same name but with .zip extension
        zip_name = source.replace(".json", ".zip")
        zip_path = backtest_results_dir / zip_name

        if not zip_path.is_file():
            continue

        # Extract _config.json from zip
        config_name = f"{zip_path.stem}_config.json"
        try:
            with zipfile.ZipFile(zip_path) as zf:
                if config_name in zf.namelist():
                    with zf.open(config_name) as f:
                        full_config = json.load(f)
                        # Filter to relevant keys
                        filtered = {k: v for k, v in full_config.items() if k in RELEVANT_KEYS}
                        configs[strategy] = filtered
                        seen_strategies.add(strategy)
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError):
            continue

    return configs


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
#wf tbody tr, #ho tbody tr { cursor: pointer; }
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
.pill.gna, .pill.na { background: rgba(148,163,184,.12); color: var(--text-faint); }
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

/* history: one chart card per strategy */
.hist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(430px, 1fr)); gap: 14px; }
.hist-grid .chart-box { flex: none; }
.hist-grid .hist-chart { height: 240px; }

/* trade map component (echarts) */
.tl-mount { display: flex; flex-direction: column; gap: 14px; }
.tl-mount .controls { margin-bottom: 2px; }
.tl-mount .chart-box { padding: 14px 10px 8px; }
.tl-mount .tl-chart { height: 360px; }
.tl-mount .tl-osc { height: 110px; margin-top: 6px; }
.tl-mount .tl-fit { position: absolute; left: 16px; bottom: 12px; z-index: 15; }
.tl-mount .legend { margin-top: 10px; }
.tl-mount .tl-empty { background: var(--bg-soft); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 18px; color: var(--text-dim); font-size: 13px;
  line-height: 1.55; }
.tl-mount .tl-empty b { color: var(--warn); }

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

/* lab strategy editor + history select share one dropdown look */
select.statusSel, #histSelect {
  appearance: none; -webkit-appearance: none; -moz-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'%3E%3Cpath d='M2 3h6l-3 4z' fill='%23a89fc4'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 10px center; background-size: 10px;
  background-color: var(--bg-soft);
  border: 1px solid var(--border); border-radius: 8px;
  color: var(--text-dim); padding: 6px 30px 6px 12px; font-size: 13px; font-weight: 500;
  font-family: inherit; cursor: pointer; outline: none; min-width: 132px;
  transition: border-color .15s ease, box-shadow .15s ease;
  color-scheme: dark;
}
select.statusSel:hover, #histSelect:hover { border-color: var(--lavender-ink); }
select.statusSel:focus-visible, #histSelect:focus-visible { border-color: var(--lavender-ink); box-shadow: 0 0 0 3px rgba(109, 91, 208, .18); }
select.statusSel option, #histSelect option { background: var(--bg-soft); color: var(--text); }
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

/* global job bar (visible from any tab) - kept for inline lab status, now also badge */
#globalJobs { background: var(--bg-soft); border-bottom: 1px solid var(--border);
  padding: 8px 24px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 12px; }
#globalJobs.hidden { display: none !important; }
#globalJobs .job-chip { display: inline-flex; gap: 8px; align-items: center;
  background: var(--card); border: 1px solid var(--border); border-radius: 999px; padding: 5px 10px; }
#globalJobs .job-chip .job-name { font-weight: 600; color: var(--text); }
#globalJobs .job-chip .job-log { color: var(--text-dim); max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#globalJobs .job-chip.paused { border-color: rgba(251,191,36,.5); }

/* jobs button badge + modal */
#jobsBtn { position: relative; }
#jobsBtn .badge { display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px;
  background: var(--lavender-ink); color: #fff; font-size: 11px; font-weight: 700;
  margin-left: 4px; vertical-align: middle; }
#jobsBtn .badge.hidden { display: none !important; }
#jobsBtn.has-active { border-color: var(--lavender-ink); }
#jobsBackdrop { position: fixed; inset: 0; background: rgba(10,7,20,.55);
  opacity: 0; pointer-events: none; transition: opacity .2s ease; z-index: 80; }
#jobsBackdrop.open { opacity: 1; pointer-events: auto; }
#jobsModal { position: fixed; left: 50%; top: 50%; transform: translate(-50%,-44%);
  width: min(720px, 96vw); max-height: 84vh; background: var(--bg-soft);
  border: 1px solid var(--border); border-radius: 14px; z-index: 90;
  display: flex; flex-direction: column; opacity: 0; pointer-events: none;
  transition: opacity .18s ease, transform .18s ease; box-shadow: 0 18px 40px rgba(0,0,0,.45); }
#jobsModal.open { opacity: 1; pointer-events: auto; transform: translate(-50%,-50%); }
#jobsModal .jm-head { display: flex; gap: 10px; align-items: center; padding: 12px 14px;
  border-bottom: 1px solid var(--border); }
#jobsModal .jm-head .title { font-weight: 700; }
#jobsModal .jm-body { padding: 12px 14px; overflow: auto; flex: 1; display: flex; flex-direction: column; gap: 16px; }
#jobsModal .jm-section-title { font-size: 12px; font-weight: 600; color: var(--lavender); text-transform: uppercase; letter-spacing: .5px; margin: 0 0 8px; }
#jobsModal .job-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
#jobsModal .job-row.errored { border-color: rgba(248,113,113,.35); }
#jobsModal .job-row .job-id { font-weight: 600; font-size: 13px; }
#jobsModal .job-row .job-cmd { color: var(--text-faint); font-size: 11px; max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#jobsModal .job-row .job-excerpt { color: var(--text-dim); font-size: 12px; flex: 1 1 100%; white-space: pre-wrap; word-break: break-word; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; margin-top: 4px; }

/* log viewer */
#logViewerBackdrop { position: fixed; inset: 0; background: rgba(10,7,20,.55);
  opacity: 0; pointer-events: none; transition: opacity .2s ease; z-index: 80; }
#logViewerBackdrop.open { opacity: 1; pointer-events: auto; }
#logViewer { position: fixed; left: 50%; top: 50%; transform: translate(-50%,-44%);
  width: min(900px, 96vw); max-height: 86vh; background: var(--bg-soft);
  border: 1px solid var(--border); border-radius: 14px; z-index: 90;
  display: flex; flex-direction: column; opacity: 0; pointer-events: none;
  transition: opacity .18s ease, transform .18s ease; box-shadow: 0 18px 40px rgba(0,0,0,.45); }
#logViewer.open { opacity: 1; pointer-events: auto; transform: translate(-50%,-50%); }
#logViewer .lv-head { display: flex; gap: 10px; align-items: center; padding: 12px 14px;
  border-bottom: 1px solid var(--border); }
#logViewer .lv-head .title { font-weight: 700; flex: 1; }
#logViewer .lv-body { padding: 12px 14px; overflow: auto; flex: 1; }
#logViewer pre.log { margin: 0; background: var(--bg); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px; font-size: 12px; line-height: 1.5; white-space: pre-wrap;
  word-break: break-word; font-family: ui-monospace, monospace; color: var(--text-dim); max-height: 64vh; overflow: auto; }

/* grade tuner modal */
#gradeBackdrop { position: fixed; inset: 0; background: rgba(10,7,20,.55);
  opacity: 0; pointer-events: none; transition: opacity .2s ease; z-index: 80; }
#gradeBackdrop.open { opacity: 1; pointer-events: auto; }
#gradeModal { position: fixed; left: 50%; top: 50%; transform: translate(-50%,-44%);
  width: min(640px, 96vw); max-height: 86vh; background: var(--bg-soft);
  border: 1px solid var(--border); border-radius: 14px; z-index: 90;
  display: flex; flex-direction: column; opacity: 0; pointer-events: none;
  transition: opacity .18s ease, transform .18s ease; box-shadow: 0 18px 40px rgba(0,0,0,.45); }
#gradeModal.open { opacity: 1; pointer-events: auto; transform: translate(-50%,-50%); }
#gradeModal .g-head { display: flex; align-items: center; gap: 10px; padding: 12px 14px;
  border-bottom: 1px solid var(--border); }
#gradeModal .g-head .title { font-weight: 700; flex: 1; }
#gradeModal .g-body { padding: 12px 14px; overflow: auto; flex: 1; }
#gradeModal table { width: 100%; }
#gradeModal th, #gradeModal td { padding: 6px 8px; font-size: 13px; }
#gradeModal input[type="number"] { width: 90px; background: var(--bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px; padding: 4px 6px; font: inherit; }
#gradeModal .g-foot { display: flex; gap: 8px; justify-content: flex-end;
  padding: 10px 14px; border-top: 1px solid var(--border); }
#gradeModal .err { color: var(--bad); font-size: 12px; }
"""

# ------------------------------------------------------------------ JS --------

JS = r"""
const state = { tab: 'dashboard', strategy: null, query: '', status: 'all' };
const tradeCache = {};
const candleCache = {};
// Retired strategies are blended out in every tab except the Lab; the Lab
// always shows the full registry so the status editor stays the single
// source of truth. The Strategies tab keeps its own status dropdown (which
// can still surface retired rows), so we skip the visibility filter there
// too.
function visibleCanonical() {
  if (state.tab === 'lab' || state.tab === 'strategies') return LAB.canonical;
  return LAB.canonical.filter(r => (r.status || 'active') !== 'retired');
}

function $(id) { return document.getElementById(id); }
function pill(cls, txt) { return `<span class="pill ${cls}">${txt}</span>`; }
function fmt(v, d=3) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!isFinite(n)) return '—';
  return n.toLocaleString('en-US', {maximumFractionDigits: d});
}
// pf sentinel: optimize_reports emits Infinity when there are no losing trades.
// Render that as "∞" so a no-loss run is distinguishable from a literal 0
// (all-loss) and from a real "—" (missing data).
function pfFmt(v) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (n === Infinity) return '∞';
  if (!isFinite(n)) return '—';
  return n.toLocaleString('en-US', {maximumFractionDigits: 3});
}
function gradePill(g) { return pill('g'+g, g); }
function propPassCount(r) {
  const pf = r.prop_firms;
  if (!pf) return -1;
  const vals = Object.values(pf);
  if (vals.every(p => p.verdict === 'na')) return -1;
  return vals.filter(p => p.verdict === 'pass').length;
}
function propPill(r) {
  const pf = r.prop_firms;
  if (!pf) return pill('na', '—');
  const keys = Object.keys(pf);
  if (!keys.some(k => pf[k].verdict !== 'na')) return pill('na', '—');
  const passed = keys.filter(k => pf[k].verdict === 'pass').length;
  const failed = keys.filter(k => pf[k].verdict === 'fail')
    .map(k => (LAB.prop_firms_spec || {})[k]?.label || k);
  const title = esc(failed.length ? 'failed: ' + failed.join(', ') : 'all programs pass');
  const cls = passed === keys.length ? 'pass' : passed > 0 ? 'warn' : 'fail';
  return `<span title="${title}">${pill(cls, passed + '/' + keys.length)}</span>`;
}
function statusPill(s) {
  if (!s) s = 'active';
  const map = {active:'active', experimental:'experimental', retired:'retired'};
  return `<span class="status ${map[s]||'active'}">${s}</span>`;
}
function pct(v) { return v===null||v===undefined ? '—' : (v*100).toFixed(1)+'%'; }
function esc(s) { return String(s==null?'':s).replace(/[&<>"']/g, c => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

/* ---------- echarts dark theme (tooltips etc.) ---------- */
echarts.registerTheme('lab', {
  backgroundColor: 'transparent',
  tooltip: {
    backgroundColor: '#1b1628',
    borderColor: '#2f2745',
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: '#e9e4f5', fontSize: 12 },
    extraCssText: 'box-shadow: 0 10px 28px rgba(0,0,0,.5); border-radius: 10px;',
    axisPointer: {
      lineStyle: { color: '#3a3254' },
      crossStyle: { color: '#3a3254' },
      shadowStyle: { color: 'rgba(109,91,208,0.12)' },
    },
  },
});
function initChart(el) { return echarts.init(el, 'lab'); }

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
  // auto-refresh report on data-driven tab activation
  if (DATA_TABS.includes(name)) ensureFresh();
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
  // Click handlers are added by attachSort after splitTableScroll moves thead.
  // This avoids duplicate handlers when thead is cloned to the header scroll strip.
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
function fmtRange(tr) {
  if (!tr) return '—';
  const p = String(tr).split('-');
  const d = s => (s && s.length === 8)
    ? `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}` : (s || '?');
  return `${d(p[0])} → ${p[1] ? d(p[1]) : 'live'}`;
}
function basisLabel(r) {
  if (r.basis === 'registry') return 'no runs yet';
  return r.basis === 'benchmark' ? 'benchmark (fallback)' : 'last backtest';
}
function basisTooltip(r) {
  if (r.basis === 'registry') return 'registered in the strategies table; no backtest or benchmark ingested yet';
  return `metrics from ${r.basis === 'benchmark' ? 'benchmark' : 'backtest'}`
    + ` run ${r.source || '?'} · ${r.run_time || '?'}`;
}
function renderDashboard() {
  const rows = visibleCanonical();
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr>
    <th>Strategy</th><th class="num">Grade</th><th class="num">Profit%</th>
    <th class="num">Sortino</th><th class="num">Calmar</th><th class="num">PF</th>
    <th class="num">MaxDD</th><th class="num">Prop</th><th class="num">Win%</th><th class="num">Trades</th>
    <th>Basis</th><th>Range</th><th>Run</th>
  </tr></thead><tbody>` + rows.map(r => {
    const prof = (r.profit_total||0)*100;
    return `<tr>
      <td>${stratLink(r.strategy)} ${statusPill(r.status)}</td>
      <td class="num" data-val="${r.score.grade}">${gradePill(r.score.grade)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt(prof,1)}%</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td>
      <td class="num" data-val="${r.calmar||0}">${fmt(r.calmar)}</td>
      <td class="num" data-val="${r.profit_factor||0}">${pfFmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.max_drawdown_account||0}">${pct(r.max_drawdown_account)}</td>
      <td class="num" data-val="${propPassCount(r)}">${propPill(r)}</td>
      <td class="num" data-val="${r.winrate||0}">${pct(r.winrate)}</td>
      <td class="num" data-val="${r.total_trades||0}">${fmt(r.total_trades,0)}</td>
      <td data-val="${r.basis||''}" title="${esc(basisTooltip(r))}">${r.basis === 'registry' ? '<span class="pill na">no runs yet</span>' : esc(basisLabel(r))}</td>
      <td data-val="${r.timerange||''}" title="${esc(r.timerange||'')}" style="font-size:12px;color:var(--text-dim)">${esc(fmtRange(r.timerange))}</td>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,10))}</td>
    </tr>`;
  }).join('') + '</tbody>';
  const wrap = $('dashboardTable');
  wrap.innerHTML = '';
  wrap.appendChild(t);
  makeSortable(t);

  // what to improve next: skip registry stubs (no metrics, no actionable
  // failure) so the panel surfaces real fixable rows
  const worst = rows
    .filter(r => r.basis !== 'registry' && r.score.grade !== 'A')
    .slice(0, 6);
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
function showConfigForStrategy(name) {
  // Show the config panel in the Lab tab for the selected strategy
  showBacktestConfig(name);
}

function renderStrategies() {
  let rows = visibleCanonical();
  const q = state.query.toLowerCase();
  rows = rows.filter(r => !q || r.strategy.toLowerCase().includes(q));
  if (state.status !== 'all') rows = rows.filter(r => (r.status||'active') === state.status);
  rows.sort((a,b) => (a.strategy||'').localeCompare(b.strategy||''));
  const t = document.createElement('table');
  t.innerHTML = `<thead><tr>
    <th>Strategy</th><th>Status</th><th class="num">Grade</th><th class="num">Trades</th>
    <th class="num">Profit%</th><th class="num">PF</th><th class="num">Sortino</th>
    <th class="num">Calmar</th><th class="num">MaxDD</th><th class="num">Prop</th><th>Basis</th><th>Range</th><th>Run</th><th></th>
  </tr></thead><tbody>` + rows.map(r => {
    return `<tr>
      <td>${stratLink(r.strategy)}</td>
      <td data-val="${r.status||'active'}">${statusPill(r.status)}</td>
      <td class="num" data-val="${r.score.grade}">${gradePill(r.score.grade)}</td>
      <td class="num" data-val="${r.total_trades||0}">${fmt(r.total_trades,0)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt((r.profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.profit_factor||0}">${pfFmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td
      <td class="num" data-val="${r.calmar||0}">${fmt(r.calmar)}</td>
      <td class="num" data-val="${r.max_drawdown_account||0}">${pct(r.max_drawdown_account)}</td>
      <td class="num" data-val="${propPassCount(r)}">${propPill(r)}</td>
      <td data-val="${r.basis||''}" title="${esc(basisTooltip(r))}">${esc(basisLabel(r))}</td>
      <td data-val="${r.timerange||''}" title="${esc(r.timerange||'')}" style="font-size:12px;color:var(--text-dim)">${esc(fmtRange(r.timerange))}</td>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,10))}</td>
      <td>${drawerBtn(r.basis === 'benchmark' ? 'benchmark' : 'backtest', r)}</td>
    </tr>`;
  }).join('') + '</tbody>';
  const wrap = $('strategiesTable');
  wrap.innerHTML = '';
  wrap.appendChild(t);
  makeSortable(t);
}

function showBacktestConfig(strategyName) {
  const config = LAB.backtest_configs?.[strategyName];
  const panel = $('backtestConfigPanel');
  const pre = $('backtestConfigJson');
  if (config) {
    const display = {};
    for (const key of [
      "stake_currency", "stake_amount", "max_open_trades",
      "timeframe", "trading_mode", "margin_mode",
      "minimal_roi", "stoploss", "trailing_stop",
      "trailing_stop_positive", "trailing_stop_positive_offset",
      "trailing_only_offset_is_reached",
      "exchange", "pair_whitelist", "pair_blacklist",
      "dry_run", "dry_run_wallet", "available_capital",
      "entry_pricing", "exit_pricing", "order_types",
      "unfilledtimeout", "use_custom_stoploss",
      "process_only_new_candles", "cancel_open_orders_on_exit",
      "position_adjustment_enable", "max_entry_position_adjustment",
      "amend_last_stake_amount", "last_stake_amount_min_ratio",
      "tradable_balance_ratio", "fiat_display_currency",
    ]) {
      if (config[key] !== undefined) display[key] = config[key];
    }
    pre.textContent = JSON.stringify(display, null, 2);
    panel.style.display = 'block';
  } else {
    panel.style.display = 'none';
  }
}

function toggleConfigPanel() {
  const panel = $('backtestConfigPanel');
  const icon = $('configPanelIcon');
  const isHidden = panel.style.display === 'none';
  panel.style.display = isHidden ? 'block' : 'none';
  icon.textContent = isHidden ? '▲' : '▼';
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
  showBacktestConfig(name);
  const canon = LAB.canonical.find(r => r.strategy === name);
  const allRuns = LAB.backtests.filter(r => r.strategy === name).sort((a,b) =>
    (b.run_time||'').localeCompare(a.run_time||''));
  const benches = LAB.benchmarks.filter(r => r.strategy === name);
  const hos = LAB.hyperopt.filter(r => r.strategy === name);
  const wfs = LAB.walkforward.filter(r => r.strategy === name);

  const head = $('detailHead');
  const canonCode = canon ? { hash: canon.code_hash, verified: canon.code_verified } : null;
  const basisTip = canon ? esc(basisTooltip(canon)) : '';
  const basisBadge = canon
    ? `grade basis: ${esc(basisLabel(canon))} · ${esc((canon.run_time||'').slice(0,16))}`
    : 'grade basis: —';
  head.innerHTML = `
    <button class="btn" onclick="closeStrategy()">← Back</button>
    <div>
      <div class="detail-head">
        <span class="name">${esc(name)}</span>
        ${canon ? gradePill(canon.score.grade) : ''}
        ${statusPill(canon ? canon.status : '')}
        <span class="basis-badge" title="${basisTip}">${basisBadge}</span>
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
    const benchEngaged = benches.filter(r => (r.total_trades||0) > 0)
      .sort((a,b) => (b.run_time||'').localeCompare(a.run_time||''))[0];
    const metricShown = (k, v) => {
      if (k==='winrate'||k==='max_drawdown_account'||k==='worst_trade') return pct(v);
      if (k==='total_trades') return fmt(v,0);
      return fmt(v);
    };
    const benchHead = benchEngaged
      ? '<th class="num">Benchmark</th><th class="num">Bench status</th>' : '';
    sb.innerHTML = `<table><thead><tr><th>Metric</th><th class="num">Value</th>
      <th>Status</th>${benchHead}
      <th class="num">Pass ≥</th><th class="num">Warn ≥</th></tr></thead><tbody>` +
      Object.entries(LAB.scorecard).map(([k, spec]) => {
        const v = canon[k];
        const g = canon.score.grades[k];
        const isPctMetric = k==='max_drawdown_account'||k==='worst_trade';
        const passStr = isPctMetric ? `≤ ${pct(spec.pass)}` : (k==='total_trades' ? fmt(spec.pass,0) : fmt(spec.pass));
        const warnStr = isPctMetric ? `≤ ${pct(spec.warn)}` : (k==='total_trades' ? fmt(spec.warn,0) : fmt(spec.warn));
        let benchCells = '';
        if (benchEngaged) {
          const bg = benchEngaged.score ? (benchEngaged.score.grades[k] || 'na') : 'na';
          benchCells = `<td class="num" data-val="${benchEngaged[k] ?? ''}">`
            + `${metricShown(k, benchEngaged[k])}</td>`
            + `<td data-val="${bg}">${pill(bg,bg)}</td>`;
        }
        return `<tr><td>${spec.label}</td><td class="num">${metricShown(k, v)}</td>`
          + `<td>${pill(g,g)}</td>${benchCells}`
          + `<td class="num">${passStr}</td><td class="num">${warnStr}</td></tr>`;
      }).join('') + '</tbody></table>';
  } else sb.innerHTML = '<p class="hint">No scorecard.</p>';

  // prop firm requirements
  const pp = $('detailProp');
  if (canon && canon.prop_firms) {
    const spec = LAB.prop_firms_spec || {};
    const fmtVal = c => c.fmt === 'int' ? fmt(c.value, 0) : pct(c.value);
    const fmtLim = c => c.fmt === 'int' ? fmt(c.limit, 0) : pct(c.limit);
    const rows = Object.entries(canon.prop_firms).map(([k, p]) => {
      const sp = spec[k] || {};
      const basisTxt = sp.daily_dd_basis === 'trailing_intraday_high'
        ? 'trailing intraday high' : 'midnight balance';
      const cells = p.checks.map(c => {
        const txt = c.status === 'na' ? 'n/a' : `${fmtVal(c)} / ${fmtLim(c)}`;
        const info = c.info != null ? ` <span class="hint" title="first day target reached">d${c.info}</span>` : '';
        return `<td class="num" data-val="${c.status === 'na' ? '' : (c.value ?? '')}">${pill(c.status, txt)}${info}</td>`;
      }).join('');
      return `<tr title="daily-DD basis: ${esc(basisTxt)}">
        <td><b>${esc(p.label)}</b> <span class="hint">${esc(k)}</span></td>${cells}
        <td class="num" data-val="${p.verdict === 'pass' ? 2 : p.verdict === 'fail' ? 0 : 1}">${pill(p.verdict, p.verdict)}</td></tr>`;
    }).join('');
    pp.innerHTML = `<table><thead><tr><th>Program</th><th class="num">Target</th><th class="num">Daily loss</th><th class="num">Max DD</th><th class="num">Min days</th><th class="num">Verdict</th></tr></thead><tbody>${rows}</tbody></table>`;
  } else pp.innerHTML = '<p class="hint">No prop-firm evaluation (missing trades or starting balance).</p>';

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
      ['Worst trade' + (canon.worst_trade_pair ? ` · ${esc(canon.worst_trade_pair)}` : ''), worstTrade, ((canon.worst_trade ?? 0) <= -0.60 ? 'bad' : (canon.worst_trade ?? 0) <= -0.25 ? 'warn' : '')],
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
    <th class="num">MaxDD</th><th class="num">Prop</th><th>TF</th><th>Source</th><th></th></tr></thead><tbody>` +
    allRuns.map(r => `<tr>
      <td data-val="${r.run_time||''}">${esc((r.run_time||'').slice(0,16))}</td>
      <td class="num" data-val="${r.score.grade}">${gradePill(r.score.grade)}</td>
      <td class="num" data-val="${r.profit_total||0}">${fmt((r.profit_total||0)*100,1)}%</td>
      <td class="num" data-val="${r.total_trades||0}">${fmt(r.total_trades,0)}</td>
      <td class="num" data-val="${r.profit_factor||0}">${pfFmt(r.profit_factor)}</td>
      <td class="num" data-val="${r.sortino||0}">${fmt(r.sortino)}</td>
      <td class="num" data-val="${r.max_drawdown_account||0}">${pct(r.max_drawdown_account)}</td>
      <td class="num" data-val="${propPassCount(r)}">${propPill(r)}</td>
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
      <td class="num">${pfFmt(r.profit_factor)}</td><td>${drawerBtn('benchmark', r)}</td></tr>`).join('')
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
        const runRow = (LAB.backtests || []).find(r => r.strategy === name && r.source === run.source)
          || (LAB.benchmarks || []).find(r => r.strategy === name && r.source === run.source);
        tlSetRun(_tmDetail, data, (runRow && runRow.timeframe) || '',
          (runRow && runRow.trading_mode) || '');
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
    else fetch(`trades/${encodeURIComponent(key)}.json?v=${encodeURIComponent(LAB.built || '')}`)
      .then(r => r.ok ? r.json() : null)
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
  // Prefer whole-set (strategy + all local imports) over single-file comparison.
  const setSnap = (LAB.snapshot_combined || {})[info.hash];
  const setCur = (LAB.current_code_set || {})[strategy];
  if (setSnap && setCur) {
    if (setSnap === setCur) return pill(info.verified ? 'pass' : 'warn', info.verified ? 'code current' : 'code current*');
    return pill('fail', 'code changed since run');
  }
  // Fallback: legacy single-file comparison for pre-provenance snapshots.
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
// Per-(hash, file) source cache; key encodes file path so the same hash can
// hold many files.
let _codeCache = {};
function codeKey(hash, file) { return hash + '|' + (file || ''); }
function loadCodeInto(hash, elId, file) {
  const el = $(elId);
  const k = codeKey(hash, file);
  let url = '/api/strategy/file?hash=' + encodeURIComponent(hash);
  if (file) url += '&file=' + encodeURIComponent(file);
  fetch(url)
    .then(r => r.ok ? r.text() : Promise.reject(r.status))
    .then(txt => {
      _codeCache[k] = txt;
      const safe = (file || hash).replace(/[^A-Za-z0-9_]/g, '_').slice(0, 24);
      const display = txt.length > 120000
        ? txt.slice(0, 120000) + '\n… (truncated preview)'
        : txt;
      el.innerHTML = `<pre class="codeblock" id="codePre-${safe}">${esc(display)}</pre>
        <button class="btn compact" onclick="copyText(_codeCache[${escAttr(JSON.stringify(k))}])">Copy code</button>`;
    })
    .catch(() => { el.innerHTML = '<p class="hint">Snapshot viewer needs the server (lab.py serve).</p>'; });
}
function paneCode(r) {
  const strategy = drawerState.ctx.strategy;
  const badge = codeBadge(strategy, { hash: r.code_hash, verified: r.code_verified });
  if (!r.code_hash) return `<p class="hint">No code snapshot for this run.</p>`;
  const meta = (LAB.snapshot_paths || {})[r.code_hash];
  const files = (LAB.snapshot_files || {})[r.code_hash] || [];
  const setCur = (LAB.current_code_set || {})[strategy];
  const setSnap = (LAB.snapshot_combined || {})[r.code_hash];
  const combined = setCur && setSnap;
  const isCurrent = combined ? setCur === setSnap
    : (LAB.current_code || {})[strategy] === r.code_hash;
  const curPath = meta && meta.path;
  const hasDeps = files.length > 1;  // more than just the main file
  const fileChips = hasDeps
    ? `<div class="file-chips" style="margin:6px 0 4px;display:flex;gap:6px;flex-wrap:wrap">
         <span class="hint">Files (${files.length}):</span>
         ${files.map((f, i) => {
           const label = (f.path || '').split(/[\\\\/]/).pop() || f.path;
           const active = i === 0;
            return `<button class="btn compact ${active ? 'primary' : ''}" data-file="${escAttr(f.path)}" onclick="paneCodeSelect(this, ${escAttr(JSON.stringify(r.code_hash))}, ${i})">${esc(label)}</button>`;
         }).join('')}
       </div>`
    : '';
  return `
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      ${badge}
      <span class="hint">snapshot ${esc(r.code_hash.slice(0, 12))}…${meta && meta.mtime ? ' · ' + esc(meta.mtime) : ''}${curPath ? ' · <code>' + esc(curPath) + '</code>' : ''}</span>
    </div>
    ${isCurrent ? '' : '<p class="hint bad">The current code (strategy + imported modules) differs from this snapshot — metrics below reflect the old code.</p>'}
    ${fileChips}
    <div id="dcode-viewer"><button class="btn compact" onclick="loadCodeInto('${escAttr(r.code_hash)}','dcode-viewer', this.dataset.file)">View snapshot source</button> <span class="hint">(loads via server)</span></div>`;
}
// Click handler for the per-file chips. The viewer element is created on
// demand and replaced each click so we can swap button states.
function paneCodeSelect(btn, hash, idx) {
  const files = (LAB.snapshot_files || {})[hash] || [];
  const f = files[idx];
  if (!f) return;
  document.querySelectorAll('#dpane-code .file-chips .btn').forEach(b => b.classList.remove('primary'));
  btn.classList.add('primary');
  const wrap = document.getElementById('dcode-viewer');
  if (!wrap) return;
  const trigger = wrap.querySelector('button');
  if (trigger) trigger.dataset.file = f.path;
  loadCodeInto(hash, 'dcode-viewer', f.path);
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
  // mirror the visibility filter: retired strategies are not selectable
  // outside the Lab tab, so we keep their history series out of the picker
  const names = state.tab === 'lab'
    ? Object.keys(LAB.history)
    : Object.keys(LAB.history).filter(n => {
        const row = (LAB.canonical || []).find(r => r.strategy === n);
        return !row || (row.status || 'active') !== 'retired';
      });
  Object.entries(LAB.history).sort((a,b) => b[1].dates.length - a[1].dates.length)
    .forEach(([name]) => { if (names.includes(name)) {
      const o = document.createElement('option'); o.value = name; o.textContent = name; sel.appendChild(o);
    } });
}
function histSelectAll() { const s=$('histSelect'); [...s.options].forEach(o=>o.selected=true); renderHistory(); }
function histSelectTop() {
  const s=$('histSelect'); [...s.options].forEach(o=>o.selected=false);
  Object.entries(LAB.history).sort((a,b)=>b[1].dates.length-a[1].dates.length).slice(0,8)
    .forEach(([name])=>{ const o=[...s.options].find(x=>x.value===name); if(o)o.selected=true; });
  renderHistory();
}
function histClear() { const s=$('histSelect'); [...s.options].forEach(o=>o.selected=false); renderHistory(); }

/* second metric shown on each history card (persisted like the chart presets) */
const HIST_METRICS2 = {
  sortino: { label: 'Sortino', pct: false },
  calmar: { label: 'Calmar', pct: false },
  profit_factor: { label: 'Profit factor', pct: false },
  max_drawdown: { label: 'Max drawdown', pct: true },
  winrate: { label: 'Win rate', pct: true },
  trades: { label: 'Trades', pct: false },
};
function histMetric2() {
  const v = localStorage.getItem('histMetric2');
  const key = HIST_METRICS2[v] ? v : 'sortino';
  return { key, ...HIST_METRICS2[key] };
}
function histMetric2Set(v) {
  if (HIST_METRICS2[v]) { try { localStorage.setItem('histMetric2', v); } catch (e) {} }
  renderHistory();
}
function renderHistory() {
  const names = histOptions();
  const useLog = $('logScale').checked;
  const m2 = histMetric2();
  const fmtM2 = v => v === null || v === undefined ? '—'
    : (m2.pct ? (v * 100).toFixed(1) + '%' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }));
  const fmtProfit = v => v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%';
  const byD = (p,q) => String(p[0]).localeCompare(String(q[0]));
  const grid = $('histGrid');
  // one chart card per strategy - the combined charts never matched the ask
  (window._histCharts || []).forEach(c => { try { c.dispose(); } catch (e) {} });
  window._histCharts = [];
  if (!names.length) {
    grid.innerHTML = '<p class="hint">No history to chart. Strategies need at least two backtest runs.</p>';
    return;
  }
  grid.innerHTML = names.map((name, i) => {
    const h = LAB.history[name];
    return `<div class="chart-box">
      <div class="section-head" style="margin-bottom:4px"><b>${esc(name)}</b>
        <span class="hint">${h.dates.length} runs</span></div>
      <div class="chart hist-chart" id="histChart-${i}"></div>
    </div>`;
  }).join('');
requestAnimationFrame(() => {
    names.forEach((name, i) => {
      const h = LAB.history[name];
      const profit = h.dates.map((d, j) => {
        let v = h.profit[j]; if (useLog && v <= 0) v = null; return [d, v];
      }).sort(byD);
      const second = h.dates.map((d, j) => [d, h[m2.key][j]]).sort(byD);
      const c = initChart($(`histChart-${i}`));
      c.setOption({ backgroundColor: 'transparent',
        tooltip: { trigger: 'axis',
          formatter: ps => ps.map(p => {
            const v = Array.isArray(p.value) ? p.value[1] : p.value;
            const txt = p.seriesName === 'Profit %' ? fmtProfit(v) : fmtM2(v);
            return `${p.marker} ${esc(p.seriesName)}: <b>${txt}</b>`;
          }).join('<br/>') },
        legend: { textStyle: { color: '#a89fc4' }, top: 0, data: ['Profit %', m2.label] },
        grid: { left: 56, right: 44, top: 28, bottom: 26 },
        xAxis: { type: 'time', axisLabel: { color: '#a89fc4', hideOverlap: true, formatter: '{yyyy}-{MM}-{dd}' }, axisLine: { lineStyle: { color: '#2f2745' } } },
        yAxis: [
          useLog ? { type: 'log', logBase: 10, axisLabel: { color: '#a89fc4', formatter: v => v === 0 ? '0' : (v * 100).toFixed(0) + '%' }, splitLine: { lineStyle: { color: '#241d36' } } }
                   : { type: 'value', scale: true, axisLabel: { color: '#a89fc4', formatter: v => (v * 100).toFixed(0) + '%' }, splitLine: { lineStyle: { color: '#241d36' } } },
          { type: 'value', scale: true, position: 'right', splitLine: { show: false },
            axisLabel: { color: '#a89fc4', formatter: m2.pct ? v => (v * 100).toFixed(0) + '%' : v => Number(v).toLocaleString('en-US', { maximumFractionDigits: 1 }) } },
        ],
        dataZoom: [{ type: 'inside' }],
        series: [
          { name: 'Profit %', type: 'line', showSymbol: true, symbolSize: 6, connectNulls: true,
            data: profit, lineStyle: { color: '#c4b5fd', width: 2 }, itemStyle: { color: '#c4b5fd' } },
          { name: m2.label, type: 'line', yAxisIndex: 1, showSymbol: true, symbolSize: 5,
            data: second, lineStyle: { color: '#74c7ec', width: 1, type: 'dashed' }, itemStyle: { color: '#74c7ec' } },
        ] });
      window._histCharts.push(c);
    });
    // Ensure all charts are properly sized after creation
    setTimeout(() => {
      (window._histCharts || []).forEach(c => { try { c.resize(); } catch (e) {} });
    }, 0);
  });
}

/* ---------- benchmark ---------- */
// quartile split: returns [min, Q1, median, Q3, max] or null when the input is empty
function _benchQuartiles(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const n = s.length;
  const pick = p => s[Math.min(n - 1, Math.max(0, Math.floor(p * (n - 1))))];
  return [s[0], pick(0.25), pick(0.5), pick(0.75), s[n - 1]];
}
// median absolute deviation: robust z-score (k=1.4826 for normal-consistency)
function _benchOutliers(arr) {
  if (arr.length < 4) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const med = s[Math.floor(s.length / 2)];
  const dev = [...arr].map(v => Math.abs(v - med)).sort((a, b) => a - b);
  const mad = dev[Math.floor(dev.length / 2)];
  if (!mad) return 0;
  const k = 1.4826;
  return arr.filter(v => Math.abs(v - med) / (k * mad) > 2.5).length;
}
function renderBenchmark() {
  const el = $('benchChart');
  const metric = $('benchMetric').value;
  const useLog = $('benchLog').checked;
  const sortMode = $('benchSort').value;
  const showPoints = $('benchPoints').checked;
  const sourceMode = ($('benchSource') || { value: 'auto' }).value;

  // Build a per-strategy list of (value, source) pairs. We always include
  // both benchmarks and backtests; a strategy with no benchmark runs
  // simply has no "B" entries. This was the original bug: only 3 of 70+
  // strategies had been benchmarked, so the chart showed 3 rows.
  // Retired strategies are filtered out outside the Lab tab.
  const includeRetired = state.tab === 'lab';
  const isRetired = name => {
    const row = (LAB.canonical || []).find(r => r.strategy === name);
    return !!(row && (row.status || 'active') === 'retired');
  };
  const all = [];
  if (sourceMode === 'auto' || sourceMode === 'benchmark') {
    (LAB.benchmarks || []).forEach(r => { if (includeRetired || !isRetired(r.strategy)) all.push({ ...r, _src: 'B' }); });
  }
  if (sourceMode === 'auto' || sourceMode === 'backtest') {
    (LAB.backtests || []).forEach(r => { if (includeRetired || !isRetired(r.strategy)) all.push({ ...r, _src: 'T' }); });
  }
  // 'auto' prefers benchmark when both exist for a strategy on the same
  // (timerange, timeframe) — keeps benchmark as the cross-strategy anchor.
  // For the per-strategy distribution this just means: keep all entries,
  // but in the summary we report how many are B vs T so the user can see.
  if (!all.length) {
    $('benchHint').textContent = 'No benchmark or backtest runs ingested. Use the Lab tab to run one.';
    el.style.display = 'none';
    return;
  }

  const byStrategy = new Map();
  all.forEach(r => {
    const v = r[metric];
    if (v === null || v === undefined || v === '') return;
    if (!byStrategy.has(r.strategy)) byStrategy.set(r.strategy, []);
    byStrategy.get(r.strategy).push({ value: Number(v), src: r._src });
  });
  if (!byStrategy.size) {
    $('benchHint').textContent =
      `No rows have a value for "${metric}". Pick a different metric or run more strategies.`;
    el.style.display = 'none';
    return;
  }

  const strategies = [...byStrategy.keys()];
  if (sortMode === 'name') strategies.sort();
  else if (sortMode === 'count') {
    strategies.sort((a, b) => byStrategy.get(b).length - byStrategy.get(a).length || a.localeCompare(b));
  } else {
    strategies.sort((a, b) => {
      const ma = _benchQuartiles(byStrategy.get(a))[2];
      const mb = _benchQuartiles(byStrategy.get(b))[2];
      return mb - ma;
    });
  }

  // per-strategy color uses the median against the same pass/warn/fail rules
  // the bar chart used, so the visual is familiar.
  const colorOf = v => {
    if (metric === 'max_drawdown_account') return v <= 0.2 ? '#6ee7a8' : v <= 0.4 ? '#fbbf24' : '#f87171';
    return v >= 1 ? '#6ee7a8' : v >= 0.3 ? '#fbbf24' : '#f87171';
  };

  // each strategy row carries a small tag showing its source mix so the
  // user can spot which strategies are benchmarked vs backtested
  const tagFor = entries => {
    const b = entries.filter(e => e.src === 'B').length;
    const t = entries.filter(e => e.src === 'T').length;
    if (b && t) return 'B+T';
    if (b) return 'B';
    return 'T';
  };

  // metrics.py emits -100 when a metric's denominator is zero (down_stdev,
  // up_stdev, max_drawdown, profits_std). The pf column can also be Infinity
  // for no-loss runs; that one is rendered as "∞" by pfFmt but is still a
  // valid data point for the box plot. Drop only the documented sentinels.
  const SENTINEL_VALUES = {
    sortino: -100,
    sharpe: -100,
    calmar: -100,
    sqn: -100,
  };
  const sentinel = SENTINEL_VALUES[metric];
  const rawBoxData = strategies.map(name => {
    const entries = byStrategy.get(name);
    const filteredEntries = sentinel !== undefined
      ? entries.filter(e => e.value !== sentinel)
      : entries;
    const values = filteredEntries.map(e => e.value);
    const q = _benchQuartiles(values);
    return {
      name, entries: filteredEntries, q,
      color: q ? colorOf(q[2]) : '#8b83a5',
      n: filteredEntries.length, tag: tagFor(entries),
    };
  });
  // drop strategies with no valid values after filtering (e.g. all -100)
  const boxData = rawBoxData.filter(b => b.q !== null);
  const pointData = [];
  if (showPoints) {
    boxData.forEach((b, i) => {
      b.entries.forEach((e, j) => {
        const jitter = ((j % 3) - 1) * 0.12;
        pointData.push([e.value, i + jitter, b.name, j, jitter, colorOf(e.value), e.src]);
      });
    });
  }

  const totalRuns = boxData.reduce((s, b) => s + b.n, 0);
  const totalOut = boxData.reduce((s, b) => s + _benchOutliers(b.entries.map(e => e.value)), 0);
  const benchCount = boxData.filter(b => b.tag === 'B' || b.tag === 'B+T').length;
  const backtestOnly = boxData.length - benchCount;
  const sourceTag = sourceMode === 'benchmark' ? 'benchmark only'
                  : sourceMode === 'backtest'  ? 'backtest only'
                  : `${benchCount} benchmarked · ${backtestOnly} backtest-only`;
  // dynamic height so 70+ strategies don't cram into a fixed-height box (~26px per row)
  const neededH = Math.max(380, boxData.length * 26 + 90);
  el.style.height = neededH + 'px';
  el.style.display = '';
  // log axes cannot display <=0 values - fall back to linear and say why in the hint
  let effectiveUseLog = useLog;
  let logNote = '';
  if (useLog && boxData.some(b => b.q && b.q.some(v => v <= 0))) {
    effectiveUseLog = false;
    logNote = ' · log scale off: values <=0 cannot be shown on a log axis';
  }
  $('benchHint').textContent =
    `${boxData.length} strategies · ${totalRuns} runs · ${totalOut} outlier${totalOut === 1 ? '' : 's'} (|z|>2.5) · ${sourceTag}` + logNote;

  if (window._benchChart && window._benchChart.dispose) { try { window._benchChart.dispose(); } catch (e) {} }
  const c = initChart(el);
  c.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter: p => {
        if (p.seriesType === 'boxplot') {
          const b = boxData[p.dataIndex];
          return `<b>${esc(b.name)}</b> [${b.tag}] · ${b.n} run${b.n === 1 ? '' : 's'}<br/>`
            + `min ${fmt(b.q[0])} · Q1 ${fmt(b.q[1])} · med ${fmt(b.q[2])} · Q3 ${fmt(b.q[3])} · max ${fmt(b.q[4])}`;
        }
        const src = p.data[6];
        return `<b>${esc(p.data[2])}</b> [${src}] · run #${p.data[3] + 1}<br/>value ${fmt(p.data[0])}`;
      },
    },
    grid: { left: 180, right: 60, top: 20, bottom: 40 },
    xAxis: effectiveUseLog
      ? { type: 'log', logBase: 10, axisLabel: { color: '#a89fc4' }, splitLine: { lineStyle: { color: '#241d36' } } }
      : { type: 'value', scale: true, axisLabel: { color: '#a89fc4' }, splitLine: { lineStyle: { color: '#241d36' } } },
    yAxis: {
      type: 'category',
      data: boxData.map(b => b.name),
      axisLabel: { color: '#a89fc4' },
    },
    series: [
      {
        name: metric, type: 'boxplot',
        data: boxData.map(b => b.q),
        itemStyle: { color: 'rgba(167, 139, 250, 0.25)', borderColor: '#a78bfa' },
        tooltip: { formatter: p => {
          const b = boxData[p.dataIndex];
          return `<b>${esc(b.name)}</b> [${b.tag}] · ${b.n} run${b.n === 1 ? '' : 's'}<br/>`
            + `min ${fmt(b.q[0])} · Q1 ${fmt(b.q[1])} · med ${fmt(b.q[2])} · Q3 ${fmt(b.q[3])} · max ${fmt(b.q[4])}`;
        } },
      },
      {
        name: 'median', type: 'scatter',
        symbol: 'diamond', symbolSize: 10,
        data: boxData.map((b, i) => ({ value: [b.q[2], i], itemStyle: { color: b.color, borderColor: '#fff', borderWidth: 1 } })),
        tooltip: { show: false },
      },
      {
        name: 'source', type: 'scatter',
        // small right-side tag column showing the source mix per strategy
        symbol: 'roundRect', symbolSize: [44, 16],
        xAxisIndex: 0, yAxisIndex: 0,
        data: boxData.map((b, i) => ({
          value: [
            // place the tag at the right edge of the data area by using
            // a fixed offset on a numeric x coordinate relative to the
            // visible axis range. ECharts ignores the second axis pair
            // when the series type is scatter with a single yAxis, so we
            // encode the position as (i, NaN) trick: we instead push the
            // tag into a separate right-side yAxis below.
            i, null,
          ],
          // we render the actual tag visually using rich text overlay via
          // graphic components rather than this series; this series is a
          // placeholder so the legend has a stable "source" key.
        })),
        tooltip: { show: false },
        silent: true,
        showInLegend: false,
        legendHoverLink: false,
      },
      ...(showPoints ? [{
        name: 'runs', type: 'scatter',
        symbolSize: 6, symbol: 'circle',
        data: pointData,
        itemStyle: {
          color: p => p.data[5],
          opacity: 0.6,
          borderColor: '#1a1430', borderWidth: 0.5,
        },
        tooltip: { formatter: p => `<b>${esc(p.data[2])}</b> [${p.data[6]}] · run #${p.data[3] + 1}<br/>value ${fmt(p.data[0])}` },
      }] : []),
    ],
  });

  // overlay source tags on each y-axis row using ECharts graphic elements.
  // This is the cleanest way to add a per-row label without inventing a
  // second yAxis layout.
  const tags = boxData.map((b, i) => ({
    type: 'group',
    children: [{
      type: 'text',
      right: 6,
      top: 0,
      style: {
        text: b.tag,
        fill: b.tag === 'B' || b.tag === 'B+T' ? '#a78bfa' : '#a89fc4',
        font: '11px ui-monospace, monospace',
        textAlign: 'right',
        textVerticalAlign: 'middle',
      },
    }],
    position: [el.clientWidth - 30, 0],
    // place one group per row by setting y via a transform tied to the
    // pixel mapping of the yAxis; ECharts graphic doesn't expose that
    // directly, so we approximate with categoryIndex-based positioning.
    $action: 'merge',
    _yIndex: i,
  }));
  // Use chart coordToPixel for accurate placement
  const yAxis = c.getOption().yAxis;
  const tagWidth = 44;
  const tagGap = 4;
  const positioned = tags.map(g => {
    const py = c.convertToPixel({ yAxisIndex: 0 }, [0, g._yIndex]);
    return {
      ...g,
      position: [el.clientWidth - tagWidth - tagGap, typeof py === 'number' ? py : 0],
    };
  });
  c.setOption({ graphic: positioned });

  // re-position tags on resize so they stay anchored to the row labels
  if (!window._benchTagResizeHooked) {
    window._benchTagResizeHooked = true;
    const reposition = () => {
      const chart = window._benchChart;
      if (!chart) return;
      const node = chart.getOption().graphic || [];
      chart.setOption({ graphic: node.map(g => {
        if (typeof g._yIndex !== 'number') return g;
        const py = chart.convertToPixel({ yAxisIndex: 0 }, [0, g._yIndex]);
        return { ...g, position: [el.clientWidth - tagWidth - tagGap, typeof py === 'number' ? py : 0] };
      }) });
    };
    window.addEventListener('resize', () => { if (window._benchChart) window._benchChart.resize(); reposition(); });
  }
  window._benchChart = c;
}

/* ---------- walk-forward ---------- */
let wfSelected = null;
function renderWalkForward() {
  const includeRetired = state.tab === 'lab';
  const isRetired = name => {
    const row = (LAB.canonical || []).find(r => r.strategy === name);
    return !!(row && (row.status || 'active') === 'retired');
  };
  const rows = includeRetired ? LAB.walkforward : LAB.walkforward.filter(r => !isRetired(r.strategy));
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
      return `<tr${sel} data-source="${esc(r.source)}"
        onclick="rowDrill(event,this,loadWFDetail)">
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
      if (window._wfChart && window._wfChart.dispose) { try { window._wfChart.dispose(); } catch (e) {} }
      const c = initChart($(chartId));
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
function rowDrill(e, tr, fn) {
  if (e.target.closest('a,button')) return;
  fn(tr.dataset.source);
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
  const includeRetired = state.tab === 'lab';
  const isRetired = name => {
    const row = (LAB.canonical || []).find(r => r.strategy === name);
    return !!(row && (row.status || 'active') === 'retired');
  };
  const rows = includeRetired ? LAB.hyperopt : LAB.hyperopt.filter(r => !isRetired(r.strategy));
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
    filtered.slice(0,60).map(r => `<tr${hoSelected===r.source?' style="background:var(--card-hover)"':''} data-source="${esc(r.source)}" onclick="rowDrill(event,this,loadHOEpochs)">
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
      <td class="num" data-val="${r.profit_factor||0}">${pfFmt(r.profit_factor)}</td>
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
        if (window._hoChart && window._hoChart.dispose) { try { window._hoChart.dispose(); } catch (e) {} }
        const c = initChart($(chartId));
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
let _renderedTradeData = null;
function loadTradeRun() {
  const sel = $('tradeRun'), status = $('tradeStatus');
  if (!sel.value) return;
  const key = sel.value;
  status.textContent = 'Loading…';
  // re-rendering the identical payload disposes + recreates the echarts on
  // every freshness auto-reload - that was the trades-tab blink
  if (tradeCache[key]) {
    if (tradeCache[key] !== _renderedTradeData) {
      renderTrades(tradeCache[key]); _renderedTradeData = tradeCache[key];
    }
    status.textContent = ''; return;
  }
  if (LAB.embedded_trades && LAB.embedded_trades.key === key) {
    tradeCache[key] = LAB.embedded_trades;
    if (LAB.embedded_trades !== _renderedTradeData) {
      renderTrades(LAB.embedded_trades); _renderedTradeData = LAB.embedded_trades;
    }
    status.textContent = ''; return;
  }
  const bust = encodeURIComponent(LAB.built || '');
  fetch(`trades/${encodeURIComponent(key)}.json?v=${bust}`)
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(d => {
      tradeCache[key] = d;
      try { renderTrades(d); _renderedTradeData = d; status.textContent = ''; }
      catch (err) {
        status.textContent = 'render failed: ' + err.message;
        console.error('renderTrades failed for ' + key, err);
      }
    })
    .catch(() => { status.textContent = 'Could not load trades — open via lab.py serve.'; });
}
function renderTradesTab() {
  if (!LAB.trade_runs.length) { $('trades').innerHTML = '<p class="hint">No trades ingested.</p>'; return; }
  // auto-pick the newest run so the user does not have to click Load
  const sel = $('tradeRun');
  if (sel && !sel.value) {
    const runs = [...LAB.trade_runs].sort((a, b) => (b.run_time || '').localeCompare(a.run_time || ''));
    if (runs.length) sel.value = runs[0].key;
  }
  loadTradeRun();
}
function tradeSide(t) { return t.s ? 'short' : 'long'; }
function renderTrades(data) {
  renderEquity(data.trades);
  renderProfitHist(data.trades);
  const runRow = (LAB.backtests || []).find(r => r.strategy === data.strategy && r.source === data.source)
    || (LAB.benchmarks || []).find(r => r.strategy === data.strategy && r.source === data.source);
  tlSetRun(_tmTab, data, (runRow && runRow.timeframe) || '', (runRow && runRow.trading_mode) || '');
  renderTradeTable(data, $('tradesTable'));
}
function renderEquity(trades, elId, storeKey) {
  elId = elId || 'equityChart';
  storeKey = storeKey || '_equityChart';
  if (window[storeKey] && window[storeKey].dispose) { try { window[storeKey].dispose(); } catch (e) {} }
  const c = initChart($(elId));
  // sort by close time before plotting - chart order must not depend on payload order
  const chrono = [...trades].filter(t => t && t.c)
    .sort((a, b) => String(a.c).localeCompare(String(b.c)));
  let cum = 0;
  const points = [];
  chrono.forEach(t => { cum += (t.pa||0); points.push([t.c, Math.round(cum*100)/100]); });
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
  if (window[storeKey] && window[storeKey].dispose) { try { window[storeKey].dispose(); } catch (e) {} }
  const c = initChart($(elId));
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

/* ---------- trade map: entries/exits per pair ---------- */
const TL_CANDLE_PRESETS = {
  lab: { name: 'Lab (default)',
    up: 'rgba(0,212,170,0.45)', upB: '#00d4aa',
    down: 'rgba(255,71,87,0.45)', downB: '#ff4757' },
  tv: { name: 'TradingView',
    up: 'rgba(38,166,154,0.9)', upB: '#26a69a',
    down: 'rgba(239,83,80,0.9)', downB: '#ef5350' },
  classic: { name: 'Classic',
    up: 'rgba(16,185,129,0.95)', upB: '#10b981',
    down: 'rgba(239,68,68,0.95)', downB: '#ef4444' },
  ghost: { name: 'Ghost (dim)',
    up: 'rgba(0,212,170,0.22)', upB: '#00d4aa',
    down: 'rgba(255,71,87,0.10)', downB: '#ff4757' },
  // 80s RETRO - Mint & Rajah
  mint: { name: 'Mint & Rajah',
    up: 'rgba(0,255,136,0.85)', upB: '#00ff88',
    down: 'rgba(255,51,102,0.85)', downB: '#ff3366' },
  // 80s RETRO - Cyan & Pink
  cyanpink: { name: 'Cyan & Pink',
    up: 'rgba(0,255,255,0.85)', upB: '#00ffff',
    down: 'rgba(255,0,127,0.85)', downB: '#ff007f' },
};
// one colour per marker kind - entries all share entLong, exits all share
// exit; profitability is never encoded in marker colour
const TL_MARKER_PRESETS = {
  lab: { 
    name: 'Lab (default)', 
    win: '#00d4aa', loss: '#ff4757', 
    entLong: '#00d4aa', entShort: '#ff4757', exit: '#ffd60a' 
  },
  tv: { 
    name: 'TradingView', 
    win: '#26a69a', loss: '#ef5350', 
    entLong: '#26a69a', entShort: '#ef5350', exit: '#ffd60a' 
  },
  classic: { 
    name: 'Classic', 
    win: '#10b981', loss: '#ef4444', 
    entLong: '#10b981', entShort: '#ef4444', exit: '#ffd60a' 
  },
  ghost: { 
    name: 'Ghost (dim)', 
    win: '#00d4aa', loss: '#ff4757', 
    entLong: '#00d4aa', entShort: '#ff4757', exit: '#ffd60a' 
  },
  // 80s RETRO - Mint & Rajah: Miami Vice / vaporwave
  mint: { 
    name: 'Mint & Rajah', 
    win: '#00ff88', loss: '#ff3366', 
    entLong: '#00ff88', entShort: '#ff3366', exit: '#ffff00' 
  },
  // 80s RETRO - Cyan & Pink: Tron / synthwave / neon nights
  cyanpink: { 
    name: 'Cyan & Pink', 
    win: '#00ffff', loss: '#ff007f', 
    entLong: '#00ffff', entShort: '#ff007f', exit: '#ffcc00' 
  },
};
function tlCandleColors() {
  const v = localStorage.getItem('tlCandlePreset');
  return TL_CANDLE_PRESETS[v] || TL_CANDLE_PRESETS.lab;
}
// exit-dot colour by exit reason. keeps take-profit exits visually distinct
// from stop-loss / trailing, so the user can see at a glance which trades
// were closed by their take-profit level
const EXIT_PAL = {
  // take-profit: green (long win)
  roi: '#00d4aa',
  // trailing stop: amber (neutral)
  trailing: '#ffd60a',
  // stop-loss + liquidation: red (short loss)
  stop_loss: '#ff4757', liquidation: '#ff4757',
  // signal-based exit: green (long)
  signal: '#00d4aa',
  // forced / delisted / unknown-other: red (short)
  force: '#ff4757', delist: '#ff4757', exit_signal: '#00d4aa',
  // fallback
  unknown: '#a89fc4',
};
function tlExitColor(t, mc) {
  const style = localStorage.getItem('tlExitStyle') || 'by_reason';
  if (style === 'single') return mc.exit;
  if (style === 'win_loss') return (t.pr || 0) >= 0 ? mc.win : mc.loss;
  // by_reason
  const key = String(t.e || '').toLowerCase();
  return EXIT_PAL[key] || EXIT_PAL.unknown;
}
function tpPriceForTrade(t, roi) {
  // minimal_roi keys are minutes-from-open, values are decimal profit targets
  // (e.g. 0.259 = 25.9%). Find the smallest key >= trade duration; fall back
  // to the largest key if the trade outlasted the table. A target of 0
  // means breakeven.
  if (!roi) return null;
  const minutes = Math.max(0, Math.floor((t.d || 0) / 60));
  const keys = Object.keys(roi).map(k => Number(k)).filter(n => Number.isFinite(n)).sort((a, b) => a - b);
  if (!keys.length) return null;
  let chosen = keys[0];
  for (const k of keys) if (k <= minutes) chosen = k; else break;
  const target = Number(roi[String(chosen)] || 0);
  if (target <= 0) return null;
  const or = Number(t.or);
  if (!Number.isFinite(or) || or <= 0) return null;
  return t.s ? or * (1 - target) : or * (1 + target);
}
function tlColors() {
  const v = localStorage.getItem('tlMarkerPreset');
  return TL_MARKER_PRESETS[v] || TL_MARKER_PRESETS.lab;
}
function tlMarkMode() { return localStorage.getItem('tlMark') === 'hilo' ? 'hilo' : 'rate'; }
function tlSyncSelects() {
  const cv = localStorage.getItem('tlCandlePreset') || 'lab';
  const mv = localStorage.getItem('tlMarkerPreset') || 'lab';
  const pm = tlMarkMode();
  const xs = localStorage.getItem('tlExitStyle') || 'by_reason';
  document.querySelectorAll('.tl-candle-sel').forEach(s => { s.value = cv; });
  document.querySelectorAll('.tl-marker-sel').forEach(s => { s.value = mv; });
  document.querySelectorAll('.tl-mark-sel').forEach(s => { s.value = pm; });
  document.querySelectorAll('.tl-exit-sel').forEach(s => { s.value = xs; });
  document.querySelectorAll('.tl-sw-long').forEach(s => {
    s.style.background = tlColors().entLong;
  });
  document.querySelectorAll('.tl-sw-exit').forEach(s => { s.style.background = tlColors().exit });
}
// preset changes only need a repaint - tlRender would re-derive pairs/reasons.
// Instances expose no paint() wrapper; tlPaint is the entry point and needs
// loaded candles.
function tlRepaintAll() {
  _tlInstances.forEach(i => { if (i.candles.length) tlPaint(i); });
}
function tlCandleSet(v) {
  if (TL_CANDLE_PRESETS[v]) { try { localStorage.setItem('tlCandlePreset', v); } catch (e) {} }
  tlSyncSelects();
  tlRepaintAll();
}
function tlMarkerSet(v) {
  if (TL_MARKER_PRESETS[v]) { try { localStorage.setItem('tlMarkerPreset', v); } catch (e) {} }
  tlSyncSelects();
  tlRepaintAll();
}
function tlMarkSet(v) {
  try { localStorage.setItem('tlMark', v); } catch (e) {}
  tlSyncSelects();
  tlRepaintAll();
}
function tlExitStyleSet(v) {
  try { localStorage.setItem('tlExitStyle', v); } catch (e) {}
  tlRepaintAll();
}
function tlPresetInit() {
  document.querySelectorAll('.tl-candle-sel').forEach(s => {
    s.innerHTML = Object.entries(TL_CANDLE_PRESETS)
      .map(([k, p]) => `<option value="${k}">${esc(p.name)}</option>`).join('');
  });
  document.querySelectorAll('.tl-marker-sel').forEach(s => {
    s.innerHTML = Object.entries(TL_MARKER_PRESETS)
      .map(([k, p]) => `<option value="${k}">${esc(p.name)}</option>`).join('');
  });
  tlSyncSelects();
}
function tradeMs(s) {
  // trade dates are UTC-naive in the DB - without a Z suffix browsers parse
  // them as local time and every overlay shifts by the TZ offset
  const v = String(s).replace(' ', 'T');
  return Date.parse(/[Z+]/.test(v.slice(-6)) ? v : v + 'Z');
}
function tlBisect(times, ms) {
  let lo = 0, hi = times.length - 1;
  if (ms <= times[0]) return 0;
  if (ms >= times[hi]) return hi;
  while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (times[mid] <= ms) lo = mid; else hi = mid; }
  return lo;
}
// ---- reusable Trade map on ECharts (canvas - fast at any zoom) ----
// marker kinds: 0 long entry (up triangle below), 1 short entry (down triangle
// above), 2 long exit (circle above + label), 3 short exit (circle below)
function getContrastColor(hex) {
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  const luminance = 0.299*r + 0.587*g + 0.114*b;
  return luminance > 128 ? '#1b1628' : '#e9e4f5';
}
// marker kinds: 0 long entry (up triangle below), 1 short entry (down triangle
// above), 2 long exit (circle above + label), 3 short exit (circle below)
function tmMarkerItem(params, api) {
  const p = api.coord([api.value(0), api.value(1)]);
  const kind = api.value(2), color = api.value(3), txt = api.value(4);
  const s = 7;
  if (kind === 0) return { type: 'polygon',
    shape: { points: [[p[0], p[1]], [p[0] - s, p[1] + s * 1.7], [p[0] + s, p[1] + s * 1.7]] },
    style: { fill: color } };
  if (kind === 1) return { type: 'polygon',
    shape: { points: [[p[0], p[1]], [p[0] - s, p[1] - s * 1.7], [p[0] + s, p[1] - s * 1.7]] },
    style: { fill: color } };
  return { type: 'circle', shape: { cx: p[0], cy: p[1], r: 5 },
    style: { fill: color, stroke: '#1b1628', lineWidth: 1 },
    textContent: { style: { text: txt, fill: getContrastColor(color), fontSize: 10, fontWeight: 600 } },
    textConfig: { position: kind === 2 ? 'top' : 'bottom', distance: 4 } };
}
function tmVisibleSpan(inst) {
  if (!inst.candles.length) return 0;
  const opt = inst.chart.getOption();
  const dz = opt && opt.dataZoom && opt.dataZoom[0];
  const first = inst.candles[0][0], last = inst.candles[inst.candles.length - 1][0];
  if (!dz) return last - first;
  if (dz.startValue != null && dz.endValue != null) {
    return Math.max(0, Number(dz.endValue) - Number(dz.startValue));
  }
  const s = dz.start == null ? 0 : dz.start, e = dz.end == null ? 100 : dz.end;
  return Math.max(0, (last - first) * (e - s) / 100);
}
// Ehlers 2-pole Super Smoother - removes the per-candle jag of the hilo
// tracks while keeping turning points; period adapts to segment length so
// short trades stay recognizable
function tmSuperSmoother(p) {
  const n = p.length;
  if (n < 5) return p.slice();
  const period = Math.max(3, Math.min(10, Math.round(n / 3)));
  const a1 = Math.exp(-1.414 * Math.PI / period);
  const b1 = 2 * a1 * Math.cos(1.414 * Math.PI / period);
  const c2 = b1, c3 = -a1 * a1, c1 = 1 - c2 - c3;
  const out = p.slice();
  for (let i = 2; i < n; i++) {
    out[i] = c1 * (p[i] + p[i - 1]) / 2 + c2 * out[i - 1] + c3 * out[i - 2];
  }
  return out;
}
function tmLineSeries(extra) {
  return Object.assign({ type: 'line', showSymbol: false, silent: true,
    emphasis: { disabled: true }, lineStyle: { width: 2 } }, extra);
}
// fixed series slots 0-7 (candles, volume, under, over, rate win, rate loss,
// SL, markers) keep setOption merge indices stable; indicator overlays append
function tmBaseSeries() {
  const cp = tlCandleColors(), mc = tlColors();
  return [
    { type: 'candlestick', z: 2,
      itemStyle: { color: cp.up, color0: cp.down, borderColor: cp.upB, borderColor0: cp.downB } },
    { type: 'bar', yAxisIndex: 1, z: 1, silent: true },
    tmLineSeries({ lineStyle: { width: 2, color: mc.entLong } }),
    tmLineSeries({ lineStyle: { width: 2, color: mc.entShort } }),
    tmLineSeries({ lineStyle: { width: 2, color: mc.entLong } }),
    tmLineSeries({ lineStyle: { width: 2, color: mc.entShort } }),
    { type: 'line', showSymbol: false, silent: true, z: 3,
      lineStyle: { width: 2, type: 'dashed', color: mc.loss } },
    { type: 'custom', z: 12, silent: true, renderItem: tmMarkerItem, encode: { x: 0, y: 1 } },
  ];
}
function tmTooltipFormatter(inst) {
  return params => {
    const p = (params || []).find(x => x.seriesType === 'candlestick');
    if (!p) return '';
    const ms = Math.round(p.axisValue);
    let html = '';
    const k = inst.candles[tlBisect(inst.times, ms)];
    if (k && Math.abs(k[0] - ms) < 12 * 3600e3) {
      const dt = new Date(k[0]).toISOString().slice(0, 16).replace('T', ' ');
      html += `<b>${dt}</b><br/>O ${fmt(k[1])} H ${fmt(k[2])}<br/>` +
        `L ${fmt(k[3])} C ${fmt(k[4])}<br/>`;
    }
    inst.shown.filter(t => tradeMs(t.o) <= ms && tradeMs(t.c) >= ms).slice(0, 6).forEach(t => {
      const pc = (t.pr || 0) >= 0 ? tlColors().win : tlColors().loss;
      html += `<hr style="border:0;border-top:1px solid #2f2745;margin:4px 0" />` +
        `<b>${esc(t.p)}</b> ${t.s ? 'short' : 'long'} | ${esc(t.e || 'unknown')}<br/>` +
        `${fmt(t.or)} -> ${fmt(t.cr)} | <b style="color:${pc}">${((t.pr || 0) * 100).toFixed(2)}%</b>`;
    });
    return html;
  };
}
/* ---------- TradeMap class: reusable trade map component ---------- */
class TradeMap {
  constructor(mountId, options = {}) {
    this.mountId = mountId;
    this.options = Object.assign({
      showLegend: true,
      showControls: true,
      syncGroup: 'tm-' + mountId,
      onPairChange: null,
      onRender: null,
    }, options);
    
    this.mount = document.getElementById(mountId);
    if (!this.mount) return;
    
    this._init();
  }
  
  _init() {
    this.mount.classList.add('tl-mount');
    this.mount.innerHTML = this._getTemplate();
    
    this.chartEl = this.mount.querySelector('.tl-chart');
    this.pairSel = this.mount.querySelector('.tl-pair');
    this.reasonSel = this.mount.querySelector('.tl-reason');
    this.candleSel = this.mount.querySelector('.tl-candle-sel');
    this.markerSel = this.mount.querySelector('.tl-marker-sel');
    this.markSel = this.mount.querySelector('.tl-mark-sel');
    this.exitSel = this.mount.querySelector('.tl-exit-sel');
    this.indSel = this.mount.querySelector('.tl-ind-sel');
    this.fitBtn = this.mount.querySelector('.tl-fit');
    
    // Instance state
    this.trades = [];
    this.shown = [];
    this.pair = null;
    this.tf = '5m';
    this.mode = '';
    this.runKey = null;
    this.candles = [];
    this.times = [];
    this.loadSeq = 0;
    this.zoomSeq = 0;
    this.appliedZoom = null;
    this.zt = null;
    this.inds = [];
    this.indSeq = 0;
    this.lastPair = null;
    this.fitted = false;
    this.roi = null;
    this.group = this.options.syncGroup;
    
    this._initChart();
    this._bindEvents();
    this._initControls();
    
    TradeMap._instances.push(this);
  }
  
  _getTemplate() {
    const showControls = this.options.showControls;
    const showLegend = this.options.showLegend;
    return `
      <div class="section-head"><h2>Trade map</h2>
        <span class="hint">one marker line per trade - long runs below the price,
        short above it, entry to exit (both marker modes) - entry arrows + exit
        dots in fixed colours, dashed line = initial stop loss</span></div>
      ${showControls ? `
      <div class="controls">
        <label>Pair: <select class="tl-pair" style="min-width:200px"></select></label>
        <label>Exit reason: <select class="tl-reason" style="min-width:180px"></select></label>
        <label>Candles: <select class="tl-candle-sel"></select></label>
        <label>Markers: <select class="tl-marker-sel"></select></label>
        <label>Exits: <select class="tl-exit-sel">
          <option value="by_reason">By reason</option>
          <option value="win_loss">Win / loss</option>
          <option value="single">Single</option>
        </select></label>
        <label>Tracks: <select class="tl-mark-sel">
          <option value="hilo">Beside candles</option>
          <option value="rate">At trade rates</option>
        </select></label>
        <label>Indicators: <select class="tl-ind-sel">
          <option value="">+ add</option>
        </select></label>
      </div>` : ''}
      <div class="chart-box" style="position:relative">
        <div class="tl-chart"></div>
        <button class="btn compact tl-fit">Fit</button>
      </div>
      ${showLegend ? `
      <div class="legend">
        <span class="tl-chips" style="display:contents"></span>
        <span><span class="sw tl-sw-long" style="background:#00d4aa"></span>
          entry (↑ long · ↓ short)</span>
        <span><span class="sw tl-sw-exit" style="background:#ffd60a"></span>exit</span>
        <span><span class="sw tl-sw-exit-reason" data-reason="roi"
          style="background:#00d4aa"></span>tp (roi)</span>
        <span><span class="sw tl-sw-exit-reason" data-reason="trailing"
          style="background:#ffd60a"></span>trailing</span>
        <span><span class="sw tl-sw-exit-reason" data-reason="stop_loss"
          style="background:#ff4757"></span>stop / liq</span>
        <span><span class="sw tl-sw-exit-reason" data-reason="signal"
          style="background:#00d4aa"></span>signal</span>
        <span><span class="sw tl-sw-exit-reason" data-reason="force"
          style="background:#ff4757"></span>force / other</span>
        <span><span class="sw" style="background:transparent;border-top:2px dashed #ff4757">
          </span>initial stop loss</span>
        <span><span class="sw tl-sw-tp" style="background:transparent;
          border-top:2px solid #00d4aa"></span>take-profit level</span>
        <span><span class="sw" style="background:rgba(167,139,250,0.4)"></span>volume</span>
      </div>` : ''}
    `;
  }
  
  _initChart() {
    this.chart = initChart(this.chartEl);
    this.chart.group = this.group;
    echarts.connect(this.group);
    
    // Oscillator stack for indicators
    this.oscStack = document.createElement('div');
    this.oscStack.className = 'tl-osc-stack';
    this.chartEl.parentNode.insertBefore(this.oscStack, this.chartEl.nextSibling);
    
    this.chart.setOption({
      animation: false,
      grid: { top: 10, left: 10, right: 62, bottom: 26 },
      xAxis: [{ type: 'time', gridIndex: 0,
        axisLine: { lineStyle: { color: '#2f2745' } },
        axisTick: { show: false }, splitLine: { show: false },
        axisLabel: { color: '#a89fc4', fontSize: 11, hideOverlap: true } }],
      yAxis: [
        { gridIndex: 0, position: 'right', scale: true, axisLine: { show: false },
          axisLabel: { color: '#a89fc4', fontSize: 11 },
          splitLine: { lineStyle: { color: '#241d36' } } },
        // hidden second axis: inflating max squeezes volume bars to the bottom
        { gridIndex: 0, show: false, max: v => (v.max || 1) * 6 },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'filter' }],
      tooltip: { trigger: 'axis', confine: true, formatter: tmTooltipFormatter(this) },
      series: tmBaseSeries(),
    });
  }
  
  _bindEvents() {
    this.paint = () => tlPaint(this);
    this.pairSel?.addEventListener('change', () => {
      tlRender(this);
      if (this.options.onPairChange) this.options.onPairChange(this.pair);
    });
    this.reasonSel?.addEventListener('change', () => tlRender(this));
    this.candleSel?.addEventListener('change', e => tlCandleSet(e.target.value));
    this.markerSel?.addEventListener('change', e => tlMarkerSet(e.target.value));
    this.markSel?.addEventListener('change', e => tlMarkSet(e.target.value));
    this.exitSel?.addEventListener('change', e => tlExitStyleSet(e.target.value));
    this.indSel?.addEventListener('change', e => {
      tlIndAdd(this, e.target.value); e.target.value = '';
    });
    this.fitBtn?.addEventListener('click', () => tlFit(this));
    
    this.chart.on('datazoom', () => {
      if (this.zt) clearTimeout(this.zt);
      this.zt = setTimeout(() => tlZoomFetch(this), 350);
    });
  }
  
  _initControls() {
    tlPresetInit();
    tlIndPopulateSelects();
    tlIndChips(this);
  }
  
  // Public API
  setRun(data, tf, mode) {
    tlSetRun(this, data, tf, mode);
  }
  
  render() {
    tlRender(this);
  }
  
  paint() {
    tlPaint(this);
  }
  
  setPair(pair) {
    this.pairSel.value = pair;
    tlRender(this);
  }
  
  destroy() {
    if (this.chart) {
      this.chart.dispose();
    }
    const idx = TradeMap._instances.indexOf(this);
    if (idx > -1) TradeMap._instances.splice(idx, 1);
  }
  
  // Static methods for managing instances
  static _instances = [];
  static getAll() { return TradeMap._instances; }
  static destroyAll() { TradeMap._instances.forEach(i => i.destroy()); TradeMap._instances = []; }
}

// Initialize global instances
let _tmTab = null;
let _tmDetail = null;

// Backwards compatibility
function mountTradeMap(mountId) {
  return new TradeMap(mountId);
}

function tlSetRun(inst, data, tf, mode) {
  inst.trades = data.trades || [];
  inst.tf = tf || '5m';
  inst.mode = mode || '';
  const runKey = `${data.strategy || ''}|${data.source || ''}`;
  if (inst.runKey === runKey) return;
  inst.runKey = runKey;
  inst.candles = []; inst.times = []; inst.fitted = false;
  inst.roi = null;
  tlFetchRoi(data.strategy, (roi) => { inst.roi = roi; tlPaint(inst); });
  tlIndDropAll(inst);
  tlRender(inst);
}
function tlRender(inst) {
  const usable = inst.trades.filter(t => t.o && t.c && t.or != null && t.cr != null);
  const pairs = {};
  usable.forEach(t => { (pairs[t.p] = pairs[t.p] || []).push(t); });
  const names = Object.keys(pairs).sort((a, b) => pairs[b].length - pairs[a].length);
  // a stale empty-state banner from a previous pair must not survive a
  // rerender - drop it up front so a run that does have candles gets a
  // clean chart, and the no-data case can re-add it after the fetch
  if (inst.mount) { const stale = inst.mount.querySelector('.tl-empty'); if (stale) stale.remove(); }
  if (inst.note && /no candle data/i.test(inst.note)) tlIndNote(inst, null);
  if (!names.length) {
    inst.chart.setOption({ series: tmBaseSeries() }, { replaceMerge: ['series'] });
    return;
  }
  inst.pair = names.includes(inst.pairSel.value) ? inst.pairSel.value : names[0];
  inst.pairSel.innerHTML = names
    .map(p => `<option ${p === inst.pair ? 'selected' : ''}>${esc(p)}</option>`).join('');
  const inPair = pairs[inst.pair];
  const reasons = [...new Set(inPair.map(t => t.e || 'unknown'))];
  const curReason = reasons.includes(inst.reasonSel.value) ? inst.reasonSel.value : 'all';
  inst.reasonSel.innerHTML = '<option value="all">all exits</option>'
    + reasons.map(r => `<option ${r === curReason ? 'selected' : ''}>${esc(r)}</option>`).join('');
  if (inst.pair !== inst.lastPair) { inst.fitted = false; inst.lastPair = inst.pair; }
  inst.shown = (curReason === 'all' ? inPair
    : inPair.filter(t => (t.e || 'unknown') === curReason)).slice()
    .sort((a, b) => tradeMs(a.o) - tradeMs(b.o));
  tlPaint(inst);
  tlEnsureCandles(inst);
}
function tlPaint(inst) {
  const cs = inst.candles, times = inst.times, mc = tlColors();
  const sers = tmBaseSeries();
  sers[0].data = cs.map(k => [k[0], k[1], k[4], k[3], k[2]]);
  sers[1].data = cs.map(k => ({ value: [k[0], k[5] || 0],
    itemStyle: { color: k[4] >= k[1] ? 'rgba(110,231,168,0.30)' : 'rgba(248,113,113,0.30)' } }));
  const hilo = tlMarkMode() === 'hilo' && cs.length > 0;
  const markers = [];
  const underPts = [], overPts = [], longRatePts = [], shortRatePts = [], slPts = [], tpPts = [];
  const underSegs = [], overSegs = [];
  let underEnd = null, overEnd = null, winEnd = null, lossEnd = null, slPrevEnd = null;
  inst.shown.forEach(t => {
    const t0 = tradeMs(t.o), t1 = tradeMs(t.c);
    const i0 = cs.length ? tlBisect(times, t0) : -1;
    const i1 = cs.length ? tlBisect(times, t1) : -1;
    const lo0 = cs.length ? Math.min(cs[i0][1], cs[i0][4]) : t.or;
    const hi0 = cs.length ? Math.max(cs[i0][1], cs[i0][4]) : t.or;
    const lo1 = cs.length ? Math.min(cs[i1][1], cs[i1][4]) : t.cr;
    const hi1 = cs.length ? Math.max(cs[i1][1], cs[i1][4]) : t.cr;
    // partial exits / DCA: one marker per fill; the profit label rides on
    // the final exit fill only
    const fills = t.px && t.px.length > 2 ? t.px : null;
    if (fills) {
      let lastExit = -1;
      fills.forEach((f, fi) => { if (!f[3]) lastExit = fi; });
      fills.forEach((f, fi) => {
        const i = cs.length ? tlBisect(times, f[0]) : -1;
        const lo = cs.length ? Math.min(cs[i][1], cs[i][4]) : f[1];
        const hi = cs.length ? Math.max(cs[i][1], cs[i][4]) : f[1];
        if (f[3]) {
          markers.push([f[0], t.s ? hi * 1.005 : lo * 0.995, t.s ? 1 : 0, mc.entLong, '']);
        } else {
          const txt = fi === lastExit ? `${((t.pr || 0) * 100).toFixed(1)}%` : '';
          markers.push([f[0], t.s ? lo * 0.99 : hi * 1.01, t.s ? 3 : 2, tlExitColor(t, mc), txt]);
        }
      });
    } else {
      markers.push([t0, t.s ? hi0 * 1.005 : lo0 * 0.995, t.s ? 1 : 0, mc.entLong, '']);
      markers.push([t1, t.s ? lo1 * 0.99 : hi1 * 1.01, t.s ? 3 : 2, tlExitColor(t, mc),
        `${((t.pr || 0) * 100).toFixed(1)}%`]);
    }
    const spanOk = cs.length && i0 >= 0 && i1 >= i0 && i1 < cs.length
      // strict window: a trade hanging past the loaded candle edge (clamped
      // bisect) would stamp its marker onto the last candle - skip it instead
      && t0 >= times[0] && t1 <= times[times.length - 1] + 300e3;
    // tracks need a price axis derived from candles; with no candles the
    // trade map still draws entry/exit markers and the stop-loss line, so
    // the SL gate stays open even when spanOk is false
    const slOk = spanOk || (cs.length === 0 && t.isl != null);
    if (spanOk) {
      // one polyline per trade with a hard null break between trades - a
      // continuous line would falsely suggest the position was not fully
      // closed. Trades whose track would collide with the previous one
      // (overlap) skip their segment.
      if (hilo) {
        const segs = t.s ? overSegs : underSegs;
        let end = t.s ? overEnd : underEnd;
        const start = times[i0];
        if (end == null || start > end) {
          const raw = [];
          for (let i = i0; i <= i1; i++) {
            const bodyLo = Math.min(cs[i][1], cs[i][4]) * 0.975;
            const bodyHi = Math.max(cs[i][1], cs[i][4]) * 1.025;
            raw.push(t.s ? bodyHi : bodyLo);
          }
          segs.push({ t: times.slice(i0, i1 + 1), raw });
          end = times[i1];
        }
        if (t.s) overEnd = end; else underEnd = end;
      } else {
        const win = (t.pr || 0) >= 0;
        const seg = win ? longRatePts : shortRatePts;
        let end = win ? winEnd : lossEnd;
        if (end == null || t0 > end) {
          if (end != null) seg.push([Math.round((end + t0) / 2), null]);
          seg.push([t0, t.or], [t1, t.cr]);
          end = t1;
        }
        if (win) winEnd = end; else lossEnd = end;
      }
    }
    if (slOk) {
      // initial stop loss as a dashed segment centred on the trade span;
      // these trades often last minutes, so each segment is padded to a
      // ~0.8% slice of the visible window (~10px at any zoom) - otherwise
      // it would be a sub-pixel dot. A wide pseudo-stop (|rate| > 35%)
      // falls back to the final stop loss and is skipped entirely if that
      // is wide too - a 99% stop would otherwise flatten the price scale
      let sl = t.isl, r = t.islr;
      if (sl == null || (r != null && Math.abs(r) > 0.35)) { sl = t.sl; r = t.slr; }
      if (sl != null && sl > 0 && !(r != null && Math.abs(r) > 0.35)) {
        const pad = Math.max(0, (tmVisibleSpan(inst) * 0.008 - (t1 - t0)) / 2);
        const a = Math.round(t0 - pad), b = Math.round(t1 + pad);
        if (slPrevEnd == null || a > slPrevEnd) {
          if (slPrevEnd != null) slPts.push([Math.round((slPrevEnd + a) / 2), null]);
          slPts.push([a, sl], [b, sl]);
          slPrevEnd = b;
        }
      }
      // take-profit level at the strategy's minimal_roi step for this trade's
      // duration - drawn as a step segment spanning open to close, green if
      // the trade actually hit the tp, red if it didn't (so the user can
      // see at a glance how often the tp was reached). only when the trade
      // has a numeric open rate and the roi table is loaded.
      const tp = tpPriceForTrade(t, inst.roi);
      if (tp != null) {
        tpPts.push([t0, tp], [t1, tp]);
      }
    }
  });
  // smooth each per-trade track segment, then join with hard null breaks
  [[underSegs, underPts], [overSegs, overPts]].forEach(([segs, pts]) => {
    segs.forEach((sg, gi) => {
      if (gi > 0) {
        const prevLast = segs[gi - 1].t[segs[gi - 1].t.length - 1];
        pts.push([Math.round((prevLast + sg.t[0]) / 2), null]);
      }
      const sm = tmSuperSmoother(sg.raw);
      sg.t.forEach((tt, k) => pts.push([tt, sm[k]]));
    });
  });
  markers.sort((a, b) => a[0] - b[0]);
  sers[2].data = underPts;
  sers[3].data = overPts;
  sers[4].data = hilo ? [] : longRatePts;
  sers[5].data = hilo ? [] : shortRatePts;
  sers[6].data = slPts;
  sers[7].data = markers;
  // take-profit step line: same chart, distinct from SL. drawn on the main
  // price scale so it sits at the actual tp price the strategy was targeting.
  // sorted by time so the line is contiguous across trades.
  if (tpPts.length) {
    tpPts.sort((a, b) => a[0] - b[0]);
    sers.push({ type: 'line', showSymbol: false, silent: true, z: 2,
      lineStyle: { width: 1, type: 'solid', color: mc.win + '88' },
      data: tpPts });
  }
  inst.inds.filter(e => e.scale === 'price').forEach(e => {
    e.cfg.forEach((s, si) => sers.push({ type: 'line', showSymbol: false, silent: true,
      lineStyle: { width: 1.5, color: e.colors[si] }, data: s.data }));
  });
  inst.chart.setOption({ series: sers }, { replaceMerge: ['series'] });
}
function tlEnsureCandles(inst) {
  const ts = inst.shown.length ? inst.shown : inst.trades;
  if (!ts.length || !inst.pair) return;
  let t0 = Math.min(...ts.map(t => tradeMs(t.o)));
  let t1 = Math.max(...ts.map(t => tradeMs(t.c)));
  const pad = Math.max((t1 - t0) * 0.02, 3600e3);
  t0 = Math.round(t0 - pad); t1 = Math.round(t1 + pad);
  const key = `${inst.pair}|${inst.tf}|${inst.mode}|${t0}|${t1}`;
  inst.appliedZoom = key;
  const done = () => {
    tlPaint(inst);
    if (inst.pendingInd) { const n = inst.pendingInd; inst.pendingInd = null; tlIndAdd(inst, n); }
    if (!inst.fitted) { tlFit(inst); inst.fitted = true; }
  };
  if (_tlFetchCache[key]) {
    inst.candles = _tlFetchCache[key]; tlTimes(inst); done(); return;
  }
  const mySeq = ++inst.loadSeq;
  fetch(`/api/candles?pair=${encodeURIComponent(inst.pair)}&timeframe=${encodeURIComponent(inst.tf)}`
    + `&trading_mode=${encodeURIComponent(inst.mode)}&start=${t0}&end=${t1}`)
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => {
      if (inst.loadSeq !== mySeq) return;
      if (d && d.candles && d.candles.length) {
        // real candles on disk - the existing mount is the empty-state banner
        // (if any); drop it and the stale note so the chart is the focus again
        const stale = inst.mount && inst.mount.querySelector('.tl-empty');
        if (stale) stale.remove();
        if (inst.note && /no candle data/i.test(inst.note)) tlIndNote(inst, null);
        _tlFetchCache[key] = d.candles;
        inst.candles = d.candles; tlTimes(inst); done();
      } else {
        // server returned 200 but no candles for this pair/tf - tell the user
        // rather than fabricate a chart from trade prices
        tlEmptyState(inst, 'no-data');
        done();
      }
    })
    .catch(() => { tlFallbackCandles(inst); done(); });
}
function tlEmptyState(inst, reason) {
  // honest "no data" instead of a pseudo-candle chart. The trade map keeps
  // entry/exit markers and the stop-loss line drawn over an empty price axis
  // so the user can still see where the trades sit in price.
  if (!inst.mount) return;
  const existing = inst.mount.querySelector('.tl-empty');
  if (existing) existing.remove();
  inst.candles = []; inst.times = []; inst.fitted = false;
  if (inst.chart) {
    try { inst.chart.setOption({ dataZoom: [{ type: 'inside', disabled: true }, { type: 'slider', disabled: true }] }, { replaceMerge: ['dataZoom'] }); } catch (e) {}
  }
  const banner = document.createElement('div');
  banner.className = 'tl-empty';
  const pair = esc(inst.pair || '?');
  const tf = esc(inst.tf || '?');
  if (reason === 'no-data') {
    banner.innerHTML = `<b>No candle data</b> for <b>${pair}</b> on <b>${tf}</b> ` +
      `&mdash; entry/exit arrows and the stop-loss line still render, but the candle ` +
      `background is omitted to avoid a misleading chart. ` +
      `Run <code>freqtrade download-data</code> to fetch the missing feed, or pick a ` +
      `different pair / timeframe in the trade header.`;
  } else {
    banner.textContent = reason || 'Trade map is empty.';
  }
  // insert above the chart-box so the chart itself is still visible below
  inst.mount.insertBefore(banner, inst.mount.querySelector('.chart-box'));
  tlIndNote(inst, `no candle data for ${inst.pair} ${inst.tf} - chart omitted, markers still render`);
}
function tlFallbackCandles(inst) {
  if (inst.candles.length) return;
  // a transient fetch failure (network / 500) is not the same as "no data on
  // disk" - the no-data case is now handled by tlEmptyState in tlEnsureCandles.
  // The synthesised candles here are a last-resort visual so a flaky server
  // does not produce a blank chart.
  const byTime = {};
  inst.shown.forEach(t => {
    const ts = tradeMs(t.o), o = t.or, c = t.cr;
    if (!byTime[ts]) byTime[ts] = [ts, o, Math.max(o, c), Math.min(o, c), c, 0];
    else { const k = byTime[ts]; k[2] = Math.max(k[2], o, c); k[3] = Math.min(k[3], o, c); }
  });
  inst.candles = Object.values(byTime).sort((a, b) => a[0] - b[0]);
  tlIndNote(inst, `could not load candles - chart approximated from trade prices`);
  tlTimes(inst); tlPaint(inst);
}
function tlTimes(inst) { inst.times = inst.candles.map(k => k[0]); }
function tlFit(inst) {
  inst.chart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 });
}
// indicators are computed SERVER-SIDE from user_data/strategies/components
// (indicators_pandas_ta) - the browser only fetches ready-made series
const _tlIndColors = ['#fbbf24', '#22d3ee', '#f472b6', '#a3e635', '#fb923c', '#e879f9'];
const TL_IND_MAX = 3;
function tlIndParse(s) {
  return s.times.map((t, i) => s.values[i] == null ? [t, null] : [t, s.values[i]]);
}
function tlMakePane(inst) {
  const el = document.createElement('div');
  el.className = 'tl-osc';
  inst.oscStack.appendChild(el);
  const chart = initChart(el);
  chart.group = inst.group;
  echarts.connect(inst.group);
  // no interactive dataZoom here - the connect relay drives this pane from
  // the main chart, so user gestures on the pane cannot desync the group
  chart.setOption({
    animation: false,
    grid: { top: 8, left: 10, right: 62, bottom: 6 },
    xAxis: [{ type: 'time', show: false }],
    yAxis: [{ position: 'right', scale: true, axisLine: { show: false },
      axisLabel: { color: '#a89fc4', fontSize: 10 },
      splitLine: { lineStyle: { color: '#241d36' } } }],
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'filter',
      zoomOnMouseWheel: false, moveOnMouseMove: false, moveOnMouseWheel: false }],
    tooltip: { show: false },
    series: [],
  });
  return { el, chart };
}
// the zoom-merge extends the main candle window - refetch the indicator
// series for the full window so pane data extents follow the main chart
function tlIndRefresh(inst) {
  if (!inst.inds.length || !inst.candles.length || !inst.pair) return;
  const t0 = inst.candles[0][0], t1 = inst.candles[inst.candles.length - 1][0];
  inst.inds.forEach(e => {
    fetch(`/api/indicator?name=${encodeURIComponent(e.name)}`
      + `&pair=${encodeURIComponent(inst.pair)}&timeframe=${encodeURIComponent(inst.tf)}`
      + `&trading_mode=${encodeURIComponent(inst.mode)}&start=${t0}&end=${t1}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => {
        if (d.error || !d.series) return;
        e.cfg = d.series.map(s => ({ data: tlIndParse(s) }));
        if (e.paneEl) {
          e.chart.setOption({ series: e.cfg.map((s, si) => ({ type: 'line',
            showSymbol: false, silent: true,
            lineStyle: { width: 1.5, color: e.colors[si] }, data: s.data })) },
            { replaceMerge: ['series'] });
        } else tlPaint(inst);
      }).catch(() => {});
  });
}
function tlIndAdd(inst, name) {
  if (!name || inst.inds.some(x => x.name === name)) return;
  if (inst.inds.length >= TL_IND_MAX) return;
  // candles may still be loading when the user picks one - retry once they land
  if (!inst.candles.length || !inst.pair) { inst.pendingInd = name; return; }
  const t0 = inst.candles[0][0], t1 = inst.candles[inst.candles.length - 1][0];
  fetch(`/api/indicator?name=${encodeURIComponent(name)}`
    + `&pair=${encodeURIComponent(inst.pair)}&timeframe=${encodeURIComponent(inst.tf)}`
    + `&trading_mode=${encodeURIComponent(inst.mode)}&start=${t0}&end=${t1}`)
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => {
      if (d.error) { console.error('indicator load failed:', name, d.error); return; }
      if (!d.series || !d.series.length) {
        // the API returns 200 + empty series when the pair/timeframe has no
        // data in this window - surface it instead of doing nothing
        tlIndNote(inst, `${d.title || name}: no data for ${inst.pair} ${inst.tf} in this window`);
        return;
      }
      if (inst.inds.length >= TL_IND_MAX) return;
      inst.note = null;
      const onPrice = d.scale === 'price';
      const pane = onPrice ? null : tlMakePane(inst);
      const entry = { id: name + '#' + (++inst.indSeq), name,
        title: d.title || name, scale: d.scale,
        colors: d.series.map((s, si) =>
          _tlIndColors[(inst.inds.length + si) % _tlIndColors.length]),
        cfg: d.series.map(s => ({ data: tlIndParse(s) })),
        chart: onPrice ? inst.chart : pane.chart, paneEl: pane ? pane.el : null };
      if (pane) {
        pane.chart.setOption({ series: entry.cfg.map((s, si) => ({ type: 'line',
          showSymbol: false, silent: true,
          lineStyle: { width: 1.5, color: entry.colors[si] }, data: s.data })) });
        // the pane auto-fits its own data extent on first setOption - re-pin
        // it to the main chart's current zoom so it starts in sync
        const dz = inst.chart.getOption().dataZoom[0];
        if (dz && dz.start != null) {
          pane.chart.dispatchAction({ type: 'dataZoom', start: dz.start, end: dz.end });
        }
      }
      inst.inds.push(entry);
      tlIndChips(inst);
    })
    .catch(err => {
      console.error('indicator load failed:', name, err);
      tlIndNote(inst, `${name}: failed to load (${err && err.message ? err.message : 'network error'})`);
    });
}
function tlIndRemove(inst, entryId) {
  const idx = inst.inds.findIndex(x => x.id === entryId);
  if (idx < 0) return;
  const e = inst.inds[idx];
  if (e.paneEl) { try { e.chart.dispose(); } catch (err) {} e.paneEl.remove(); }
  inst.inds.splice(idx, 1);
  tlIndChips(inst);
  tlPaint(inst);
}
function tlIndMove(inst, entryId, dir) {
  const idx = inst.inds.findIndex(x => x.id === entryId);
  const j = idx + dir;
  if (idx < 0 || j < 0 || j >= inst.inds.length) return;
  const [e] = inst.inds.splice(idx, 1);
  inst.inds.splice(j, 0, e);
  // price-scale overlays have no pane - they reorder in the chips only
  inst.inds.forEach(x => { if (x.paneEl) inst.oscStack.appendChild(x.paneEl); });
  tlIndChips(inst);
  tlPaint(inst);
}
function tlIndNote(inst, msg) { inst.note = msg || null; tlIndChips(inst); }
function tlIndChips(inst) {
  const c = inst.mount.querySelector('.tl-chips');
  if (!c) return;
  const note = inst.note ? `<span class="hint" style="color:var(--warn)">⚠ ${esc(inst.note)}</span>` : '';
  if (!inst.inds.length) {
    c.innerHTML = note
      + '<span class="hint">no indicators - add up to 3 via the "Indicators" dropdown, controls appear here</span>';
    return;
  }
  const btn = (act, id, label) =>
    `<b data-act="${act}" data-ind="${esc(id)}"`
    + ` style="cursor:pointer;padding:0 3px;font-weight:400">${label}</b>`;
  c.innerHTML = note + inst.inds.map(e =>
    `<span class="pill gB">${esc(e.title)} `
    + `${btn('up', e.id, '↑')}${btn('dn', e.id, '↓')}${btn('x', e.id, 'x')}</span>`
  ).join('')
  + (inst.inds.length >= TL_IND_MAX ? ' <span class="hint">max 3 indicators</span>' : '');
  c.querySelectorAll('[data-act]').forEach(el => {
    el.addEventListener('click', () => {
      const act = el.dataset.act, id = el.dataset.ind;
      if (act === 'x') tlIndRemove(inst, id);
      else tlIndMove(inst, id, act === 'up' ? -1 : 1);
    });
  });
}
function tlIndDropAll(inst) {
  (inst.inds || []).forEach(e => {
    if (e.paneEl) { try { e.chart.dispose(); } catch (err) {} e.paneEl.remove(); }
  });
  inst.inds = [];
  if (inst.chart) tlPaint(inst);
}
function tlIndServerList(cb) {
  if (window._tlIndList) { cb(window._tlIndList); return; }
  fetch('/api/indicators').then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(list => { window._tlIndList = list || []; cb(window._tlIndList); })
    .catch(() => { window._tlIndList = []; cb(window._tlIndList); });
}
function tlIndPopulateSelects() {
  tlIndServerList(list => {
    document.querySelectorAll('.tl-ind-sel').forEach(sel => {
      sel.innerHTML = '<option value="">+ add</option>' + list
        .map(i => `<option value="${esc(i.name)}">${esc(i.title)}</option>`).join('');
    });
  });
}
function tlTfMs(tf) {
  const m = /^(\d+)\s*([mhd])$/i.exec(String(tf || '').trim());
  if (!m) return null;
  return Number(m[1]) * { m: 60e3, h: 3600e3, d: 86400e3 }[m[2].toLowerCase()];
}
function tlZoomFetch(inst) {
  if (!inst.candles.length || !inst.pair) return;
  const opt = inst.chart.getOption();
  const dz = opt && opt.dataZoom && opt.dataZoom[0];
  if (!dz) return;
  const first = inst.candles[0][0], last = inst.candles[inst.candles.length - 1][0];
  let v0, v1;
  if (dz.startValue != null && dz.endValue != null) {
    v0 = Math.round(Number(dz.startValue)); v1 = Math.round(Number(dz.endValue));
  } else {
    const s = dz.start == null ? 0 : dz.start, e = dz.end == null ? 100 : dz.end;
    v0 = Math.round(first + (last - first) * s / 100);
    v1 = Math.round(first + (last - first) * e / 100);
  }
  // transient states can surface NaN/empty ranges - never fetch or merge on those
  if (!Number.isFinite(v0) || !Number.isFinite(v1) || v1 <= v0) return;
  if (v1 < first || v0 > last) return;
  // local candle interval around the view center - merges mix coarse
  // (downsampled) and fine candles, so a global spacing would lie
  const midIdx = tlBisect(inst.times, (v0 + v1) / 2);
  const a = inst.candles[midIdx];
  const b = inst.candles[Math.min(midIdx + 1, inst.candles.length - 1)];
  const spacing = Math.max(1, b[0] - a[0]);
  const tfMs = tlTfMs(inst.tf) || spacing;
  const covered = v0 >= first && v1 <= last;
  // zoom-in only matters while the loaded candles are coarser than the
  // timeframe; once they are fine, panning inside the loaded range must not
  // refetch: every merge + setdata nudges the visible range, which produced a
  // new fetch key, which merged again - the move-by-itself + blink loop
  const zoomIn = covered && spacing > tfMs * 1.5 && (v1 - v0) < (last - first) * 0.6;
  if (covered && !zoomIn) return;
  const key = `${inst.pair}|${inst.tf}|${inst.mode}|${v0}|${v1}`;
  if (key === inst.appliedZoom) return;
  inst.appliedZoom = key;
  const mySeq = ++inst.zoomSeq;
  const apply = fine => {
    const inside = fine.filter(k => k[0] >= v0 && k[0] <= v1);
    const merged = inst.candles.filter(k => k[0] < v0 || k[0] > v1)
      .concat(inside).sort((a, b) => a[0] - b[0]);
    inst.candles = merged.length > 20000 ? inst.candles : merged;
    tlTimes(inst); tlPaint(inst);
    tlIndRefresh(inst);
  };
  if (_tlFetchCache[key]) { apply(_tlFetchCache[key]); return; }
  if (Object.keys(_tlFetchCache).length > 60) {
    for (const k of Object.keys(_tlFetchCache)) { if (k !== key) delete _tlFetchCache[k]; }
  }
  fetch(`/api/candles?pair=${encodeURIComponent(inst.pair)}&timeframe=${encodeURIComponent(inst.tf)}`
    + `&trading_mode=${encodeURIComponent(inst.mode)}&start=${v0}&end=${v1}`)
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => {
      if (inst.zoomSeq !== mySeq) return;
      if (d && d.candles && d.candles.length) {
        _tlFetchCache[key] = d.candles; apply(d.candles);
      }
    }).catch(() => {});
}
const _roiCache = {};
function tlFetchRoi(name, cb) {
  if (!name) { cb({}); return; }
  if (Object.prototype.hasOwnProperty.call(_roiCache, name)) { cb(_roiCache[name]); return; }
  fetch(`/api/tp?strategy=${encodeURIComponent(name)}`)
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => { _roiCache[name] = (d && d.roi) || {}; cb(_roiCache[name]); })
    .catch(() => { _roiCache[name] = {}; cb({}); });
}
const _tlInstances = [];
const _tlFetchCache = {};
function tlUpdate() { _tlInstances.forEach(i => { if (i.trades) tlRender(i); }); }
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
        <td class="num" data-val="${td.pr||0}">${pill(prof>=0?'pass':'fail', (prof<=-0.25?'⚠ ':'')+prof.toFixed(2)+'%')}</td>
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

/* ---------- lab + global jobs ---------- */
let jobTimer = null;
let lastJobs = {};
function jobPill(j) {
  if (j.status === 'done') return pill('pass', 'done');
  if (j.status === 'error') return pill('fail', 'error');
  if (j.status === 'stopped') return pill('fail', 'stopped');
  if (j.status === 'paused') return pill('warn', 'paused');
  return pill('warn', j.status || 'running');
}
function renderGlobalJobs(jobs) {
  // Global bar is now superseded by the header badge + jobs modal.
  // Keep #globalJobs hidden to avoid duplicating the list inline; all
  // rendering lives in updateJobsBadge() + renderJobsModal().
  const bar = $('globalJobs');
  if (bar) { bar.classList.add('hidden'); bar.innerHTML = ''; }
  updateJobsBadge(jobs);
  if (jobsModalOpen) renderJobsModal(jobs);
}
let jobsModalOpen = false;
function updateJobsBadge(jobs) {
  const badge = $('jobsBadge');
  const btn = $('jobsBtn');
  if (!badge || !btn) return;
    const entries = Object.entries(jobs);
    const active = entries.filter(([,j]) => j.status === 'running' || j.status === 'paused' || j.status === 'queued').length;
  if (active > 0) {
    badge.textContent = String(active);
    badge.classList.remove('hidden');
    btn.classList.add('has-active');
    btn.title = active + ' active job' + (active > 1 ? 's' : '');
  } else {
    badge.textContent = '0';
    badge.classList.add('hidden');
    btn.classList.remove('has-active');
    btn.title = 'Background jobs';
  }
  const cnt = $('jobsModalCount');
  if (cnt) cnt.textContent = active ? active + ' active' : entries.length ? entries.length + ' total' : '';
}
function renderJobsModal(jobs) {
  const activeEl = $('jobsModalActive');
  const recentEl = $('jobsModalRecent');
  const emptyEl = $('jobsModalEmpty');
  if (!activeEl || !recentEl) return;
  const entries = Object.entries(jobs).sort((a,b)=> (b[1].created||0)-(a[1].created||0))
    .filter(([id]) => !dismissedJobs.has(id));
  const active = entries.filter(([,j])=> j.status==='running' || j.status==='paused' || j.status==='queued');
  const recent = entries.filter(([,j])=> j.status==='error' || j.status==='done' || j.status==='stopped' || j.status==='skipped').slice(0, 20);
  if (!entries.length) {
    activeEl.innerHTML = '';
    recentEl.innerHTML = '';
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');
  const rowHtml = (id, j) => {
    const isErr = j.status === 'error';
    const excerpt = isErr ? jobErrorExcerpt(j) : lastLogLine(j.log);
    const cmd = jobShortCmd(j);
    const step = j.step ? `step ${esc(j.step)}` : '';
    const code = j.code != null ? `exit ${j.code}` : '';
    return `<div class="job-row ${isErr?'errored':''}">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;flex:1">
        ${jobPill(j)} <span class="job-id">${esc(id)}</span>
        <span class="hint">${esc(j.name||'')}${step?' · '+esc(step):''}${code?' · '+esc(code):''}</span>
        ${cmd ? `<span class="job-cmd" title="${escAttr(j.cmd||'')}">${esc(cmd)}</span>` : ''}
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn compact" onclick="openLogViewer('${escAttr(id)}')">View log</button>
        ${j.status==='running' ? `<button class="btn compact" onclick="jobAction('${escAttr(id)}','pause')">Pause</button><button class="btn compact" onclick="jobAction('${escAttr(id)}','stop')">Stop</button>` : ''}
        ${j.status==='paused' ? `<button class="btn compact" onclick="jobAction('${escAttr(id)}','resume')">Resume</button><button class="btn compact" onclick="jobAction('${escAttr(id)}','stop')">Stop</button>` : ''}
        ${j.status==='queued' ? `<button class="btn compact" onclick="jobAction('${escAttr(id)}','stop')">Stop</button>` : ''}
        ${(j.status==='error'||j.status==='done'||j.status==='stopped') ? `<button class="btn compact" onclick="dismissJob('${escAttr(id)}')">Dismiss</button>` : ''}
      </div>
      ${excerpt ? `<div class="job-excerpt">${esc(excerpt)}</div>` : ''}
    </div>`;
  };
  if (active.length) {
    activeEl.innerHTML = `<div class="jm-section-title">Active — ${active.length}</div>` + active.map(([id,j])=>rowHtml(id,j)).join('');
  } else {
    activeEl.innerHTML = `<div class="jm-section-title">Active</div><div class="hint">No active jobs.</div>`;
  }
  if (recent.length) {
    recentEl.innerHTML = `<div class="jm-section-title">Recent — ${recent.length}</div>` + recent.map(([id,j])=>rowHtml(id,j)).join('');
  } else {
    recentEl.innerHTML = `<div class="jm-section-title">Recent</div><div class="hint">No recent finished jobs.</div>`;
  }
}
function openJobsModal() {
  jobsModalOpen = true;
  $('jobsModal').classList.add('open');
  $('jobsBackdrop').classList.add('open');
  $('jobsModal').setAttribute('aria-hidden','false');
  renderJobsModal(lastJobs);
}
function closeJobsModal() {
  jobsModalOpen = false;
  $('jobsModal').classList.remove('open');
  $('jobsBackdrop').classList.remove('open');
  $('jobsModal').setAttribute('aria-hidden','true');
}
function lastLogLine(log) {
  if (!log) return '';
  const lines = log.split('\n').filter(Boolean);
  return (lines[lines.length - 1] || '').slice(-400);
}
function jobErrorExcerpt(j) {
  const log = j.log || '';
  if (!log) return j.code != null ? 'exit code ' + j.code : '';
  const lines = log.split('\n');
  const needle = /(error|exception|traceback|fail|warning|hint|diag|provenance not linked|exit code)/i;
  const hits = lines.filter(l => needle.test(l)).slice(-4);
  if (hits.length) return hits.join(' | ').slice(0, 600);
  const tail = lines.filter(Boolean).slice(-2).join(' | ');
  const code = (j.code != null && j.code !== 0) ? ' (exit ' + j.code + ')' : '';
  return (tail + code).slice(0, 600);
}
function jobShortCmd(j) {
  const c = j.cmd || j.step_cmd || '';
  if (!c) return '';
  return c.length > 120 ? '…' + c.slice(-120) : c;
}
function pollJobs() {
  fetch('/api/jobs').then(r => r.json()).then(jobs => {
    lastJobs = jobs;
    // The lab tab no longer renders an inline jobs list; the header badge and
    // jobs modal own all job output. Just update the badge/modal, keep the
    // modal log in sync, and watch report jobs.
    renderGlobalJobs(jobs);
    if (logViewerState.open) refreshLogViewer(true);
    const hasLive = Object.values(jobs).some(j => j.status === 'running' || j.status === 'paused' || j.status === 'queued');
    if (!hasLive && jobTimer) { clearInterval(jobTimer); jobTimer = null; }
    if (hasLive && !jobTimer) { /* keep timer */ }
    watchReportJobs();
  }).catch(() => {});
}
const dismissedJobs = new Set();
function dismissJob(id) {
  // hide a finished job from the jobs modal. The server keeps the entry in
  // /api/jobs until its natural eviction; we just stop showing it.
  dismissedJobs.add(id);
  if (lastJobs) { renderGlobalJobs(lastJobs); }
}
function ensureJobPolling() {
  pollJobs();
  if (!jobTimer) jobTimer = setInterval(() => { pollJobs(); }, 1500);
}
function jobAction(jobId, action) {
  fetch('/api/jobs/' + encodeURIComponent(jobId) + '/' + action, {method:'POST'})
    .then(r=>r.json()).then(d=>{
      if (!d.ok) { alert(d.msg || 'failed'); }
      pollJobs();
    }).catch(e=> alert(String(e)));
}
let logViewerState = { open: false, jobId: null };
function openLogViewer(jobId) {
  logViewerState.open = true; logViewerState.jobId = jobId;
  $('logViewer').classList.add('open');
  $('logViewerBackdrop').classList.add('open');
  $('lvTitle').textContent = 'Logs — ' + jobId;
  $('lvPre').textContent = 'Loading…';
  refreshLogViewer();
}
function closeLogViewer() {
  logViewerState.open = false; logViewerState.jobId = null;
  $('logViewer').classList.remove('open');
  $('logViewerBackdrop').classList.remove('open');
}

/* ---------- freshness check (auto-refresh on tab activation) ---------- */
const DATA_TABS = ['dashboard','strategies','history','benchmark','walkforward','hyperopt','trades'];
let freshCheckInFlight = false;
let freshTimer = null;
let lastReportJobId = null;
async function ensureFresh() {
  if (freshCheckInFlight) return;
  freshCheckInFlight = true;
  try {
    const r = await fetch('/api/freshness', { cache: 'no-store' });
    if (!r.ok) return;
    const d = await r.json();
    if (d && d.stale) { labRefresh(); }
  } catch (e) { /* server may be down; ignore */ }
  finally { freshCheckInFlight = false; }
}
function startFreshnessLoop() {
  if (freshTimer) return;
  freshTimer = setInterval(() => {
    if (document.hidden) return;
    ensureFresh();
  }, 180000);
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) ensureFresh();
});
// when a report job ends successfully, reload LAB and re-render the active tab
function watchReportJobs() {
  fetch('/api/jobs').then(r => r.json()).then(jobs => {
    const reports = Object.entries(jobs).filter(([, j]) => (j.name || '').startsWith('report'));
    if (!reports.length) { lastReportJobId = null; return; }
    reports.sort((a, b) => (b[1].created || 0) - (a[1].created || 0));
    const [id, j] = reports[0];
    if (lastReportJobId === id) return;
    const firstSeen = !lastReportJobId;
    lastReportJobId = id;
    if (!firstSeen && (j.status === 'done' || j.status === 'error')) {
      reloadLab();
    }
  }).catch(() => {});
}
async function reloadLab() {
  try {
    const r = await fetch('/api/data', { cache: 'no-store' });
    if (!r.ok) return;
    const d = await r.json();
    Object.assign(LAB, d);
    // a fresh report may carry new runs - trade payloads must be refetched,
    // not replayed from cache through the no-re-render guard
    Object.keys(tradeCache).forEach(k => { delete tradeCache[k]; });
    _renderedTradeData = null;
    // dispose existing chart instances to avoid double-init
    ['_benchChart','_equityChart','_profitHistChart',
     '_detailEquityChart','_detailHistChart'].forEach(k => {
      if (window[k] && window[k].dispose) { try { window[k].dispose(); } catch (e) {} }
      window[k] = null;
    });
    (window._histCharts || []).forEach(c => { try { c.dispose(); } catch (e) {} });
    window._histCharts = [];
    if (DATA_TABS.includes(state.tab)) showTab(state.tab, true);
    else renderDashboard();
  } catch (e) { /* ignore */ }
}
function refreshLogViewer(silent) {
  const id = logViewerState.jobId;
  if (!id) return;
  const hint = $('lvHint');
  fetch('/api/jobs/' + encodeURIComponent(id) + '/log?tail=120000').then(r=>r.json()).then(d=>{
    if (d.error) { $('lvPre').textContent = d.error; return; }
    $('lvPre').textContent = d.log || '(empty)';
    if (!silent) { $('lvPre').scrollTop = $('lvPre').scrollHeight; }
    else { /* keep scroll if near bottom */ const el=$('lvPre'); const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40; if (nearBottom) el.scrollTop = el.scrollHeight; }
    const j = lastJobs[id];
    hint.textContent = j ? `${j.status} · ${esc(j.name||'')} · ${d.len} chars` : `${d.len} chars`;
  }).catch(()=>{ if(!silent) $('lvPre').textContent='Failed to load log (need server).'; });
}
/* ---------- grade tuner (client-side thresholds via localStorage) ---------- */
const GRADE_LS_KEY = 'gradeFactors';
function loadGradeFactors() {
  try {
    const raw = localStorage.getItem(GRADE_LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch (e) { return null; }
}
function saveGradeFactors(obj) {
  try { localStorage.setItem(GRADE_LS_KEY, JSON.stringify(obj)); } catch (e) {}
}
function activeGradeFactors() {
  const base = LAB.scorecard || {};
  const overrides = loadGradeFactors() || {};
  const out = {};
  for (const k of Object.keys(base)) {
    const o = overrides[k] || {};
    out[k] = {
      pass: o.pass !== undefined ? Number(o.pass) : base[k].pass,
      warn: o.warn !== undefined ? Number(o.warn) : base[k].warn,
      higher_is_better: base[k].higher_is_better,
      label: base[k].label,
    };
  }
  return out;
}
function gradeValueTuned(value, spec) {
  if (value === null || value === undefined || value === '') return 'na';
  const v = Number(value);
  if (!Number.isFinite(v)) return 'na';
  if (spec.higher_is_better) {
    if (v >= spec.pass) return 'pass';
    if (v >= spec.warn) return 'warn';
    return 'fail';
  }
  if (v <= spec.pass) return 'pass';
  if (v <= spec.warn) return 'warn';
  return 'fail';
}
function demoteSoleWorstTrade(grades) {
  const lst = Object.values(grades);
  if (lst.filter(g => g === 'fail').length === 1 && grades.worst_trade === 'fail') {
    return Object.fromEntries(Object.entries(grades).map(([k, g]) => [k, k === 'worst_trade' ? 'warn' : g]));
  }
  return grades;
}
function overallGradeTuned(grades) {
  const c = { pass: 0, warn: 0, fail: 0, na: 0 };
  for (const g of Object.values(grades)) c[g] = (c[g] || 0) + 1;
  if (c.pass + c.warn + c.fail === 0) return 'na';
  if (c.fail >= 2) return 'D';
  if (c.fail === 1) return 'C';
  if (c.pass >= 5 && c.fail === 0) return 'A';
  if (c.pass >= 3) return 'B';
  return 'C';
}
function scoreRowTuned(row) {
  const sc = activeGradeFactors();
  const raw = {};
  for (const k of Object.keys(sc)) raw[k] = gradeValueTuned(row[k], sc[k]);
  // A 0-trade run has no evidence - grade na rather than fake fails (mirrors score_strategy)
  if (!row.total_trades) {
    for (const k of Object.keys(raw)) raw[k] = 'na';
  }
  const counted = demoteSoleWorstTrade(raw);
  return {
    grade: overallGradeTuned(counted),
    grades: raw,
    pass_count: Object.values(counted).filter(g => g === 'pass').length,
    warn_count: Object.values(counted).filter(g => g === 'warn').length,
    fail_count: Object.values(counted).filter(g => g === 'fail').length,
  };
}
function applyTunedScoresInPlace() {
  const sc = (LAB.backtests || []).concat(LAB.benchmarks || []);
  sc.forEach(r => { r.score = scoreRowTuned(r); });
  (LAB.canonical || []).forEach(r => { r.score = scoreRowTuned(r); });
}
function repaintGradeCells() {
  document.querySelectorAll('[data-grade-cell]').forEach(td => {
    const name = td.dataset.gradeCell;
    const row = (LAB.canonical || []).find(r => r.strategy === name)
             || (LAB.backtests || []).find(r => r.strategy === name);
    if (row && row.score) {
      td.dataset.val = row.score.grade;
      td.innerHTML = gradePill(row.score.grade);
    }
  });
}
function openGradeTuner() {
  const factors = activeGradeFactors();
  const rows = Object.entries(factors).map(([k, s]) => {
    const dir = s.higher_is_better ? 'higher better' : 'lower better';
    return `<tr data-key="${k}">
      <td>${esc(s.label || k)}</td>
      <td class="num"><input type="number" step="any" data-fld="pass" value="${s.pass}"></td>
      <td class="num"><input type="number" step="any" data-fld="warn" value="${s.warn}"></td>
      <td><span class="hint">${dir}</span></td>
    </tr>`;
  }).join('');
  $('gradeTunerRows').innerHTML = rows;
  $('gradeTunerErr').style.display = 'none';
  $('gradeBackdrop').classList.add('open');
  $('gradeModal').classList.add('open');
  $('gradeModal').setAttribute('aria-hidden', 'false');
}
function closeGradeTuner() {
  $('gradeBackdrop').classList.remove('open');
  $('gradeModal').classList.remove('open');
  $('gradeModal').setAttribute('aria-hidden', 'true');
}
function readGradeTunerInputs() {
  const out = {};
  let err = null;
  $('gradeTunerRows').querySelectorAll('tr').forEach(tr => {
    const k = tr.dataset.key;
    const pass = Number(tr.querySelector('input[data-fld="pass"]').value);
    const warn = Number(tr.querySelector('input[data-fld="warn"]').value);
    if (!Number.isFinite(pass) || !Number.isFinite(warn)) {
      err = `Bad number in row "${k}".`; return;
    }
    out[k] = { pass, warn };
  });
  return { factors: out, err };
}
function applyGradeFactors() {
  const { factors, err } = readGradeTunerInputs();
  if (err) { $('gradeTunerErr').textContent = err; $('gradeTunerErr').style.display = ''; return; }
  saveGradeFactors(factors);
  applyTunedScoresInPlace();
  // re-render every place grades are shown
  if (state.tab === 'dashboard') renderDashboard();
  if (state.tab === 'strategies') renderStrategies();
  if (state.tab === 'history') renderHistory();
  if (state.tab === 'benchmark') renderBenchmark();
  if (state.tab === 'walkforward') renderWalkForward();
  if (state.tab === 'hyperopt') renderHyperopt();
  if (state.strategy) openStrategy(state.strategy, true);
  repaintGradeCells();
  closeGradeTuner();
}
function resetGradeFactors() {
  try { localStorage.removeItem(GRADE_LS_KEY); } catch (e) {}
  openGradeTuner();
}

function labRefresh() {
  fetch('/api/refresh', {method:'POST'}).then(r=>r.json()).then(() => { ensureJobPolling(); });
}
function labBench() {
  const strategies = $('benchStrategies').value.split(',').map(s=>s.trim()).filter(Boolean);
  const body = { timerange: $('benchRange').value, timeframe: $('benchTf').value, strategies };
  fetch('/api/bench', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r=>r.json()).then(() => { ensureJobPolling(); });
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
  const sel = $('runLoss');
  const seen = new Set();
  const addLosses = (arr) => {
    if (!sel || !Array.isArray(arr)) return;
    arr.forEach(l => {
      if (!l || seen.has(l)) return;
      seen.add(l);
      if ([...sel.options].some(o => o.value === l)) return;
      const o = document.createElement('option'); o.value = l; o.textContent = l; sel.appendChild(o);
    });
  };
  // synchronous seed from the build-time embedded list so the static file works offline
  try {
    if (typeof LAB_LOSSES !== 'undefined' && Array.isArray(LAB_LOSSES)) addLosses(LAB_LOSSES);
  } catch (e) {}
  // ensure a sensible default if nothing selected
  if (sel && !sel.value && sel.options.length) {
    const def = [...sel.options].some(o => o.value === 'SharpeHyperOptLossDaily') ? 'SharpeHyperOptLossDaily' : sel.options[0].value;
    sel.value = def;
  }
  fetch('/api/losses').then(r => r.json()).then(d => {
    const live = d.losses || [];
    if (live.length) {
      const prev = sel.value;
      addLosses(live);
      if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    }
  }).catch((err) => {
    console.warn('loadLosses: fetch /api/losses failed (static file or server down)', err);
    const hint = $('runHint');
    if (hint && typeof LAB_LOSSES !== 'undefined' && Array.isArray(LAB_LOSSES) && LAB_LOSSES.length) {
      hint.textContent = 'Loss list offline -- showing built-in set from last report build (start the Lab server for live discovery of custom losses).';
    }
  });
}
function loadConfigs() {
  fetch('/api/configs').then(r => r.json()).then(d => {
    const sel = $('runConfig');
    if (!sel) return;
    const cfgs = d.configs || [];
    sel.innerHTML = '<option value="">auto (optional)</option>' + cfgs.map(c =>
      `<option value="${escAttr(c.path)}">${esc(c.name + (c.hint ? ' (' + c.hint + ')' : ''))}</option>`
    ).join('');
    const hint = $('runHint');
    if (hint) {
      if (!cfgs.length) hint.textContent = 'No configs found — check user_data/config*.json';
      else hint.textContent = 'Auto: user_data/config_<strategy>.json or config_benchmark.json, or pick one from the dropdown.';
    }
  }).catch(() => {
    const hint = $('runHint');
    if (hint) hint.textContent = 'Auto config: user_data/config_<strategy>.json if it exists, else config_benchmark.json. Config dropdown needs the lab server.';
  });
}
function validateWfTimerange() {
  const start = ($('runStart').value || '').replace(/-/g, '');
  const end   = ($('runEnd').value   || '').replace(/-/g, '');
  if (!start || !end) return 'Walk-forward needs both From and To dates.';
  if (start.length !== 8 || end.length !== 8) return 'Walk-forward dates must be YYYY-MM-DD.';
  const sUtc = Date.UTC(+start.slice(0,4), +start.slice(4,6)-1, +start.slice(6,8));
  const eUtc = Date.UTC(+end.slice(0,4),   +end.slice(4,6)-1,   +end.slice(6,8));
  if (!(eUtc > sUtc)) return 'Walk-forward To date must be after From date.';
  const days = Math.floor((eUtc - sUtc) / 86400000) + 1;
  const train = Number($('runTrain').value) || 90;
  const test  = Number($('runTest').value)  || 7;
  // freqtrade needs at least one (train+test) window plus a 1-day margin; B2 in
  // server.py applies the same floor server-side.
  const minDays = train + test + 1;
  if (days < minDays) {
    return `Timerange too short for walk-forward: ${days} day(s), need at least ${minDays} (train ${train} + test ${test} + 1).`;
  }
  return null;
}
function validateRunParams() {
  // Common + mode-specific param checks. Mirrors server-side _validate_run_params.
  // Walk-forward uses its own validateWfTimerange (train/test days check) but
  // still goes through this function for the field-level checks.
  const mode = $('runMode').value;
  const start = ($('runStart').value || '').replace(/-/g, '');
  const end   = ($('runEnd').value   || '').replace(/-/g, '');
  if (!start || !end) return 'Pick both From and To dates.';
  if (start.length !== 8 || end.length !== 8) return 'Dates must be valid (YYYY-MM-DD).';
  const sUtc = Date.UTC(+start.slice(0,4), +start.slice(4,6)-1, +start.slice(6,8));
  const eUtc = Date.UTC(+end.slice(0,4),   +end.slice(4,6)-1,   +end.slice(6,8));
  if (!(eUtc >= sUtc)) return 'To date must be on or after From date.';
  const tf = ($('runTf').value || '').trim();
  if (!tf) return 'Pick a timeframe (e.g. 5m, 1h, 1d).';
  if (!/^[1-9]\d*[mhdw]$/.test(tf)) return `Timeframe "${tf}" doesn't look like 5m / 1h / 1d.`;

  // Optional config path: if provided, must look like a non-empty string. The
  // server does the is_file check.
  const cfg = ($('runConfig').value || '').trim();

  const fail = (msg) => msg;

  if (mode === 'hyperopt' || mode === 'walkforward') {
    // epochs: required, positive integer, sane upper bound.
    const epochsRaw = ($('runEpochs').value || '').trim();
    if (epochsRaw === '') return fail(`${mode} requires epochs (positive integer).`);
    const epochs = Number(epochsRaw);
    if (!Number.isFinite(epochs) || Math.floor(epochs) !== epochs || epochs < 1)
      return fail(`epochs must be a positive integer, got "${epochsRaw}".`);
    if (epochs > 100000) return fail(`epochs looks unreasonably large (${epochs}); cap at 100000.`);

    // loss: required, must be a known loss (embedded list + live select). When
    // both are empty (fetch still in flight and no LAB_LOSSES), defer to server.
    const loss = ($('runLoss').value || '').trim();
    if (!loss) return fail(`${mode} requires a loss function.`);
    const selEl = $('runLoss');
    const selKnown = selEl ? Array.from(selEl.options).map(o => o.value).filter(Boolean) : [];
    const labKnown = (typeof LAB_LOSSES !== 'undefined' && Array.isArray(LAB_LOSSES)) ? LAB_LOSSES : [];
    const known = [...new Set([...labKnown, ...selKnown])];
    if (known.length && !known.includes(loss)) {
      const sugg = known.filter(k => k.toLowerCase().includes(loss.toLowerCase())).slice(0, 3);
      return fail(`unknown loss "${loss}".${sugg.length ? ' Did you mean: ' + sugg.join(', ') + '?' : ''}`);
    }

    // spaces: required, non-empty, each token must be a known space.
    const spacesRaw = ($('runSpaces').value || '').trim();
    const tokens = spacesRaw.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
    if (tokens.length === 0)
      return fail(`${mode} requires spaces (e.g. "buy sell roi stoploss trailing").`);
    const validSpaces = new Set(['buy', 'sell', 'roi', 'stoploss', 'trailing', 'protections']);
    const bad = tokens.filter(t => !validSpaces.has(t));
    if (bad.length) return fail(`unknown space(s): ${bad.join(', ')}. Valid: ${Array.from(validSpaces).sort().join(', ')}.`);

    // jobs: optional int >= -1.
    const jobsRaw = ($('runJobs').value || '').trim();
    if (jobsRaw !== '') {
      const jobs = Number(jobsRaw);
      if (!Number.isFinite(jobs) || Math.floor(jobs) !== jobs || jobs < -1)
        return fail(`jobs must be -1 (all CPUs) or a non-negative integer, got "${jobsRaw}".`);
    }

    // random_state: optional int.
    const seedRaw = ($('runRandomState').value || '').trim();
    if (seedRaw !== '' && !/^-?\d+$/.test(seedRaw))
      return fail(`random_state must be an integer, got "${seedRaw}".`);

    // min_trades: optional int >= 1.
    const mtRaw = ($('runMinTrades').value || '').trim();
    if (mtRaw !== '') {
      const mt = Number(mtRaw);
      if (!Number.isFinite(mt) || Math.floor(mt) !== mt || mt < 1)
        return fail(`min_trades must be a positive integer, got "${mtRaw}".`);
    }
  }

  if (mode === 'walkforward') {
    // train/test/step days: required, positive integers.
    for (const [id, name] of [['runTrain', 'train_days'], ['runTest', 'test_days'], ['runStep', 'step_days']]) {
      const raw = ($(id).value || '').trim();
      if (raw === '') return fail(`${name} is required for walk-forward.`);
      const v = Number(raw);
      if (!Number.isFinite(v) || Math.floor(v) !== v || v < 1)
        return fail(`${name} must be a positive integer, got "${raw}".`);
    }

    // wf_min_trades: optional int >= 1.
    const wfmt = ($('runWfMinTrades').value || '').trim();
    if (wfmt !== '') {
      const v = Number(wfmt);
      if (!Number.isFinite(v) || Math.floor(v) !== v || v < 1)
        return fail(`wf_min_trades must be a positive integer, got "${wfmt}".`);
    }

    // wf_max_drawdown: optional float in [0, 1] (a ratio; 0.25 = 25%).
    const wfdd = ($('runWfMaxDD').value || '').trim();
    if (wfdd !== '') {
      const v = Number(wfdd);
      if (!Number.isFinite(v) || v < 0 || v > 1)
        return fail(`wf_max_drawdown must be a ratio between 0 and 1, got "${wfdd}".`);
    }
  }

  return null;
}
async function labRun() {
  const strategy = $('runStrategy').value;
  if (!strategy) { alert('Pick a strategy first.'); return; }
  const mode = $('runMode').value;
  // B1: walk-forward uses its own timerange check (train/test days too).
  if (mode === 'walkforward') {
    const wfErr = validateWfTimerange();
    if (wfErr) { alert(wfErr); return; }
  } else {
    // backtest / hyperopt: require both dates and a plausible timeframe.
    const err = validateRunParams();
    if (err) { alert(err); return; }
  }
  // A4: pre-flight - confirm the strategy file resolves before spawning freqtrade.
  // Best-effort: a network error falls through and run_strategy.py's A2 diagnostic
  // catches the case server-side.
  try {
    const r = await fetch('/api/strategy/current?name=' + encodeURIComponent(strategy));
    const j = await r.json();
    if (j && j.found === false) {
      alert(`Strategy '${strategy}' has no .py under user_data/strategies (or strategies_legacy). Pick another strategy.`);
      return;
    }
  } catch (_) { /* proceed; A2 will catch it */ }
  const start = ($('runStart').value || '').replace(/-/g, '');
  const end = ($('runEnd').value || '').replace(/-/g, '');
  const body = {
    mode,
    strategy,
    timerange: (start && end) ? start + '-' + end : '',
    timeframe: $('runTf').value,
    config: $('runConfig').value.trim(),
    rebuild: true,
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
  // Verbose checkbox: when checked, request -vvv from the server (most detail).
  // Off by default - the run uses the server's default verbosity (-v / INFO).
  if ($('runVerbose').checked) body.verbosity = 3;
  fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r => r.json().then(d => ({ ok: r.ok, status: r.status, body: d })))
    .then(({ ok, status, body }) => {
      if (!ok || body.error) {
        alert(`Run rejected (${status}): ${body.error || 'unknown error'}`);
        return;
      }
      ensureJobPolling();
      // Auto-open the jobs panel so the user immediately sees the running job
      // and its log streaming - otherwise the panel starts hidden and the
      // user has to hunt for the badge.
      const gj = $('globalJobs');
      if (gj && gj.classList && gj.classList.contains('hidden')) openJobsModal();
    })
    .catch(e => { alert('Run failed: ' + e); });
}
function renderLab() {
  // strategy status editor
  const strategyListError = msg => {
    $('strategyEditor').innerHTML = `<p class="hint">Strategy list unavailable: ${esc(msg)}</p>`;
  };
  fetch('/api/strategies')
    .then(r => r.json().then(d => ({ ok: r.ok, body: d })))
    .then(({ ok, body: list }) => {
    if (!ok || !Array.isArray(list)) {
      strategyListError((list && list.error) || 'unknown error');
      return;
    }
    const sel = $('runStrategy');
    sel.innerHTML = '<option value="">(choose…)</option>';
    list.forEach(s => { const o = document.createElement('option'); o.value = s.name; o.textContent = s.name; sel.appendChild(o); });
    // A1: pre-select a known-resolvable strategy so the Lab form has a sane default.
    if (!sel.value && list.some(s => s.name === 'ScreenerDpoEveningStar')) {
      sel.value = 'ScreenerDpoEveningStar';
      showConfigForStrategy(sel.value);
    }
    // hint is populated by loadConfigs() (dropdown-aware text); keep a fallback here for offline mode
    if (!$('runHint').textContent) $('runHint').textContent = 'Auto: user_data/config_<strategy>.json or config_benchmark.json. Pick from dropdown or type a path.';
    const wrap = $('strategyEditor');
    if (!list.length) { wrap.innerHTML = '<p class="hint">No strategies registered.</p>'; return; }
    const t = document.createElement('table');
    t.innerHTML = `<thead><tr><th>Strategy</th><th>Status</th><th class="num">Backtests</th><th class="num">Trades</th><th>Notes</th></tr></thead><tbody>` +
      list.map(s => `<tr>
        <td><b>${esc(s.name)}</b></td>
        <td><select class="statusSel ${esc(s.status||'active')}" data-name="${esc(s.name)}" onchange="this.className='statusSel '+this.value;saveStrategy(this.dataset.name)">
            ${['active','experimental','retired'].map(o=>`<option ${s.status===o?'selected':''}>${o}</option>`).join('')}
          </select></td>
        <td class="num">${fmt(s.n_backtests,0)}</td>
        <td class="num">${fmt(s.n_trades,0)}</td>
        <td><input class="notesInput" data-name="${esc(s.name)}" value="${esc(s.notes||'')}" placeholder="notes" onchange="saveStrategy(this.dataset.name)"></td>
      </tr>`).join('') + '</tbody>';
    wrap.innerHTML = '';
    wrap.appendChild(t);
    makeSortable(t);
    // hook up strategy selection to show its config in the panel below
    const stratSel = $('runStrategy');
    if (stratSel && !stratSel._configBound) {
      stratSel._configBound = true;
      stratSel.addEventListener('change', () => showConfigForStrategy(stratSel.value));
    }
  }).catch(e => { strategyListError(String(e)); });
}
function saveStrategy(name) {
  const sel = document.querySelector(`.statusSel[data-name="${CSS.escape(name)}"]`);
  const notes = document.querySelector(`.notesInput[data-name="${CSS.escape(name)}"]`);
  const body = { name, status: sel ? sel.value : 'active', notes: notes ? notes.value : '' };
  fetch('/api/strategies', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r=>r.json()).then(d => {
      if (d && d.error) { console.error('Strategy save failed:', name, d.error); return; }
      // keep the in-memory registry in sync so every tab reflects the change
      // without waiting for a full report rebuild
      let row = (LAB.canonical || []).find(r => r.strategy === name);
      if (row) {
        row.status = body.status;
        if (notes) row.notes = body.notes;
      } else {
        // strategy exists in the registry but had no runs at report build
        // time; insert a stub so the next render shows the new status
        row = {
          strategy: name, status: body.status, notes: body.notes || '',
          basis: 'registry', run_time: null, source: null, timerange: null,
          profit_total: null, sortino: null, calmar: null, profit_factor: null,
          max_drawdown_account: null, winrate: null, total_trades: null,
          prop_firms: null, score: { grade: '—', grades: {}, score: 0 },
          recommendations: [],
        };
        LAB.canonical.push(row);
      }
      if (DATA_TABS.includes(state.tab)) showTab(state.tab, true);
    })
    .catch(e => console.error('Strategy save failed:', name, e));
}

/* ---------- init ---------- */
function init() {
  setupTableSplitter();
  document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); closeLogViewer(); closeGradeTuner(); closeJobsModal(); } });
  // apply user-tuned grade factors (localStorage) before any render
  applyTunedScoresInPlace();
  populateHistSelect();
  try { $('histMetric2').value = localStorage.getItem('histMetric2') || 'sortino'; } catch (e) {}
  populateTradeRunSelect();
  _tmTab = mountTradeMap('tm-tab');
  _tmDetail = mountTradeMap('tm-detail');
  tlPresetInit();
  tlIndPopulateSelects();
  renderDashboard();
  renderLab();
  updateRunFields();
  defaultRunRange();
  loadLosses();
  loadConfigs();
  // global job polling – visible from any tab (Lab or otherwise)
  ensureJobPolling();
  // first-load freshness check (catches the case where the user lands on
  // a tab with stale data after a manual backtest)
  ensureFresh();
  startFreshnessLoop();

  // resize charts when the viewport changes
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      ['_benchChart','_equityChart','_profitHistChart',
       '_detailEquityChart','_detailHistChart'].forEach(k => {
        if (window[k]) window[k].resize();
      });
      (window._histCharts || []).forEach(c => c.resize());
      _tlInstances.forEach(i => {
        if (i.chart) i.chart.resize();
        (i.inds || []).forEach(e => { if (e.paneEl && e.chart) e.chart.resize(); });
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
  <button id="jobsBtn" class="btn compact" onclick="openJobsModal()" title="Background jobs">
    Jobs <span id="jobsBadge" class="badge hidden">0</span>
  </button>
</header>
<div id="globalJobs" class="hidden"></div>
<div id="jobsBackdrop" onclick="closeJobsModal()"></div>
<div id="jobsModal" aria-hidden="true">
  <div class="jm-head">
    <span class="title">Jobs</span>
    <span id="jobsModalCount" class="hint"></span>
    <span style="flex:1"></span>
    <button class="btn compact" onclick="closeJobsModal()">✕ Close</button>
  </div>
  <div class="jm-body">
    <div id="jobsModalActive"></div>
    <div id="jobsModalRecent"></div>
    <div id="jobsModalEmpty" class="hint hidden">No jobs yet. Run a backtest from the Lab tab.</div>
  </div>
</div>

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
        <span class="hint">each metric → pass / warn / fail against thresholds · grade from those</span>
        <button class="btn compact" onclick="openGradeTuner()">Tune grades</button></div>
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
          <div><b style="color:var(--lavender)">Worst trade</b> ≥ −15% pass · ≥ −25% warn · below flags outlier trades (robust avg of 3 worst; n&lt;20 uses single worst)</div>
        </div>
        <div class="hint">Each strategy shows ONE grade from its most recent benchmark run (else latest backtest). A robust Worst trade (avg of 3 worst, −25% or worse) flags the metric; a −60% outlier also raises a fail recommendation. A lone −15% to −25% wick is now warn-only and will not alone force grade C/D. Click a strategy for the full breakdown and every run.</div>
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
        <label><input type="checkbox" id="logScale" checked onchange="renderHistory()"> Profit % (log scale)</label>
        <label>2nd metric:
          <select id="histMetric2" onchange="histMetric2Set(this.value)">
            <option value="sortino">Sortino</option>
            <option value="calmar">Calmar</option>
            <option value="profit_factor">Profit factor</option>
            <option value="max_drawdown">Max drawdown</option>
            <option value="winrate">Win rate</option>
            <option value="trades">Trades</option>
          </select>
        </label>
        <select id="histSelect" size="1" multiple style="min-width:260px" onchange="renderHistory()">
          <option value="__top" selected>Top by run count</option>
          <option value="__all">All</option>
        </select>
        <button class="btn" onclick="histSelectAll()">Select all</button>
        <button class="btn" onclick="histSelectTop()">Top 8</button>
        <button class="btn" onclick="histClear()">Clear</button>
      </div>
      <div class="hist-grid" id="histGrid"></div>
    </section>
  </div>

  <!-- ============ BENCHMARK ============ -->
  <div class="tab" id="tab-benchmark">
    <section>
      <div class="section-head"><h2>Benchmark</h2>
        <span class="hint">one box per strategy, one dot per run · outliers visible at a glance</span></div>
      <details class="paramsBlock" style="margin-bottom:10px">
        <summary>How to read this (plain English)</summary>
        <div style="font-size:12.5px;line-height:1.65;color:var(--text-dim)">
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">The idea:</b>
            every strategy is run against the same data and (ideally) the same config, so the numbers
            are comparable. For a <b>benchmark</b> run, all strategies use the shared
            <code>config_benchmark.json</code> on a fixed timerange — fair across the board.
            A strategy with no benchmark runs yet falls back to its <b>backtest</b> runs (the ones
            stored under <code>user_data/backtest_results/</code>) so nothing is invisible.
            Those backtest runs may have used each strategy's own per-strategy config, so
            cross-strategy differences blend "strategy edge" and "config choice" — the chart marks
            each row with a <b>B</b> (benchmark) or <b>T</b> (backtest) tag so you can tell.</p>
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">Why it matters:</b>
            a single backtest number hides variance. A <b>distribution</b> over many runs is
            what a real data scientist would look at — it tells you whether the strategy's
            performance is consistent or whether one lucky run is carrying the average.</p>
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">The chart:</b>
            each row is one strategy. The <b>box</b> spans the interquartile range (Q1 → Q3)
            with a line at the <b>median</b> (the diamond marker). Whiskers reach to the
            min/max inside a sane range. <b>Individual dots</b> are the raw runs — turn them
            off via "Show every run" if you only want the box. The horizontal axis is the
            selected metric.</p>
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">Metrics:</b>
            <b>Sortino</b> = risk-adjusted return, penalising only downside volatility
            (&gt;1 strong, &gt;0.3 ok). <b>Total Profit</b> = sum of all trade profits in the run.
            <b>Calmar</b> = CAGR divided by max drawdown (&gt;1 means return exceeds worst loss).
            <b>Profit factor</b> = gross profit ÷ gross loss (&gt;1.2 good).
            <b>Max Drawdown</b> = worst peak-to-trough loss as a fraction of account
            (lower is better; ≤20% pass, ≤40% warn). <b>Log scale</b> helps when some
            strategies are near zero — without it those rows collapse to a flat line.</p>
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">Colors and outliers:</b>
            the median diamond is <span style="color:#6ee7a8">green</span> when it clears the
            pass threshold, <span style="color:#fbbf24">amber</span> when it lands in the
            warn band, <span style="color:#f87171">red</span> when it fails. The summary
            line reports the count of strategies / runs / <b>MAD outliers</b> (points whose
            distance from the strategy's median is more than 2.5 × the median absolute
            deviation — robust to skew, unlike mean/stddev).</p>
          <p style="margin:0"><b style="color:var(--lavender)">What good looks like:</b>
            tight boxes centered above the pass threshold = consistent edge.
            Wide boxes = high variance between runs (could be regime sensitivity or just
            a small sample). A single point and no box means only one run exists for that
            strategy — no distribution to speak of; rerun benchmarks to get a real picture.
            To produce a fair cross-strategy benchmark, open the <b>Lab</b> tab and hit
            <b>Run benchmark</b>.</p>
        </div>
      </details>
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
        <label>Source:
          <select id="benchSource" onchange="renderBenchmark()">
            <option value="auto" selected>Benchmark + backtest (default)</option>
            <option value="benchmark">Benchmark only</option>
            <option value="backtest">Backtest only</option>
          </select>
        </label>
        <label>Sort by:
          <select id="benchSort" onchange="renderBenchmark()">
            <option value="median">Median (default)</option>
            <option value="count">Run count</option>
            <option value="name">Strategy name</option>
          </select>
        </label>
        <label><input type="checkbox" id="benchLog" onchange="renderBenchmark()"> Log scale</label>
        <label><input type="checkbox" id="benchPoints" checked onchange="renderBenchmark()"> Show every run</label>
      </div>
      <div class="chart-box"><p id="benchHint" class="hint"></p><div id="benchChart" class="chart" style="height:460px"></div></div>
    </section>
  </div>

  <!-- ============ WALK-FORWARD ============ -->
  <div class="tab" id="tab-walkforward">
    <section>
      <div class="section-head"><h2>Walk-Forward (out-of-sample)</h2>
        <span class="hint">profitable windows / total = OOS consistency · click any row for per-window OOS</span></div>
      <details class="paramsBlock" style="margin-bottom:10px">
        <summary>How to read this (plain English)</summary>
        <div style="font-size:12.5px;line-height:1.65;color:var(--text-dim)">
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">The idea:</b>
            the strategy's parameters are re-optimized on a rolling training window (say 90 days),
            then traded on the <b>next</b> chunk of data the optimizer never saw (say 14 days) — the
            <b>out-of-sample (OOS)</b> period. This repeats across the whole date range,
            one "window" per step. It simulates real usage: fit on the past, trade the future.</p>
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">Why it matters:</b>
            a normal backtest optimizes parameters on <i>all</i> the data,
            which flatters the result. OOS numbers are the honest ones — they show how the
            strategy performs on data it was not tuned on.</p>
          <p style="margin:0 0 6px"><b style="color:var(--lavender)">Columns:</b>
            <b>Windows</b> = how many re-optimize→test steps ran (2 is weak evidence, 40+ is solid).
            <b>Profitable</b> = share of test windows that ended in profit — the consistency column
            (<span class="pill pass">pass</span> ≥60%, <span class="pill warn">warn</span> ≥40%,
            otherwise fail). <b>OOS Trades</b> = total trades in test windows only
            (very few trades = statistically weak). <b>OOS Profit</b> = profit summed over test
            windows only — training-period profit is excluded, so this is <i>not</i> the same as
            the backtest profit. <b>Avg Sortino</b> = risk-adjusted return per window
            (&gt;0 good, &gt;1 strong). <b>Avg PF</b> = profit factor, gross profit ÷ gross loss
            per window (&gt;1.15 decent, &gt;1.5 good). <b>Loss</b> = the hyperopt loss function
            used to re-optimize each training window. The "90/14/14 d" tag in the detail view =
            90 training days / 14 test days / step 14 days.</p>
          <p style="margin:0 0 6px">
            <b style="color:var(--lavender)">The detail view (click a row):</b>
            each bar is one window's OOS profit (<span style="color:#6ee7a8">green</span> =
            profitable window, <span style="color:#f87171">red</span> = losing window);
            the line shows the trend. The table gives Test range (the unseen period), Trades,
            Profit, Win%, Sortino, PF and <b>DD</b> (max drawdown inside that window).</p>
          <p style="margin:0"><b style="color:var(--lavender)">What good looks like:</b>
            most bars positive <i>and</i> similar in size = robust edge. One or two huge bars
            carrying all the profit = fragile (one lucky period). Bars shrinking left→right =
            edge decaying over time. 38/41 profitable windows beats 2/2 — more windows,
            more trustworthy the result.</p>
        </div>
      </details>
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
        <button class="btn" id="tradeLoadBtn" onclick="loadTradeRun()" title="auto-loaded — click to reload" style="display:none">Load</button>
        <span id="tradeStatus" class="hint">auto-loaded · newest run</span>
      </div>
      <div class="charts">
        <div class="chart-box"><div id="equityChart" class="chart"></div></div>
        <div class="chart-box"><div id="profitHistChart" class="chart"></div></div>
      </div>
      <section>
        <div id="tm-tab"></div>
      </section>
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
            <select id="runLoss"></select></label>
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
          <label>Config:
            <select id="runConfig" style="min-width:220px">
              <option value="">auto (optional)</option>
            </select>
          </label>
          <label title="Adds -vvv to the freqtrade command for the most detailed log output. Off by default (the run uses -v / INFO). Useful when a run is misbehaving and you need to see what freqtrade is doing internally."><input type="checkbox" id="runVerbose"> Verbose (-vvv)</label>
          <button class="btn primary" onclick="labRun()">▶ Run</button>
          <button class="btn" onclick="labRefresh()">↻ Refresh data &amp; rebuild report</button>
        </div>
        <div id="runHint" class="hint"></div>
      </div>
      <!-- Backtest Config Panel - shows the config used for the selected strategy -->
      <div id="backtestConfigPanel" class="card" style="display:none;">
        <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border);">
          <h5 style="margin:0;color:var(--lavender);font-size:14px;">Backtest Config Used</h5>
          <button class="btn compact" onclick="toggleConfigPanel()" style="padding:4px 10px;font-size:12px;">
            <span id="configPanelIcon">▼</span>
          </button>
        </div>
        <pre id="backtestConfigJson" class="mb-0" style="max-height:400px;overflow:auto;font-size:12px;line-height:1.5;"></pre>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Benchmark</h2>
        <span class="hint">run every strategy on the shared config and compare distributions</span></div>
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
        <span class="hint">active / experimental / retired + notes (stored in DB) · changes save automatically · registry is the single source of truth; see the Strategies tab for the full list with latest results</span></div>
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
    <div class="section-head"><h2>Prop firm requirements</h2>
      <span class="hint">challenge rules vs reconstructed equity — conservative: trade-close granularity, worst-case open-trade excursions, CE(S)T midnights</span></div>
    <div class="table-wrap"><div id="detailProp"></div></div>
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
    <div id="tm-detail"></div>
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

<!-- ============ GRADE TUNER MODAL ============ -->
<div id="gradeBackdrop" onclick="closeGradeTuner()"></div>
<div id="gradeModal" aria-hidden="true">
  <div class="g-head">
    <span class="title">Tune grade thresholds</span>
    <span class="hint">persisted in localStorage · grades re-derive client-side</span>
  </div>
  <div class="g-body">
    <table>
      <thead><tr><th>Metric</th><th class="num">Pass</th><th class="num">Warn</th><th>Direction</th></tr></thead>
      <tbody id="gradeTunerRows"></tbody>
    </table>
    <p id="gradeTunerErr" class="err" style="display:none;margin-top:8px"></p>
    <p class="hint" style="margin-top:8px">Lower pass / warn = stricter. "Higher better" means pass when value ≥ threshold; "lower better" means pass when value ≤ threshold. Worst-trade thresholds are negative (e.g. -0.15 = −15%).</p>
  </div>
  <div class="g-foot">
    <button class="btn" onclick="resetGradeFactors()">Reset to defaults</button>
    <span style="flex:1"></span>
    <button class="btn" onclick="closeGradeTuner()">Cancel</button>
    <button class="btn primary" onclick="applyGradeFactors()">Apply</button>
  </div>
</div>

<!-- ============ JOB LOG VIEWER ============ -->
<div id="logViewerBackdrop" onclick="closeLogViewer()"></div>
<div id="logViewer" aria-hidden="true">
  <div class="lv-head">
    <span class="title" id="lvTitle">Job log</span>
    <button class="btn compact" onclick="copyText($('lvPre').textContent)">Copy</button>
    <button class="btn compact" onclick="refreshLogViewer()">↻ Refresh</button>
    <button class="btn compact" onclick="closeLogViewer()">✕ Close</button>
  </div>
  <div class="lv-body"><pre class="log" id="lvPre">Loading…</pre><div class="hint" id="lvHint" style="margin-top:8px"></div></div>
</div>

<footer>Strategy Lab · results.db → dashboard.html · ingest_results.py · benchmark_runner.py · build_report.py · server.py</footer>

<script>
const LAB = {data_placeholder};
const LAB_LOSSES = {losses_placeholder};
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

    # Extract backtest configs from zip files
    user_data = ANALYSIS_DIR.parent
    backtest_configs = extract_backtest_configs(user_data, data["backtests"])

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
        "prop_firms_spec": PROP_FIRMS,
        "built": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "configs": extras["configs"],
        "current_code": extras["current_code"],
        "current_code_set": extras["current_code_set"],
        "snapshot_paths": extras["snapshot_paths"],
        "snapshot_combined": extras["snapshot_combined"],
        "snapshot_files": extras["snapshot_files"],
        "backtest_configs": backtest_configs,
    }

    losses = discover_losses(ANALYSIS_DIR.parent)

    html = HTML_TEMPLATE
    html = html.replace("{css}", CSS)
    html = html.replace("{js}", JS)
    html = html.replace("{data_placeholder}", json.dumps(lab, default=str))
    html = html.replace("{losses_placeholder}", json.dumps(losses))
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
