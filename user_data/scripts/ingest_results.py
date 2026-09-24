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

from ft_metrics import (
    apply_run_artifacts,
    connect_wal,
    ensure_provenance,
    extract_metrics,
    run_time_iso,
    stamp_legacy_code_hashes,
    store_config_text,
    timerange_str,
)  # noqa: E402

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
    random_state INTEGER,
    jobs INTEGER,
    min_trades INTEGER,
    loss_function TEXT,
    spaces TEXT,
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
    windows_json TEXT,
    jobs INTEGER,
    random_state INTEGER,
    min_trades INTEGER,
    loss_function TEXT,
    spaces TEXT,
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
    orders_json TEXT,
    UNIQUE(source, strategy, open_date, close_date, pair, profit_abs)
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for existing DBs (no drop)."""
    cur = conn.cursor()
    # hyperopt new columns
    try:
        cols = {r[1] for r in cur.execute("PRAGMA table_info(hyperopt)").fetchall()}
        for col, ddl in {
            "random_state": "ALTER TABLE hyperopt ADD COLUMN random_state INTEGER",
            "jobs": "ALTER TABLE hyperopt ADD COLUMN jobs INTEGER",
            "min_trades": "ALTER TABLE hyperopt ADD COLUMN min_trades INTEGER",
            "loss_function": "ALTER TABLE hyperopt ADD COLUMN loss_function TEXT",
            "spaces": "ALTER TABLE hyperopt ADD COLUMN spaces TEXT",
        }.items():
            if col not in cols:
                cur.execute(ddl)
        cols = {r[1] for r in cur.execute("PRAGMA table_info(walkforward)").fetchall()}
        for col, ddl in {
            "windows_json": "ALTER TABLE walkforward ADD COLUMN windows_json TEXT",
            "jobs": "ALTER TABLE walkforward ADD COLUMN jobs INTEGER",
            "random_state": "ALTER TABLE walkforward ADD COLUMN random_state INTEGER",
            "min_trades": "ALTER TABLE walkforward ADD COLUMN min_trades INTEGER",
            "loss_function": "ALTER TABLE walkforward ADD COLUMN loss_function TEXT",
            "spaces": "ALTER TABLE walkforward ADD COLUMN spaces TEXT",
        }.items():
            if col not in cols:
                cur.execute(ddl)
        # trades.orders_json (partial exits / DCA fills)
        cols = {r[1] for r in cur.execute("PRAGMA table_info(trades)").fetchall()}
        if cols and "orders_json" not in cols:
            cur.execute("ALTER TABLE trades ADD COLUMN orders_json TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_wal(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    ensure_provenance(conn)
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
        config_hash = store_config_text(conn, config_json) if config_json else None
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
        if config_hash and not cur.rowcount:
            # row existed without a hash (pre-provenance ingest) — stamp it now
            try:
                conn.execute(
                    "UPDATE backtests SET config_hash=?, config_json=COALESCE(config_json, ?)"
                    " WHERE source=? AND strategy=? AND config_hash IS NULL",
                    (config_hash, config_json, source, sname),
                )
            except sqlite3.OperationalError:
                pass
        count += cur.rowcount
    conn.commit()
    return count


TRADE_COLS = (
    "pair", "is_short", "enter_tag", "exit_reason", "open_date", "close_date",
    "open_rate", "close_rate", "min_rate", "max_rate", "amount", "stake_amount",
    "leverage", "profit_ratio", "profit_abs", "trade_duration", "stop_loss_abs",
    "stop_loss_ratio", "initial_stop_loss_abs", "initial_stop_loss_ratio",
    "fee_open", "fee_close", "orders_json",
)

# compact per-order fills kept for partial exits / DCA rendering; JSON only
# when the trade actually has more than one entry or exit fill
ORDER_KEYS = ("ft_is_entry", "safe_price", "filled", "order_filled_date")


def _orders_json(t: dict) -> str | None:
    orders = t.get("orders") or []
    if len(orders) <= 2:
        return None
    fills = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        fills.append([
            o.get("order_filled_date") or o.get("order_date") or "",
            o.get("safe_price", o.get("price")),
            o.get("filled", o.get("amount")),
            int(bool(o.get("ft_is_entry"))),
        ])
    return json.dumps(fills, separators=(",", ":")) if fills else None


def _trade_row(sdata: dict, source: str):
    """Extract normalized trade tuples from a backtest strategy dict."""
    trades = sdata.get("trades") or []
    for t in trades:
        if not isinstance(t, dict):
            continue
        row = []
        for col in TRADE_COLS:
            v = _orders_json(t) if col == "orders_json" else t.get(col)
            if isinstance(v, bool):
                v = int(v)
            row.append(v)
        yield tuple(row)


def _ingest_trade_row(cur: sqlite3.Cursor, sname: str, source: str, trow: tuple) -> int:
    cur.execute(
        f"""INSERT OR IGNORE INTO trades
           (strategy, source, {', '.join(TRADE_COLS)})
           VALUES ({', '.join('?' for _ in range(2 + len(TRADE_COLS)))})""",
        (sname, source, *trow),
    )
    if cur.rowcount:
        return 1
    # row already ingested: backfill fills only for partial exits / DCA
    # (rare) so re-ingesting a file upgrades it without a full rescan
    oj = trow[-1]
    if oj is not None:
        cur.execute(
            """UPDATE trades SET orders_json=? WHERE strategy=? AND source=?
               AND open_date=? AND close_date=? AND pair=? AND profit_abs=?
               AND orders_json IS NULL""",
            (oj, sname, source, trow[4], trow[5], trow[0], trow[14]),
        )
    return 0


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
                count += _ingest_trade_row(cur, sname, f.name, trow)

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
                count += _ingest_trade_row(cur, sname, zf.name, trow)

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


def _hyperopt_meta_from_path(path: Path) -> dict:
    """Best-effort extract of jobs/random_state/loss/spaces from .fthypt first epoch."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # hyperopt epoch may embed config hints; also check sibling .json if exists
                return {
                    "loss": row.get("hyperopt_loss") or row.get("loss_function") or None,
                    "random_state": row.get("random_state"),
                    "jobs": row.get("jobs") or row.get("hyperopt_jobs"),
                    "min_trades": row.get("min_trades") or row.get("hyperopt_min_trades"),
                    "spaces": ",".join(row.get("spaces") or []) if isinstance(row.get("spaces"), list) else row.get("spaces"),
                }
    except OSError:
        pass
    return {}


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
        meta = _hyperopt_meta_from_path(f)
        # infer strategy more robustly (strategy_BigZ08_... -> BigZ08)
        raw = f.name.replace("strategy_", "")
        # split on _YYYY- pattern
        import re as _re
        strat = _re.split(r"_\d{4}-\d{2}-\d{2}", raw, maxsplit=1)[0]
        if not strat:
            strat = raw.split("_")[0]
        cur.execute(
            """INSERT OR IGNORE INTO hyperopt
               (strategy, source, run_time, epochs, best_loss, best_trades, best_profit_total,
                best_profit_abs, best_winrate, best_sortino, best_calmar, best_profit_factor,
                best_max_drawdown, best_params, random_state, jobs, min_trades, loss_function, spaces)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                strat, f.name,
                run_time_iso(epoch, os.path.getmtime(f)), n, best_loss,
                m.get("total_trades"), m.get("profit_total"), m.get("profit_total_abs"),
                m.get("winrate"), m.get("sortino"), m.get("calmar"), m.get("profit_factor"),
                m.get("max_drawdown_account"),
                json.dumps(params, sort_keys=True),
                meta.get("random_state"), meta.get("jobs"), meta.get("min_trades"),
                meta.get("loss"), meta.get("spaces"),
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


def ingest_walkforward(conn: sqlite3.Connection) -> int:
    count = 0
    cur = conn.cursor()
    # migrate legacy absolute Windows paths to relative POSIX
    try:
        for rowid, src in conn.execute("SELECT rowid, source FROM walkforward").fetchall():
            if "\\" in src or (":" in src and "walk_forward" in src):
                norm = src.replace("\\", "/")
                if "walk_forward/" in norm:
                    rel_norm = "walk_forward/" + norm.split("walk_forward/", 1)[-1]
                else:
                    rel_norm = norm
                if rel_norm != src:
                    conn.execute("UPDATE walkforward SET source=? WHERE rowid=?", (rel_norm, rowid))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    files = sorted(WALK_FORWARD_DIR.rglob("walk_forward.json"))
    for f in files:
        rel = f.relative_to(USER_DATA).as_posix()
        if cur.execute("SELECT 1 FROM walkforward WHERE source=?", (rel,)).fetchone():
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
        windows_compact: list[dict] = []
        for w in windows:
            oos = w.get("out_of_sample") or {}
            ins = w.get("in_sample") or {}
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
            windows_compact.append({
                "train_range": w.get("train_timerange") or (ins.get("timerange") if isinstance(ins, dict) else None) or w.get("train_range"),
                "test_range": w.get("test_timerange") or (oos.get("timerange") if isinstance(oos, dict) else None) or w.get("test_range"),
                "oos_trades": t,
                "oos_profit_abs": p,
                "oos_profit_total": m.get("profit_total"),
                "oos_winrate": m.get("winrate"),
                "oos_sortino": m.get("sortino"),
                "oos_calmar": m.get("calmar"),
                "oos_pf": m.get("profit_factor"),
                "oos_dd": m.get("max_drawdown_account"),
                "oos_expectancy": m.get("expectancy"),
            })

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
                avg_oos_sortino, avg_oos_calmar, avg_oos_profit_factor, avg_oos_max_drawdown,
                windows_json, jobs, random_state, min_trades, loss_function, spaces)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.get("strategy"), data.get("run_id"), rel, run_time,
                settings.get("train_days"), settings.get("test_days"), settings.get("step_days"),
                data.get("timerange"), len(windows), profitable, oos_trades, oos_profit,
                (oos_profit / oos_trades if oos_trades else None),
                avg(sortino_s), avg(calmar_s), avg(pf_s), avg(dd_s),
                json.dumps(windows_compact),
                settings.get("jobs") or settings.get("hyperopt_jobs"),
                settings.get("random_state") or settings.get("hyperopt_random_state"),
                settings.get("min_trades") or settings.get("hyperopt_min_trades"),
                settings.get("loss") or settings.get("hyperopt_loss"),
                ",".join(settings.get("spaces") or []) if isinstance(settings.get("spaces"), list) else settings.get("spaces"),
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

    n_art = apply_run_artifacts(conn)
    if n_art:
        print(f"Run artifacts matched: {n_art} rows stamped with config/code hashes")

    n_legacy = stamp_legacy_code_hashes(conn, USER_DATA)
    if n_legacy:
        print(f"Legacy code hashes (unverified): {n_legacy} rows stamped")

    for table in ("backtests", "hyperopt", "walkforward", "trades"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n} total rows")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
