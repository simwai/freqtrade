"""Vectorized technical indicators extracted from user_data/strategies.

Every function here operates on a DataFrame of OHLCV candles (columns
``date, open, high, low, close, volume``) and returns pandas Series / DataFrames
aligned to the input index. All computations are vectorized with numpy/pandas
rolling/EWM operations; only inherently recursive indicators (supertrend, PSAR,
Ehlers IT) fall back to a tight numpy loop.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame, Series


# ---------------------------------------------------------------------------
# Moving averages / smoothers
# ---------------------------------------------------------------------------
def sma(series: Series, length: int) -> Series:
    return series.rolling(window=max(1, int(length))).mean()


def _ewm_seeded(series: Series, alpha: float, seed: Series) -> Series:
    """EMA recursion with an explicit seed value, matching talib/Pine warmup.

    The recursion ``out[i] = (1 - alpha) * out[i - 1] + alpha * x[i]`` starts
    from ``seed[first]`` (the first non-NaN seed), so values are NaN until the
    seed window is complete — identical to ``talib.EMA`` / ``ta.rma``.
    """
    values = series.to_numpy(dtype=float)
    seed_values = seed.to_numpy(dtype=float)
    first = int(np.argmax(np.isfinite(seed_values)))
    if not np.isfinite(seed_values[first]):
        return Series(np.full(len(series), np.nan), index=series.index)
    out = np.full(len(values), np.nan, dtype=float)
    sub = values[first:].copy()
    sub[0] = seed_values[first]
    out[first:] = pd.Series(sub).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return Series(out, index=series.index)


def ema(series: Series, length: int) -> Series:
    """Exponential MA seeded with SMA(length) — matches ``talib.EMA``."""
    length = max(1, int(length))
    alpha = 2.0 / (length + 1.0)
    seed = series.rolling(length).mean()
    return _ewm_seeded(series, alpha, seed)


def rma(series: Series, length: int) -> Series:
    """Wilder's moving average (ta.rma / talib ATR internals)."""
    length = max(1, int(length))
    alpha = 1.0 / length
    seed = series.rolling(length).mean()
    return _ewm_seeded(series, alpha, seed)


def smma(series: Series, length: int) -> Series:
    """Pine ``smma()`` — SMMA seeded with SMA, computed on the previous close."""
    length = max(1, int(length))
    previous = series.shift(1)
    alpha = 1.0 / length
    seed = previous.rolling(length).mean()
    return _ewm_seeded(previous, alpha, seed)


def ma_convergence(
    series: Series,
    ema_length: int = 15,
    smma_length: int = 25,
    lookback: int = 5,
) -> DataFrame:
    """SMMA EMA Dual MA Convergence (simwai).

    Faithful port of the Pine state machine: tracks whether the fast EMA is
    converging toward the slow SMMA, and returns the long/short entry gates.
    Recursive flags are computed with a tight numpy loop.
    """
    ma_slow = smma(series, smma_length)
    ma_fast = ema(series.shift(1), ema_length)
    above = (ma_fast > ma_slow).to_numpy(dtype=bool)
    below = (ma_fast < ma_slow).to_numpy(dtype=bool)
    going_up = (ma_fast > ma_fast.shift(lookback)).fillna(False).to_numpy(dtype=bool)
    going_down = (ma_fast < ma_fast.shift(lookback)).fillna(False).to_numpy(dtype=bool)
    fast = ma_fast.to_numpy(dtype=float)
    slow = ma_slow.to_numpy(dtype=float)

    n = len(series)
    conv_down = False
    conv_up = False
    out_down = np.zeros(n, dtype=bool)
    out_up = np.zeros(n, dtype=bool)
    long_allowed = np.zeros(n, dtype=bool)
    short_allowed = np.zeros(n, dtype=bool)

    for i in range(n):
        if i > 0 and conv_down and fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]:
            conv_down = False
        if i > 0 and conv_up and fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]:
            conv_up = False
        if going_up[i] and below[i]:
            conv_down = True
        if going_down[i] and below[i]:
            conv_down = False
        if going_up[i] and above[i]:
            conv_up = False
        if going_down[i] and above[i]:
            conv_up = True
        out_down[i] = conv_down
        out_up[i] = conv_up
        long_allowed[i] = (not conv_down) and (not conv_up) and above[i]
        short_allowed[i] = (not conv_down) and (not conv_up) and below[i]

    index = series.index
    return DataFrame(
        {
            "ma_fast": ma_fast,
            "ma_slow": ma_slow,
            "ma1_above_ma2": pd.Series(above, index=index),
            "ma1_below_ma2": pd.Series(below, index=index),
            "is_out1_going_up": pd.Series(going_up, index=index),
            "is_out1_going_down": pd.Series(going_down, index=index),
            "is_out1_converging_from_down": pd.Series(out_down, index=index),
            "is_out1_converging_from_up": pd.Series(out_up, index=index),
            "is_long_allowed": pd.Series(long_allowed, index=index),
            "is_short_allowed": pd.Series(short_allowed, index=index),
        },
        index=index,
    )


def tema(series: Series, length: int) -> Series:
    e1 = ema(series, length)
    e2 = ema(e1, length)
    e3 = ema(e2, length)
    return 3 * e1 - 3 * e2 + e3


def zema(series: Series, length: int) -> Series:
    """Zero-lag EMA: ema + (ema - ema(ema))."""
    e1 = ema(series, length)
    e2 = ema(e1, length)
    return e1 + (e1 - e2)


