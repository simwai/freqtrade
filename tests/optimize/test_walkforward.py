from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from freqtrade.configuration import TimeRange
from freqtrade.enums import State
from freqtrade.freqtradebot import FreqtradeBot
from freqtrade.optimize.hyperopt_tools import HyperoptTools
from freqtrade.optimize.walk_forward_tools import (
    generate_walk_forward_windows,
    next_schedule,
    pending_parameter_file,
    read_json,
)
from freqtrade.optimize.walkforward import WalkForwardHistoricalRunner, WalkForwardLiveRunner
from freqtrade.persistence import Trade


def test_generate_walk_forward_windows() -> None:
    timerange = TimeRange.parse_timerange("20240101-20240430")

    windows = generate_walk_forward_windows(timerange, train_days=90, test_days=7, step_days=7)

    assert windows[0].train_timerange == "20240101-20240330"
    assert windows[0].test_timerange == "20240331-20240406"
    assert windows[1].train_timerange == "20240108-20240406"
    assert windows[1].test_timerange == "20240407-20240413"
    assert windows[-1].test_timerange == "20240428-20240430"


def test_generate_walk_forward_windows_requires_finite_timerange() -> None:
    with pytest.raises(ValueError, match="finite"):
        generate_walk_forward_windows(TimeRange.parse_timerange("20240101-"))

    with pytest.raises(ValueError, match="step_days"):
        generate_walk_forward_windows(TimeRange.parse_timerange("20240101-20240430"), 90, 7, 1)


def test_next_schedule() -> None:
    now = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    assert next_schedule(now, "sun 00:05") == datetime(2024, 1, 7, 0, 5, tzinfo=timezone.utc)


def test_apply_params(hyperopt) -> None:
    strategy = hyperopt.hyperopter.backtesting.strategy
    result = {
        "params_dict": {"buy_plusdi": 0.8, "sell_rsi": 80},
        "params_details": {
            "roi": {"0": 0.02, "30": 0},
            "stoploss": {"stoploss": -0.2},
            "trailing": {
                "trailing_stop": True,
                "trailing_stop_positive": 0.02,
                "trailing_stop_positive_offset": 0.04,
                "trailing_only_offset_is_reached": False,
            },
            "max_open_trades": {"max_open_trades": 3},
        },
        "params_not_optimized": {},
    }

    HyperoptTools.apply_params(hyperopt.config, strategy, result)

    assert strategy.buy_plusdi.value == 0.8
    assert strategy.sell_rsi.value == 80
    assert strategy.minimal_roi == {0: 0.02, 30: 0}
    assert strategy.stoploss == -0.2
    assert strategy.max_open_trades == 3
    assert hyperopt.config["max_open_trades"] == 3


def test_live_runner_publishes_candidate(mocker, tmp_path) -> None:
    config = {
        "user_data_dir": tmp_path,
        "strategy": "SampleStrategy",
        "walk_forward": {"train_days": 30, "min_trades": 2},
    }
    result = {
        "loss": 1.0,
        "params_dict": {},
        "params_details": {
            "buy": {"buy_rsi": 23},
            "stoploss": {"stoploss": -0.1},
        },
        "params_not_optimized": {},
        "results_metrics": {"total_trades": 5, "max_drawdown_account": 0.1},
    }
    result_file = tmp_path / "hyperopt.fthypt"
    mocker.patch("freqtrade.optimize.walkforward._run_hyperopt", return_value=(result, result_file))
    runner = WalkForwardLiveRunner(config)

    runner._run_once(datetime(2024, 4, 10, tzinfo=timezone.utc))

    pending = pending_parameter_file(config, "SampleStrategy")
    assert pending.is_file()
    candidate = read_json(pending)
    assert candidate["strategy_name"] == "SampleStrategy"
    assert isinstance(candidate["params"]["buy"]["buy_rsi"], int)
    assert isinstance(candidate["params"]["stoploss"]["stoploss"], float)


