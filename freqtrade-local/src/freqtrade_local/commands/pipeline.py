"""Pipeline command - orchestrates gate -> backtest -> dry-run -> live via freqtrade CLI."""

import argparse
import logging
import subprocess
import sys
import time

logger = logging.getLogger(__name__)


def run_freqtrade_cmd(cmd_args: list[str], timeout: int = 600, capture: bool = True) -> tuple[int, str, str]:
    """Run freqtrade CLI command via subprocess using Python 3.11."""
    freqtrade_python = r"C:\Users\Simon\AppData\Local\pdm\pdm\python\cpython@3.11.13\python.exe"
    freqtrade_cmd = [freqtrade_python, "-m", "freqtrade"] + cmd_args
    logger.debug(f"Running: {' '.join(freqtrade_cmd)}")
    try:
        if capture:
            result = subprocess.run(freqtrade_cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode, result.stdout, result.stderr
        else:
            # Run with live output
            result = subprocess.run(freqtrade_cmd, text=True, timeout=timeout)
            return result.returncode, "", ""
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout}s")
        return -1, "", f"Timeout after {timeout}s"
    except FileNotFoundError:
        logger.error("freqtrade Python not found.")
        return -1, "", "freqtrade not found"
    except Exception as e:
        logger.error(f"Command failed: {e}")
        return -1, "", str(e)