def t3(series: Series, period: int = 5, vfactor: float = 0.7) -> Series:
    """Tim Tillson's T3 (vectorized via chained EWM)."""
    period = max(1, int(period))
    a = float(vfactor)
    e1 = series.ewm(span=period).mean()
    e2 = e1.ewm(span=period).mean()
    e3 = e2.ewm(span=period).mean()
    e4 = e3.ewm(span=period).mean()
    e5 = e4.ewm(span=period).mean()
    e6 = e5.ewm(span=period).mean()
    c1 = -a * a * a
    c2 = 3 * a * a + 3 * a * a * a
    c3 = -6 * a * a - 3 * a - 3 * a * a * a
    c4 = 1 + 3 * a + a * a * a + 3 * a * a
    return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


def jma(series: Series, period: int = 10) -> Series:
    """Jurik-like approximation: MA of price + MA of |diff| (volatility add-on)."""
    period = max(1, int(period))
    diff = series.diff().abs()
    vola = diff.rolling(window=period).mean()
    ma = series.rolling(window=period).mean()
    return ma + vola


def ewo(df: DataFrame, sma1_length: int = 5, sma2_length: int = 35) -> Series:
    """Elliot Wave Oscillator: (EMA fast - EMA slow) / close * 100."""
    sma1 = ema(df["close"], sma1_length)
    sma2 = ema(df["close"], sma2_length)
    return (sma1 - sma2) / df["close"] * 100


# ---------------------------------------------------------------------------
# True range / ATR family
# ---------------------------------------------------------------------------
def true_range(df: DataFrame) -> Series:
    """True range matching ``talib.TRANGE`` (first value NaN)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = np.nan
    return tr


def atr(df: DataFrame, length: int = 14) -> Series:
    return rma(true_range(df), length)


def hann_atr(df: DataFrame, length: int = 14) -> Series:
    """Hann-window ATR: ATR filtered through a Hann cosine window.

    Matches the Pine ``atr()`` helper used by OctopusNest / TrendOMatic.
    Vectorized as a sliding dot-product.
    """
    length = max(1, int(length))
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    previous_close = np.roll(close, 1)
    previous_close[0] = 0.0
    tr = np.maximum.reduce(
        [high - low, np.abs(high - previous_close), np.abs(low - previous_close)]
    )
    tr = np.where(np.isfinite(tr), tr, 0.0)
    weights = 1.0 - np.cos(2.0 * np.pi * np.arange(1, length + 1) / (length + 1))
    coefficient = float(weights.sum())
    result = np.zeros(len(df), dtype=float)

    from numpy.lib.stride_tricks import sliding_window_view

    if len(df) >= length:
        windows = sliding_window_view(tr, length)
        result[length - 1 :] = (windows @ weights[::-1]) / coefficient
    for index in range(min(length - 1, len(df))):
        available = index + 1
        result[index] = (
            np.dot(tr[:available], weights[:available][::-1]) / coefficient
        )
    return Series(result, index=df.index)


# ---------------------------------------------------------------------------
# Bands / channels
# ---------------------------------------------------------------------------
def bollinger(series: Series, length: int = 20, mult: float = 2.0) -> DataFrame:
    length = max(1, int(length))
    mid = series.rolling(length).mean()
    std = series.rolling(length).std(ddof=0)
    return DataFrame(
        {
            "upper": mid + mult * std,
            "mid": mid,
            "lower": mid - mult * std,
        },
        index=series.index,
    )


def keltner(
    df: DataFrame,
    length: int = 20,
    atr_length: int = 10,
    mult: float = 1.0,
    base: str = "ema",
    range_style: str = "atr",
) -> DataFrame:
    """Keltner channel. base: 'ema'|'sma'; range_style: 'atr'|'hann_atr'|'hl'."""
    ma = ema(df["close"], length) if base == "ema" else sma(df["close"], length)
    if range_style == "hann_atr":
        width = hann_atr(df, atr_length)
    elif range_style == "hl":
        width = (df["high"] - df["low"]).rolling(atr_length).mean()
    else:
        width = atr(df, atr_length)
    return DataFrame(
        {"mid": ma, "upper": ma + width * mult, "lower": ma - width * mult},
        index=df.index,
    )


def supertrend(df: DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple[Series, Series]:
    """TradingView-style supertrend.

    Returns ``(supertrend_line, direction)`` where direction is ``+1`` for an
    uptrend and ``-1`` for a downtrend (NaN until the ATR is seeded).
    """
    period = max(1, int(period))
    atr_series = atr(df, period)
    atr_values = atr_series.to_numpy(dtype=float)
    close_values = df["close"].to_numpy(dtype=float)
    hl2 = ((df["high"] + df["low"]) / 2.0).to_numpy(dtype=float)
    basic_ub = hl2 + float(multiplier) * atr_values
    basic_lb = hl2 - float(multiplier) * atr_values

    n = len(df)
    final_ub = np.full(n, np.nan, dtype=float)
    final_lb = np.full(n, np.nan, dtype=float)
    for i in range(n):
        if i == 0 or not np.isfinite(atr_values[i]):
            final_ub[i] = basic_ub[i]
            final_lb[i] = basic_lb[i]
            continue
        if (
            not np.isfinite(final_ub[i - 1])
            or basic_ub[i] < final_ub[i - 1]
            or close_values[i - 1] > final_ub[i - 1]
        ):
            final_ub[i] = basic_ub[i]
        else:
            final_ub[i] = final_ub[i - 1]
        if (
            not np.isfinite(final_lb[i - 1])
            or basic_lb[i] > final_lb[i - 1]
            or close_values[i - 1] < final_lb[i - 1]
        ):
            final_lb[i] = basic_lb[i]
        else:
            final_lb[i] = final_lb[i - 1]

    st = np.full(n, np.nan, dtype=float)
    for i in range(n):
        if not np.isfinite(final_ub[i]) or not np.isfinite(final_lb[i]):
            continue
        if i == 0 or np.isnan(st[i - 1]):
            st[i] = final_lb[i]
        elif st[i - 1] == final_ub[i - 1]:
            st[i] = final_lb[i] if close_values[i] <= final_ub[i] else final_ub[i]
        else:
            st[i] = final_ub[i] if close_values[i] >= final_lb[i] else final_lb[i]

    direction = np.where(close_values > st, 1.0, np.where(close_values < st, -1.0, np.nan))
    direction_series = Series(direction, index=df.index).ffill()
    return Series(st, index=df.index), direction_series


def supertrend_simple(
    df: DataFrame, factor: float = 3.0, atr_period: int = 10
) -> tuple[Series, Series]:
    """Simplified single-state supertrend used by StrategyTemplate/SuperKeltner.

    Direction is ``+1`` uptrend / ``-1`` downtrend.
    """
    atr_values = atr(df, atr_period)
    hl2 = (df["high"] + df["low"]) / 2
    upperband = hl2 + factor * atr_values
    lowerband = hl2 - factor * atr_values
    st = Series(index=df.index, dtype=float)
    direction = Series(index=df.index, dtype=float)
    trend = 1
    closes = df["close"].to_numpy(dtype=float)
    upper = upperband.to_numpy(dtype=float)
    lower = lowerband.to_numpy(dtype=float)
    for i in range(1, len(df)):
        if closes[i] > upper[i - 1]:
            trend = 1
        elif closes[i] < lower[i - 1]:
            trend = -1
        st.iloc[i] = lower[i] if trend == 1 else upper[i]
        direction.iloc[i] = trend
    return st, direction


def sar(
    df: DataFrame, start: float = 0.02, increment: float = 0.02, maximum: float = 0.2
) -> Series:
    """Classic Parabolic SAR (TradingView ta.sar). Recursive numpy loop."""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    result = np.full(len(df), np.nan, dtype=float)
    if len(df) == 0:
        return Series(result, index=df.index)
    rising = True
    acceleration = start
    extreme = high[0]
    result[0] = low[0]
    for i in range(1, len(df)):
        sar_val = result[i - 1] + acceleration * (extreme - result[i - 1])
        if rising:
            sar_val = min(sar_val, low[i - 1])
            if i > 1:
                sar_val = min(sar_val, low[i - 2])
            if low[i] < sar_val:
                rising = False
                sar_val = extreme
                extreme = low[i]
                acceleration = start
            elif high[i] > extreme:
                extreme = high[i]
                acceleration = min(maximum, acceleration + increment)
        else:
            sar_val = max(sar_val, high[i - 1])
            if i > 1:
                sar_val = max(sar_val, high[i - 2])
            if high[i] > sar_val:
                rising = True
                sar_val = extreme
                extreme = high[i]
                acceleration = start
            elif low[i] < extreme:
                extreme = low[i]
                acceleration = min(maximum, acceleration + increment)
        result[i] = sar_val
    return Series(result, index=df.index)


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------
def rsi(df: DataFrame, length: int = 14) -> Series:
    return Series(ta.RSI(df, timeperiod=length), index=df.index)


def williams_r(df: DataFrame, period: int = 14) -> Series:
    highest = df["high"].rolling(window=period, center=False).max()
    lowest = df["low"].rolling(window=period, center=False).min()
    wr = (highest - df["close"]) / (highest - lowest)
    return wr * -100


def mfi(df: DataFrame, period: int = 14) -> Series:
    """Money Flow Index without talib (vectorized)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    raw = tp * df["volume"]
    pos = raw.where(tp > tp.shift(1), 0.0).rolling(period).sum()
    neg = raw.where(tp < tp.shift(1), 0.0).rolling(period).sum()
    ratio = pos / (neg + 1e-8)
    return 100 - (100 / (1 + ratio))


