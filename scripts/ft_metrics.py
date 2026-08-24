"""Shared metric extraction helpers for the strategy-lab toolset.

Both the ingester and the benchmark runner use these so every row in the
database is produced the same way.
"""

from __future__ import annotations

from datetime import datetime, timezone


METRIC_KEYS = (
    "total_trades",
    "wins",
    "losses",
    "winrate",
    "profit_total",
    "profit_total_abs",
    "profit_factor",
    "sortino",
    "sharpe",
    "calmar",
    "sqn",
    "cagr",
    "expectancy",
    "expectancy_ratio",
    "max_drawdown_account",
    "max_relative_drawdown",
    "max_drawdown_abs",
    "trades_per_day",
    "holding_avg_s",
    "winner_holding_avg_s",
    "loser_holding_avg_s",
)


def _num(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_metrics(obj: dict) -> dict:
    """Pull a flat set of metrics from a backtest/hyperopt strategy dict.

    The value may be a plain flat dict (modern files) or contain a nested
    ``results_metrics`` / ``results`` dict (hyperopt epochs / older files).
    """
    source = obj
    if isinstance(source, dict):
        for nested in ("results_metrics", "results"):
            if isinstance(source.get(nested), dict):
                source = source[nested]
                break

    out: dict = {}
    for key in METRIC_KEYS:
        out[key] = _num(source.get(key)) if isinstance(source, dict) else None

    if isinstance(source, dict):
        # pair count (best-effort)
        pairs = source.get("results_per_pair")
        out["pair_count"] = len(pairs) if isinstance(pairs, list) else None

        for tskey in ("timerange", "timeframe", "trading_mode", "stake_currency", "strategy_name"):
            out[tskey] = source.get(tskey)
        out["dry_run_wallet"] = _num(source.get("dry_run_wallet"))
        out["backtest_start"] = _num(source.get("backtest_start_ts"))
        out["backtest_end"] = _num(source.get("backtest_end_ts"))
    return out


def run_time_iso(obj: dict, fallback_ts: float | None = None) -> str | None:
    """Best-effort ISO timestamp for a run."""
    ts = None
    if isinstance(obj, dict):
        ts = _num(obj.get("backtest_run_start_ts"))
        if ts is None:
            ts = _num(obj.get("backtest_run_end_ts"))
    if ts is None:
        ts = fallback_ts
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return None


def timerange_str(obj: dict, start_ts: float | None = None, end_ts: float | None = None) -> str:
    """Human readable timerange for display."""
    if isinstance(obj, dict):
        tr = obj.get("timerange")
        if tr:
            return str(tr)
        start = _num(obj.get("backtest_start_ts")) or start_ts
        end = _num(obj.get("backtest_end_ts")) or end_ts
    else:
        start, end = start_ts, end_ts
    fmt = lambda ts: datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc).strftime("%Y%m%d")
    if start and end:
        try:
            return f"{fmt(start)}-{fmt(end)}"
        except (OverflowError, OSError, ValueError):
            return ""
    return ""
