"""Walk-forward hyperoptimization and evaluation."""

from __future__ import annotations

import logging
import time as time_module
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pandas as pd

from freqtrade.configuration import TimeRange
from freqtrade.constants import Config
from freqtrade.enums import RunMode
from freqtrade.exceptions import OperationalException
from freqtrade.ft_types import BacktestContentType, BacktestContentTypeIcomplete
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.optimize.hyperopt import Hyperopt
from freqtrade.optimize.hyperopt_tools import HyperoptTools
from freqtrade.optimize.optimize_reports import generate_strategy_stats
from freqtrade.optimize.walk_forward_tools import (
    WalkForwardWindow,
    generate_walk_forward_windows,
    live_training_timerange,
    next_schedule,
    parameter_file_from_result,
    pending_parameter_file,
    walk_forward_settings,
    write_json_atomic,
)
from freqtrade.persistence import LocalTrade


logger = logging.getLogger(__name__)
UTC = timezone.utc


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")


def _strategy_name(config: Config) -> str:
    return str(config["strategy"])


def _run_directory(config: Config, strategy_name: str, run_id: str) -> Path:
    return Path(config["user_data_dir"]) / "walk_forward" / strategy_name / run_id


def _best_snapshot(result: dict[str, Any], result_file: Path | None = None) -> dict[str, Any]:
    snapshot = {
        key: result.get(key)
        for key in (
            "loss",
            "params_dict",
            "params_details",
            "params_not_optimized",
            "current_epoch",
            "is_initial_point",
            "is_random",
        )
        if key in result
    }
    if result_file:
        snapshot["result_file"] = str(result_file)
    return snapshot


def _run_hyperopt(
    config: Config,
    timerange: TimeRange,
    work_directory: Path,
) -> tuple[dict[str, Any] | None, Path]:
    """Run one isolated hyperopt without touching active strategy parameters."""
    if config.get("freqai", {}).get("enabled", False):
        raise OperationalException(
            "Walk-forward hyperopt does not support FreqAI yet. FreqAI support will be added "
            "after the regular strategy workflow is stable."
        )

    hyperopt_config = deepcopy(config)
    hyperopt_config["runmode"] = RunMode.HYPEROPT
    hyperopt_config["timerange"] = timerange.timerange_str
    hyperopt_config["disableparamexport"] = True
    hyperopt_config["walk_forward_run"] = True
    results_directory = work_directory / "hyperopt_results"
    hyperopt_config["hyperopt_results_dir"] = results_directory
    hyperopt_config["hyperopt_result_filename"] = "hyperopt.fthypt"

    hyperopt = Hyperopt(hyperopt_config)
    best = hyperopt.start()
    if hyperopt.interrupted:
        raise KeyboardInterrupt
    return best, hyperopt.results_file


def _window_data(
    data: dict[str, pd.DataFrame], window: WalkForwardWindow, startup_candles: int
) -> dict[str, pd.DataFrame]:
    """Keep startup candles before a test window, then only candles in that window."""
    result: dict[str, pd.DataFrame] = {}
    for pair, dataframe in data.items():
        start_index = int(dataframe["date"].searchsorted(window.test.startdt, side="left"))
        end_index = int(dataframe["date"].searchsorted(window.test.stopdt, side="right"))
        start_index = max(0, start_index - startup_candles)
        sliced = dataframe.iloc[start_index:end_index].copy()
        if not sliced.empty:
            result[pair] = sliced
    return result


def _stats_for_results(
    backtesting: Backtesting,
    content: BacktestContentType,
    results: pd.DataFrame,
    start_balance: float,
    timerange: TimeRange,
    run_start: int,
    run_end: int,
) -> dict[str, Any]:
    config = deepcopy(content["config"])
    config["dry_run_wallet"] = start_balance
    config["timerange"] = timerange.timerange_str
    segment_content = cast(BacktestContentType, dict(content))
    segment_content["config"] = config
    segment_content["results"] = results
    segment_content["backtest_start_time"] = run_start
    segment_content["backtest_end_time"] = run_end
    start_dt = timerange.startdt
    stop_dt = timerange.stopdt
    if start_dt is None or stop_dt is None:
        raise OperationalException("Walk-forward statistics require a finite time range.")
    return generate_strategy_stats(
        backtesting.pairlists.whitelist,
        backtesting.strategy.get_strategy_name(),
        segment_content,
        start_dt,
        stop_dt,
        market_change=0.0,
    )


