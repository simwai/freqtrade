"""
strategy_lib.indicators

Vectorized / reusable indicator primitives for Freqtrade strategies.

All functions in this module are pure numpy helpers (no strategy state), so they
can be imported and reused across any number of strategies. Functions that need
Freqtrade's dataprovider (higher-timeframe merges) are kept free of strategy
state too and take the dataprovider as an explicit argument.

The hot paths were ported from OctopusNestStrategy (TradingView "Octopus Nest"
by simwai, CC BY-NC-SA 4.0). `hann_atr` is fully vectorized via a convolution;
`classic_psar` and `adaptive_psar` are inherently sequential (the value at each
bar depends on the previous bar's state) and keep a tight numpy loop.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.exchange.exchange_utils_timeframe import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import merge_informative_pair


try:
    import numba

    _HAS_NUMBA = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_NUMBA = False

# Ceiling for the stochastic-range low clamp in the Pine port (values at or
# above this are treated as "no range").
_STOCH_RANGE_CEILING = 1_000_000_000.0


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Wilder true range. The first bar's previous close is treated as 0.0."""
    previous_close = np.roll(close, 1)
    previous_close[0] = 0.0
    return np.maximum.reduce(
        [high - low, np.abs(high - previous_close), np.abs(low - previous_close)]
    )


def hann_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """
    Hann-window ATR used by the Octopus Nest source.

    Equivalent to the Pine reference: a weighted moving average of the true
    range where the newest sample uses the first Hann coefficient. Vectorized
    as a convolution (result[i] == dot(tr[i-available+1:i+1], w[:available][::-1])
    for every bar, including the warm-up region).
    """
    tr = true_range(high, low, close)
    weights = 1.0 - np.cos(2.0 * np.pi * np.arange(1, length + 1) / (length + 1))
    coefficient = float(weights.sum())
    return np.convolve(tr, weights)[: len(tr)] / coefficient


def classic_psar(
    high: np.ndarray, low: np.ndarray, start: float, increment: float, maximum: float
) -> np.ndarray:
    """
    Three-parameter Parabolic SAR equivalent to TradingView's ``ta.sar``.

    Sequential state machine (the SAR at each bar depends on the previous
    bar's trend / extreme / acceleration), so a tight numpy loop is used. When
    numba is installed the core is JIT-compiled (30-50x speedup) with an
    identical pure-Python fallback.
    """
    return _classic_psar_core(
        np.asarray(high, dtype=np.float64),
        np.asarray(low, dtype=np.float64),
        float(start),
        float(increment),
        float(maximum),
    )


def _classic_psar_core(
    high: np.ndarray, low: np.ndarray, start: float, increment: float, maximum: float
) -> np.ndarray:
    """numba-compatible PSAR core (no pandas, plain numpy + scalars)."""
    result = np.full(len(high), np.nan, dtype=np.float64)
    n = len(high)
    if n == 0:
        return result

    rising = True
    acceleration = start
    extreme_point = high[0]
    result[0] = low[0]

    for index in range(1, n):
        previous_sar = result[index - 1]
        sar = previous_sar + acceleration * (extreme_point - previous_sar)

        if rising:
            sar = min(sar, low[index - 1])
            if index > 1:
                sar = min(sar, low[index - 2])
            if low[index] < sar:
                rising = False
                sar = extreme_point
                extreme_point = low[index]
                acceleration = start
            elif high[index] > extreme_point:
                extreme_point = high[index]
                acceleration = min(maximum, acceleration + increment)
        else:
            sar = max(sar, high[index - 1])
            if index > 1:
                sar = max(sar, high[index - 2])
            if high[index] > sar:
                rising = True
                sar = extreme_point
                extreme_point = high[index]
                acceleration = start
            elif low[index] < extreme_point:
                extreme_point = low[index]
                acceleration = min(maximum, acceleration + increment)

        result[index] = sar

    return result


if _HAS_NUMBA:
    _classic_psar_core = numba.njit(cache=True, nogil=True)(_classic_psar_core)