def mfv(df: DataFrame) -> Series:
    """Chaikin Money Flow Volume multiplier."""
    money = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (
        df["high"] - df["low"]
    )
    return money * df["volume"]


def cmf(df: DataFrame, length: int = 20) -> Series:
    """Chaikin Money Flow (vectorized)."""
    money = mfv(df).fillna(0.0)
    return money.rolling(length, min_periods=0).sum() / df["volume"].rolling(
        length, min_periods=0
    ).sum()


def fisher(close: Series, length: int = 13) -> Series:
    """Fisher transform of price position within its rolling range."""
    length = max(1, int(length))
    high = close.rolling(length, min_periods=length).max()
    low = close.rolling(length, min_periods=length).min()
    price_range = (high - low).replace(0, np.nan)
    value = 2 * ((close - low) / price_range - 0.5)
    value = value.clip(-0.999, 0.999)
    return 0.5 * np.log((1 + value) / (1 - value))


def fisher_rsi(rsi_series: Series) -> Series:
    """Fisher transform applied on RSI (ClucHAnix style)."""
    r = 0.1 * (rsi_series - 50)
    return (np.exp(2 * r) - 1) / (np.exp(2 * r) + 1)


def wavetrend(
    df: DataFrame, channel_length: int = 10, avg_length: int = 21, sma_length: int = 4
) -> DataFrame:
    """LazyBear WaveTrend oscillator.

    Adds columns ``wt1``, ``wt2``, ``wt1-wt2`` to a copy of ``df`` and returns
    the extended dataframe (drop-in for the MfiEmaWaveTrend WaveTrend helper).
    """
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = ema(hlc3, channel_length)
    d = ema((hlc3 - esa).abs(), channel_length)
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ema(ci, avg_length)
    wt2 = sma(wt1, sma_length)
    result = df.copy()
    result["wt1"] = wt1
    result["wt2"] = wt2
    result["wt1-wt2"] = wt1 - wt2
    return result


