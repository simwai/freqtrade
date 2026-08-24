"""ingest_results.py — build user_data/analysis/results.db from all freqtrade artifacts.

Scans:
  - user_data/backtest_results/       (backtest-result-*.json and *.zip)
  - user_data/hyperopt_results/**/    (*.fthypt — line streamed, best epoch kept)
  - user_data/walk_forward/**/walk_forward.json

Writes an idempotent SQLite DB. Safe to re-run after every backtest/hyperopt run.

Usage:
    python user_data/scripts/ingest_results.py [--db user_data/analysis/results.db]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ft_metrics import extract_metrics, run_time_iso, timerange_str  # noqa: E402

USER_DATA = Path(__file__).resolve().parents[1]
BACKTEST_DIR = USER_DATA / "backtest_results"
HYPEROPT_DIR = USER_DATA / "hyperopt_results"
WALK_FORWARD_DIR = USER_DATA / "walk_forward"
ANALYSIS_DIR = USER_DATA / "analysis"

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT,
    source TEXT,
    run_time TEXT,
    timeframe TEXT,
    timerange TEXT,
    trading_mode TEXT,
    stake_currency TEXT,
    dry_run_wallet REAL,
    config_json TEXT,
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
    UNIQUE(source, strategy)
);

CREATE TABLE IF NOT EXISTS hyperopt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT,
    source TEXT,
    run_time TEXT,
    epochs INTEGER,
    best_loss REAL,
    best_trades INTEGER,
    best_profit_total REAL,
    best_profit_abs REAL,
    best_winrate REAL,
    best_sortino REAL,
    best_calmar REAL,
    best_profit_factor REAL,
    best_max_drawdown REAL,
    best_params TEXT,
    UNIQUE(source)
);

CREATE TABLE IF NOT EXISTS walkforward (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT,
    run_id TEXT,
    source TEXT,
    run_time TEXT,
    train_days INTEGER,
    test_days INTEGER,
    step_days INTEGER,
    timerange TEXT,
    n_windows INTEGER,
    profitable_windows INTEGER,
    oos_trades INTEGER,
    oos_profit_abs REAL,
    oos_winrate REAL,
    avg_oos_sortino REAL,
    avg_oos_calmar REAL,
    avg_oos_profit_factor REAL,
    avg_oos_max_drawdown REAL,
    UNIQUE(source)
);

CREATE TABLE IF NOT EXISTS strategies (
    name TEXT PRIMARY KEY,
    status TEXT DEFAULT 'active',
    notes TEXT DEFAULT '',
    updated_at TEXT
);

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

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT,
    source TEXT,
    pair TEXT,
    is_short INTEGER,
    enter_tag TEXT,
    exit_reason TEXT,
    open_date TEXT,
    close_date TEXT,
    open_rate REAL,
    close_rate REAL,
    min_rate REAL,
    max_rate REAL,
    amount REAL,
    stake_amount REAL,
    leverage REAL,
    profit_ratio REAL,
    profit_abs REAL,
    trade_duration INTEGER,
    stop_loss_abs REAL,
    stop_loss_ratio REAL,
    initial_stop_loss_abs REAL,
    initial_stop_loss_ratio REAL,
    fee_open REAL,
    fee_close REAL,
    UNIQUE(source, strategy, open_date, close_date, pair, profit_abs)
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def iter_backtest_jsons():
    """Yield (strategy_name, metrics_dict, source_label, config_json) per backtest file."""
    # plain JSON files
    for f in sorted(BACKTEST_DIR.glob("backtest-result-*.json")):
        if f.name.endswith(".meta.json"):
            continue
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        for sname, sdata in _strategies_of(data):
            yield sname, sdata, f.name, None

    # zipped backtests (newer format)
    for zf in sorted(BACKTEST_DIR.glob("backtest-result-*.zip")):
        try:
            with zipfile.ZipFile(zf) as z:
                names = z.namelist()
                jname = next((n for n in names if n.endswith(".json") and "_config" not in n and "meta" not in n), None)
                cname = next((n for n in names if n.endswith("_config.json")), None)
                if not jname:
                    continue
                data = json.loads(z.read(jname))
                config_json = json.dumps(json.loads(z.read(cname)), sort_keys=True) if cname else None
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError):
            continue
        for sname, sdata in _strategies_of(data):
            yield sname, sdata, zf.name, config_json


def _strategies_of(data: dict):
    strategies = data.get("strategy") or {}
    if not isinstance(strategies, dict):
        return
    for sname, sdata in strategies.items():
        if not isinstance(sdata, dict):
            continue
        yield sname, sdata


def ingest_backtests(conn: sqlite3.Connection) -> int:
    count = 0
    cur = conn.cursor()
    for sname, sdata, source, config_json in iter_backtest_jsons():
        m = extract_metrics(sdata)
        run_time = run_time_iso(sdata, os.path.getmtime(BACKTEST_DIR / source))
        timerange = timerange_str(sdata)
        cur.execute(
            """INSERT OR IGNORE INTO backtests
               (strategy, source, run_time, timeframe, timerange, trading_mode, stake_currency,
                dry_run_wallet, config_json, pair_count, total_trades, wins, losses, winrate,
                profit_total, profit_total_abs, profit_factor, sortino, sharpe, calmar, sqn,
                cagr, expectancy, expectancy_ratio, max_drawdown_account, max_relative_drawdown,
                max_drawdown_abs, trades_per_day, holding_avg_s)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sname, source, run_time, m.get("timeframe"), timerange, m.get("trading_mode"),
                m.get("stake_currency"), m.get("dry_run_wallet"), config_json, m.get("pair_count"),
                m.get("total_trades"), m.get("wins"), m.get("losses"), m.get("winrate"),
                m.get("profit_total"), m.get("profit_total_abs"), m.get("profit_factor"),
                m.get("sortino"), m.get("sharpe"), m.get("calmar"), m.get("sqn"), m.get("cagr"),
                m.get("expectancy"), m.get("expectancy_ratio"), m.get("max_drawdown_account"),
                m.get("max_relative_drawdown"), m.get("max_drawdown_abs"),
                m.get("trades_per_day"), m.get("holding_avg_s"),
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


