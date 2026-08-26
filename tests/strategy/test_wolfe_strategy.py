import numpy as np
import pandas as pd
import pytest


try:
    from user_data.strategies.pattern.WolfeStrategy import (
        WolfeFuturesShortMarketStrategy,
        WolfeFuturesShortStrategy,
        WolfeSpotStrategy,
        _base_zigzag,
        _find_pattern,
        _is_limit_entry,
        _Pivot,
        _valid_bracket,
    )
except ModuleNotFoundError:
    pytest.skip("user_data strategies are not available", allow_module_level=True)


def _candles(values: list[float]) -> pd.DataFrame:
    close = np.asarray(values, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(close), freq="5min", tz="UTC"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100.0,
        }
    )


def test_wolfe_detector_is_causal() -> None:
    values = [100.0 + np.sin(index / 3.0) * 10.0 for index in range(80)]
    prefix = _candles(values[:50])
    extended = _candles(values)

    prefix_snapshots, prefix_new, prefix_double = _base_zigzag(prefix, 8, 250)
    extended_snapshots, extended_new, extended_double = _base_zigzag(extended, 8, 250)

    assert prefix_snapshots == extended_snapshots[: len(prefix)]
    assert prefix_new == extended_new[: len(prefix)]
    assert prefix_double == extended_double[: len(prefix)]


def test_find_long_wolfe_pattern_uses_point_four_for_target() -> None:
    chronological = (
        _Pivot(10.0, 0, -1),
        _Pivot(20.0, 2, 1),
        _Pivot(8.0, 4, -1),
        _Pivot(15.0, 6, 1),
        _Pivot(5.0, 8, -1),
    )
    newest_first = list(reversed(chronological))

    pattern = _find_pattern(newest_first, 0, 8, "long", 1, 1.0)

    assert pattern is not None
    assert pattern.side == "long"
    assert pattern.stop == -2.5
    assert pattern.target > pattern.entry
    assert pattern.target == 10.0 + (15.0 - 10.0) / 6.0 * pattern.expiry


def test_strategy_classes_are_separated_by_market_mode() -> None:
    assert WolfeSpotStrategy.can_short is False
    assert WolfeFuturesShortStrategy.can_short is True
    strategy = WolfeFuturesShortStrategy({})
    assert strategy.leverage("TEST/USDT:USDT", None, 100.0, 1.0, 5.0, None, "short") == 2.0
    assert strategy.leverage("TEST/USDT:USDT", None, 100.0, 1.0, 1.5, None, "short") == 1.5


def test_only_limit_entries_are_supported() -> None:
    assert _is_limit_entry("long", close=110.0, entry=100.0)
    assert not _is_limit_entry("long", close=90.0, entry=100.0)
    assert _is_limit_entry("short", close=90.0, entry=100.0)
    assert not _is_limit_entry("short", close=110.0, entry=100.0)


def test_invalid_bracket_geometry_is_rejected() -> None:
    assert _valid_bracket("long", entry=100.0, stop=95.0, target=110.0)
    assert not _valid_bracket("long", entry=100.0, stop=105.0, target=110.0)
    assert _valid_bracket("short", entry=100.0, stop=105.0, target=95.0)
    assert not _valid_bracket("short", entry=100.0, stop=95.0, target=90.0)


def test_strategy_defaults_are_conservative() -> None:
    assert WolfeSpotStrategy.min_risk_reward.value == 1.5
    assert WolfeSpotStrategy.avoid_overlap.value is True
    assert WolfeSpotStrategy.max_patterns.value == 3
    assert WolfeFuturesShortMarketStrategy.wolfe_entry_mode == "market"
    assert WolfeFuturesShortMarketStrategy.order_types["entry"] == "market"


def test_strategy_populates_native_signal_columns() -> None:
    dataframe = _candles([100.0 + np.sin(index / 4.0) * 8.0 for index in range(120)])
    strategy = WolfeSpotStrategy({})

    result = strategy.populate_indicators(dataframe, {"pair": "TEST/USDT"})
    result = strategy.populate_entry_trend(result, {"pair": "TEST/USDT"})
    result = strategy.populate_exit_trend(result, {"pair": "TEST/USDT"})

    assert len(result) == len(dataframe)
    assert {
        "wolfe_entry",
        "wolfe_stop",
        "wolfe_target",
        "enter_long",
        "enter_short",
        "exit_long",
        "exit_short",
        "wolfe_rejected_stop_entry",
        "wolfe_rejected_rr",
        "wolfe_rejected_overlap",
        "wolfe_rejected_geometry",
        "wolfe_expired",
    }.issubset(result.columns)
