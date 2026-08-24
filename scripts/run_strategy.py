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
    python user_data/scripts/run_strategy.py backtest --strategy BigZ08 --timerange 20230101-20240101
    python user_data/scripts/run_strategy.py hyperopt --strategy BigZ08 --timerange 20220101-20240101 --epochs 100 --loss SharpeHyperOptLossDaily
    python user_data/scripts/run_strategy.py walkforward --strategy BigZ08 --timerange 20210101-20240101 --train-days 90 --test-days 7 --step-days 7 --epochs 50
    python user_data/scripts/run_strategy.py --list
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

USER_DATA = Path(__file__).resolve().parents[1]
DEFAULT_DB = USER_DATA / "analysis" / "results.db"

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
    proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")
    return proc.returncode


def cmd_backtest(args) -> int:
    config = resolve_config(args.strategy, args.config)
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
    return run(cmd)


def cmd_hyperopt(args) -> int:
    config = resolve_config(args.strategy, args.config)
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
    print(f"Hyperopt {args.strategy} on {args.timerange}, {args.epochs} epochs, loss={args.loss}")
    return run(cmd)


def cmd_walkforward(args) -> int:
    config = resolve_config(args.strategy, args.config)
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
    print(f"Walk-forward {args.strategy} on {args.timerange} "
          f"(train={args.train_days}d test={args.test_days}d step={args.step_days}d, {args.epochs} epochs)")
    return run(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one freqtrade backtest / hyperopt / walk-forward.")
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
    p.set_defaults(func=cmd_hyperopt)

    p = sub.add_parser("walkforward", parents=[common], help="Run walk-forward optimization")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--loss", default="SharpeHyperOptLossDaily")
    p.add_argument("--spaces", nargs="+", default=None)
    p.add_argument("--train-days", type=int, default=90)
    p.add_argument("--test-days", type=int, default=7)
    p.add_argument("--step-days", type=int, default=7)
    p.set_defaults(func=cmd_walkforward)

    p = sub.add_parser("losses", help="List known hyperopt loss functions")
    p.set_defaults(func=lambda a: print("\n".join(KNOWN_LOSSES)) or 0)

    p = sub.add_parser("list", help="List strategies in the db")
    p.set_defaults(func=lambda a: print("\n".join(list_strategies(sqlite3.connect(a.db)) or ["(none)"])) or 0)

    args = ap.parse_args()
    if not args.mode:
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
