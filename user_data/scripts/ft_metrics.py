"""Shared metric extraction helpers for the strategy-lab toolset.

Both the ingester and the benchmark runner use these so every row in the
database is produced the same way.

Also hosts the run-provenance helpers (config + strategy code snapshots) so
run_strategy.py, ingest_results.py and benchmark_runner.py all stamp hashes
the same way.
"""

from __future__ import annotations

import ast
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


def connect_wal(path, timeout: float = 5.0) -> sqlite3.Connection:
    """Open results.db with WAL journaling so readers don't block on writers.

    Ingest/report jobs hold long write transactions; in rollback-journal mode
    any concurrent reader (e.g. server /api/strategies) hits SQLITE_BUSY. WAL
    lets reads proceed while a writer works. The mode is persistent per DB
    file, but setting it on every connect is cheap and re-converts a recreated
    DB.
    """
    conn = sqlite3.connect(path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass  # another process holds an exclusive lock mid-conversion; next connect retries
    return conn


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

# additive columns on provenance tables (e.g. strategy_snapshots.combined_hash)
SNAPSHOT_COLS = {
    "strategy_snapshots": ["combined_hash"],
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

CREATE TABLE IF NOT EXISTS strategy_snapshot_files (
    hash TEXT NOT NULL,
    path TEXT NOT NULL,
    source TEXT,
    PRIMARY KEY (hash, path)
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
    for table, cols in SNAPSHOT_COLS.items():
        try:
            existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.OperationalError:
            continue
        for col in cols:
            if col not in existing and existing:
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
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


# --- local-import capture: walk a strategy's transitive local imports --------

def _resolve_roots(user_data: Path) -> list[Path]:
    return [
        user_data.resolve(),
        (user_data / "strategies").resolve(),
        (user_data.parent / "strategy_lib").resolve(),
        user_data.parent.resolve(),
    ]


def _allowed_roots(user_data: Path) -> list[Path]:
    """Files under these roots are considered "local, snapshottable" code."""
    return [user_data.resolve(), (user_data.parent / "strategy_lib").resolve()]


def _in_allowed(path: Path, allowed: list[Path]) -> bool:
    path = path.resolve()
    return any(path.is_relative_to(root) for root in allowed)


def _resolve_abs_module(module: str, roots: list[Path], allowed: list[Path]) -> Path | None:
    """Resolve an absolute dotted module name to a local file under allowed roots."""
    rel = module.replace(".", "/")
    seen: set[Path] = set()
    for root in roots:
        for cand in (root / (rel + ".py"), root / rel / "__init__.py"):
            cand = cand.resolve()
            if cand in seen:
                continue
            seen.add(cand)
            if cand.is_file() and _in_allowed(cand, allowed):
                return cand
    return None


def _resolve_relative(module: str | None, level: int, base_dir: Path,
                      allowed: list[Path]) -> Path | None:
    """Resolve a relative import (from .x import y) against base_dir."""
    pkg = base_dir.resolve()
    for _ in range(1, level):
        pkg = pkg.parent
    rel = (module or "").replace(".", "/")
    for cand in (pkg / (rel + ".py"), pkg / rel / "__init__.py"):
        cand = cand.resolve()
        if cand.is_file() and _in_allowed(cand, allowed):
            return cand
    return None


def imported_files(source: str, base_dir: Path, user_data: Path) -> list[Path]:
    """Local files this source imports, resolved under user_data / strategy_lib."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    roots = _resolve_roots(user_data)
    allowed = _allowed_roots(user_data)
    out: list[Path] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                t = _resolve_abs_module(a.name, roots, allowed)
                if t and t not in out:
                    out.append(t)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                t = _resolve_relative(node.module, node.level, base_dir, allowed)
            elif node.module:
                t = _resolve_abs_module(node.module, roots, allowed)
            else:
                t = None
            if t and t not in out:
                out.append(t)
    return out


def rel_label(path: Path, user_data: Path) -> str:
    """Human-friendly label, repo-root-relative (or user_data-relative fallback)."""
    path = path.resolve()
    for root in (user_data.parent.resolve(), user_data.resolve()):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def collect_local_imports(strategy_file: Path, user_data: Path) -> dict[str, str]:
    """Return {absolute path: source} for the strategy file + its local imports (recursive).

    Excludes the strategy file itself so the caller can keep the main file in
    ``strategy_snapshots.source`` and the deps in ``strategy_snapshot_files`` without
    duplication.
    """
    allowed = _allowed_roots(user_data)
    files: dict[str, str] = {}
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in seen or not path.is_file() or not _in_allowed(path, allowed):
            return
        seen.add(path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        # skip the strategy file itself
        if path != strategy_file.resolve():
            files[str(path)] = source
        for dep in imported_files(source, path.parent, user_data):
            visit(dep)

    visit(strategy_file)
    return files


def combined_code_hash(strategy_text: str, strategy_path: Path,
                        deps: dict[str, str], user_data: Path) -> str:
    """Stable hash of (strategy + all deps) for whole-set staleness checks.

    Sorted by repo-root-relative label so the hash is independent of the order
    files were discovered.
    """
    entries: list[tuple[str, str]] = []
    entries.append((rel_label(strategy_path, user_data), sha1_text(strategy_text)))
    for abs_path, src in deps.items():
        entries.append((rel_label(Path(abs_path), user_data), sha1_text(src)))
    entries.sort()
    payload = "\n".join(f"{rel}\x00{h}" for rel, h in entries)
    return sha1_text(payload)


def current_code_set_hash(user_data: Path, strategy: str) -> str | None:
    """Combined hash of the strategy file + its current local imports on disk."""
    path = find_strategy_file(user_data, strategy)
    if path is None:
        return None
    try:
        strategy_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    deps = collect_local_imports(path, user_data)
    return combined_code_hash(strategy_text, path, deps, user_data)


def store_snapshot_files(conn: sqlite3.Connection, code_hash: str,
                         deps: dict[str, str]) -> None:
    """Persist dependency files for a snapshot. Upserts so re-captures update."""
    cur = conn.cursor()
    for abs_path, src in deps.items():
        cur.execute(
            """INSERT INTO strategy_snapshot_files (hash, path, source)
               VALUES (?,?,?)
               ON CONFLICT(hash, path) DO UPDATE SET source=excluded.source""",
            (code_hash, abs_path, src),
        )
    conn.commit()


def load_snapshot_files(conn: sqlite3.Connection, code_hash: str) -> list[dict]:
    """Return dep file metadata for a snapshot (no source content)."""
    rows = conn.execute(
        "SELECT path FROM strategy_snapshot_files WHERE hash=? ORDER BY path",
        (code_hash,),
    ).fetchall()
    return [{"path": r[0]} for r in rows]


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
    """Capture strategy file + local imports into strategy_snapshots; returns hash.

    Stores the strategy file in ``strategy_snapshots.source`` and the transitive
    local imports (components, strategy_lib, shared modules) in
    ``strategy_snapshot_files``. The combined sha1 of (strategy + deps) is
    recorded in ``strategy_snapshots.combined_hash`` so the UI can detect when
    ANY file in the dependency set has changed since the run, not just the
    strategy file itself.

    verified=True means captured at run time by run_strategy.py / benchmark_runner.py;
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
    deps = collect_local_imports(path, user_data)
    combined = combined_code_hash(text, path, deps, user_data)
    conn.execute(
        """INSERT INTO strategy_snapshots
              (hash, strategy, path, source, mtime, captured_at, verified, combined_hash)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(hash) DO UPDATE SET
              verified = MAX(strategy_snapshots.verified, excluded.verified),
              combined_hash = excluded.combined_hash""",
        (h, strategy, str(path), text, path.stat().st_mtime,
         datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
         int(verified), combined),
    )
    store_snapshot_files(conn, h, deps)
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
                    f"""UPDATE {table} SET
                          config_hash=COALESCE(?, config_hash),
                          code_hash=COALESCE(?, code_hash),
                          code_verified=CASE
                              WHEN COALESCE(?, code_hash) IS NOT NULL THEN 1
                              ELSE code_verified END
                        WHERE strategy=? AND source=?""",
                    (chash, cdhash, cdhash, strategy, source),
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