class WalkForwardHistoricalRunner:
    """Replay historical weekly optimization and out-of-sample testing."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.settings = walk_forward_settings(config)
        self.strategy_name = _strategy_name(config)
        self.run_id = _run_id()
        self.run_directory = _run_directory(config, self.strategy_name, self.run_id)
        self.manifest_file = self.run_directory / "walk_forward.json"

        timerange = TimeRange.parse_timerange(str(config.get("timerange", "")))
        self.windows = generate_walk_forward_windows(
            timerange,
            self.settings["train_days"],
            self.settings["test_days"],
            self.settings["step_days"],
        )
        self.overall_timerange = timerange

    def _initial_manifest(self) -> dict[str, Any]:
        return {
            "version": 1,
            "type": "walk-forward",
            "strategy": self.strategy_name,
            "run_id": self.run_id,
            "settings": self.settings,
            "timerange": self.overall_timerange.timerange_str,
            "windows": [],
        }

    def run(self) -> dict[str, Any]:
        manifest = self._initial_manifest()
        write_json_atomic(self.manifest_file, manifest)

        backtest_config = deepcopy(self.config)
        backtest_config["runmode"] = RunMode.BACKTEST
        backtest_config["timerange"] = self.overall_timerange.timerange_str
        backtest_config["disableparamexport"] = True

        backtesting = Backtesting(backtest_config)
        backtesting._set_strategy(backtesting.strategylist[0])
        data, _ = backtesting.load_bt_data()
        backtesting.load_bt_data_detail()

        active_result: dict[str, Any] | None = None
        all_results: list[pd.DataFrame] = []
        content: BacktestContentTypeIcomplete | None = None

        for window in self.windows:
            logger.info(
                "Walk-forward window %s: hyperopting %s, testing %s",
                window.index,
                window.train_timerange,
                window.test_timerange,
            )
            work_directory = self.run_directory / f"window_{window.index:04d}"
            best, result_file = _run_hyperopt(self.config, window.train, work_directory)
            if best is None:
                raise OperationalException(
                    "No usable hyperopt result was produced for "
                    f"walk-forward window {window.index}."
                )

            applied = False
            if not LocalTrade.bt_trades_open:
                HyperoptTools.apply_params(backtest_config, backtesting.strategy, best)
                active_result = best
                applied = True

            backtesting.timerange = window.test
            backtesting.config["timerange"] = window.test.timerange_str
            before_count = len(LocalTrade.bt_trades)
            start_balance = float(
                backtesting.wallets.get_total(backtesting.strategy.config["stake_currency"])
            )
            run_start = int(datetime.now(UTC).timestamp())
            segment_data = _window_data(data, window, backtesting.required_startup)
            processed = backtesting.strategy.advise_all_indicators(segment_data)
            test_start = window.test.startdt
            test_stop = window.test.stopdt
            if test_start is None or test_stop is None:
                raise OperationalException(
                    f"Walk-forward window {window.index} requires a finite test range."
                )
            content = backtesting.backtest(
                processed,
                test_start,
                test_stop,
                preserve_state=True,
                finalize=window.index == self.windows[-1].index,
            )
            run_end = int(datetime.now(UTC).timestamp())
            segment_results = content["results"].iloc[before_count:].copy()
            all_results.append(segment_results)
            stats = _stats_for_results(
                backtesting,
                cast(BacktestContentType, content),
                segment_results,
                start_balance,
                window.test,
                run_start,
                run_end,
            )

            record = {
                "index": window.index,
                "train_timerange": window.train_timerange,
                "test_timerange": window.test_timerange,
                "parameters_applied_at_boundary": applied,
                "active_parameters_epoch": active_result.get("current_epoch")
                if active_result
                else None,
                "best": _best_snapshot(best, result_file),
                "out_of_sample": stats,
            }
            manifest["windows"].append(record)
            write_json_atomic(self.manifest_file, manifest)

            # The per-window hyperopt data pickle is a re-computable cache;
            # keeping it for 40+ windows fills multi-GB drives mid-run.
            tickerdata = work_directory / "hyperopt_results" / "hyperopt_tickerdata.pkl"
            tickerdata.unlink(missing_ok=True)

        all_results = [r for r in all_results if not r.empty]
        if not all_results:
            raise OperationalException("Walk-forward produced no out-of-sample results.")
        if content is None:
            raise OperationalException("Walk-forward produced no backtesting content.")

        aggregate_results = pd.concat(all_results, ignore_index=True)
        if "is_short" in aggregate_results.columns:
            # Windows without out-of-sample trades contribute empty object-dtype
            # frames; normalise the column so boolean masking works downstream.
            aggregate_results["is_short"] = aggregate_results["is_short"].astype(bool)
        aggregate_config = deepcopy(content["config"])
        aggregate_config["dry_run_wallet"] = self.config["dry_run_wallet"]
        aggregate_config["timerange"] = self.overall_timerange.timerange_str
        aggregate_content = cast(BacktestContentType, dict(content))
        aggregate_content["config"] = aggregate_config
        aggregate_content["results"] = aggregate_results
        aggregate_content["backtest_start_time"] = int(datetime.now(UTC).timestamp())
        aggregate_content["backtest_end_time"] = int(datetime.now(UTC).timestamp())
        overall_start = self.overall_timerange.startdt
        overall_stop = self.overall_timerange.stopdt
        if overall_start is None or overall_stop is None:
            raise OperationalException("Walk-forward requires a finite --timerange.")
        manifest["aggregate"] = generate_strategy_stats(
            backtesting.pairlists.whitelist,
            backtesting.strategy.get_strategy_name(),
            aggregate_content,
            overall_start,
            overall_stop,
            market_change=0.0,
        )
        write_json_atomic(self.manifest_file, manifest)

        logger.info("Walk-forward results saved to '%s'.", self.manifest_file)
        print(f"Walk-forward results saved to {self.manifest_file}")
        return manifest


class WalkForwardLiveRunner:
    """Run a scheduled weekly hyperopt and publish a pending parameter file."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.settings = walk_forward_settings(config)
        self.strategy_name = _strategy_name(config)
        self.run_root = _run_directory(config, self.strategy_name, "live")
        self.state_file = self.run_root / "live_state.json"

    def _run_once(self, now: datetime | None = None) -> dict[str, Any] | None:
        current_time = now or datetime.now(UTC)
        training_range = live_training_timerange(current_time, self.settings["train_days"])
        run_id = _run_id()
        run_directory = self.run_root / run_id
        logger.info("Running live walk-forward hyperopt for %s.", training_range.timerange_str)
        best, result_file = _run_hyperopt(self.config, training_range, run_directory)
        if best is None:
            logger.warning("No usable live walk-forward result was produced.")
            return None

        metrics = best.get("results_metrics", {})
        min_trades = self.settings["min_trades"]
        if min_trades and metrics.get("total_trades", 0) < min_trades:
            logger.warning(
                "Rejecting live walk-forward parameters: %s trades is below the configured "
                "minimum of %s.",
                metrics.get("total_trades", 0),
                min_trades,
            )
            return None

        max_drawdown = self.settings.get("max_drawdown")
        if max_drawdown is not None and metrics.get("max_drawdown_account", 0) > max_drawdown:
            logger.warning(
                "Rejecting live walk-forward parameters: drawdown %.2f exceeds %.2f.",
                metrics.get("max_drawdown_account", 0),
                max_drawdown,
            )
            return None

        metadata = {
            "run_id": run_id,
            "train_timerange": training_range.timerange_str,
            "loss": best.get("loss"),
            "result_file": str(result_file),
        }
        candidate = parameter_file_from_result(best, self.strategy_name, metadata)
        pending = pending_parameter_file(self.config, self.strategy_name)
        write_json_atomic(pending, candidate)
        state = {
            "last_run": metadata,
            "pending_file": str(pending),
            "published_at": datetime.now(UTC),
        }
        write_json_atomic(self.state_file, state)
        logger.info("Published pending walk-forward parameters to '%s'.", pending)
        return candidate

    def run_once(self, now: datetime | None = None) -> dict[str, Any] | None:
        from filelock import FileLock, Timeout

        lock = FileLock(Hyperopt.get_lock_filename(self.config))
        try:
            with lock.acquire(timeout=1):
                return self._run_once(now)
        except Timeout:
            logger.info("Another optimization is running; keeping current parameters.")
            return None

    def run(self, run_now: bool = False) -> None:
        logger.info("Starting scheduled live walk-forward runner.")
        if run_now:
            self.run_once(datetime.now(UTC))
        while True:
            try:
                current = datetime.now(UTC)
                scheduled = next_schedule(current, self.settings["schedule"])
                wait_seconds = max((scheduled - current).total_seconds(), 0)
                logger.info("Next live walk-forward run at %s UTC.", scheduled.isoformat())
                time_module.sleep(wait_seconds)
                self.run_once(datetime.now(UTC))
            except Exception:
                # One failed cycle must not kill the weekly scheduler; the next
                # scheduled attempt retries with fresh data.
                logger.exception("Scheduled live walk-forward run failed.")