TRADE_COLS = (
    "pair", "is_short", "enter_tag", "exit_reason", "open_date", "close_date",
    "open_rate", "close_rate", "min_rate", "max_rate", "amount", "stake_amount",
    "leverage", "profit_ratio", "profit_abs", "trade_duration", "stop_loss_abs",
    "stop_loss_ratio", "initial_stop_loss_abs", "initial_stop_loss_ratio",
    "fee_open", "fee_close",
)


def _trade_row(sdata: dict, source: str):
    """Extract normalized trade tuples from a backtest strategy dict."""
    trades = sdata.get("trades") or []
    for t in trades:
        if not isinstance(t, dict):
            continue
        row = []
        for col in TRADE_COLS:
            v = t.get(col)
            if isinstance(v, bool):
                v = int(v)
            row.append(v)
        yield tuple(row)


def ingest_trades(conn: sqlite3.Connection) -> int:
    """Ingest per-trade details (SL/TP, exit reason, tags) from all backtests."""
    count = 0
    cur = conn.cursor()
    seen = set()
    for f in sorted(BACKTEST_DIR.glob("backtest-result-*.json")):
        if f.name.endswith(".meta.json"):
            continue
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        for sname, sdata in _strategies_of(data):
            key = (sname, f.name)
            if key in seen:
                continue
            seen.add(key)
            for trow in _trade_row(sdata, f.name):
                cur.execute(
                    f"""INSERT OR IGNORE INTO trades
                       (strategy, source, {', '.join(TRADE_COLS)})
                       VALUES ({', '.join('?' for _ in range(2 + len(TRADE_COLS)))})""",
                    (sname, f.name, *trow),
                )
                count += cur.rowcount

    for zf in sorted(BACKTEST_DIR.glob("backtest-result-*.zip")):
        try:
            with zipfile.ZipFile(zf) as z:
                jname = next((n for n in z.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n), None)
                if not jname:
                    continue
                data = json.loads(z.read(jname))
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError):
            continue
        for sname, sdata in _strategies_of(data):
            key = (sname, zf.name)
            if key in seen:
                continue
            seen.add(key)
            for trow in _trade_row(sdata, zf.name):
                cur.execute(
                    f"""INSERT OR IGNORE INTO trades
                       (strategy, source, {', '.join(TRADE_COLS)})
                       VALUES ({', '.join('?' for _ in range(2 + len(TRADE_COLS)))})""",
                    (sname, zf.name, *trow),
                )
                count += cur.rowcount

    conn.commit()
    return count


def best_epoch_from_fthypt(path: Path) -> tuple[dict | None, int]:
    """Line-stream a .fthypt file and return the best (lowest loss) epoch.

    Best is determined by the ``is_best`` flag, falling back to min loss.
    Multi-GB files are handled by streaming a single line at a time.
    """
    best = None
    best_loss = float("inf")
    n = 0
    best_epoch_idx = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            if row.get("is_best"):
                best = row
                best_epoch_idx = n
                continue
            loss = row.get("loss")
            try:
                loss = float(loss)
            except (TypeError, ValueError):
                continue
            if loss < best_loss:
                best_loss = loss
                best = row
                best_epoch_idx = n
    return best, n


