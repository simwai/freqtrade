"""benchmark_runner.py — run strategies through one shared config for fair cross-comparison.

Every strategy is backtested on the same config / pairlist / timerange, and the
results are appended to a ``benchmarks`` table in results.db. This lets you compare
strategies that otherwise use different per-strategy configs.

Usage:
    python user_data/scripts/benchmark_runner.py --strategies BigZ08 MfiEmaWaveTrend OctopusNestStrategy
    python user_data/scripts/benchmark_runner.py --strategies BigZ08 --timerange 20220101-20240101 --timeframe 5m
    python user_data/scripts/benchmark_runner.py --list

Requires freqtrade on PATH or --freqtrade to point at the executable.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ft_metrics import (
    connect_wal,
    ensure_provenance,
    extract_metrics,
    run_time_iso,
    snapshot_strategy,
    store_config_text,
    timerange_str,
)  # noqa: E402

USER_DATA = Path(__file__).resolve().parents[1]
# freqtrade defaults user_data to <cwd>/user_data when config has no user_data_dir;
# pin cwd to the repo root so server-launched runs resolve it regardless of launch dir
REPO_ROOT = USER_DATA.parent
DEFAULT_CONFIG = USER_DATA / "config_benchmark.json"
DEFAULT_DB = USER_DATA / "analysis" / "results.db"

BENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT,
    source TEXT,
    run_time TEXT,
    timeframe TEXT,
    timerange TEXT,
    trading_mode TEXT,
    stake_currency TEXT,
    dry_run_wallet REAL,
    pair_count INTEGER,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    winrate REAL,
    profit_total REAL,
    profit_total_abs REAL,
    profit_factor REAL,
    sortino REAL,
    sharpe REAL,
    calmar REAL,
    sqn REAL,
    cagr REAL,
    expectancy REAL,
    expectancy_ratio REAL,
    max_drawdown_account REAL,
    max_relative_drawdown REAL,
    max_drawdown_abs REAL,
    trades_per_day REAL,
    holding_avg_s REAL,
    UNIQUE(strategy, source)
);
"""


def list_strategies(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT strategy FROM backtests ORDER BY strategy"
    ).fetchall()]


