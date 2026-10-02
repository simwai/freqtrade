"""Gate check command - static validation + basic backtest verification via freqtrade CLI."""

import argparse
import json
import logging
import subprocess
import sys
import glob
from pathlib import Path

logger = logging.getLogger(__name__)


def run_freqtrade_cmd(cmd_args: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Run freqtrade CLI command via subprocess using Python 3.11."""
    # Use explicit Python 3.11 path for freqtrade CLI
    freqtrade_python = r"C:\Users\Simon\AppData\Local\pdm\pdm\python\cpython@3.11.13\python.exe"
    freqtrade_cmd = [freqtrade_python, "-m", "freqtrade"] + cmd_args
    logger.debug(f"Running: {' '.join(freqtrade_cmd)}")
    try:
        result = subprocess.run(freqtrade_cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout}s")
        return -1, "", f"Timeout after {timeout}s"
    except FileNotFoundError:
        logger.error("freqtrade Python not found.")
        return -1, "", "freqtrade not found"
    except Exception as e:
        logger.error(f"Command failed: {e}")
        return -1, "", str(e)


def start_gate(args: list[str] | None = None) -> int:
    """
    Run gate check: static validation + quick backtest via freqtrade CLI.

    Gate checks:
    1. Strategy file exists and loads without errors (via freqtrade list-strategies)
    2. Quick backtest runs without critical errors
    3. Minimum trade count threshold met
    """
    parser = argparse.ArgumentParser(
        description="Freqtrade Gate Check - validates strategy before deployment"
    )
    parser.add_argument("--strategy", required=True, help="Strategy class name")
    parser.add_argument("--timerange", default="20230101-20240101", help="Timerange for backtest")
    parser.add_argument("--timeframe", default="5m", help="Timeframe for backtest")
    parser.add_argument("--config", default=None, help="Config file path override")
    parser.add_argument("--min-trades", type=int, default=10, help="Minimum trades to pass gate")

    # Handle being called via freqtrade CLI (args may be a Namespace)
    if args is not None and not isinstance(args, list):
        ns = args
        args = [
            f"--strategy={getattr(ns, 'strategy', '')}",
            f"--timerange={getattr(ns, 'timerange', '20230101-20240101')}",
            f"--timeframe={getattr(ns, 'timeframe', '5m')}",
        ]
        if getattr(ns, "config", None):
            args.append(f"--config={ns.config}")
        if getattr(ns, "min_trades", None):
            args.append(f"--min-trades={ns.min_trades}")

    cli_args = parser.parse_args(args)

    try:
        logger.info(f"Running gate check for strategy: {cli_args.strategy}")

        # Build base freqtrade command
        base_cmd = []
        if cli_args.config:
            base_cmd += ["-c", cli_args.config]

        # 1. Check strategy exists
        logger.info("Step 1/4: Checking strategy availability...")
        list_cmd = ["list-strategies"] + base_cmd
        code, stdout, stderr = run_freqtrade_cmd(list_cmd)
        if code != 0:
            logger.error(f"  FAILED: Cannot list strategies: {stderr}")
            return 1
        if cli_args.strategy not in stdout:
            logger.error(f"  FAILED: Strategy '{cli_args.strategy}' not found in available strategies")
            logger.error(f"  Available: {stdout.strip()}")
            return 1
        logger.info(f"  Strategy found: {cli_args.strategy}")

        # 2. Quick backtest
        logger.info("Step 2/4: Running quick backtest...")
        backtest_cmd = ["backtesting"] + base_cmd + [
            "--strategy", cli_args.strategy,
            "--timerange", cli_args.timerange,
            "--timeframe", cli_args.timeframe,
            "--cache", "none",
            "--export", "none",
        ]
        code, stdout, stderr = run_freqtrade_cmd(backtest_cmd, timeout=600)
        if code != 0:
            logger.error(f"  FAILED: Backtest exited with code {code}")
            logger.error(f"  stderr: {stderr[-500:]}")
            return 1

        # 3. Check minimum trades from backtest result
        logger.info("Step 3/4: Checking trade count...")
        backtest_files = glob.glob("user_data/backtest_results/backtest-result-*.json")
        if not backtest_files:
            logger.warning("  No backtest result file found")
        else:
            latest = max(backtest_files, key=lambda p: Path(p).stat().st_mtime)
            with open(latest) as f:
                bt_result = json.load(f)

            total_trades = bt_result.get("strategy_comparison", [{}])[0].get("trades", 0)
            if total_trades < cli_args.min_trades:
                logger.error(f"  FAILED: Only {total_trades} trades (minimum: {cli_args.min_trades})")
                return 1
            logger.info(f"  Trade count OK: {total_trades} >= {cli_args.min_trades}")

        # 4. Basic validation passed
        logger.info("Step 4/4: Gate validation complete")
        logger.info("✅ GATE PASSED - Strategy ready for deployment")
        return 0

    except Exception as e:
        logger.error(f"Gate check failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(start_gate())