def choppiness(df: DataFrame, length: int = 14) -> Series:
    """Choppiness index in [0, 100]. Low = trending, high = ranging."""
    atr_sum = atr(df, length).rolling(length).sum()
    high_low_range = df["high"].rolling(length).max() - df["low"].rolling(length).min()
    return 100 * np.log10(atr_sum / (high_low_range + 1e-8)) / np.log10(length)


def ppo(close: Series, fast: int = 12, slow: int = 26, signal: int = 9) -> DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    ppo_series = 100 * (fast_ema - slow_ema) / slow_ema.replace(0, np.nan)
    signal_series = ema(ppo_series, signal)
    return DataFrame(
        {"ppo": ppo_series, "signal": signal_series, "hist": ppo_series - signal_series},
        index=close.index,
    )


def vix_fix(df: DataFrame, lookback: int = 22) -> Series:
    """Williams VIX Fix / WVF: 100 * (hh(close) - low) / hh(close)."""
    highest_close = df["close"].rolling(lookback).max()
    return (highest_close - df["low"]) / highest_close.replace(0, np.nan) * 100


# ---------------------------------------------------------------------------
# Adaptive / regime machinery (GkdAdaptive family)
# ---------------------------------------------------------------------------
def ewma_zscore(close: Series, length: int = 20) -> Series:
    """EWMA z-score: (close - EWMA) / EWMA std."""
    mean = close.ewm(span=length, adjust=False).mean()
    std = close.ewm(span=length, adjust=False).std()
    return (close - mean) / (std + 1e-8)


def rls_mean(close: Series, alpha: float = 0.95) -> Series:
    """RLS-style adaptive mean (EWMA with alpha as smoothing)."""
    return close.ewm(alpha=1.0 - float(alpha), adjust=False).mean()


def rls_slope(close: Series, alpha: float = 0.95, bars: int = 3) -> Series:
    return rls_mean(close, alpha) - rls_mean(close, alpha).shift(bars)


def volatility_ratio(df: DataFrame, atr_length: int = 14, lookback: int = 50) -> Series:
    atr_values = atr(df, atr_length)
    return atr_values / atr_values.rolling(lookback).mean()


def vwap_anchor(close: Series, volume: Series, lookback: int = 24) -> Series:
    pv = close * volume
    return pv.rolling(lookback).sum() / volume.rolling(lookback).sum().replace(0, np.nan)


def prior_lows_highs(df: DataFrame, lookback: int = 20) -> DataFrame:
    """Liquidity-sweep levels: previous N-bar low/high (excluding current candle)."""
    prior_low = df["low"].shift(1).rolling(lookback).min()
    prior_high = df["high"].shift(1).rolling(lookback).max()
    return DataFrame({"prior_low": prior_low, "prior_high": prior_high}, index=df.index)


def swing_detection(df: DataFrame, window: int = 5) -> DataFrame:
    """Fractal swing highs/lows (confirmed after right-hand candles close).

    Adds ``is_swing_high/low``, ``swing_high_price/low_price`` and the
    forward-filled ``last_swing_high/low``. Fully vectorized.
    """
    window = max(3, int(window))
    right_side = window // 2
    pivot_high = df["high"].shift(right_side)
    pivot_low = df["low"].shift(right_side)
    rolling_high = df["high"].rolling(window, min_periods=window).max()
    rolling_low = df["low"].rolling(window, min_periods=window).min()

    is_swing_high = (
        pivot_high.eq(rolling_high)
        & pivot_high.gt(df["high"].shift(right_side + 1))
        & pivot_high.gt(df["high"].shift(right_side - 1))
    ).fillna(False)
    is_swing_low = (
        pivot_low.eq(rolling_low)
        & pivot_low.lt(df["low"].shift(right_side + 1))
        & pivot_low.lt(df["low"].shift(right_side - 1))
    ).fillna(False)

    swing_high_price = pivot_high.where(is_swing_high)
    swing_low_price = pivot_low.where(is_swing_low)
    return DataFrame(
        {
            "is_swing_high": is_swing_high,
            "is_swing_low": is_swing_low,
            "swing_high_price": swing_high_price,
            "swing_low_price": swing_low_price,
            "last_swing_high": swing_high_price.ffill(),
            "last_swing_low": swing_low_price.ffill(),
        },
        index=df.index,
    )


def kama_slope(
    close: Series,
    length: int = 10,
    fast: int = 2,
    slow: int = 30,
    slope_bars: int = 5,
) -> Series:
    """KAMA slope normalized by ATR, clipped to [-1, 1] (signed)."""
    try:
        import pandas_ta as pta

        kama = pta.kama(close, length=length, fast=fast, slow=slow)
    except (ImportError, AttributeError):
        kama = _kama(close, length, fast, slow)
    atr14 = pta_atr_from_close(close, 14)
    denominator = (slope_bars * atr14).replace(0, np.nan)
    slope = (kama - kama.shift(slope_bars)) / denominator
    return (slope / 0.03).replace([np.inf, -np.inf], np.nan).clip(-1.0, 1.0)


def _kama(close: Series, length: int, fast: int, slow: int) -> Series:
    """Kaufman Adaptive MA fallback (vectorized)."""
    length = max(1, int(length))
    er = (close - close.shift(length)).abs() / close.diff().abs().rolling(length).sum().replace(
        0, np.nan
    )
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    kama = close.copy()
    kama.iloc[:length] = np.nan
    first = close.iloc[length:length + 1].values
    if len(first):
        kama.iloc[length] = first[0]
    prev = None
    for i in range(length + 1, len(close)):
        prev = kama.iloc[i - 1]
        kama.iloc[i] = prev + sc.iloc[i] * (close.iloc[i] - prev)
    return kama