def run_backtest(strategy: str, config: Path, timerange: str, timeframe: str,
                 freqtrade: str, extra: list[str]) -> str:
    """Run one freqtrade backtest and return the path of the newest bench result zip."""
    out_dir = USER_DATA / "analysis"
    cmd = [
        *freqtrade.split(), "backtesting",
        "-c", str(config),
        "--strategy", strategy,
        "--timerange", timerange,
        "--timeframe", timeframe,
        "--cache", "none",
        "--export", "trades",
        "--export-filename", str(out_dir / "bench_results.json"),
        *extra,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"backtesting failed for {strategy}:\n{proc.stderr[-2000:]}")
    # freqtrade writes bench_results-<timestamp>.zip
    zips = sorted(out_dir.glob("bench_results-*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        raise RuntimeError(f"no result file produced for {strategy}")
    return str(zips[-1])


def read_result(path: str) -> dict | None:
    """Return the metrics dict for the single strategy in a bench result zip."""
    import zipfile

    with zipfile.ZipFile(path) as z:
        jname = next((n for n in z.namelist() if n.endswith(".json") and "meta" not in n), None)
        if not jname:
            return None
        data = json.loads(z.read(jname))
    strategies = data.get("strategy")
    if not strategies:
        return None
    return next(iter(strategies.values()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", nargs="*", help="Strategy names (default: all in db)")
    ap.add_argument("--list", action="store_true", help="List strategies in db and exit")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--timerange", default="20230101-20240101")
    ap.add_argument("--timeframe", default="5m")
    default_ft = f"{sys.executable} -m freqtrade" if sys.executable else "freqtrade"
    ap.add_argument("--freqtrade", default=default_ft, help="freqtrade command (default: current python -m freqtrade)")
    ap.add_argument("--keep-results", action="store_true",
                    help="Don't delete the intermediate bench_results.json")
    args = ap.parse_args()

    conn = connect_wal(args.db)
    conn.executescript(BENCH_SCHEMA)
    ensure_provenance(conn)

    if args.list:
        for s in list_strategies(conn):
            print(s)
        conn.close()
        return 0

    strategies = args.strategies or list_strategies(conn)
    if not strategies:
        print("No strategies found. Run ingest_results.py first.", file=sys.stderr)
        conn.close()
        return 1

    config = Path(args.config)
    if not config.is_file():
        print(f"Config not found: {config}", file=sys.stderr)
        conn.close()
        return 1

    print(f"Benchmark: {len(strategies)} strategies, config={config.name}, "
          f"timerange={args.timerange}, tf={args.timeframe}")
    bench_config_hash = None
    try:
        bench_config_hash = store_config_text(conn, config.read_text(encoding="utf-8"), path=str(config))
    except OSError:
        pass
    cur = conn.cursor()
    imported = 0
    for s in strategies:
        code_hash = snapshot_strategy(conn, USER_DATA, s, verified=True)
        try:
            res = run_backtest(s, config, args.timerange, args.timeframe, args.freqtrade, [])
        except RuntimeError as e:
            print(f"  SKIP {s}: {str(e)[:120]}")
            continue
        sdata = read_result(res)
        if sdata is None:
            print(f"  SKIP {s}: no result data")
            continue
        m = extract_metrics(sdata)
        source = f"bench_{args.timerange}_{args.timeframe}.json"
        cur.execute(
            """INSERT OR IGNORE INTO benchmarks
               (strategy, source, run_time, timeframe, timerange, trading_mode, stake_currency,
                dry_run_wallet, pair_count, total_trades, wins, losses, winrate,
                profit_total, profit_total_abs, profit_factor, sortino, sharpe, calmar, sqn,
                cagr, expectancy, expectancy_ratio, max_drawdown_account, max_relative_drawdown,
                max_drawdown_abs, trades_per_day, holding_avg_s)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                s, source, run_time_iso(sdata), m.get("timeframe"), timerange_str(sdata),
                m.get("trading_mode"), m.get("stake_currency"), m.get("dry_run_wallet"),
                m.get("pair_count"), m.get("total_trades"), m.get("wins"), m.get("losses"),
                m.get("winrate"), m.get("profit_total"), m.get("profit_total_abs"),
                m.get("profit_factor"), m.get("sortino"), m.get("sharpe"), m.get("calmar"),
                m.get("sqn"), m.get("cagr"), m.get("expectancy"), m.get("expectancy_ratio"),
                m.get("max_drawdown_account"), m.get("max_relative_drawdown"),
                m.get("max_drawdown_abs"), m.get("trades_per_day"), m.get("holding_avg_s"),
            ),
        )
        if cur.rowcount:
            imported += 1
            try:
                cur.execute(
                    "UPDATE benchmarks SET config_hash=COALESCE(?, config_hash),"
                    " code_hash=COALESCE(?, code_hash),"
                    " code_verified=CASE WHEN ? IS NOT NULL THEN 1 ELSE 0 END"
                    " WHERE strategy=? AND source=?",
                    (bench_config_hash, code_hash, code_hash, s, source),
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()
            print(f"  OK   {s}: trades={m.get('total_trades')} profit={m.get('profit_total'):.4f} "
                  f"sortino={m.get('sortino')} dd={m.get('max_drawdown_account'):.3f}")
        else:
            print(f"  DUP  {s} (already benchmarked for {timerange_str(sdata)})")

    if not args.keep_results:
        for leftover in Path(USER_DATA / "analysis").glob("bench_results-*.zip"):
            try:
                leftover.unlink()
            except OSError:
                pass

    conn.commit()
    conn.close()
    print(f"\n{imported} benchmark results added to {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