def adaptive_psar(  # noqa: C901
    high: np.ndarray,
    low: np.ndarray,
    source: np.ndarray,
    base_unit: float,
    *,
    start_a_factor: float,
    min_step: float,
    max_step: float,
    max_a_factor: float,
    adapt_smooth: int,
    adapt_mode: str,
    hilo_mode: str,
    flip_filter: float,
    min_change: float,
) -> np.ndarray:
    """
    Adaptive PSAR state machine ported from the Octopus Nest Pine strategy.

    ``adapt_mode`` is ``"Kaufman"`` (efficiency-ratio based) or anything else
    (Stochastic-style normalized range). ``hilo_mode`` only affects the source
    fed into the efficiency computation (both branches use the same input in
    the original Pine code; kept for compatibility).
    """
    n = len(high)
    length = max(1, math.ceil(2.0 / max(max_a_factor, 1e-9) - 1.0))
    efficiency_length = length if adapt_mode == "Kaufman" else max(20, math.ceil(5.0 * length))

    input_values = np.asarray(source, dtype=float).copy()

    raw_efficiency = np.zeros(n, dtype=float)
    if adapt_mode == "Kaufman":
        # Vectorized over the original per-bar difference window: denominator is
        # the sum of |x[i-k] - x[i-k-1]| for k in 0..efficiency_length. Window
        # sums may associate additions differently than the naive Python loop,
        # which can shift results by floating point ULPs only.
        input_diffs = np.abs(np.diff(input_values))
        diff_window = efficiency_length + 1
        if n > diff_window:
            window_sums = np.lib.stride_tricks.sliding_window_view(input_diffs, diff_window).sum(
                axis=1
            )
            indices = np.arange(diff_window, n)
            denominators = window_sums[indices - diff_window]
            numerators = np.abs(input_values[indices] - input_values[indices - efficiency_length])
            usable = denominators > 0
            raw_efficiency[indices[usable]] = numerators[usable] / denominators[usable]
    else:
        source_series = pd.Series(input_values)
        rolling_high = source_series.rolling(efficiency_length + 1).max().to_numpy(dtype=float)
        rolling_low = source_series.rolling(efficiency_length + 1).min().to_numpy(dtype=float)
        indices = np.arange(efficiency_length, n)
        high_values = np.maximum(rolling_high[indices], 0.0)
        low_values = np.minimum(rolling_low[indices], _STOCH_RANGE_CEILING)
        spans = high_values - low_values
        usable = spans > 0
        raw_efficiency[indices[usable]] = (input_values[indices] - low_values)[usable] / spans[
            usable
        ]

    alpha = 2.0 / (max(1, adapt_smooth) + 1.0)
    smoothed_efficiency = np.zeros(n, dtype=float)
    for index, value in enumerate(raw_efficiency):
        smoothed_efficiency[index] = (
            value
            if index == 0
            else (alpha * value + (1.0 - alpha) * smoothed_efficiency[index - 1])
        )

    trend = np.zeros(n, dtype=int)
    acceleration_factors = np.zeros(n, dtype=float)
    up_sar = np.zeros(n, dtype=float)
    down_sar = np.zeros(n, dtype=float)

    for index in range(n):
        if index == 1:
            trend[index] = 1
            acceleration_factors[index] = start_a_factor
            up_sar[index] = min(low[index], low[index - 1])
            continue
        if index == 0:
            continue

        previous_trend = trend[index - 1]
        previous_previous_trend = trend[index - 2]
        acceleration = acceleration_factors[index - 1]
        high_value_1 = high[index - 1]
        high_value_2 = high[index - 2] if index > 1 else high_value_1
        low_value_1 = low[index - 1]
        low_value_2 = low[index - 2] if index > 1 else low_value_1
        step = min_step + smoothed_efficiency[index] * (max_step - min_step)

        trend[index] = previous_trend
        if previous_trend > 0:
            if previous_trend == previous_previous_trend:
                if high_value_1 > high_value_2:
                    acceleration += step
                acceleration = min(acceleration, max_a_factor)
                if high_value_1 < high_value_2:
                    acceleration = start_a_factor
            up_sar[index] = up_sar[index - 1] + acceleration * (high_value_1 - up_sar[index - 1])
            up_sar[index] = min(up_sar[index], low_value_1, low_value_2)
        elif previous_trend < 0:
            if previous_trend == previous_previous_trend:
                if low_value_1 < low_value_2:
                    acceleration += step
                acceleration = min(acceleration, max_a_factor)
                if low_value_1 > low_value_2:
                    acceleration = start_a_factor
            down_sar[index] = down_sar[index - 1] + acceleration * (
                low_value_1 - down_sar[index - 1]
            )
            down_sar[index] = max(down_sar[index], high_value_1, high_value_2)

        acceleration_factors[index] = acceleration
        high_value_0 = max(high[index], high_value_1)
        low_value_0 = min(low[index], low_value_1)

        if min_change > 0.0:
            if (
                up_sar[index] - up_sar[index - 1] < min_change * base_unit
                and up_sar[index] != 0.0
                and up_sar[index - 1] != 0.0
            ):
                up_sar[index] = up_sar[index - 1]
            if (
                down_sar[index - 1] - down_sar[index] < min_change * base_unit
                and down_sar[index] != 0.0
                and down_sar[index - 1] != 0.0
            ):
                down_sar[index] = down_sar[index - 1]

        if trend[index] < 0 and down_sar[index] > down_sar[index - 1]:
            down_sar[index] = down_sar[index - 1]
        if trend[index] > 0 and up_sar[index] < up_sar[index - 1]:
            up_sar[index] = up_sar[index - 1]

        if trend[index] < 0 and high[index] >= down_sar[index] + flip_filter * base_unit:
            trend[index] = 1
            up_sar[index] = low_value_0
            down_sar[index] = 0.0
            acceleration_factors[index] = start_a_factor
        elif trend[index] > 0 and low[index] <= up_sar[index] - flip_filter * base_unit:
            trend[index] = -1
            down_sar[index] = high_value_0
            up_sar[index] = 0.0
            acceleration_factors[index] = start_a_factor

    return np.where(up_sar > 0.0, up_sar, down_sar)