def pta_atr_from_close(close: Series, length: int = 14) -> Series:
    """ATR approximated from a close-only series (used for slope normalization)."""
    high = close * 1.0001
    low = close * 0.9999
    try:
        import pandas_ta as pta

        return pta.atr(high=high, low=low, close=close, length=length)
    except (ImportError, AttributeError):
        return atr(DataFrame({"high": high, "low": low, "close": close}), length)


def smma_ema_convergence(
    close: Series, smma_len: int = 7, ema_lens: tuple[int, ...] = (10, 20, 50)
) -> Series:
    """Trend-strength score: 1 - spread(MA stack)/max spread, clipped to [0,1]."""
    smma_len = max(1, int(smma_len))
    alpha = 1.0 / smma_len
    smma = close.ewm(alpha=alpha, adjust=False).mean()
    all_mas = DataFrame({"smma": smma})
    for length in ema_lens:
        all_mas[f"ema_{length}"] = ema(close, length)
    spread = all_mas.std(axis=1)
    eff = 1 - (spread / spread.rolling(50).max())
    return np.clip(eff, 0, 1)


def vol_index(
    df: DataFrame,
    t3_length: int = 14,
    t3_factor: float = 0.618,
    percentile_window: int = 100,
    std_window: int = 20,
) -> Series:
    """Volatility regime index in [0,1] combining percentile rank and norm std."""
    tr_values = true_range(df)
    t3_values = t3(tr_values, t3_length, t3_factor)
    rank = t3_values.rolling(percentile_window).rank(pct=True)
    std = t3_values.rolling(std_window).std()
    norm_std = std / (std.rolling(200).max() + 1e-10)
    return (rank * norm_std).fillna(0.5)


def extreme_vol(
    volume: Series,
    length: int = 20,
    t3_factor: float = 0.618,
    percentile_window: int = 100,
    std_window: int = 20,
) -> Series:
    """Volume shock score in [0,1] (rank * normalized std of T3 volume)."""
    t3_vol = t3(volume, length, t3_factor)
    rank = t3_vol.rolling(percentile_window).rank(pct=True)
    std = t3_vol.rolling(std_window).std()
    norm_std = std / (std.rolling(200).max() + 1e-10)
    return (rank * norm_std).fillna(0)


