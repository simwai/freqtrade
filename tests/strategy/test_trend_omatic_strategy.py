import numpy as np
import pandas as pd
import pytest


try:
    from user_data.strategies.trend.TrendOMaticStrategy import (
        TrendOMaticDoubleSupertrendStrategy,
        TrendOMaticHPHSuperKeltnerStrategy,
        TrendOMaticNadarayaStrategy,
        TrendOMaticNoTrendStrategy,
        TrendOMaticStrategy,
        TrendOMaticVHFStrategy,
        TrendOMaticVixFixStrategy,
        TrendOMaticWildersStrategy,
        _resample_ohlcv,
    )
except ModuleNotFoundError:
    pytest.skip("user_data strategies are not available", allow_module_level=True)


def _candles(count: int = 700) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=count, freq="5min", tz="UTC")
    movement = np.sin(np.arange(count) / 17.0) * 0.2
    movement += np.random.default_rng(7).normal(0.0, 0.25, count)
    close = 100.0 + np.cumsum(movement)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close + 0.05,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0,
        }
    )


def test_trend_omatic_all_modes_populate() -> None:
    dataframe = _candles()
    required = {"enter_long", "enter_short", "exit_long", "exit_short"}

    for mode in TrendOMaticStrategy.trend_modes:
        strategy = TrendOMaticStrategy({})
        strategy.trend_mode = mode
        result = strategy.populate_indicators(dataframe.copy(), {})
        result = strategy.populate_entry_trend(result, {})
        result = strategy.populate_exit_trend(result, {})

        assert required.issubset(result.columns)
        assert len(result) == len(dataframe)
        assert result[list(required)].notna().all().all()


def test_higher_timeframe_values_are_available_only_after_close() -> None:
    dataframe = _candles(8)
    result = _resample_ohlcv(dataframe, "15m", "5m")

    assert result.loc[dataframe.index[:3], "close"].isna().all()
    assert result.loc[dataframe.index[3], "close"] == dataframe.loc[2, "close"]
    assert result.loc[dataframe.index[3], "volume"] == dataframe.loc[:2, "volume"].sum()


def test_mode_specific_strategy_classes_and_vhf_space() -> None:
    mode_strategies = (
        TrendOMaticHPHSuperKeltnerStrategy,
        TrendOMaticDoubleSupertrendStrategy,
        TrendOMaticNadarayaStrategy,
        TrendOMaticVHFStrategy,
        TrendOMaticWildersStrategy,
        TrendOMaticVixFixStrategy,
        TrendOMaticNoTrendStrategy,
    )
    dataframe = _candles()

    for strategy_class in mode_strategies:
        strategy = strategy_class({})
        result = strategy.populate_indicators(dataframe.copy(), {})
        result = strategy.populate_entry_trend(result, {})
        result = strategy.populate_exit_trend(result, {})
        assert strategy.trend_mode in strategy.trend_modes
        assert {"enter_long", "enter_short", "exit_long", "exit_short"}.issubset(result.columns)

    vhf = TrendOMaticVHFStrategy({})
    assert vhf.itrend_length.value == 13
    assert vhf.itrend_level_factor.value == 0.8


def test_optional_position_management_columns_populate() -> None:
    strategy = TrendOMaticStrategy({})
    strategy.enable_triple_take_profit = True
    strategy.enable_trailing_atr_stoploss = True
    strategy.enable_high_low_exit = True
    strategy.enable_superkeltner_take_profit = True
    strategy.enable_superkeltner_adds = True

    result = strategy.populate_indicators(_candles(), {})

    for column in (
        "tom_trailing_long",
        "tom_trailing_short",
        "tom_high_low_stop_long",
        "tom_high_low_stop_short",
        "tom_hpk_upper_tp",
        "tom_hpk_lower_tp",
        "tom_hpk_upper_add",
        "tom_hpk_lower_add",
    ):
        assert column in result


def test_atr_percentile_filter_gates_entries() -> None:
    strategy = TrendOMaticStrategy({})
    dataframe = _candles()

    result = strategy.populate_indicators(dataframe.copy(), {})
    assert "tom_atr_rank" in result
    assert result["tom_atr_rank"].notna().any()
    assert result["tom_atr_rank"].dropna().between(0.0, 1.0).all()

    unfiltered = strategy.populate_entry_trend(result.copy(), {})
    assert unfiltered["enter_long"].sum() + unfiltered["enter_short"].sum() > 0

    strategy.enable_atr_percentile_filter = True
    strategy.atr_percentile_threshold = 99.0
    filtered = strategy.populate_entry_trend(result.copy(), {})
    assert filtered["enter_long"].sum() + filtered["enter_short"].sum() < (
        unfiltered["enter_long"].sum() + unfiltered["enter_short"].sum()
    )
    allowed = result["tom_atr_rank"].gt(0.99)
    assert (filtered["enter_long"] | filtered["enter_short"]).where(~allowed, False).eq(False).all()