def start_pipeline(args: list[str] | None = None) -> int:
    """
    Run full deployment pipeline via freqtrade CLI:
    1. Gate check (static validation + quick backtest)
    2. Full backtest
    3. Dry-run (simulated trading)
    4. Telegram confirmation prompt
    5. Live trading (on confirmation)
    """
    parser = argparse.ArgumentParser(
        description="Freqtrade Deployment Pipeline - gate -> backtest -> dry-run -> live"
    )
    parser.add_argument("--strategy", required=True, help="Strategy class name")
    parser.add_argument("--timerange", default="20230101-20240101", help="Timerange for backtest")
    parser.add_argument("--timeframe", default="5m", help="Timeframe")
    parser.add_argument("--config", default=None, help="Config file path override")
    parser.add_argument("--dryrun-id", default=None, help="Dry-run identifier (default: timestamp)")
    parser.add_argument("--skip-gate", action="store_true", help="Skip gate check")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip full backtest")
    parser.add_argument("--skip-dryrun", action="store_true", help="Skip dry-run")
    parser.add_argument("--auto-confirm", action="store_true", help="Auto-confirm live (DANGEROUS)")
    parser.add_argument("--min-trades", type=int, default=10, help="Minimum trades for gate")

    # Handle being called via freqtrade CLI
    if args is not None and not isinstance(args, list):
        ns = args
        args = [
            f"--strategy={getattr(ns, 'strategy', '')}",
            f"--timerange={getattr(ns, 'timerange', '20230101-20240101')}",
            f"--timeframe={getattr(ns, 'timeframe', '5m')}",
        ]
        if getattr(ns, "config", None):
            args.append(f"--config={ns.config}")
        if getattr(ns, "dryrun_id", None):
            args.append(f"--dryrun-id={ns.dryrun_id}")
        if getattr(ns, "skip_gate", None):
            args.append("--skip-gate")
        if getattr(ns, "skip_backtest", None):
            args.append("--skip-backtest")
        if getattr(ns, "skip_dryrun", None):
            args.append("--skip-dryrun")
        if getattr(ns, "auto_confirm", None):
            args.append("--auto-confirm")
        if getattr(ns, "min_trades", None):
            args.append(f"--min-trades={ns.min_trades}")

    cli_args = parser.parse_args(args)

    dryrun_id = cli_args.dryrun_id or str(int(time.time()))

    # Build base command parts
    base_cmd = []
    if cli_args.config:
        base_cmd = ["-c", cli_args.config]

    logger.info(f"🚀 Starting pipeline for {cli_args.strategy} (dryrun-id: {dryrun_id})")

    try:
        # ============ STAGE 1: GATE CHECK ============
        if not cli_args.skip_gate:
            logger.info("=" * 60)
            logger.info("STAGE 1/4: GATE CHECK")
            logger.info("=" * 60)

            gate_cmd = ["gate"] + base_cmd + [
                "--strategy", cli_args.strategy,
                "--timerange", cli_args.timerange,
                "--timeframe", cli_args.timeframe,
                "--min-trades", str(cli_args.min_trades),
            ]
            code, _, _ = run_freqtrade_cmd(gate_cmd)
            if code != 0:
                logger.error("❌ GATE FAILED - Pipeline aborted")
                return 1
            logger.info("✅ Gate passed")
        else:
            logger.info("⏭️  Skipping gate check (--skip-gate)")

        # ============ STAGE 2: FULL BACKTEST ============
        if not cli_args.skip_backtest:
            logger.info("=" * 60)
            logger.info("STAGE 2/4: FULL BACKTEST")
            logger.info("=" * 60)

            backtest_cmd = ["backtesting"] + base_cmd + [
                "--strategy", cli_args.strategy,
                "--timerange", cli_args.timerange,
                "--timeframe", cli_args.timeframe,
                "--cache", "none",
                "--export", "trades",
            ]
            code, _, _ = run_freqtrade_cmd(backtest_cmd)
            if code != 0:
                logger.error("❌ BACKTEST FAILED - Pipeline aborted")
                return 1
            logger.info("✅ Backtest completed")
        else:
            logger.info("⏭️  Skipping backtest (--skip-backtest)")

        # ============ STAGE 3: DRY-RUN ============
        if not cli_args.skip_dryrun:
            logger.info("=" * 60)
            logger.info("STAGE 3/4: DRY-RUN (SIMULATED TRADING)")
            logger.info("=" * 60)

            dryrun_cmd = ["trade"] + base_cmd + [
                "--strategy", cli_args.strategy,
                "--dry-run",
                "--dry-run-wallet", "5000",
            ]
            logger.info("Starting dry-run. Press Ctrl+C to stop and proceed to confirmation.")
            logger.info(f"Dry-run ID: {dryrun_id}")

            try:
                result = subprocess.run(dryrun_cmd, timeout=30)
                logger.info(f"Dry-run test completed (exit: {result.returncode})")
            except subprocess.TimeoutExpired:
                logger.info("Dry-run running (timeout reached for test)")
            except KeyboardInterrupt:
                logger.info("Dry-run interrupted by user")

            logger.info("✅ Dry-run phase completed")
        else:
            logger.info("⏭️  Skipping dry-run (--skip-dryrun)")

        # ============ STAGE 4: TELEGRAM CONFIRMATION ============
        logger.info("=" * 60)
        logger.info("STAGE 4/4: LIVE DEPLOYMENT CONFIRMATION")
        logger.info("=" * 60)

        if cli_args.auto_confirm:
            logger.warning("⚠️  AUTO-CONFIRM ENABLED - Skipping human confirmation!")
            confirm = True
        else:
            print("\n" + "=" * 60)
            print("⚠️  READY FOR LIVE DEPLOYMENT")
            print(f"Strategy: {cli_args.strategy}")
            print(f"Dry-run ID: {dryrun_id}")
            print("=" * 60)
            response = input("Confirm live deployment? Type 'YES' to proceed: ").strip()
            confirm = response == "YES"

        if not confirm:
            logger.info("❌ Live deployment cancelled by user")
            return 0

        # ============ STAGE 5: LIVE TRADING ============
        logger.info("=" * 60)
        logger.info("STAGE 5/5: LIVE TRADING")
        logger.info("=" * 60)

        live_cmd = ["trade"] + base_cmd + [
            "--strategy", cli_args.strategy,
        ]
        logger.info("Starting LIVE trading. Press Ctrl+C to stop.")
        logger.warning("💰 REAL CAPITAL AT RISK")

        try:
            subprocess.run(live_cmd, check=True)
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
        except subprocess.CalledProcessError as e:
            logger.error(f"Live trading failed: {e}")
            return 1

        logger.info("✅ Pipeline completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(start_pipeline())