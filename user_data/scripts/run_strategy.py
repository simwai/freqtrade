"""run_strategy.py — run one freqtrade job (backtest / hyperopt / walk-forward) from the Lab.

Wraps the freqtrade CLI for a single strategy so the dashboard can start runs
without fiddling with config files. Config resolution:

    1. --config PATH  (explicit override)
    2. user_data/config_<strategy-lowercase>.json  (per-strategy config)
    3. user_data/config_benchmark.json              (shared fallback)

Artifacts are written to freqtrade's default locations, so a later
ingest_results.py picks everything up:

    backtest        -> user_data/backtest_results/backtest-result-<ts>.json
    hyperopt        -> user_data/hyperopt_results/strategy_<strategy>_<ts>.fthypt
    walk-forward    -> user_data/walk_forward/<strategy>/<run_id>/walk_forward.json

Usage:
    python user_data/scripts/run_strategy.py backtest --timerange 20230101-20240101
    python user_data/scripts/run_strategy.py hyperopt --strategy BigZ08 --epochs 100
    python user_data/scripts/run_strategy.py walkforward --strategy BigZ08 --train-days 90
    python user_data/scripts/run_strategy.py --list
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

USER_DATA = Path(__file__).resolve().parents[1]
# freqtrade defaults user_data to <cwd>/user_data when config has no user_data_dir;
# pin cwd to the repo root so server-launched runs resolve it regardless of launch dir
REPO_ROOT = USER_DATA.parent
DEFAULT_DB = USER_DATA / "analysis" / "results.db"

from ft_metrics import (  # noqa: E402
    find_strategy_file,
    record_run_artifact,
    snapshot_strategy,
    store_config_text,
)


KNOWN_LOSSES = [
    "DefaultHyperOptLoss",
    "OnlyProfitHyperOptLoss",
    "SharpeHyperOptLoss",
    "SharpeHyperOptLossDaily",
    "SortinoHyperOptLoss",
    "SortinoHyperOptLossDaily",
    "CalmarHyperOptLoss",
    "MaxDrawDownRelativeHyperOptLoss",
    "MultiMetricHyperOptLoss",
    "ProfitDrawDownHyperOptLoss",
]

DEFAULT_SPACES = ["buy", "sell", "roi", "stoploss", "trailing"]


def freqtrade_cmd() -> str:
    return f"{sys.executable} -m freqtrade" if sys.executable else "freqtrade"


def list_strategies(conn: sqlite3.Connection) -> list[str]:
    try:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT name FROM strategies ORDER BY name"
        ).fetchall()]
    except sqlite3.OperationalError:
        return []


def resolve_config(strategy: str, override: str | None) -> Path:
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = USER_DATA / path
        if path.is_file():
            return path
        print(f"Config not found: {path} (falling back)", file=sys.stderr)
    per_strategy = USER_DATA / f"config_{strategy.lower()}.json"
    if per_strategy.is_file():
        return per_strategy
    fallback = USER_DATA / "config_benchmark.json"
    if fallback.is_file():
        return fallback
    raise SystemExit(f"No config found for {strategy} (tried {per_strategy} and {fallback})")


def run(cmd: list[str]) -> int:
    print(f"  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, encoding="utf-8", errors="replace", check=False)
    return proc.returncode


def open_results_db() -> sqlite3.Connection | None:
    if not DEFAULT_DB.is_file():
        return None
    try:
        conn = sqlite3.connect(DEFAULT_DB)
        return conn
    except sqlite3.Error:
        return None


def capture_provenance(strategy: str, config: Path, db_conn: sqlite3.Connection | None) -> tuple[str | None, str | None]:
    """Snapshot strategy code + resolved config before the run. Returns (config_hash, code_hash)."""
    if db_conn is None:
        return None, None
    config_hash = None
    code_hash = None
    try:
        config_hash = store_config_text(db_conn, config.read_text(encoding="utf-8"), path=str(config))
    except OSError:
        pass
    try:
        code_hash = snapshot_strategy(db_conn, USER_DATA, strategy, verified=True)
    except (OSError, sqlite3.Error):
        pass
    if code_hash is None:
        src = find_strategy_file(USER_DATA, strategy)
        print(f"  warning: strategy file for '{strategy}' not found"
              f"{f' (looked near {src})' if src else ''}; run will lack a code snapshot")
    return config_hash, code_hash


def _artifact_candidates(kind: str) -> list[Path]:
    """All candidate artifact files for *kind*, sorted newest-first (for diagnostics)."""
    if kind == "backtest":
        base = USER_DATA / "backtest_results"
        if not base.is_dir():
            return []
        j = [p for p in base.glob("backtest-result-*.json") if not p.name.endswith(".meta.json")]
        z = list(base.glob("backtest-result-*.zip"))
        all_cands = j + z
    elif kind == "hyperopt":
        all_cands = list((USER_DATA / "hyperopt_results").rglob("*.fthypt")) if (USER_DATA / "hyperopt_results").is_dir() else []
    elif kind == "walkforward":
        all_cands = list((USER_DATA / "walk_forward").rglob("walk_forward.json")) if (USER_DATA / "walk_forward").is_dir() else []
    else:
        return []
    all_cands.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return all_cands


def record_artifact(kind: str, strategy: str, started_at: float,
                    config_hash: str | None, code_hash: str | None,
                    db_conn: sqlite3.Connection | None,
                    exit_code: int | None = None) -> None:
    """Find the artifact produced by this run and link it to its provenance hashes."""
    if db_conn is None or (config_hash is None and code_hash is None):
        return
    source = _newest_artifact(kind, started_at)
    if source is None:
        started_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at))
        print(
            f"  note: no {kind} artifact found newer than run start"
            f" ({started_s}); provenance not linked"
        )
        if exit_code is not None and exit_code != 0:
            print(
                f"  hint: {kind} process exited with code {exit_code}"
                " — artifact was likely never written;"
                " check the log above for the freqtrade error"
            )
        # Diagnostics: list newest candidates with their mtimes vs started_at
        cands = _artifact_candidates(kind)[:8]
        if not cands:
            base = {
                "backtest": USER_DATA / "backtest_results",
                "hyperopt": USER_DATA / "hyperopt_results",
                "walkforward": USER_DATA / "walk_forward",
            }.get(kind, USER_DATA)
            print(f"  diag: no candidate files found under {base}")
        else:
            print(f"  diag: newest {kind} candidates (mtime vs run start {started_s}):")
            for p in cands:
                try:
                    mt = p.stat().st_mtime
                    delta = mt - started_at
                    mt_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt))
                    sign = "+" if delta >= 0 else ""
                    print(f"    {sign}{delta:.1f}s  {mt_s}  {p.name}")
                except OSError:
                    print(f"    ?  {p}")
            print(
                f"  diag: look for the freqtrade error above (exit code {exit_code});"
                " fix the strategy/config/timerange and retry"
            )
        return
    try:
        record_run_artifact(db_conn, kind, strategy, source, config_hash, code_hash)
        print(f"  provenance linked: {source}")
    except sqlite3.Error as e:
        print(f"  warning: could not record provenance: {e}")


def _newest_artifact(kind: str, started_at: float) -> str | None:
    def newest_in(base: Path, pattern: str, exclude_meta: bool = False) -> Path | None:
        if not base.is_dir():
            return None
        files = [p for p in base.rglob(pattern)
                 if p.stat().st_mtime >= started_at - 1
                 and not (exclude_meta and p.name.endswith(".meta.json"))]
        return max(files, key=lambda p: p.stat().st_mtime, default=None)

    p: Path | None
    if kind == "backtest":
        p = newest_in(USER_DATA / "backtest_results", "backtest-result-*.json", exclude_meta=True)
        z = newest_in(USER_DATA / "backtest_results", "backtest-result-*.zip")
        if z is not None and (p is None or z.stat().st_mtime > p.stat().st_mtime):
            p = z
        return p.name if p else None
    if kind == "hyperopt":
        p = newest_in(USER_DATA / "hyperopt_results", "*.fthypt")
        return p.name if p else None
    if kind == "walkforward":
        p = newest_in(USER_DATA / "walk_forward", "walk_forward.json")
        if p is None:
            return None
        try:
            return p.relative_to(USER_DATA).as_posix()
        except ValueError:
            return p.as_posix()
    return None


def cmd_backtest(args) -> int:
    config = resolve_config(args.strategy, args.config)
    started_at = time.time()
    db_conn = open_results_db()
    config_hash, code_hash = capture_provenance(args.strategy, config, db_conn)
    cmd = [
        *freqtrade_cmd().split(), "backtesting",
        "-c", str(config),
        "--strategy", args.strategy,
        "--timerange", args.timerange,
        "--timeframe", args.timeframe,
        "--cache", "none",
        "--export", "trades",
    ]
    print(f"Backtest {args.strategy} on {args.timerange} ({args.timeframe}) with {config.name}")
    code = run(cmd)
    if code != 0:
        print(
            f"  error: backtest failed with exit code {code}"
            " — check strategy/config/timerange and the log above"
        )
    record_artifact(
        "backtest",
        args.strategy,
        started_at,
        config_hash,
        code_hash,
        db_conn,
        exit_code=code,
    )
    if db_conn:
        db_conn.close()
    return code


def cmd_hyperopt(args) -> int:
    config = resolve_config(args.strategy, args.config)
    started_at = time.time()
    db_conn = open_results_db()
    config_hash, code_hash = capture_provenance(args.strategy, config, db_conn)
    cmd = [
        *freqtrade_cmd().split(), "hyperopt",
        "-c", str(config),
        "--strategy", args.strategy,
        "--timerange", args.timerange,
        "--epochs", str(args.epochs),
        "--hyperopt-loss", args.loss,
    ]
    if args.spaces:
        cmd += ["--spaces", *args.spaces]
    # advanced hyperopt controls (freqtrade cli_options.py: hyperopt_jobs/random_state/min_trades)
    if args.jobs is not None:
        cmd += ["--job-workers", str(args.jobs)]
    if args.random_state is not None:
        cmd += ["--random-state", str(args.random_state)]
    if args.min_trades is not None:
        cmd += ["--min-trades", str(args.min_trades)]
    if getattr(args, "analyze_per_epoch", False):
        cmd += ["--analyze-per-epoch"]
    if getattr(args, "disable_param_export", False):
        cmd += ["--disable-param-export"]
    if getattr(args, "print_all", False):
        cmd += ["--print-all"]
    print(f"Hyperopt {args.strategy} on {args.timerange}, {args.epochs} epochs, loss={args.loss}"
           + (f", jobs={args.jobs}" if args.jobs is not None else "")
           + (f", seed={args.random_state}" if args.random_state is not None else ""))
    code = run(cmd)
    if code != 0:
        print(
            f"  error: hyperopt failed with exit code {code}"
            " — check strategy/config/timerange and the log above"
        )
    record_artifact(
        "hyperopt",
        args.strategy,
        started_at,
        config_hash,
        code_hash,
        db_conn,
        exit_code=code,
    )
    if db_conn:
        db_conn.close()
    return code


def cmd_walkforward(args) -> int:
    config = resolve_config(args.strategy, args.config)
    started_at = time.time()
    db_conn = open_results_db()
    config_hash, code_hash = capture_provenance(args.strategy, config, db_conn)
    cmd = [
        *freqtrade_cmd().split(), "walk-forward",
        "-c", str(config),
        "--strategy", args.strategy,
        "--timerange", args.timerange,
        "--train-days", str(args.train_days),
        "--test-days", str(args.test_days),
        "--step-days", str(args.step_days),
        "--epochs", str(args.epochs),
        "--hyperopt-loss", args.loss,
    ]
    if args.spaces:
        cmd += ["--spaces", *args.spaces]
    if getattr(args, "jobs", None) is not None:
        cmd += ["--job-workers", str(args.jobs)]
    if getattr(args, "random_state", None) is not None:
        cmd += ["--random-state", str(args.random_state)]
    if getattr(args, "min_trades", None) is not None:
        cmd += ["--min-trades", str(args.min_trades)]
    if getattr(args, "analyze_per_epoch", False):
        cmd += ["--analyze-per-epoch"]
    # walk-forward live thresholds (cli_options walk_forward_min_trades/max_drawdown)
    if getattr(args, "wf_min_trades", None) is not None:
        cmd += ["--walk-forward-min-trades", str(args.wf_min_trades)]
    if getattr(args, "wf_max_drawdown", None) is not None:
        cmd += ["--walk-forward-max-drawdown", str(args.wf_max_drawdown)]
    print(f"Walk-forward {args.strategy} on {args.timerange} "
          f"(train={args.train_days}d test={args.test_days}d step={args.step_days}d, "
          f"{args.epochs} epochs)")
    code = run(cmd)
    if code != 0:
        print(
            f"  error: walk-forward failed with exit code {code}"
            " — check strategy/config/timerange and the log above"
        )
    record_artifact(
        "walkforward",
        args.strategy,
        started_at,
        config_hash,
        code_hash,
        db_conn,
        exit_code=code,
    )
    if db_conn:
        db_conn.close()
    return code


def cmd_list(args) -> int:
    names = list_strategies(sqlite3.connect(args.db)) or ["(none)"]
    print("\n".join(names))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run one freqtrade backtest / hyperopt / walk-forward.")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to results.db (for --list)")
    sub = ap.add_subparsers(dest="mode")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--strategy", required=True)
    common.add_argument("--timerange", default="20220101-20240101")
    common.add_argument("--timeframe", default="5m")
    common.add_argument("--config", default=None, help="Config path override")

    p = sub.add_parser("backtest", parents=[common], help="Run a single backtest")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("hyperopt", parents=[common], help="Run a single hyperopt")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--loss", default="SharpeHyperOptLossDaily")
    p.add_argument("--spaces", nargs="+", default=None)
    p.add_argument("--jobs", "-j", type=int, default=None, help="Job workers (-1 all CPUs, 1 no parallel)")
    p.add_argument("--random-state", type=int, default=None, help="Random seed for reproducibility")
    p.add_argument("--min-trades", type=int, default=None, help="Min trades per epoch (default 1)")
    p.add_argument("--analyze-per-epoch", action="store_true", help="Re-run populate_indicators per epoch")
    p.add_argument("--disable-param-export", action="store_true", help="Don't auto-export best params to .json")
    p.add_argument("--print-all", action="store_true", help="Print all epochs not only best")
    p.set_defaults(func=cmd_hyperopt)

    p = sub.add_parser("walkforward", parents=[common], help="Run walk-forward optimization")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--loss", default="SharpeHyperOptLossDaily")
    p.add_argument("--spaces", nargs="+", default=None)
    p.add_argument("--train-days", type=int, default=90)
    p.add_argument("--test-days", type=int, default=7)
    p.add_argument("--step-days", type=int, default=7)
    p.add_argument("--jobs", "-j", type=int, default=None, help="Job workers")
    p.add_argument("--random-state", type=int, default=None)
    p.add_argument("--min-trades", type=int, default=None, help="Min trades per hyperopt window")
    p.add_argument("--analyze-per-epoch", action="store_true")
    p.add_argument("--wf-min-trades", type=int, default=None, help="Reject live WF params with fewer trades")
    p.add_argument("--wf-max-drawdown", type=float, default=None, help="Reject live WF params above DD ratio")
    p.set_defaults(func=cmd_walkforward)

    p = sub.add_parser("losses", help="List known hyperopt loss functions")
    p.set_defaults(func=lambda a: print("\n".join(KNOWN_LOSSES)) or 0)

    p = sub.add_parser("list", help="List strategies in the db")
    p.set_defaults(func=cmd_list)
    args = ap.parse_args()
    if not args.mode:
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
