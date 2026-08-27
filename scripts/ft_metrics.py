"""Shared metric extraction helpers for the strategy-lab toolset.

Both the ingester and the benchmark runner use these so every row in the
database is produced the same way.

Also hosts the run-provenance helpers (config + strategy code snapshots) so
run_strategy.py, ingest_results.py and benchmark_runner.py all stamp hashes
the same way.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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


# ------------------------------------------------------------- run provenance ---

HASH_COLS = {
    "backtests": ["config_hash", "code_hash", "code_verified"],
    "benchmarks": ["config_hash", "code_hash", "code_verified"],
    "hyperopt": ["config_hash", "code_hash", "code_verified"],
    "walkforward": ["config_hash", "code_hash", "code_verified"],
}

PROVENANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS configs (
    hash TEXT PRIMARY KEY,
    config_json TEXT,
    size INTEGER,
    path TEXT
);

CREATE TABLE IF NOT EXISTS strategy_snapshots (
    hash TEXT PRIMARY KEY,
    strategy TEXT,
    path TEXT,
    source TEXT,
    mtime REAL,
    captured_at TEXT,
    verified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_artifacts (
    kind TEXT,
    strategy TEXT,
    source TEXT,
    config_hash TEXT,
    code_hash TEXT,
    recorded_at TEXT,
    PRIMARY KEY (kind, strategy, source)
);
"""


def ensure_provenance(conn: sqlite3.Connection) -> None:
    """Create provenance tables + additive hash columns on run tables."""
    conn.executescript(PROVENANCE_SCHEMA)
    cur = conn.cursor()
    for table, cols in HASH_COLS.items():
        try:
            existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.OperationalError:
            continue
        for col in cols:
            if col not in existing and existing:
                ddl_type = "INTEGER" if col == "code_verified" else "TEXT"
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}")
                except sqlite3.OperationalError:
                    pass
    conn.commit()


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def find_strategy_file(user_data: Path, name: str) -> Path | None:
    """Locate <name>.py under user_data/strategies (and legacy trees)."""
    if not name:
        return None
    roots = [user_data / "strategies", user_data / "strategies_legacy"]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(p for p in root.rglob(f"{name}.py"))
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: len(str(p)))[0]


def store_config_text(conn: sqlite3.Connection, text: str, path: str | None = None) -> str | None:
    """Dedupe-store a config JSON blob; returns its sha1 hash."""
    try:
        json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass  # still store raw text, drawer renders best-effort
    h = sha1_text(text)
    conn.execute(
        "INSERT OR IGNORE INTO configs (hash, config_json, size, path) VALUES (?,?,?,?)",
        (h, text, len(text), path),
    )
    conn.commit()
    return h


def snapshot_strategy(conn: sqlite3.Connection, user_data: Path, strategy: str,
                      verified: bool) -> str | None:
    """Hash the current strategy file into strategy_snapshots; returns hash.

    verified=True means captured at run time by run_strategy.py;
    verified=False is a best-effort ingest-time guess for legacy rows.
    """
    path = find_strategy_file(user_data, strategy)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    h = sha1_text(text)
    conn.execute(
        """INSERT INTO strategy_snapshots (hash, strategy, path, source, mtime, captured_at, verified)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(hash) DO UPDATE SET
             verified = MAX(strategy_snapshots.verified, excluded.verified)""",
        (h, strategy, str(path), text, path.stat().st_mtime,
         datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), int(verified)),
    )
    conn.commit()
    return h


def record_run_artifact(conn: sqlite3.Connection, kind: str, strategy: str,
                        source: str, config_hash: str | None, code_hash: str | None) -> None:
    """Remember which config/code a finished run produced (matched at ingest)."""
    conn.execute(
        """INSERT INTO run_artifacts (kind, strategy, source, config_hash, code_hash, recorded_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(kind, strategy, source) DO UPDATE SET
             config_hash=excluded.config_hash, code_hash=excluded.code_hash,
             recorded_at=excluded.recorded_at""",
        (kind, strategy, source, config_hash, code_hash,
         datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()


def apply_run_artifacts(conn: sqlite3.Connection) -> int:
    """Stamp hashes from run_artifacts onto ingested rows. Returns rows updated."""
    cur = conn.cursor()
    tables = {"backtest": ("backtests",), "benchmark": ("benchmarks",),
              "hyperopt": ("hyperopt",), "walkforward": ("walkforward",)}
    n = 0
    for kind, (table,) in tables.items():
        try:
            arts = cur.execute(
                "SELECT strategy, source, config_hash, code_hash FROM run_artifacts WHERE kind=?",
                (kind,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for strategy, source, chash, cdhash in arts:
            try:
                cur.execute(
                    f"""UPDATE {table} SET config_hash=?, code_hash=?, code_verified=1
                        WHERE strategy=? AND source=?""",
                    (chash, cdhash, strategy, source),
                )
                n += cur.rowcount
            except sqlite3.OperationalError:
                break
    conn.commit()
    return n


def stamp_legacy_code_hashes(conn: sqlite3.Connection, user_data: Path) -> int:
    """Best-effort code_hash for runs without one (file may have changed since).

    Marks snapshots as verified=0 so the UI can flag them as unverified.
    """
    cur = conn.cursor()
    n = 0
    for table, in (("backtests",), ("benchmarks",), ("hyperopt",), ("walkforward",)):
        try:
            rows = cur.execute(
                f"""SELECT DISTINCT strategy FROM {table}
                    WHERE code_hash IS NULL AND strategy IS NOT NULL"""
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for (strategy,) in rows:
            h = snapshot_strategy(conn, user_data, strategy, verified=False)
            if h is None:
                continue
            try:
                cur.execute(
                    f"""UPDATE {table} SET code_hash=?, code_verified=0
                        WHERE strategy=? AND code_hash IS NULL""",
                    (h, strategy),
                )
                n += cur.rowcount
            except sqlite3.OperationalError:
                continue
    conn.commit()
    return n