def volume_zscore(volume: Series, t3_length: int, t3_factor: float, z_window: int) -> Series:
    t3_vol = t3(volume, t3_length, t3_factor)
    mean = t3_vol.rolling(z_window, min_periods=z_window).mean()
    std = t3_vol.rolling(z_window, min_periods=z_window).std().replace(0, np.nan)
    return ((t3_vol - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def ehlers_it(close: Series, alpha: float = 0.07) -> Series:
    """Ehlers Instantaneous Trendline. Recursive numpy loop."""
    alpha = float(alpha)
    values = close.to_numpy(dtype=float)
    result = values.copy()
    c1 = alpha - alpha**2 / 4
    c2 = alpha**2 / 2
    c3 = alpha - 3 * alpha**2 / 4
    c4 = alpha**2 / 4
    for i in range(2, len(values)):
        result[i] = (
            c1 * values[i]
            + c2 * values[i - 1]
            - c3 * result[i - 1]
            - c4 * result[i - 2]
        )
    return Series(result, index=close.index)


def nadaraya_watson(
    close: Series, length: int = 20, bandwidth: float = 3.0, mult: float = 3.0
) -> DataFrame:
    """Nadaraya-Watson Gaussian kernel envelope.

    ``center`` is a Gaussian-weighted average of the last ``length`` closes;
    band width is ``mult * mean(|close - center|)``. Vectorized rolling apply.
    """
    length = max(1, int(length))
    bandwidth = max(float(bandwidth), 1e-9)
    offsets = np.arange(length - 1, -1, -1, dtype=float)
    weights = np.exp(-(offsets**2) / (2 * bandwidth**2))
    weights /= weights.sum()

    def weighted_average(values: np.ndarray) -> float:
        return float(np.dot(values, weights))

    center = close.rolling(length, min_periods=length).apply(weighted_average, raw=True)
    mae = (close - center).abs().rolling(length, min_periods=length).mean()
    return DataFrame(
        {"center": center, "upper": center + mult * mae, "lower": center - mult * mae},
        index=close.index,
    )


# ---------------------------------------------------------------------------
# Pump / gap protection helpers (BigZ / Nostalgia family)
# ---------------------------------------------------------------------------
def range_percent_change(df: DataFrame, length: int, method: str = "HL") -> Series:
    """Rolling percentage change across interval: HL (high-low) or OC (open-close)."""
    if method == "HL":
        low_roll = df["low"].rolling(length).min()
        return (df["high"].rolling(length).max() - low_roll) / low_roll
    if method == "OC":
        close_roll = df["close"].rolling(length).min()
        return (df["open"].rolling(length).max() - close_roll) / close_roll
    raise ValueError(f"Method {method} not defined!")


def top_percent_change(df: DataFrame, length: int) -> Series:
    """% change of close from the interval's maximum open."""
    if length == 0:
        return (df["open"] - df["close"]) / df["close"]
    return (df["open"].rolling(length).max() - df["close"]) / df["close"]


def range_maxgap(df: DataFrame, length: int) -> Series:
    return df["open"].rolling(length).max() - df["close"].rolling(length).min()


def range_height(df: DataFrame, length: int) -> Series:
    return df["close"] - df["close"].rolling(length).min()


def volume_mean(df: DataFrame, length: int = 48) -> Series:
    return df["volume"].rolling(window=length).mean()


def heikin_ashi(df: DataFrame) -> DataFrame:
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_open = (df["open"].shift(1) + ha_close.shift(1)) / 2
    ha_open = ha_open.fillna((df["open"] + df["close"]) / 2)
    ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)
    return DataFrame(
        {"open": ha_open, "high": ha_high, "low": ha_low, "close": ha_close}, index=df.index
    )


def typical_price(df: DataFrame) -> Series:
    return (df["high"] + df["low"] + df["close"]) / 3


# ---------------------------------------------------------------------------
# Pine MA library (simwai/ma/4) — vectorized ports
# ---------------------------------------------------------------------------
def _rolling_dot(series: Series, weights: np.ndarray) -> Series:
    """Sliding dot-product ``sum(src[i-n+1..i] * weights)`` with NaN head."""
    length = int(weights.size)
    arr = series.to_numpy(dtype=float)
    out = np.full(len(series), np.nan, dtype=float)
    if len(arr) >= length:
        windows = np.lib.stride_tricks.sliding_window_view(arr, length)
        out[length - 1 :] = windows @ weights
    return Series(out, index=series.index)


def wma(series: Series, length: int) -> Series:
    """Weighted MA (Pine ``ta.wma``): newest bar weighted ``length``."""
    length = max(1, int(length))
    weights = np.arange(1, length + 1, dtype=float)
    return _rolling_dot(series, weights) / weights.sum()


def hma(series: Series, length: int) -> Series:
    """Hull MA: ``wma(2*wma(src, n/2) - wma(src, n), sqrt(n))``."""
    length = max(1, int(length))
    half = max(1, int(round(length / 2)))
    root = max(1, int(round(length**0.5)))
    w1 = wma(series, half)
    w2 = wma(series, length)
    return wma(2 * w1 - w2, root)


def dema(series: Series, length: int) -> Series:
    """Double EMA: ``2*ema - ema(ema)``."""
    e1 = ema(series, length)
    return 2 * e1 - ema(e1, length)


def kama(series: Series, length: int = 10, fast: int = 2, slow: int = 30) -> Series:
    """Kaufman Adaptive MA (public wrapper around the internal fallback)."""
    return _kama(series, max(1, int(length)), max(1, int(fast)), max(1, int(slow)))


def ehma(series: Series, length: int) -> Series:
    """Exponential Hull MA: ``ema(2*ema(src, n/2) - ema(src, n), sqrt(n))``."""
    length = max(1, int(length))
    half = max(1, int(round(length / 2)))
    root = max(1, int(round(length**0.5)))
    e1 = ema(series, half)
    e2 = ema(series, length)
    return ema(2 * e1 - e2, root)


def vwma(df: DataFrame, length: int) -> Series:
    """Volume-Weighted MA: ``sum(close*volume, n) / sum(volume, n)``."""
    length = max(1, int(length))
    pv = df["close"] * df["volume"]
    vol = df["volume"].rolling(length).sum().replace(0, np.nan)
    return pv.rolling(length).sum() / vol


def cmo(series: Series, length: int) -> Series:
    """Chande Momentum Oscillator in [-100, 100] (drives VIDYA)."""
    length = max(1, int(length))
    diff = series.diff().fillna(0.0)
    up = diff.clip(lower=0.0).rolling(length).sum()
    down = (-diff.clip(upper=0.0)).rolling(length).sum()
    total = up + down
    return ((up - down) / total.replace(0, np.nan) * 100).replace([np.inf, -np.inf], np.nan)


def vidya(series: Series, length: int, cmo_length: int | None = None) -> Series:
    """Variable Index Dynamic Average (recursive, Chande).

    ``out[i] = src[i]*alpha + (1-alpha)*out[i-1]`` with
    ``alpha = abs(cmo)/100 * 2/(length+1)``.
    """
    length = max(1, int(length))
    cmo_len = max(1, int(cmo_length if cmo_length else length))
    cmo_values = cmo(series, cmo_len).abs().fillna(0.0).to_numpy(dtype=float)
    values = series.to_numpy(dtype=float)
    alpha_scale = 2.0 / (length + 1.0)
    out = np.full(len(series), np.nan, dtype=float)
    first = int(np.argmax(np.isfinite(values)))
    if np.isfinite(values[first]):
        out[first] = values[first]
        for i in range(first + 1, len(values)):
            alpha = cmo_values[i] / 100.0 * alpha_scale
            out[i] = values[i] * alpha + (1.0 - alpha) * out[i - 1]
    return Series(out, index=series.index)


# ---------------------------------------------------------------------------
# Pine Strategy Template filter inputs (vectorized)
# ---------------------------------------------------------------------------
def fir_kernel_weights(length: int, harmonics: int, wave_type: str = "Square") -> np.ndarray:
    """FIR filter tap weights (Pine ``firKernel`` windowed-sinc).

    ``wave_type`` ``'Sawtooth'`` sums every harmonic, ``'Square'`` every other
    one. The weights are constant per configuration and are convolved with the
    price series to produce the FIR output.
    """
    length = max(1, int(length))
    harmonics = max(1, int(harmonics))
    step = 1 if wave_type == "Sawtooth" else 2
    pi = np.pi

    def _kernel(x: float) -> float:
        total = 0.0
        for i in range(1, harmonics + 1, step):
            xi = i * pi / harmonics
            sigma = np.sin(xi) / xi if xi != 0 else 1.0
            total += sigma * np.sin(x * i * pi) / i
        return total

    return np.array(
        [
            _kernel(i / length) - _kernel((i - 1) / length)
            for i in range(1, length + 1)
        ]
    )


def fir(series: Series, length: int, harmonics: int, wave_type: str = "Square") -> Series:
    """FIR trend filter (Pine ``fir``): convolution with the windowed-sinc taps.

    NaN until ``bar_index > length`` exactly like the Pine guard.
    """
    weights = fir_kernel_weights(length, harmonics, wave_type)
    out = _rolling_dot(series, weights)
    if len(out) > length + 1:
        out.iloc[: length + 1] = np.nan
    return out


def chaikin_volatility(df: DataFrame, length: int = 21, roc_length: int = 34) -> Series:
    """Chaikin volatility: ROC of EMA(high-low, length) over ``roc_length``."""
    hl = df["high"] - df["low"]
    ema_hl = ema(hl, length)
    return (ema_hl - ema_hl.shift(roc_length)) / ema_hl.shift(roc_length) * 100.0


def aroon_upper_lower(df: DataFrame, length: int) -> DataFrame:
    """Pine ``aroonUpperLower``: 0-100 strength of the highest/lowest bar."""
    length = max(1, int(length))
    win = length + 1

    def _offsets(series: Series, window: int, want_max: bool) -> Series:
        return series.rolling(window, min_periods=1).apply(
            lambda w: float(
                (np.argmax(w) if want_max else np.argmin(w)) - (window - 1)
            ),
            raw=True,
        )

    upper = 100.0 * (_offsets(df["high"], win, True) + length) / length
    lower = 100.0 * (_offsets(df["low"], win, False) + length) / length
    return DataFrame({"upper": upper, "lower": lower}, index=df.index)


def aroon(df: DataFrame, length: int) -> Series:
    """Pine ``aroon`` oscillator: ``upper - lower``."""
    bands = aroon_upper_lower(df, length)
    return bands["upper"] - bands["lower"]


def aroon_sidetrend(bands: DataFrame) -> Series:
    """True when the aroon upper/lower slopes are equal (Pine ``isSidetrendByAroon``).

    In Pine the equality is taken on per-time-frame slopes; both share the same
    time denominator, so it reduces to equality of the frame-to-frame deltas.
    """
    return (bands["upper"].diff() == bands["lower"].diff()).fillna(False)


def woodies_cci(df: DataFrame, length: int = 7) -> DataFrame:
    """Woodies CCI: were the last 5 bars all below/above zero.

    Returns ``(last5_is_down, last5_is_up)`` boolean Series.
    """
    cci = Series(ta.CCI(df, timeperiod=length), index=df.index)
    below = cci.shift(1).rolling(5).apply(lambda w: bool(np.all(w < 0)), raw=True)
    above = cci.shift(1).rolling(5).apply(lambda w: bool(np.all(w > 0)), raw=True)
    return DataFrame(
        {
            "last5_is_down": below.fillna(False).astype(bool),
            "last5_is_up": above.fillna(False).astype(bool),
        },
        index=df.index,
    )


def stochastic(df: DataFrame, k_length: int = 14, d_length: int = 3, smooth_k: int = 1) -> DataFrame:
    """Pine ``stochK``/``stochD``: smoothed %K and its SMA."""
    stoch_out = ta.STOCH(
        df,
        fastk_period=max(1, int(k_length)),
        slowk_period=max(1, int(smooth_k)),
        slowk_matype=0,
        slowd_period=1,
        slowd_matype=0,
    )
    k_raw = Series(np.asarray(stoch_out)[:, 0], index=df.index)
    k = sma(k_raw, max(1, int(smooth_k))) if smooth_k > 1 else k_raw
    d = sma(k, max(1, int(d_length)))
    return DataFrame({"stoch_k": k, "stoch_d": d}, index=df.index)


def roc(series: Series, length: int) -> Series:
    """Rate of change (%): ``(src - src[n]) / src[n] * 100``."""
    length = max(1, int(length))
    return (series - series.shift(length)) / series.shift(length) * 100.0


def fhv(src: Series, length: int, avg: int) -> Series:
    """Historical volatility of log returns (Pine ``fHV``)."""
    length = max(1, int(length))
    avg = max(1, int(avg))
    r = np.log(src / src.shift(1).fillna(src))
    r_avg = sma(r, length)
    var = ((r - r_avg) ** 2).rolling(length).sum() / (length - 1)
    return np.sqrt(var) * np.sqrt(avg)


def fhvp(hv: Series, avg: int) -> Series:
    """Percentile position of current HV among the last ``avg`` bars (Pine ``fHVP``)."""
    avg = max(1, int(avg))
    return (
        hv.rolling(avg, min_periods=1)
        .apply(lambda w: float(np.sum(w < w[-1])) / avg * 100.0, raw=True)
        .fillna(0.0)
    )


def historical_volatility(
    df: DataFrame,
    length: int = 33,
    avg: int = 180,
    sma_length: int = 35,
    include_source: bool = True,
    include_volume: bool = True,
) -> DataFrame:
    """Combined normalized historical volatility (Pine ``vvHtf``) + its SMA.

    Source volatility (log-close) and volume volatility (log10-volume) are each
    ranked into a percentile; the sum is normalized to ``[0, 100]`` with the
    running historic min/max, then smoothed with an SMA.
    """
    from .ehlers import normalize

    hv = fhv(df["close"], length, avg)
    hv_pct = fhvp(hv, avg) if include_source else pd.Series(0.0, index=df.index)
    hvv = fhv(df["volume"].replace(0, np.nan), length, avg)
    hvv_pct = fhvp(hvv, avg) if include_volume else pd.Series(0.0, index=df.index)
    vv = normalize(hv_pct + hvv_pct, 0.0, 100.0)
    svv = sma(vv, sma_length)
    return DataFrame({"hv": vv, "hv_sma": svv}, index=df.index)


def holt(y: Series, alpha: float, beta: float) -> DataFrame:
    """Holt's linear trend forecast (recursive): level, trend, forecast.

    ``level[i] = alpha*y + (1-alpha)*(level[i-1] + trend[i-1])``
    ``trend[i] = beta*(level[i]-level[i-1]) + (1-beta)*trend[i-1]``
    """
    values = y.to_numpy(dtype=float)
    n = len(values)
    level = np.zeros(n)
    trend = np.zeros(n)
    forecast = np.zeros(n)
    for i in range(n):
        level_prev = level[i - 1] if i >= 1 else 0.0
        trend_prev = trend[i - 1] if i >= 1 else 0.0
        v = values[i] if np.isfinite(values[i]) else level_prev
        level[i] = alpha * v + (1 - alpha) * (level_prev + trend_prev)
        trend[i] = beta * (level[i] - level_prev) + (1 - beta) * trend_prev
        forecast[i] = level_prev + trend_prev
    return DataFrame({"level": level, "trend": trend, "forecast": forecast}, index=y.index)


def chop_zone(df: DataFrame, length: int = 30) -> DataFrame:
    """Ehlers-style chop zone angle.

    The Pine template block references a global ``chopZoneHtfClose`` inside the
    function and calls ``ta.lowest()`` without a series — both apparent bugs.
    This port applies the intended logic to the supplied ``df``: the EMA-34
    slope is scaled by ``span = 25/(hh - ll) * ll`` and converted to a degree
    angle; ``>= 5`` deg is treated as trending.
    """
    length = max(1, int(length))
    hh = df["high"].rolling(length).max()
    ll = df["low"].rolling(length).min()
    span = 25.0 / (hh - ll) * ll
    ema34 = ema(df["close"], 34)
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    y2 = (ema34.shift(1) - ema34) / hlc3 * span
    c = np.sqrt(1.0 + y2**2)
    angle = np.degrees(np.arccos((1.0 / c).clip(-1.0, 1.0)))
    angle = np.round(angle)
    angle = np.where(y2 > 0, -angle, angle)
    angle = Series(angle, index=df.index)
    return DataFrame({"angle": angle, "trending": angle >= 5, "choppy": angle < 5}, index=df.index)


def zscore(series: Series, length: int) -> Series:
    """``(src - sma(src, n)) / stdev(src, n)``."""
    length = max(1, int(length))
    mean = sma(series, length)
    std = series.rolling(length).std(ddof=0)
    return (series - mean) / std


def candlestick_patterns(df: DataFrame) -> DataFrame:
    """Pine ``checkLastBarsCandlestick`` pattern primitives per candle.

    Returns ``(cs_long, cs_short)`` boolean Series for the 16 template patterns.
    The Pine source has index inconsistencies (mixes ``_high``/``_open[i]``,
    ``body`` of the current bar with ``_close[i]`` of the loop bar); this port
    applies the intended geometry consistently per candle ``t`` vs ``t-k``.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    oc2 = o.clip(lower=c) + body / 2.0
    upperwick = h - pd.concat([o, c], axis=1).max(axis=1)
    lowerwick = pd.concat([o, c], axis=1).min(axis=1) - l
    is_up = c > o
    is_doji = (c - o).abs() / rng < 0.05

    wm = is_up & (upperwick <= 0.05 * body) & (lowerwick <= 0.05 * body)
    bm = ~is_up & (upperwick <= 0.05 * body) & (lowerwick <= 0.05 * body)
    hm = is_up & (lowerwick >= 2 * body) & (upperwick <= 0.1 * body)
    hg = ~is_up & (lowerwick >= 2 * body) & (upperwick <= 0.1 * body)
    ih = is_up & (upperwick >= 2 * body) & (lowerwick <= 0.1 * body)
    ss = ~is_up & (upperwick >= 2 * body) & (lowerwick <= 0.1 * body)

    b = lambda s: s.astype("boolean").fillna(False).astype(bool)  # noqa: E731
    is_doji_p = b(is_doji.shift(1))
    is_up_p = b(is_up.shift(1))
    is_up_p2 = b(is_up.shift(2))
    is_up_p3 = b(is_up.shift(3))

    bulle = ~is_doji_p & ~is_up_p & is_up & (c > o.shift(1)) & (o < c.shift(1))
    beare = ~is_doji_p & is_up_p & ~is_up & (o > c.shift(1)) & (c < o.shift(1))
    twb = ~is_up_p & is_up & (lowerwick / lowerwick.shift(1).replace(0, np.nan) >= 0.99) & (
        l / l.shift(1).replace(0, np.nan) >= 0.99
    )
    twt = is_up_p & ~is_up & (upperwick / upperwick.shift(1).replace(0, np.nan) >= 0.99) & (
        h / h.shift(1).replace(0, np.nan) >= 0.99
    )

    tws = ~is_up_p3 & is_up_p2 & is_up_p & is_up & (
        body.shift(1) > body.shift(2)
    ) & (upperwick < 0.1 * body) & (lowerwick < 0.1 * body)
    tbc = is_up_p3 & ~is_up_p2 & ~is_up_p & ~is_up & (
        body.shift(1) > body.shift(2)
    ) & (upperwick < 0.1 * body) & (lowerwick < 0.1 * body)
    ms = ~is_up_p & ((c.shift(1) - o.shift(1)).abs() / rng.shift(1) < 0.1) & (
        c < oc2.shift(2)
    ) & (c > o.shift(2))
    es = is_up_p & ((c.shift(1) - o.shift(1)).abs() / rng.shift(1) < 0.1) & (
        c > oc2.shift(2)
    ) & (c < o.shift(2))
    tiu = ~is_up_p2 & (c.shift(1) > oc2.shift(2)) & (c.shift(1) < o.shift(2)) & (c > h.shift(2))
    tid = is_up_p2 & (c.shift(1) < oc2.shift(2)) & (c.shift(1) > o.shift(2)) & (c < l.shift(2))

    cs_short = (bm | hg | ss | beare | twt | tbc | es | tid).fillna(False)
    cs_long = (wm | hm | ih | bulle | twb | tws | ms | tiu).fillna(False)
    return DataFrame({"cs_long": cs_long, "cs_short": cs_short}, index=df.index)