def ingest_hyperopt(conn: sqlite3.Connection) -> int:
    count = 0
    cur = conn.cursor()
    files = sorted(HYPEROPT_DIR.rglob("*.fthypt"))
    for f in files:
        if cur.execute("SELECT 1 FROM hyperopt WHERE source=?", (f.name,)).fetchone():
            continue
        epoch, n = best_epoch_from_fthypt(f)
        if epoch is None:
            continue
        m = extract_metrics(epoch.get("results_metrics") or {})
        best_loss = None
        try:
            best_loss = float(epoch.get("loss"))
        except (TypeError, ValueError):
            pass
        params = epoch.get("params_dict") or {}
        cur.execute(
            """INSERT OR IGNORE INTO hyperopt
               (strategy, source, run_time, epochs, best_loss, best_trades, best_profit_total,
                best_profit_abs, best_winrate, best_sortino, best_calmar, best_profit_factor,
                best_max_drawdown, best_params)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f.name.replace("strategy_", "").split("_")[0], f.name,
                run_time_iso(epoch, os.path.getmtime(f)), n, best_loss,
                m.get("total_trades"), m.get("profit_total"), m.get("profit_total_abs"),
                m.get("winrate"), m.get("sortino"), m.get("calmar"), m.get("profit_factor"),
                m.get("max_drawdown_account"),
                json.dumps(params, sort_keys=True),
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


def ingest_walkforward(conn: sqlite3.Connection) -> int:
    count = 0
    cur = conn.cursor()
    files = sorted(WALK_FORWARD_DIR.rglob("walk_forward.json"))
    for f in files:
        if cur.execute("SELECT 1 FROM walkforward WHERE source=?", (str(f),)).fetchone():
            continue
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        windows = data.get("windows") or []
        if not windows:
            continue
        settings = data.get("settings") or {}
        oos_trades = 0
        oos_profit = 0.0
        profitable = 0
        sortino_s, calmar_s, pf_s, dd_s = [], [], [], []
        for w in windows:
            oos = w.get("out_of_sample") or {}
            m = extract_metrics(oos)
            t = m.get("total_trades") or 0
            oos_trades += t
            p = m.get("profit_total_abs") or 0.0
            oos_profit += p
            if p > 0:
                profitable += 1
            if m.get("sortino") is not None:
                sortino_s.append(m["sortino"])
            if m.get("calmar") is not None:
                calmar_s.append(m["calmar"])
            if m.get("profit_factor") is not None:
                pf_s.append(m["profit_factor"])
            if m.get("max_drawdown_account") is not None:
                dd_s.append(m["max_drawdown_account"])

        run_time = None
        try:
            run_time = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            pass
        avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        cur.execute(
            """INSERT OR IGNORE INTO walkforward
               (strategy, run_id, source, run_time, train_days, test_days, step_days, timerange,
                n_windows, profitable_windows, oos_trades, oos_profit_abs, oos_winrate,
                avg_oos_sortino, avg_oos_calmar, avg_oos_profit_factor, avg_oos_max_drawdown)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.get("strategy"), data.get("run_id"), str(f), run_time,
                settings.get("train_days"), settings.get("test_days"), settings.get("step_days"),
                data.get("timerange"), len(windows), profitable, oos_trades, oos_profit,
                (oos_profit / oos_trades if oos_trades else None),
                avg(sortino_s), avg(calmar_s), avg(pf_s), avg(dd_s),
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


def ingest_strategies(conn: sqlite3.Connection) -> int:
    """Populate the strategies registry from .py files + names seen in results.

    Only inserts missing names with default status 'active'. Existing rows
    (with user-set status/notes) are left untouched.
    """
    cur = conn.cursor()
    known = set()
    for f in sorted((USER_DATA / "strategies").glob("*.py")):
        known.add(f.stem)
    # names that appear in results but have no file are still registered
    for table in ("backtests", "benchmarks", "hyperopt", "walkforward"):
        try:
            for (name,) in cur.execute(f"SELECT DISTINCT strategy FROM {table} WHERE strategy IS NOT NULL"):
                known.add(name)
        except sqlite3.OperationalError:
            continue
    count = 0
    for name in sorted(known):
        cur.execute(
            "INSERT OR IGNORE INTO strategies (name, status, notes) VALUES (?, 'active', '')",
            (name,),
        )
        count += cur.rowcount
    conn.commit()
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Build results.db from all freqtrade artifacts")
    ap.add_argument("--db", default=str(ANALYSIS_DIR / "results.db"), help="Output sqlite path")
    args = ap.parse_args()

    conn = open_db(Path(args.db))
    print(f"Database: {args.db}")

    n_bt = ingest_backtests(conn)
    print(f"Backtests imported: {n_bt} new")

    n_st = ingest_strategies(conn)
    print(f"Strategies registered: {n_st} new")

    n_ho = ingest_hyperopt(conn)
    print(f"Hyperopt imported: {n_ho} new")

    n_wf = ingest_walkforward(conn)
    print(f"Walk-forward imported: {n_wf} new")

    n_tr = ingest_trades(conn)
    print(f"Trades imported: {n_tr} new")

    for table in ("backtests", "hyperopt", "walkforward", "trades"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n} total rows")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