def squeeze_bands(
    dataframe: DataFrame,
    bb_length: int,
    mult_bb: float,
    kc_length: int,
    mult_kc: float,
    *,
    use_true_range: bool = True,
    atr: np.ndarray | None = None,
) -> DataFrame:
    """
    Bollinger / Keltner bands for the TTM squeeze, plus the squeeze-momentum
    oscillator (LINREG of price relative to the mid-band). Operates in place on
    ``dataframe`` and returns it.

    If ``use_true_range`` is True the Keltner range is the Hann-window ATR
    (``atr`` array or computed), otherwise the mean of high-low.
    """
    source = dataframe["close"].astype(float)
    basis = source.rolling(bb_length).mean()
    deviation = source.rolling(bb_length).std(ddof=0) * mult_bb
    dataframe["bb_middleband"] = basis
    dataframe["bb_upperband"] = basis + deviation
    dataframe["bb_lowerband"] = basis - deviation

    if use_true_range:
        if atr is None:
            atr = hann_atr(
                dataframe["high"].to_numpy(dtype=float),
                dataframe["low"].to_numpy(dtype=float),
                dataframe["close"].to_numpy(dtype=float),
                kc_length,
            )
        range_value = atr
    else:
        range_value = (dataframe["high"] - dataframe["low"]).rolling(kc_length).mean()

    kc_middle = ta.EMA(source, timeperiod=kc_length)
    dataframe["kc_middleband"] = kc_middle
    dataframe["kc_upperband"] = kc_middle + range_value * mult_kc
    dataframe["kc_lowerband"] = kc_middle - range_value * mult_kc

    highest = dataframe["high"].rolling(kc_length).max()
    lowest = dataframe["low"].rolling(kc_length).min()
    sma_close = dataframe["close"].rolling(kc_length).mean()
    oscillator_source = source - ((highest + lowest) / 2.0 + sma_close) / 2.0
    dataframe["osc"] = ta.LINEARREG(oscillator_source, timeperiod=kc_length)

    return dataframe


def higher_timeframe_ema(
    dataframe: DataFrame,
    metadata: dict,
    dp,
    base_timeframe: str,
    ema_timeframe: str,
    ema_length: int,
) -> DataFrame:
    """
    Merge the previous completed higher-timeframe EMA into ``dataframe`` as an
    ``ema`` column, falling back to the base timeframe EMA if the informative
    data is unavailable. ``dp`` is the strategy's dataprovider.
    """
    if ema_timeframe == base_timeframe or dp is None:
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=ema_length)
        return dataframe

    try:
        informative = dp.get_pair_dataframe(pair=metadata["pair"], timeframe=ema_timeframe)
        if informative.empty:
            raise ValueError("higher-timeframe dataframe is empty")
        informative = informative[["date", "open", "high", "low", "close", "volume"]].copy()
        informative["ema"] = ta.EMA(informative, timeperiod=ema_length)
        dataframe = merge_informative_pair(
            dataframe, informative, base_timeframe, ema_timeframe, ffill=True
        )
        dataframe["ema"] = dataframe[f"ema_{ema_timeframe}"]
        return dataframe
    except (KeyError, ValueError, AttributeError):
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=ema_length)
        return dataframe


def _as_float_array(value: pd.Series | np.ndarray) -> np.ndarray:
    return (
        value.to_numpy(dtype=float)
        if isinstance(value, pd.Series)
        else np.asarray(value, dtype=float)
    )


def _previous_value(values: np.ndarray) -> np.ndarray:
    previous = np.empty_like(values)
    previous[0] = values[0]
    previous[1:] = values[:-1]
    return previous


def _crossed(
    series: pd.Series | np.ndarray,
    level: float | pd.Series | np.ndarray,
    *,
    above: bool,
) -> np.ndarray:
    values = _as_float_array(series)
    previous_values = _previous_value(values)
    if np.ndim(level) == 0:
        if above:
            return (values > level) & (previous_values <= level)
        return (values < level) & (previous_values >= level)
    levels = _as_float_array(level)
    previous_levels = _previous_value(levels)
    if above:
        return (values > levels) & (previous_values <= previous_levels)
    return (values < levels) & (previous_values >= previous_levels)


def crossed_above(
    series: pd.Series | np.ndarray, level: float | pd.Series | np.ndarray
) -> np.ndarray:
    """True where ``series`` crosses above ``level`` on the current bar."""
    return _crossed(series, level, above=True)


def crossed_below(
    series: pd.Series | np.ndarray, level: float | pd.Series | np.ndarray
) -> np.ndarray:
    """True where ``series`` crosses below ``level`` on the current bar."""
    return _crossed(series, level, above=False)


def find_entry_index(dataframe: DataFrame, trade: Trade, timeframe: str) -> int:
    """Index of the last candle at or before the trade's entry date."""
    entry_date = timeframe_to_prev_date(timeframe, trade.open_date_utc)
    dates = pd.to_datetime(dataframe["date"], utc=True)
    matches = np.flatnonzero((dates <= entry_date).to_numpy())
    if len(matches):
        return int(matches[-1])
    return 0
