"""Freqtrade port of the Trend-O-Matic TradingView strategy.

The original script uses TradingView's ``request.security`` and a number of
stateful ``strategy.order`` calls.  Freqtrade only exposes completed candles,
so this implementation deliberately does not reproduce Pine's repainting
mode.  Higher timeframes are resampled from completed base-timeframe candles
and position state is kept on the Trade object instead of in module globals.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    BooleanParameter,
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
    stoploss_from_absolute,
    timeframe_to_minutes,
)
from strategy_lib import risk as sl_risk
from strategy_lib.risk import SlTpConfig, TradeLevelsManager


logger = logging.getLogger(__name__)


def _crossed_above(left: Series, right: Series) -> Series:
    """Return the equivalent of Pine's ``ta.crossover``."""

    return ((left > right) & (left.shift(1) <= right.shift(1))).fillna(False)


def _crossed_below(left: Series, right: Series) -> Series:
    """Return the equivalent of Pine's ``ta.crossunder``."""

    return ((left < right) & (left.shift(1) >= right.shift(1))).fillna(False)


def _crossed(left: Series, right: Series) -> Series:
    """Return the equivalent of Pine's ``ta.cross``."""

    return (_crossed_above(left, right) | _crossed_below(left, right)).fillna(False)


def _true_range(dataframe: DataFrame) -> Series:
    """Calculate true range while retaining Pine's first-candle behavior."""

    previous_close = dataframe["close"].shift(1)
    ranges = pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous_close).abs(),
            (dataframe["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _rma(series: Series, length: int) -> Series:
    """Wilder's moving average with an SMA seed, like Pine's ``ta.rma``."""

    length = max(1, int(length))
    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    buffer: list[float] = []
    previous = np.nan

    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue

        if len(buffer) < length:
            buffer.append(float(value))
            if len(buffer) == length:
                previous = float(np.mean(buffer))
                result[index] = previous
            continue

        previous = previous + (float(value) - previous) / length
        result[index] = previous

    return pd.Series(result, index=series.index)


def _ema(series: Series, length: int) -> Series:
    return series.ewm(span=max(1, int(length)), adjust=False, min_periods=1).mean()


def _hann_window(series: Series, length: int) -> Series:
    """Port of the Pine Hann-window smoother used by ``atr()``."""

    length = max(1, int(length))
    result = pd.Series(0.0, index=series.index)
    coefficient = 0.0

    for offset in range(length):
        i = offset + 1
        weight = 1.0 - np.cos(2.0 * np.pi * i / (length + 1.0))
        result = result.add(series.shift(offset).fillna(0.0) * weight, fill_value=0.0)
        coefficient += weight

    if coefficient == 0:
        return pd.Series(0.0, index=series.index)
    return result / coefficient


def _rational_quadratic(
    series: Series, lookback: int, relative_weight: float, start_at_bar: int
) -> Series:
    """Port of jdehorty's rational quadratic kernel.

    ``array.from(_src)`` in the supplied library contains the current series
    value, so the Pine loop covers lags 0 through ``start_at_bar + 1``.
    """

    lookback = max(1, int(lookback))
    relative_weight = max(float(relative_weight), np.finfo(float).eps)
    start_at_bar = max(0, int(start_at_bar))

    numerator = pd.Series(0.0, index=series.index)
    valid = pd.Series(True, index=series.index)
    cumulative_weight = 0.0

    for offset in range(start_at_bar + 2):
        weight = (1.0 + (offset**2 / (lookback**2 * 2.0 * relative_weight))) ** (-relative_weight)
        shifted = series.shift(offset)
        numerator = numerator.add(shifted.fillna(0.0) * weight, fill_value=0.0)
        valid &= shifted.notna()
        cumulative_weight += weight

    result = numerator / cumulative_weight
    return result.where(valid)


def _t3(
    series: Series,
    periods: int | Series,
    hot: float = 1.0,
    clean: str = "T3",
) -> Series:
    """Port of the recursive T3 function in the Pine source."""

    values = series.to_numpy(dtype=float)
    if isinstance(periods, Series):
        period_values = periods.to_numpy(dtype=float)
    else:
        period_values = np.full(len(values), float(periods), dtype=float)

    a = float(hot)
    c1 = -a * a * a
    c2 = 3.0 * a * a + 3.0 * a * a * a
    c3 = -6.0 * a * a - 3.0 * a - 3.0 * a * a * a
    c4 = 1.0 + 3.0 * a + a * a * a + 3.0 * a * a

    result = np.full(len(values), np.nan, dtype=float)
    t30 = t31 = t32 = t33 = t34 = t35 = np.nan

    for index, value in enumerate(values):
        if not np.isfinite(value):
            t30 = t31 = t32 = t33 = t34 = t35 = np.nan
            continue

        period = period_values[index] if np.isfinite(period_values[index]) else 1.0
        period = max(1.0, period)
        if clean == "T3 New":
            alpha = 2.0 / (2.0 + (period - 1.0) / 2.0)
        else:
            alpha = 2.0 / (1.0 + period)

        previous_t30 = 0.0 if not np.isfinite(t30) else t30
        previous_t31 = 0.0 if not np.isfinite(t31) else t31
        previous_t32 = 0.0 if not np.isfinite(t32) else t32
        previous_t33 = 0.0 if not np.isfinite(t33) else t33
        previous_t34 = 0.0 if not np.isfinite(t34) else t34
        previous_t35 = 0.0 if not np.isfinite(t35) else t35

        t30 = previous_t30 + alpha * (value - previous_t30)
        t31 = previous_t31 + alpha * (t30 - previous_t31)
        t32 = previous_t32 + alpha * (t31 - previous_t32)
        t33 = previous_t33 + alpha * (t32 - previous_t33)
        t34 = previous_t34 + alpha * (t33 - previous_t34)
        t35 = previous_t35 + alpha * (t34 - previous_t35)
        result[index] = c1 * t35 + c2 * t34 + c3 * t33 + c4 * t32

    return pd.Series(result, index=series.index)


def _supertrend(dataframe: DataFrame, factor: float, period: int) -> tuple[Series, Series]:
    """Return TradingView-style supertrend and direction.

    The direction follows TradingView's convention: ``-1`` is uptrend and
    ``1`` is downtrend.  The second returned series is the signed trail used
    by the Pine script's ``nonVectorSupertrend`` helper.
    """

    period = max(1, int(period))
    atr = _rma(_true_range(dataframe), period)
    midpoint = (dataframe["high"] + dataframe["low"]) / 2.0
    upper = midpoint + float(factor) * atr
    lower = midpoint - float(factor) * atr

    upper_final = np.full(len(dataframe), np.nan, dtype=float)
    lower_final = np.full(len(dataframe), np.nan, dtype=float)
    direction = np.full(len(dataframe), 1.0, dtype=float)
    trail = np.full(len(dataframe), np.nan, dtype=float)
    closes = dataframe["close"].to_numpy(dtype=float)
    upper_values = upper.to_numpy(dtype=float)
    lower_values = lower.to_numpy(dtype=float)
    atr_values = atr.to_numpy(dtype=float)

    for index in range(len(dataframe)):
        if index == 0:
            upper_final[index] = upper_values[index]
            lower_final[index] = lower_values[index]
            direction[index] = 1.0
        else:
            previous_upper = upper_final[index - 1]
            previous_lower = lower_final[index - 1]
            previous_close = closes[index - 1]

            if (
                not np.isfinite(previous_lower)
                or not np.isfinite(lower_values[index])
                or lower_values[index] > previous_lower
                or previous_close < previous_lower
            ):
                lower_final[index] = lower_values[index]
            else:
                lower_final[index] = previous_lower

            if (
                not np.isfinite(previous_upper)
                or not np.isfinite(upper_values[index])
                or upper_values[index] < previous_upper
                or previous_close > previous_upper
            ):
                upper_final[index] = upper_values[index]
            else:
                upper_final[index] = previous_upper

            if not np.isfinite(atr_values[index - 1]):
                direction[index] = 1.0
            elif direction[index - 1] == 1.0:
                direction[index] = -1.0 if closes[index] > upper_final[index] else 1.0
            else:
                direction[index] = 1.0 if closes[index] < lower_final[index] else -1.0

        trail[index] = lower_final[index] if direction[index] == -1.0 else upper_final[index]

    trail_series = pd.Series(trail, index=dataframe.index)
    direction_series = pd.Series(direction, index=dataframe.index)
    return trail_series, trail_series * direction_series


def _resample_ohlcv(dataframe: DataFrame, timeframe: str, base_timeframe: str) -> DataFrame:
    """Resample completed candles and make each HTF candle available after close."""

    columns = ["open", "high", "low", "close", "volume"]
    source = dataframe.loc[:, [column for column in columns if column in dataframe]].copy()
    if "date" not in dataframe or not timeframe or timeframe == base_timeframe:
        return source

    try:
        timeframe_minutes = int(timeframe_to_minutes(timeframe))
        base_minutes = int(timeframe_to_minutes(base_timeframe))
    except (TypeError, ValueError):
        return source

    if timeframe_minutes <= base_minutes or "date" not in dataframe:
        return source

    source = dataframe.loc[:, ["date", *columns]].copy().sort_values("date")
    indexed = source.set_index("date")
    rule = f"{timeframe_minutes}min"
    aggregated = indexed.resample(rule, origin="start_day", label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    aggregated = aggregated.dropna(subset=["open", "high", "low", "close"])
    if aggregated.empty:
        return source.set_index(dataframe.index)[columns]

    available = aggregated.reset_index()
    available["date"] = available["date"] + pd.Timedelta(minutes=timeframe_minutes)

    left = source[["date"]].copy()
    left["_row"] = np.arange(len(left))
    merged = pd.merge_asof(
        left.sort_values("date"),
        available.sort_values("date"),
        on="date",
        direction="backward",
    )
    merged = merged.sort_values("_row").drop(columns=["_row", "date"])
    merged.index = dataframe.index
    return merged[columns]


class TrendOMaticStrategy(IStrategy):
    """Trend-O-Matic strategy translated to Freqtrade's strategy interface."""

    INTERFACE_VERSION = 3
    can_short = True

    timeframe = "5m"
    signal_timeframe = ""  # Empty means the strategy timeframe.
    wilders_timeframe = "15m"
    vix_timeframe = ""

    # Change this value to select one of the Pine script's trend engines.
    trend_mode = "VHF T3 iTrend"
    trend_modes = (
        "HPH's SuperKeltner",
        "Double Supertrend",
        "Nadaraya-Watson Envelope",
        "VHF T3 iTrend",
        "Wilders Volatility",
        "Vix Fix KC BB",
        "None",
    )

    # Pine strategy settings.
    order_size_percentage = 100.0
    add_percentage = 1.0
    reduce_percentage = 100.0
    commission_percentage = 0.075

    key_factor = 13.0
    key_factor_2 = 20.0
    is_htf_confirmation = False

    # Optional exits and position adjustments.
    enable_trailing_atr_stoploss = False
    trailing_atr_length = 5
    trailing_atr_multiplier = 1.5
    enable_triple_take_profit = False
    long_take_profit = 2.0
    long_take_profit_2 = 3.5
    long_take_profit_3 = 5.0
    take_profit_reduce_percentage = 10.0
    take_profit_2_reduce_percentage = 50.0
    take_profit_3_reduce_percentage = 40.0
    enable_high_low_exit = False
    high_low_risk_reward = 2.0
    high_low_lookback = 20
    enable_superkeltner_take_profit = False
    superkeltner_take_profit_atr_length = 10
    superkeltner_take_profit_multiplier = 2.2
    enable_superkeltner_adds = False
    superkeltner_adds_atr_length = 10
    superkeltner_adds_multiplier = 1.0
    sic_type = "High/Low"
    channel_mode = "Bollinger Bands"
    kc_band_style = "ATR"
    is_wvf_ma_enabled = False
    wvf_ma_length = 50

    # Optional high-volatility gate.  When enabled, entries only fire when
    # the current ATR sits in the top ``atr_percentile_threshold`` percent of
    # its recent ``atr_percentile_length``-bar window.
    enable_atr_percentile_filter = False
    atr_percentile_length = 50
    atr_percentile_threshold = 70.0
    atr_percentile_atr_length = 10

    # Freqtrade settings.  The Pine script has no fixed stoploss or ROI.
    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = True
    max_entry_position_adjustment = -1
    startup_candle_count = 500
    process_only_new_candles = True

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    plot_config = {
        "main_plot": {
            "tom_supertrend_1": {"color": "#90e2f4"},
            "tom_supertrend_2": {"color": "#f2a654"},
            "tom_hpk_basis": {"color": "#e8d7ff"},
            "tom_nw_yhat": {"color": "#abedc6"},
            "tom_trailing_long": {"color": "#68df99"},
            "tom_trailing_short": {"color": "#ef922e"},
        },
        "subplots": {
            "Trend": {
                "tom_itrend": {"color": "#b5a1e2"},
                "tom_wilders_ts": {"color": "#68df99"},
            },
            "Vix Fix": {
                "tom_wvf": {"color": "#f2a654"},
                "tom_vix_upper": {"color": "#ef922e"},
                "tom_vix_lower": {"color": "#68df99"},
            },
            "Volatility": {
                "tom_atr_rank": {"color": "#f2a654"},
            },
        },
    }

    def _source_ohlcv(self, dataframe: DataFrame, timeframe: str) -> DataFrame:
        selected_timeframe = timeframe or self.timeframe
        return _resample_ohlcv(dataframe, selected_timeframe, self.timeframe)

    def _parameter_value(self, name: str, fallback: Any) -> Any:
        """Read a hyperopt parameter when a mode-specific subclass defines one."""

        parameter = getattr(self, name, fallback)
        return getattr(parameter, "value", parameter)

    def _atr_percentile_rank(self, source: DataFrame) -> Series:
        """Return the rolling percentile rank (0..1) of the current ATR value.

        A rank near 1.0 means volatility is elevated relative to its recent
        history; near 0.0 means the market has gone quiet.
        """

        atr_length = max(1, int(self._parameter_value("atr_percentile_atr_length", 14)))
        window = max(10, int(self._parameter_value("atr_percentile_length", 100)))
        atr = _rma(_true_range(source), atr_length)
        return atr.rolling(window, min_periods=window).rank(pct=True)

    def _volatility_gate(self, dataframe: DataFrame) -> Series | None:
        """Return a boolean series allowing entries, or None when disabled."""

        if not bool(self._parameter_value("enable_atr_percentile_filter", False)):
            return None
        threshold = float(self._parameter_value("atr_percentile_threshold", 50.0)) / 100.0
        return dataframe["tom_atr_rank"].gt(threshold)

    @staticmethod
    def _previous_htf_values(source: DataFrame) -> DataFrame:
        """Return previous distinct candle values from an aligned HTF series."""

        candle_columns = ["open", "high", "low", "close"]
        changed = source[candle_columns].ne(source[candle_columns].shift(1)).any(axis=1)
        previous_low = source["low"].where(changed).shift(1).ffill()
        previous_close = source["close"].where(changed).shift(1).ffill()
        result = source.copy()
        result["low"] = previous_low
        result["close"] = previous_close
        return result

    @staticmethod
    def _initialize_signal_columns(dataframe: DataFrame) -> None:
        boolean_columns = [
            "tom_enter_long",
            "tom_enter_short",
            "tom_exit_long",
            "tom_exit_short",
            "tom_add_long",
            "tom_add_short",
            "tom_super_tp_long",
            "tom_super_tp_short",
            "tom_trailing_long_signal",
            "tom_trailing_short_signal",
        ]
        for column in boolean_columns:
            dataframe[column] = False

    @staticmethod
    def _double_supertrend_signals(
        source: DataFrame,
        trail: Series,
        direction_1: Series,
        direction_2: Series,
        diff_from_top: Series,
        diff_from_bottom: Series,
    ) -> tuple[Series, Series, Series, Series]:
        """Reproduce the Pine ``buy``/``sell`` gates for double supertrend."""

        close = source["close"]
        ohlc4 = (source["open"] + source["high"] + source["low"] + close) / 4.0
        previous_direction_1 = direction_1.shift(1)
        previous_direction_2 = direction_2.shift(1)
        cond_long = (
            (direction_1 < 0)
            & (direction_2 < 0)
            & ((previous_direction_1 > 0) | (previous_direction_2 > 0))
        )
        cond_short = (
            (direction_1 > 0)
            & (direction_2 > 0)
            & ((previous_direction_1 < 0) | (previous_direction_2 < 0))
        )

        long_entry = np.zeros(len(source), dtype=bool)
        short_entry = np.zeros(len(source), dtype=bool)
        long_exit = np.zeros(len(source), dtype=bool)
        short_exit = np.zeros(len(source), dtype=bool)
        buy = True
        sell = True
        trail_values = trail.to_numpy(dtype=float)
        low_values = source["low"].to_numpy(dtype=float)
        high_values = source["high"].to_numpy(dtype=float)
        close_values = close.to_numpy(dtype=float)
        ohlc_values = ohlc4.to_numpy(dtype=float)
        top_values = diff_from_top.to_numpy(dtype=float)
        bottom_values = diff_from_bottom.to_numpy(dtype=float)
        cond_long_values = cond_long.fillna(False).to_numpy(dtype=bool)
        cond_short_values = cond_short.fillna(False).to_numpy(dtype=bool)

        for index in range(len(source)):
            previous_ohlc = ohlc_values[index - 1] if index > 0 else np.nan
            previous_top = top_values[index - 1] if index > 0 else np.nan
            previous_bottom = bottom_values[index - 1] if index > 0 else np.nan
            top_exit = (
                np.isfinite(previous_ohlc)
                and np.isfinite(previous_top)
                and ohlc_values[index] <= top_values[index]
                and previous_ohlc > previous_top
            )
            bottom_exit = (
                np.isfinite(previous_ohlc)
                and np.isfinite(previous_bottom)
                and ohlc_values[index] >= bottom_values[index]
                and previous_ohlc < previous_bottom
            )
            long_exit[index] = top_exit and sell and not cond_long_values[index]
            # The supplied Pine source uses ``not condLong`` here as well.
            short_exit[index] = bottom_exit and buy and not cond_long_values[index]

            valid_trail = np.isfinite(trail_values[index])
            long_entry[index] = (cond_long_values[index] and buy) or (
                valid_trail
                and low_values[index] < trail_values[index]
                and close_values[index] > trail_values[index]
                and sell
                and not top_exit
            )
            short_entry[index] = (cond_short_values[index] and sell) or (
                valid_trail
                and high_values[index] > trail_values[index]
                and close_values[index] < trail_values[index]
                and buy
                and not bottom_exit
            )

            if cond_long_values[index] and buy:
                buy = False
                sell = True
            if cond_short_values[index] and sell:
                sell = False
                buy = True

        index = source.index
        return (
            pd.Series(long_entry, index=index),
            pd.Series(short_entry, index=index),
            pd.Series(long_exit, index=index),
            pd.Series(short_exit, index=index),
        )

    @staticmethod
    def _wilders_trail(source: DataFrame, atr_multiplier: float, atr_length: int, sic_type: str):
        true_range = _true_range(source)
        selected_low = source["close"] if sic_type == "close" else source["low"]
        selected_high = source["close"] if sic_type == "close" else source["high"]
        # getLowest/getHighest in the Pine source initialize at src[len] and
        # then iterate through src[0]..src[len], yielding len + 1 candles.
        upper_trail = selected_low.rolling(21, min_periods=1).min() + atr_multiplier * true_range
        lower_trail = selected_high.rolling(21, min_periods=1).max() - atr_multiplier * true_range

        closes = source["close"].to_numpy(dtype=float)
        upper_values = upper_trail.to_numpy(dtype=float)
        lower_values = lower_trail.to_numpy(dtype=float)
        raw = np.zeros(len(source), dtype=float)
        previous = 0.0
        for index in range(len(source)):
            if index > 0:
                if np.isfinite(closes[index]) and closes[index] < previous:
                    raw[index] = upper_values[index - 1]
                elif np.isfinite(closes[index]) and closes[index] > previous:
                    raw[index] = lower_values[index - 1]
                else:
                    raw[index] = previous
            previous = raw[index]

        trail = _t3(pd.Series(raw, index=source.index), atr_length, hot=0.5, clean="Normal")
        return trail

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:  # noqa: C901
        self._initialize_signal_columns(dataframe)
        source = self._source_ohlcv(dataframe, self.signal_timeframe)
        signal_close = source["close"]
        signal_high = source["high"]
        signal_low = source["low"]
        signal_ohlc4 = (source["open"] + source["high"] + source["low"] + source["close"]) / 4.0
        true_range = _true_range(source)

        dataframe["tom_signal_open"] = source["open"]
        dataframe["tom_signal_high"] = signal_high
        dataframe["tom_signal_low"] = signal_low
        dataframe["tom_signal_close"] = signal_close
        dataframe["tom_signal_close_previous"] = signal_close.shift(1)
        dataframe["tom_signal_ohlc4"] = signal_ohlc4

        mode = self.trend_mode
        if mode not in self.trend_modes:
            raise ValueError(f"Unknown trend_mode: {mode}")

        if mode == "Double Supertrend":
            factor_1 = float(self._parameter_value("double_factor_1", self.key_factor))
            factor_2 = float(self._parameter_value("double_factor_2", self.key_factor_2))
            atr_period = max(
                1,
                int(self._parameter_value("double_atr_period", 34)),
            )
            exit_length = max(
                4,
                int(self._parameter_value("double_exit_length", 200)),
            )
            quarter_length = max(1, exit_length // 4)
            trail_1, signed_1 = _supertrend(source, factor_1, atr_period)
            trail_2, signed_2 = _supertrend(source, factor_2, atr_period)
            direction_1 = signed_1.gt(0).astype(float).where(signed_1.notna(), np.nan)
            direction_1 = direction_1.where(direction_1.eq(1), -1.0)
            direction_2 = signed_2.gt(0).astype(float).where(signed_2.notna(), np.nan)
            direction_2 = direction_2.where(direction_2.eq(1), -1.0)
            highest_exit = signal_close.rolling(exit_length, min_periods=1).max()
            lowest_exit = signal_close.rolling(exit_length, min_periods=1).min()
            highest_quarter = signal_close.rolling(quarter_length, min_periods=1).max()
            lowest_quarter = signal_close.rolling(quarter_length, min_periods=1).min()
            diff_from_top = highest_exit - (highest_exit - lowest_quarter) / 2.0
            diff_from_bottom = lowest_exit + (highest_quarter - lowest_exit) / 2.0
            (
                dataframe["tom_enter_long"],
                dataframe["tom_enter_short"],
                dataframe["tom_exit_long"],
                dataframe["tom_exit_short"],
            ) = self._double_supertrend_signals(
                source,
                trail_1,
                direction_1,
                direction_2,
                diff_from_top,
                diff_from_bottom,
            )
            dataframe["tom_supertrend_1"] = trail_1
            dataframe["tom_supertrend_2"] = trail_2
            dataframe["tom_double_direction_1"] = direction_1
            dataframe["tom_double_direction_2"] = direction_2
        else:
            dataframe["tom_supertrend_1"] = np.nan
            dataframe["tom_supertrend_2"] = np.nan

        if mode == "HPH's SuperKeltner":
            supertrend_period = max(
                1,
                int(self._parameter_value("hpk_supertrend_period", round(self.key_factor))),
            )
            supertrend_factor = float(
                self._parameter_value("hpk_supertrend_factor", self.key_factor_2)
            )
            _, signed_supertrend = _supertrend(source, supertrend_factor, supertrend_period)
            direction = (
                signed_supertrend.gt(0).astype(float).where(signed_supertrend.notna(), np.nan)
            )
            direction = direction.where(direction.eq(1), -1.0)
            dataframe["tom_hpk_direction"] = direction
            dataframe["tom_hpk_basis"] = _ema(signal_close, 20)
            dataframe["tom_supertrend_1"] = signed_supertrend.abs()
            zero = pd.Series(0.0, index=direction.index)
            dataframe["tom_enter_long"] = _crossed_below(direction, zero)
            dataframe["tom_enter_short"] = _crossed_above(direction, zero)
            dataframe["tom_exit_long"] = _crossed_above(direction, zero)
            dataframe["tom_exit_short"] = _crossed_below(direction, zero)

        if mode == "Nadaraya-Watson Envelope":
            nw_lookback = max(1, int(self._parameter_value("nw_lookback", 8)))
            nw_relative_weight = float(self._parameter_value("nw_relative_weight", 8.0))
            nw_start_at_bar = max(0, int(self._parameter_value("nw_start_at_bar", 25)))
            nw_atr_length = max(1, int(self._parameter_value("nw_atr_length", 60)))
            nw_near_factor = float(self._parameter_value("nw_near_factor", 1.5))
            nw_far_factor = float(self._parameter_value("nw_far_factor", self.key_factor))
            yhat_close = _rational_quadratic(
                signal_close, nw_lookback, nw_relative_weight, nw_start_at_bar
            )
            yhat_high = _rational_quadratic(
                signal_high, nw_lookback, nw_relative_weight, nw_start_at_bar
            )
            yhat_low = _rational_quadratic(
                signal_low, nw_lookback, nw_relative_weight, nw_start_at_bar
            )
            kernel_range = DataFrame(
                {
                    "high": yhat_high,
                    "low": yhat_low,
                    "close": yhat_close,
                },
                index=dataframe.index,
            )
            kernel_atr = _rma(_true_range(kernel_range), nw_atr_length)
            upper_near = yhat_close + nw_near_factor * kernel_atr
            upper_far = yhat_close + nw_far_factor * kernel_atr
            lower_near = yhat_close - nw_near_factor * kernel_atr
            lower_far = yhat_close - nw_far_factor * kernel_atr
            dataframe["tom_nw_yhat"] = yhat_close
            dataframe["tom_nw_upper_near"] = upper_near
            dataframe["tom_nw_upper_far"] = upper_far
            dataframe["tom_nw_lower_near"] = lower_near
            dataframe["tom_nw_lower_far"] = lower_far
            dataframe["tom_enter_long"] = _crossed_below(signal_close, lower_far)
            dataframe["tom_enter_short"] = _crossed_above(signal_close, upper_far)
            dataframe["tom_exit_long"] = _crossed_above(signal_close, yhat_close)
            dataframe["tom_exit_short"] = _crossed_below(signal_close, yhat_close)

        if mode == "VHF T3 iTrend":
            itrend_length = max(
                2,
                int(self._parameter_value("itrend_length", round(self.key_factor))),
            )
            itrend_level_factor = float(self._parameter_value("itrend_level_factor", 0.8))
            highest_close = signal_close.rolling(itrend_length, min_periods=1).max()
            lowest_close = signal_close.rolling(itrend_length, min_periods=1).min()
            noise = signal_close.diff().abs().rolling(itrend_length, min_periods=1).sum()
            vhf = (highest_close - lowest_close) / noise.replace(0.0, np.nan)
            dynamic_length = (-np.log(vhf) * itrend_length).replace([np.inf, -np.inf], np.nan)
            dynamic_length = dynamic_length.fillna(1.0).astype(int).clip(lower=1)
            moving_value = _t3(signal_close, dynamic_length, hot=1.0, clean="T3")
            fill_up = signal_close - moving_value
            fill_down = -(signal_low + signal_high - 2.0 * moving_value)
            highest_fill = pd.concat([fill_up, fill_down], axis=1).max(axis=1).fillna(0.0)
            itrend = highest_fill.rolling(201, min_periods=1).max() * itrend_level_factor
            dataframe["tom_vhf"] = vhf
            dataframe["tom_itrend_ma"] = moving_value
            dataframe["tom_fill_up"] = fill_up
            dataframe["tom_fill_down"] = fill_down
            dataframe["tom_itrend"] = itrend
            dataframe["tom_enter_long"] = _crossed_above(fill_up, itrend)
            dataframe["tom_enter_short"] = _crossed_above(fill_down, itrend)
            dataframe["tom_exit_long"] = dataframe["tom_enter_short"]
            dataframe["tom_exit_short"] = dataframe["tom_enter_long"]

        if mode == "Wilders Volatility":
            wilders_source = self._source_ohlcv(dataframe, self.wilders_timeframe)
            wilders_source_previous = self._previous_htf_values(wilders_source)
            wilders_close = wilders_source_previous["close"]
            wilders_atr_multiplier = float(
                self._parameter_value("wilders_atr_multiplier", self.key_factor_2)
            )
            wilders_atr_length = max(
                1,
                int(self._parameter_value("wilders_atr_length", round(self.key_factor))),
            )
            wilders_sic_type = str(self._parameter_value("wilders_sic_type", self.sic_type))
            wilders_trail = self._wilders_trail(
                source,
                wilders_atr_multiplier,
                wilders_atr_length,
                wilders_sic_type,
            )
            htf_trail = self._wilders_trail(
                wilders_source_previous,
                wilders_atr_multiplier,
                wilders_atr_length,
                wilders_sic_type,
            )
            dataframe["tom_wilders_ts"] = htf_trail
            dataframe["tom_wilders_main_ts"] = wilders_trail
            enter_long = _crossed_above(wilders_close, htf_trail)
            enter_short = _crossed_below(wilders_close, htf_trail)
            if bool(self._parameter_value("wilders_htf_confirmation", self.is_htf_confirmation)):
                enter_long = _crossed_above(signal_close, wilders_trail) & (
                    wilders_close > htf_trail
                )
                enter_short = _crossed_below(signal_close, wilders_trail) & (
                    wilders_close < htf_trail
                )
            dataframe["tom_enter_long"] = enter_long
            dataframe["tom_enter_short"] = enter_short
            dataframe["tom_exit_long"] = enter_short
            dataframe["tom_exit_short"] = enter_long

        if mode == "Vix Fix KC BB":
            vix_source = self._source_ohlcv(dataframe, self.vix_timeframe)
            vix_close = vix_source["close"]
            vix_low = vix_source["low"]
            highest_vix_close = vix_close.rolling(22, min_periods=1).max()
            wvf = (highest_vix_close - vix_low) / highest_vix_close.replace(0.0, np.nan) * 100.0
            kc_length = max(1, int(self._parameter_value("vix_kc_length", round(self.key_factor))))
            vix_multiplier = float(self._parameter_value("vix_multiplier", self.key_factor_2))
            vix_channel_mode = str(self._parameter_value("vix_channel_mode", self.channel_mode))
            vix_band_style = str(self._parameter_value("vix_band_style", self.kc_band_style))
            vix_ma_enabled = bool(self._parameter_value("vix_ma_enabled", self.is_wvf_ma_enabled))
            vix_ma_length = max(
                1,
                int(self._parameter_value("vix_ma_length", self.wvf_ma_length)),
            )
            volume = vix_source["volume"].replace(0.0, np.nan)
            vwma_numerator = (wvf * volume).rolling(kc_length, min_periods=1).sum()
            vwma_denominator = volume.rolling(kc_length, min_periods=1).sum()
            basis = vwma_numerator / vwma_denominator
            deviation = wvf.rolling(kc_length, min_periods=1).std(ddof=0)
            channel_range = (
                _hann_window(true_range, kc_length)
                if vix_band_style == "ATR"
                else _rma(vix_source["high"] - vix_source["low"], kc_length)
            )
            upper = basis + deviation * vix_multiplier
            lower = basis - deviation * vix_multiplier
            # The original input is incorrectly typed as a timeframe, but its
            # options make the intended channel selection unambiguous.
            if vix_channel_mode == "Keltner Channels":
                upper = basis + channel_range * vix_multiplier
                lower = basis - channel_range * vix_multiplier
            vix_ma = (
                (wvf * volume).rolling(vix_ma_length, min_periods=1).sum()
                / volume.rolling(vix_ma_length, min_periods=1).sum()
                if vix_ma_enabled
                else pd.Series(np.nan, index=dataframe.index)
            )
            long_filter = vix_ma.isna() | (wvf < vix_ma)
            short_filter = vix_ma.isna() | (wvf > vix_ma)
            dataframe["tom_wvf"] = wvf
            dataframe["tom_vix_basis"] = basis
            dataframe["tom_vix_upper"] = upper
            dataframe["tom_vix_lower"] = lower
            dataframe["tom_vix_ma"] = vix_ma
            dataframe["tom_enter_long"] = _crossed_below(wvf, upper) & long_filter
            dataframe["tom_enter_short"] = _crossed_above(wvf, lower) & short_filter
            dataframe["tom_exit_long"] = dataframe["tom_enter_long"]
            dataframe["tom_exit_short"] = dataframe["tom_enter_short"]

        # SuperKeltner TP/add bands are calculated even when SuperKeltner is
        # not the selected trend, because they are independent optional exits.
        hpk_basis = _ema(signal_close, 20)
        if self.enable_superkeltner_take_profit:
            tp_range = _hann_window(true_range, self.superkeltner_take_profit_atr_length)
            tp_range = tp_range * self.superkeltner_take_profit_multiplier
            upper_tp = hpk_basis + tp_range
            lower_tp = hpk_basis - tp_range
            dataframe["tom_hpk_upper_tp"] = upper_tp
            dataframe["tom_hpk_lower_tp"] = lower_tp
            dataframe["tom_super_tp_long"] = (
                (signal_close.shift(1) > upper_tp.shift(1)) & (signal_close < upper_tp)
            ).fillna(False)
            dataframe["tom_super_tp_short"] = (
                (signal_close.shift(1) < lower_tp.shift(1)) & (signal_close > lower_tp)
            ).fillna(False)
        else:
            dataframe["tom_hpk_upper_tp"] = np.nan
            dataframe["tom_hpk_lower_tp"] = np.nan

        if self.enable_superkeltner_adds:
            add_range = _hann_window(true_range, self.superkeltner_adds_atr_length)
            add_range = add_range * self.superkeltner_adds_multiplier
            upper_add = hpk_basis + add_range
            lower_add = hpk_basis - add_range
            dataframe["tom_hpk_upper_add"] = upper_add
            dataframe["tom_hpk_lower_add"] = lower_add
            dataframe["tom_add_long"] = (
                (signal_close.shift(1) < lower_add.shift(1)) & (signal_close > lower_add)
            ).fillna(False)
            dataframe["tom_add_short"] = (
                (signal_close.shift(1) > upper_add.shift(1)) & (signal_close < upper_add)
            ).fillna(False)
        else:
            dataframe["tom_hpk_upper_add"] = np.nan
            dataframe["tom_hpk_lower_add"] = np.nan

        dataframe["tom_atr_rank"] = self._atr_percentile_rank(source)

        if self.enable_trailing_atr_stoploss:
            trailing_atr = (
                _hann_window(true_range, self.trailing_atr_length) * self.trailing_atr_multiplier
            )
            long_stop = (signal_ohlc4 - trailing_atr).rolling(10, min_periods=1).min().shift(1)
            short_stop = (signal_ohlc4 + trailing_atr).rolling(10, min_periods=1).max().shift(1)
            dataframe["tom_trailing_long"] = long_stop
            dataframe["tom_trailing_short"] = short_stop
            dataframe["tom_trailing_long_signal"] = _crossed_below(signal_close, long_stop)
            dataframe["tom_trailing_short_signal"] = _crossed_above(signal_close, short_stop)
        else:
            dataframe["tom_trailing_long"] = np.nan
            dataframe["tom_trailing_short"] = np.nan

        if self.enable_high_low_exit:
            lookback = max(1, int(self.high_low_lookback))
            lowest = signal_low.rolling(lookback, min_periods=1).min()
            highest = signal_high.rolling(lookback, min_periods=1).max()
            dataframe["tom_high_low_stop_long"] = np.where(
                lowest.eq(signal_low), signal_high * 0.98, lowest
            )
            dataframe["tom_high_low_stop_short"] = np.where(
                highest.eq(signal_high), signal_high * 1.02, highest
            )
        else:
            dataframe["tom_high_low_stop_long"] = np.nan
            dataframe["tom_high_low_stop_short"] = np.nan

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None
        long_condition = dataframe["tom_enter_long"].fillna(False)
        short_condition = dataframe["tom_enter_short"].fillna(False)
        volatility_gate = self._volatility_gate(dataframe)
        if volatility_gate is not None:
            long_condition = long_condition & volatility_gate
            short_condition = short_condition & volatility_gate
        dataframe.loc[long_condition, "enter_long"] = 1
        dataframe.loc[short_condition, "enter_short"] = 1
        dataframe.loc[long_condition, "enter_tag"] = f"trend_long_{self.trend_mode}"
        dataframe.loc[short_condition, "enter_tag"] = f"trend_short_{self.trend_mode}"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        long_condition = dataframe["tom_exit_long"].fillna(False)
        short_condition = dataframe["tom_exit_short"].fillna(False)
        dataframe.loc[long_condition, "exit_long"] = 1
        dataframe.loc[short_condition, "exit_short"] = 1
        dataframe.loc[long_condition, "exit_tag"] = f"trend_exit_long_{self.trend_mode}"
        dataframe.loc[short_condition, "exit_tag"] = f"trend_exit_short_{self.trend_mode}"
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        """Reserve the requested fraction of the wallet for the initial order."""

        stake = proposed_stake * self.order_size_percentage / 100.0
        return max(0.0, min(stake, max_stake))

    def _last_candle(self, pair: str) -> tuple[DataFrame, Any] | None:
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        return dataframe, dataframe.iloc[-1]

    @staticmethod
    def _set_trade_data(trade: Trade, key: str, value: Any) -> None:
        try:
            trade.set_custom_data(key, value)
        except Exception:
            logger.debug("Unable to persist Trend-O-Matic trade data %s", key, exc_info=True)

    @staticmethod
    def _get_trade_data(trade: Trade, key: str, default: Any = None) -> Any:
        return trade.get_custom_data(key, default)

    def _trade_reference_price(self, trade: Trade) -> float:
        reference = self._get_trade_data(trade, "tom_reference_entry_price")
        if reference is None:
            reference = trade.open_rate
        try:
            return float(reference)
        except (TypeError, ValueError):
            return 0.0

    def _trade_levels(self, trade: Trade, candle: Any) -> dict[str, float] | None:
        if not self.enable_high_low_exit:
            return None
        existing = self._get_trade_data(trade, "tom_high_low_levels")
        if isinstance(existing, dict) and "stop" in existing and "target" in existing:
            return {"stop": float(existing["stop"]), "target": float(existing["target"])}

        reference = self._trade_reference_price(trade)
        if reference <= 0:
            return None
        stop_column = "tom_high_low_stop_short" if trade.is_short else "tom_high_low_stop_long"
        stop = candle.get(stop_column, np.nan)
        if not np.isfinite(stop):
            return None
        risk = abs(reference - float(stop))
        target = (
            reference - self.high_low_risk_reward * risk
            if trade.is_short
            else reference + self.high_low_risk_reward * risk
        )
        levels = {"stop": float(stop), "target": float(target)}
        self._set_trade_data(trade, "tom_high_low_levels", levels)
        return levels

    def _mark_adjustment(self, trade: Trade, candle: Any) -> None:
        date = candle.get("date", "")
        self._set_trade_data(trade, "tom_last_adjustment", str(date))

    def _cooldown_elapsed(self, last_date: Any, current_date: Any, bars: int) -> bool:
        if not last_date:
            return True
        try:
            elapsed = pd.Timestamp(current_date) - pd.Timestamp(last_date)
            return elapsed >= pd.Timedelta(minutes=timeframe_to_minutes(self.timeframe) * bars)
        except (TypeError, ValueError):
            return True

    def _partial_take_profit(self, trade: Trade, candle: Any) -> tuple[float, str] | None:
        if not self.enable_triple_take_profit:
            return None

        try:
            stage = int(self._get_trade_data(trade, "tom_tp_stage", 0))
        except (TypeError, ValueError):
            stage = 0
        if stage >= 3:
            return None

        reference = self._trade_reference_price(trade)
        close = candle.get("tom_signal_close", np.nan)
        previous_close = candle.get("tom_signal_close_previous", np.nan)
        if reference <= 0 or not np.isfinite(close) or not np.isfinite(previous_close):
            return None

        if trade.is_short:
            targets = [
                reference * (1.0 - self.long_take_profit / 100.0),
                reference * (1.0 - self.long_take_profit_2 / 100.0),
                reference * (1.0 - self.long_take_profit_3 / 100.0),
            ]
            crossed = [previous_close >= target and close < target for target in targets]
        else:
            targets = [
                reference * (1.0 + self.long_take_profit / 100.0),
                reference * (1.0 + self.long_take_profit_2 / 100.0),
                reference * (1.0 + self.long_take_profit_3 / 100.0),
            ]
            crossed = [previous_close <= target and close > target for target in targets]

        hit = [index for index in range(stage, 3) if crossed[index]]
        if not hit:
            return None

        reductions = [
            self.take_profit_reduce_percentage,
            self.take_profit_2_reduce_percentage,
            self.take_profit_3_reduce_percentage,
        ]
        reduction_percentage = min(100.0, sum(reductions[index] for index in hit))
        current_stake = float(trade.stake_amount)
        initial_stake = self._get_trade_data(trade, "tom_initial_stake")
        add_stakes = self._get_trade_data(trade, "tom_add_stakes", [])
        try:
            initial_stake = float(initial_stake)
            add_stakes = [float(value) for value in add_stakes]
            base_remaining = float(self._get_trade_data(trade, "tom_base_remaining", initial_stake))
            reduction = base_remaining * reduction_percentage / 100.0
            reduction += sum(add_stakes) * reduction_percentage / 100.0
        except (TypeError, ValueError):
            reduction = current_stake * reduction_percentage / 100.0

        reduction = min(current_stake, max(0.0, reduction))
        if reduction <= 0:
            return None
        tag = "_".join(f"tp{index + 1}" for index in hit)
        return -reduction, tag

    def adjust_trade_position(  # noqa: C901
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs: Any,
    ) -> float | tuple[float | None, str | None] | None:
        """Implement Pine pyramiding and partial reductions safely per candle."""

        if trade.has_open_orders:
            return None
        candle_data = self._last_candle(trade.pair)
        if candle_data is None:
            return None
        _, candle = candle_data
        candle_date = str(candle.get("date", current_time))
        if self._get_trade_data(trade, "tom_last_adjustment") == candle_date:
            return None

        # Pine's main exit branch has precedence over adds and reductions.
        if bool(candle.get("exit_short" if trade.is_short else "exit_long", 0)):
            return None

        reference = self._trade_reference_price(trade)
        close = candle.get("tom_signal_close", current_rate)

        if self.enable_superkeltner_adds:
            can_add = trade.nr_of_successful_entries
            if self.max_entry_position_adjustment >= 0:
                can_add = can_add <= self.max_entry_position_adjustment
            add_signal = bool(
                candle.get("tom_add_short" if trade.is_short else "tom_add_long", False)
            )
            favorable = close < reference if trade.is_short else close > reference
            last_add = self._get_trade_data(trade, "tom_last_add")
            if (
                can_add
                and add_signal
                and favorable
                and self._cooldown_elapsed(last_add, candle_date, 10)
                and np.isfinite(max_stake)
            ):
                stake = max_stake * self.add_percentage / 100.0
                if stake > 0 and (min_stake is None or stake >= min_stake):
                    self._mark_adjustment(trade, candle)
                    self._set_trade_data(trade, "tom_last_add", candle_date)
                    return stake, "superkeltner_add"

        partial = self._partial_take_profit(trade, candle)
        if partial is not None:
            self._mark_adjustment(trade, candle)
            return partial

        if self.enable_superkeltner_take_profit:
            signal_column = "tom_super_tp_short" if trade.is_short else "tom_super_tp_long"
            favorable = close < reference if trade.is_short else close > reference
            last_super_tp = self._get_trade_data(trade, "tom_last_super_tp")
            if (
                bool(candle.get(signal_column, False))
                and favorable
                and self._cooldown_elapsed(last_super_tp, candle_date, 10)
            ):
                stake = float(trade.stake_amount) * self.reduce_percentage / 100.0
                stake = min(float(trade.stake_amount), max(0.0, stake))
                if stake > 0:
                    self._mark_adjustment(trade, candle)
                    self._set_trade_data(trade, "tom_last_super_tp", candle_date)
                    return -stake, "superkeltner_tp"

        trailing_column = (
            "tom_trailing_short_signal" if trade.is_short else "tom_trailing_long_signal"
        )
        if self.enable_trailing_atr_stoploss and bool(candle.get(trailing_column, False)):
            stake = float(trade.stake_amount) * self.reduce_percentage / 100.0
            stake = min(float(trade.stake_amount), max(0.0, stake))
            if stake > 0:
                self._mark_adjustment(trade, candle)
                return -stake, "trailing_atr"

        return None

    def _risk_config(self) -> SlTpConfig:
        """High/low bracket via the shared strategy_lib.risk engine.

        Reproduces the Pine ``calculateHighLowSltp`` locked structure used by the
        optional high/low exit: normal stop at the lookback low/high (multiplier
        1.0), a backup level when the current candle prints a new extreme, and a
        target locked at entry from the entry-to-stop risk * R:R.
        """
        return SlTpConfig(
            mode="Highest Lowest",
            risk_reward_ratio=float(self.high_low_risk_reward),
            my_backup_multiplier=0.98,
            high_low_stop_loss_lookback=max(1, int(self.high_low_lookback)),
            high_low_stop_loss_multiplier=1.0,
            enable_take_profit=True,
        )

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool = False,
        **kwargs: Any,
    ) -> float | None:
        """Expose the optional high/low stop as a Freqtrade-compatible distance."""

        if not self.enable_high_low_exit or current_rate <= 0:
            return None
        config = self._risk_config()
        manager = getattr(self, "_risk_manager", None)
        if manager is None:
            manager = TradeLevelsManager(config)
            self._risk_manager = manager
        else:
            manager.config = config
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        levels = manager.current_trade_levels(pair, dataframe, trade, self.timeframe)
        if levels is None:
            return None
        stop = levels["short_stop"] if trade.is_short else levels["long_stop"]
        if not np.isfinite(stop) or stop <= 0.0:
            return None
        return stoploss_from_absolute(stop, current_rate, trade.is_short, trade.leverage)

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | None:
        """Handle the optional automatic high/low risk-reward target."""

        if not self.enable_high_low_exit or current_rate <= 0:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 2:
            return None

        current_index = len(dataframe) - 1
        previous_index = current_index - 1
        config = self._risk_config()
        manager = getattr(self, "_risk_manager", None)
        if manager is None:
            manager = TradeLevelsManager(config)
            self._risk_manager = manager
        else:
            manager.config = config
        levels = manager.cached_trade_level_series(pair, dataframe, trade, self.timeframe)
        if levels is None:
            return None
        entry_index = int(levels["entry_index"][0])
        if current_index <= entry_index:
            return None
        previous_levels = sl_risk.levels_at(levels, previous_index)
        current_levels = sl_risk.levels_at(levels, current_index)

        previous_close = float(dataframe["close"].iloc[previous_index])
        current_close = float(dataframe["close"].iloc[current_index])
        return sl_risk.exit_cross_signal(
            previous_close,
            current_close,
            previous_levels,
            current_levels,
            trade.is_short,
        )

    def order_filled(  # noqa: C901
        self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs: Any
    ) -> None:
        """Advance TP/DCA state only after Freqtrade confirms an order fill."""

        if order.ft_order_side == trade.entry_side:
            if trade.nr_of_successful_entries == 1:
                self._set_trade_data(trade, "tom_reference_entry_price", float(order.safe_price))
                self._set_trade_data(trade, "tom_initial_stake", float(order.stake_amount_filled))
                self._set_trade_data(trade, "tom_base_remaining", float(order.stake_amount_filled))
                self._set_trade_data(trade, "tom_add_stakes", [])
                self._set_trade_data(trade, "tom_tp_stage", 0)
                candle_data = self._last_candle(pair)
                if candle_data is not None:
                    self._trade_levels(trade, candle_data[1])
            elif order.ft_order_tag == "superkeltner_add":
                add_stakes = self._get_trade_data(trade, "tom_add_stakes", [])
                if not isinstance(add_stakes, list):
                    add_stakes = []
                add_stakes.append(float(order.stake_amount_filled))
                self._set_trade_data(trade, "tom_add_stakes", add_stakes)
            return

        if order.ft_order_side != trade.exit_side:
            return

        tag = str(order.ft_order_tag or "")
        if tag.startswith("tp"):
            parts = tag.split("_")
            hit = []
            for part in parts:
                if part.startswith("tp"):
                    try:
                        hit.append(int(part[2:]))
                    except ValueError:
                        continue
            if hit:
                stage = max(int(self._get_trade_data(trade, "tom_tp_stage", 0)), max(hit))
                self._set_trade_data(trade, "tom_tp_stage", stage)
                reductions = {
                    1: self.take_profit_reduce_percentage,
                    2: self.take_profit_2_reduce_percentage,
                    3: self.take_profit_3_reduce_percentage,
                }
                reduction_percentage = min(100.0, sum(reductions[index] for index in hit))
                initial_stake = float(
                    self._get_trade_data(trade, "tom_initial_stake", trade.stake_amount)
                )
                base_remaining = float(
                    self._get_trade_data(trade, "tom_base_remaining", initial_stake)
                )
                add_stakes = self._get_trade_data(trade, "tom_add_stakes", [])
                self._set_trade_data(
                    trade,
                    "tom_base_remaining",
                    max(0.0, base_remaining - initial_stake * reduction_percentage / 100.0),
                )
                if isinstance(add_stakes, list):
                    self._set_trade_data(
                        trade,
                        "tom_add_stakes",
                        [
                            max(0.0, float(stake) * (1.0 - reduction_percentage / 100.0))
                            for stake in add_stakes
                        ],
                    )


class TrendOMaticHPHSuperKeltnerStrategy(TrendOMaticStrategy):
    """HPH SuperKeltner mode using the shared Trend-O-Matic implementation."""

    trend_mode = "HPH's SuperKeltner"
    hpk_supertrend_period = IntParameter(
        low=5, high=40, default=13, space="buy", optimize=True, load=True
    )
    hpk_supertrend_factor = DecimalParameter(
        low=5.0,
        high=30.0,
        decimals=1,
        default=20.0,
        space="buy",
        optimize=True,
        load=True,
    )


class TrendOMaticDoubleSupertrendStrategy(TrendOMaticStrategy):
    """Double Supertrend mode using the shared Trend-O-Matic implementation."""

    trend_mode = "Double Supertrend"
    double_factor_1 = DecimalParameter(
        low=1.0,
        high=30.0,
        decimals=1,
        default=13.0,
        space="buy",
        optimize=True,
        load=True,
    )
    double_factor_2 = DecimalParameter(
        low=1.0,
        high=40.0,
        decimals=1,
        default=20.0,
        space="buy",
        optimize=True,
        load=True,
    )
    double_atr_period = IntParameter(
        low=5, high=80, default=34, space="buy", optimize=True, load=True
    )
    double_exit_length = IntParameter(
        low=100, high=400, default=200, space="sell", optimize=True, load=True
    )


class TrendOMaticNadarayaStrategy(TrendOMaticStrategy):
    """Nadaraya-Watson mode using the shared Trend-O-Matic implementation."""

    trend_mode = "Nadaraya-Watson Envelope"
    nw_lookback = IntParameter(low=4, high=20, default=8, space="buy", optimize=True, load=True)
    nw_relative_weight = DecimalParameter(
        low=1.0,
        high=20.0,
        decimals=1,
        default=8.0,
        space="buy",
        optimize=True,
        load=True,
    )
    nw_start_at_bar = IntParameter(
        low=10, high=50, default=25, space="buy", optimize=True, load=True
    )
    nw_atr_length = IntParameter(
        low=20, high=100, default=60, space="buy", optimize=True, load=True
    )
    nw_near_factor = DecimalParameter(
        low=0.5,
        high=3.0,
        decimals=2,
        default=1.5,
        space="buy",
        optimize=True,
        load=True,
    )
    nw_far_factor = DecimalParameter(
        low=4.0,
        high=20.0,
        decimals=1,
        default=13.0,
        space="buy",
        optimize=True,
        load=True,
    )
    enable_atr_percentile_filter = BooleanParameter(
        default=True,
        space="buy",
        optimize=True,
        load=True,
    )
    atr_percentile_length = IntParameter(
        low=30, high=300, default=50, space="buy", optimize=True, load=True
    )
    atr_percentile_threshold = DecimalParameter(
        low=10.0,
        high=90.0,
        decimals=0,
        default=70.0,
        space="buy",
        optimize=True,
        load=True,
    )
    atr_percentile_atr_length = IntParameter(
        low=5, high=50, default=10, space="buy", optimize=True, load=True
    )


class TrendOMaticVHFStrategy(TrendOMaticStrategy):
    """VHF T3 iTrend mode with its first hyperoptable parameter space."""

    trend_mode = "VHF T3 iTrend"

    # Run hyperopt with ``--spaces buy`` and ``--analyze-per-epoch`` because
    # these values change recursive indicator calculations.
    itrend_length = IntParameter(low=5, high=60, default=13, space="buy", optimize=True, load=True)
    itrend_level_factor = DecimalParameter(
        low=0.4,
        high=1.2,
        decimals=2,
        default=0.8,
        space="buy",
        optimize=True,
        load=True,
    )


class TrendOMaticWildersStrategy(TrendOMaticStrategy):
    """Wilders Volatility mode using the shared Trend-O-Matic implementation."""

    trend_mode = "Wilders Volatility"
    wilders_atr_multiplier = DecimalParameter(
        low=5.0,
        high=30.0,
        decimals=1,
        default=20.0,
        space="buy",
        optimize=True,
        load=True,
    )
    wilders_atr_length = IntParameter(
        low=5, high=50, default=13, space="buy", optimize=True, load=True
    )
    wilders_sic_type = CategoricalParameter(
        ["close", "High/Low"],
        default="High/Low",
        space="buy",
        optimize=True,
        load=True,
    )
    wilders_htf_confirmation = BooleanParameter(
        default=False,
        space="buy",
        optimize=True,
        load=True,
    )


class TrendOMaticVixFixStrategy(TrendOMaticStrategy):
    """Vix Fix KC/BB mode using the shared Trend-O-Matic implementation."""

    trend_mode = "Vix Fix KC BB"
    vix_kc_length = IntParameter(low=5, high=50, default=13, space="buy", optimize=True, load=True)
    vix_multiplier = DecimalParameter(
        low=5.0,
        high=30.0,
        decimals=1,
        default=20.0,
        space="buy",
        optimize=True,
        load=True,
    )
    vix_channel_mode = CategoricalParameter(
        ["Bollinger Bands", "Keltner Channels"],
        default="Bollinger Bands",
        space="buy",
        optimize=True,
        load=True,
    )
    vix_band_style = CategoricalParameter(
        ["ATR", "RMA"],
        default="ATR",
        space="buy",
        optimize=True,
        load=True,
    )
    vix_ma_enabled = BooleanParameter(
        default=False,
        space="buy",
        optimize=True,
        load=True,
    )
    vix_ma_length = IntParameter(
        low=20, high=100, default=50, space="buy", optimize=True, load=True
    )


class TrendOMaticNoTrendStrategy(TrendOMaticStrategy):
    """Explicit no-trend mode, useful for validating configuration behavior."""

    trend_mode = "None"