def test_bot_applies_pending_walk_forward_params(mocker, tmp_path) -> None:
    strategy_file = tmp_path / "SampleStrategy.py"
    strategy_file.write_text("", encoding="utf-8")
    active_file = strategy_file.with_suffix(".json")
    active_file.write_text('{"strategy_name":"SampleStrategy","params":{}}', encoding="utf-8")
    config = {"user_data_dir": tmp_path, "walk_forward": {"enabled": True}}
    pending = pending_parameter_file(config, "SampleStrategy")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(
        '{"strategy_name":"SampleStrategy","params":{"stoploss":{"stoploss":-0.2}}}',
        encoding="utf-8",
    )

    bot = object.__new__(FreqtradeBot)
    bot.config = config
    bot.strategy = SimpleNamespace(
        __file__=str(strategy_file), get_strategy_name=lambda: "SampleStrategy"
    )
    bot._walk_forward_pending_file = pending
    bot.state = State.RUNNING
    bot.notify_status = MagicMock()
    mocker.patch.object(Trade, "get_open_trade_count", return_value=0)

    assert bot._check_walk_forward_update() is True
    assert bot.state == State.RELOAD_CONFIG
    assert not pending.exists()
    assert '"stoploss"' in active_file.read_text(encoding="utf-8")


def test_historical_runner_reuses_backtesting_state(mocker, tmp_path) -> None:
    config = {
        "user_data_dir": tmp_path,
        "strategy": "SampleStrategy",
        "timerange": "20240101-20240430",
        "spaces": ["default"],
        "stake_currency": "USDT",
        "dry_run_wallet": 1000,
    }
    data = {
        "BTC/USDT": pd.DataFrame(
            {"date": pd.date_range("2024-01-01", "2024-04-30", freq="D", tz="UTC")}
        )
    }

    class FakeBacktesting:
        required_startup = 0

        def __init__(self) -> None:
            self.config = config
            self.strategy = SimpleNamespace(
                config=config,
                get_strategy_name=lambda: "SampleStrategy",
                enumerate_parameters=lambda _category: [],
                advise_all_indicators=lambda segment_data: segment_data,
            )
            self.strategylist = [self.strategy]
            self.pairlists = SimpleNamespace(whitelist=["BTC/USDT"])
            self.wallets = SimpleNamespace(get_total=lambda _currency: 1000.0)
            self.backtest_calls = []

        def load_bt_data(self):
            return data, TimeRange.parse_timerange(config["timerange"])

        def load_bt_data_detail(self):
            return None

        def _set_strategy(self, _strategy):
            return None

        def backtest(self, processed, start, end, **kwargs):
            self.backtest_calls.append(kwargs)
            return {
                "results": pd.DataFrame({"value": [1]}),
                "config": config,
                "final_balance": 1000.0,
            }

    fake_backtesting = FakeBacktesting()
    mocker.patch("freqtrade.optimize.walkforward.Backtesting", return_value=fake_backtesting)
    mocker.patch(
        "freqtrade.optimize.walkforward._run_hyperopt",
        return_value=(
            {
                "loss": 1.0,
                "params_dict": {},
                "params_details": {},
                "params_not_optimized": {},
                "current_epoch": 1,
            },
            tmp_path / "hyperopt.fthypt",
        ),
    )
    mocker.patch(
        "freqtrade.optimize.walkforward._stats_for_results", return_value={"total_trades": 1}
    )
    mocker.patch(
        "freqtrade.optimize.walkforward.generate_strategy_stats", return_value={"total_trades": 5}
    )

    Trade.reset_trades()
    manifest = WalkForwardHistoricalRunner(config).run()

    assert len(manifest["windows"]) == 5
    assert len(fake_backtesting.backtest_calls) == 5
    assert all(call["preserve_state"] for call in fake_backtesting.backtest_calls)
    assert fake_backtesting.backtest_calls[-1]["finalize"] is True
    assert all(call["finalize"] is False for call in fake_backtesting.backtest_calls[:-1])
