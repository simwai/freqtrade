"""Pine Strategy Template filters, ported as reusable ``Filter`` classes.

Each filter mirrors the Pine template's inputs (matching defaults), computes
``long_allowed`` / ``short_allowed`` boolean Series on the base dataframe and
(optionally) a merged higher-timeframe informative frame, and defaults to
``True`` when disabled exactly like Pine's ``isXEnabled ? condition : true``.

Confirmation-mode filters (PSAR, MFI, Stoch, ROC, Candlestick) do not modify
the filter signal; instead they gate the raw entry/exit signals through
:func:`confirmation_gate`, which replays Pine's per-bar counter state machine
(start a ``lookback`` window on signal, suppress it, and re-inject it the bar
the filter condition turns true).

Known Pine deviations are documented inline; the most important is the FIR
filter which in the template always evaluates to ``True`` (its ternary
re-checks the same conditions it gated on) — here it is implemented as
intended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from . import indicators as ind

_PI = 3.141592653589793


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def nz(series: Series, default: float = 0.0) -> Series:
    return series.fillna(default)


def normalize_resolution(resolution: str | None) -> str:
    """Convert Pine-style timeframes to freqtrade format.

    ``"15"`` -> ``"15m"``, ``"240"`` -> ``"4h"``, ``"1D"`` -> ``"1d"``;
    ``"1h"``/``"4h"``/``"1d"``/``"1w"`` pass through unchanged.
    """
    if not resolution:
        return ""
    import re

    match = re.fullmatch(r"(\d+)([smhDWM]?)", resolution.strip())
    if not match:
        return resolution
    number, unit = match.group(1), match.group(2) or "m"
    mapping = {"m": "m", "h": "h", "D": "d", "W": "w", "M": "M", "s": "s"}
    return f"{int(number)}{mapping[unit]}"


def _pick(df: DataFrame, base_col: str, resolution: str, base_tf: str) -> Series:
    """Pick the HTF-merged column when a different resolution is requested."""
    resolution = normalize_resolution(resolution)
    if resolution and resolution != base_tf:
        col = f"{base_col}_{resolution}"
        if col in df.columns:
            return df[col]
    return df[base_col]


def _adaptive_periods(df: DataFrame, src: str, base_len: int, cycle_part: float) -> Series:
    """Per-bar Ehlers Cyber Cycle length, or a constant when not adaptive."""
    from .ehlers import get_cyber_cycle

    return get_cyber_cycle(df[src], 2.0 / (base_len + 1.0), cycle_part)


def _adaptive_apply(
    series: Series, periods: Series, func: Callable[[np.ndarray], float]
) -> Series:
    """Apply ``func`` to a trailing window whose size varies per bar."""
    values = series.to_numpy(dtype=float)
    periods_arr = periods.to_numpy(dtype=int)
    out = np.full(len(series), np.nan, dtype=float)
    for i in range(len(values)):
        p = int(periods_arr[i])
        p = max(1, min(p, i + 1))
        out[i] = func(values[i - p + 1 : i + 1])
    return Series(out, index=series.index)


def confirmation_gate(raw: Series, allowed: Series, lookback: int) -> Series:
    """Pine confirmation-mode state machine.

    A raw signal starts a ``lookback`` window; while it runs the raw signal is
    suppressed. On each bar the filter ``allowed`` condition is tested and, if
    true, a confirmed signal is emitted and the window resets. If the window
    expires without a confirmation no signal is emitted.
    """
    raw_arr = raw.fillna(False).astype(bool).to_numpy(dtype=bool)
    allow_arr = allowed.fillna(False).astype(bool).to_numpy(dtype=bool)
    lookback = max(1, int(lookback))
    n = len(raw_arr)
    out = np.zeros(n, dtype=bool)
    counter = 0
    for i in range(n):
        if raw_arr[i] and counter == 0:
            counter = lookback
        if counter > 0:
            counter -= 1
            if allow_arr[i]:
                out[i] = True
                counter = 0
    return Series(out, index=raw.index)


@dataclass
class Filter:
    """Base filter: enabled flag + long/short allowance columns."""

    enabled: bool = False
    key: str = "filter"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        raise NotImplementedError

    def populate(self, df: DataFrame, base_tf: str = "5m") -> DataFrame:
        long_allowed, short_allowed = self.compute(df, base_tf)
        df[f"long_{self.key}"] = long_allowed.fillna(True)
        df[f"short_{self.key}"] = short_allowed.fillna(True)
        return df


# ---------------------------------------------------------------------------
# FIR trend filter
# ---------------------------------------------------------------------------
@dataclass
class FIRFilter(Filter):
    """Windowed-sinc FIR trend filter.

    Pine's template ternary always yields ``True`` (it re-tests the conditions
    it just gated on); this implements the intended ``firOut[htf] > 0`` logic.
    """

    length: int = 20
    harmonics: int = 20
    wave_type: str = "Square"
    resolution: str = ""
    htf_enabled: bool = False

    def __post_init__(self):
        self.key = "fir"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        if not self.enabled:
            true = Series(True, index=df.index)
            return true, true
        close = df["close"]
        htf_close = _pick(df, "close", self.resolution, base_tf)
        fir_out = ind.fir(close, self.length, self.harmonics, self.wave_type)
        fir_out_htf = ind.fir(htf_close, self.length, self.harmonics, self.wave_type)
        long = (fir_out_htf > 0) & ((~self.htf_enabled) | (fir_out > 0))
        short = (fir_out_htf < 0) & ((~self.htf_enabled) | (fir_out < 0))
        return long.fillna(True), short.fillna(True)


# ---------------------------------------------------------------------------
# Parabolic SAR filter
# ---------------------------------------------------------------------------
@dataclass
class PSARFilter(Filter):
    """Parabolic SAR trend/confirmation filter (sar above price = long allowed,
    mirroring the template's literal ``sar > close`` condition)."""

    start: float = 0.04
    increment: float = 0.04
    maximum: float = 0.215
    resolution: str = ""
    htf_enabled: bool = False
    mode: str = "Filter Mode"
    confirmation_lookback: int = 3

    def __post_init__(self):
        self.key = "sar"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled or self.mode != "Filter Mode":
            return true, true
        sar = ind.sar(df, self.start, self.increment, self.maximum).shift(1)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        long = (sar > htf_close) & ((~self.htf_enabled) | (sar > df["close"]))
        short = (sar < htf_close) & ((~self.htf_enabled) | (sar < df["close"]))
        return long.fillna(True), short.fillna(True)

    def allowed(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        """Unconditional allowance used by the confirmation gates."""
        sar = ind.sar(df, self.start, self.increment, self.maximum).shift(1)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        long = (sar > htf_close) & ((~self.htf_enabled) | (sar > df["close"]))
        short = (sar < htf_close) & ((~self.htf_enabled) | (sar < df["close"]))
        return long.fillna(False), short.fillna(False)


# ---------------------------------------------------------------------------
# MFI filter
# ---------------------------------------------------------------------------
@dataclass
class MFIFilter(Filter):
    """Money Flow Index: allowed when MFI is beyond the bands on the last
    decisive bar within ``lookback`` (Pine ``checkLastBarsMfi``)."""

    length: int = 12
    upper: float = 80.0
    lower: float = 20.0
    resolution: str = ""
    htf_enabled: bool = False
    mode: str = "Filter Mode"
    lookback: int = 3
    confirmation_lookback: int = 3
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "mfi"

    def _mfi(self, frame: DataFrame) -> Series:
        """MFI with ``source`` as the typical price (Pine ``ta.mfi(src, len)``)."""
        if self.adaptive:
            periods = _adaptive_periods(frame, "close", self.length, self.cycle_part)
            tp = frame["close"].to_numpy(dtype=float)
            raw = tp * frame["volume"].to_numpy(dtype=float)
            pos0 = np.where(tp > np.roll(tp, 1), raw, 0.0)
            neg0 = np.where(tp < np.roll(tp, 1), raw, 0.0)
            pos0[0] = 0.0
            neg0[0] = 0.0
            periods_arr = periods.to_numpy(dtype=int)
            out = np.full(len(frame), np.nan, dtype=float)
            for i in range(len(frame)):
                p = max(1, min(int(periods_arr[i]), i + 1))
                pos = pos0[i - p + 1 : i + 1].sum()
                neg = neg0[i - p + 1 : i + 1].sum()
                out[i] = 100.0 - 100.0 / (1.0 + pos / (neg + 1e-8))
            return Series(out, index=frame.index)
        return _mfi_shifted(frame, "close", self.length)

    def _decisive(self, frame: DataFrame) -> Series:
        mfi = self._mfi(frame)
        decisive = pd.Series(
            np.where(mfi < self.lower, 1.0, np.where(mfi > self.upper, 2.0, 0.0)),
            index=frame.index,
        )
        recent = decisive.replace(0.0, np.nan).ffill(limit=max(1, self.lookback - 1)).fillna(0.0)
        return recent

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled or self.mode != "Filter Mode":
            return true, true
        base_result = self._decisive(df)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        htf_result = self._decisive(DataFrame(df).assign(close=htf_close))
        long = (htf_result == 1.0) & ((~self.htf_enabled) | (base_result == 1.0))
        short = (htf_result == 2.0) & ((~self.htf_enabled) | (base_result == 2.0))
        return long.fillna(True), short.fillna(True)

    def allowed(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        base_result = self._decisive(df)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        htf_result = self._decisive(DataFrame(df).assign(close=htf_close))
        long = (htf_result == 1.0) & ((~self.htf_enabled) | (base_result == 1.0))
        short = (htf_result == 2.0) & ((~self.htf_enabled) | (base_result == 2.0))
        return long.fillna(False), short.fillna(False)


def _mfi_window(df: DataFrame, window: np.ndarray) -> float:
    return 0.0


def _mfi_shifted(df: DataFrame, src: str, length: int) -> Series:
    """MFI computed on ``src`` as the typical price (vectorized)."""
    tp = df[src]
    raw = tp * df["volume"]
    pos = raw.where(tp > tp.shift(1), 0.0).rolling(length).sum()
    neg = raw.where(tp < tp.shift(1), 0.0).rolling(length).sum()
    ratio = pos / (neg + 1e-8)
    return 100.0 - (100.0 / (1.0 + ratio))


# ---------------------------------------------------------------------------
# Chaikin volatility filter
# ---------------------------------------------------------------------------
@dataclass
class ChaikinFilter(Filter):
    """Long/short both allowed when Chaikin volatility is positive."""

    length: int = 21
    roc_length: int = 34
    resolution: str = ""
    htf_enabled: bool = False
    adaptive: bool = False
    cycle_part: float = 0.5
    roc_cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "chaikin"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        base = ind.chaikin_volatility(df, self.length, self.roc_length)
        htf = ind.chaikin_volatility(df, self.length, self.roc_length)
        allowed = (htf > 0) & ((~self.htf_enabled) | (base > 0))
        return allowed.fillna(True), allowed.fillna(True)


# ---------------------------------------------------------------------------
# CMO filter
# ---------------------------------------------------------------------------
@dataclass
class CMOFilter(Filter):
    """Chande Momentum Oscillator sign filter."""

    length: int = 120
    resolution: str = ""
    htf_enabled: bool = False
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "cmo"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        base = ind.cmo(df["close"], self.length)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        htf = ind.cmo(htf_close, self.length)
        long = (htf > 0) & ((~self.htf_enabled) | (base > 0))
        short = (htf < 0) & ((~self.htf_enabled) | (base < 0))
        return long.fillna(True), short.fillna(True)


# ---------------------------------------------------------------------------
# CMF filter
# ---------------------------------------------------------------------------
@dataclass
class CMFFilter(Filter):
    """Chaikin Money Flow sign filter."""

    length: int = 21
    resolution: str = ""
    htf_enabled: bool = False
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "cmf"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        base = ind.cmf(df, self.length)
        allowed = (base > 0) if not self.htf_enabled else base > 0
        long = (base > 0) & ((~self.htf_enabled) | (base > 0))
        short = (base < 0) & ((~self.htf_enabled) | (base < 0))
        return long.fillna(True), short.fillna(True)


# ---------------------------------------------------------------------------
# Aroon filter (+ sidetrend)
# ---------------------------------------------------------------------------
@dataclass
class AroonFilter(Filter):
    """Aroon oscillator sign filter (HTF by design, like the template)."""

    length: int = 10
    resolution: str = ""
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "aroon"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        htf_high = _pick(df, "high", self.resolution, base_tf)
        htf_low = _pick(df, "low", self.resolution, base_tf)
        osc = ind.aroon(DataFrame({"high": htf_high, "low": htf_low}), self.length)
        return (osc > 0).fillna(True), (osc < 0).fillna(True)


@dataclass
class AroonSidetrendFilter(Filter):
    """Aroon sidetrend filter: block trades while the aroon slopes are equal."""

    sidetrend_mode: str = "I want trending market"
    resolution: str = ""

    def __post_init__(self):
        self.key = "aroon_sidetrend"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        htf_high = _pick(df, "high", self.resolution, base_tf)
        htf_low = _pick(df, "low", self.resolution, base_tf)
        bands = ind.aroon_upper_lower(DataFrame({"high": htf_high, "low": htf_low}), 10)
        sidetrend = ind.aroon_sidetrend(bands)
        if self.sidetrend_mode == "I want trending market":
            allowed = ~sidetrend
        else:
            allowed = sidetrend
        return allowed.fillna(True), allowed.fillna(True)


# ---------------------------------------------------------------------------
# Woodies CCI filter
# ---------------------------------------------------------------------------
@dataclass
class WoodiesCCIFilter(Filter):
    """Woodies CCI last-5-bars mode filter."""

    length: int = 7
    mode: str = "I want up or down trend"
    resolution: str = ""
    htf_enabled: bool = False

    def __post_init__(self):
        self.key = "woci"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        w = ind.woodies_cci(df, self.length)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        w_htf = ind.woodies_cci(DataFrame(df).assign(close=htf_close), self.length)
        green = w_htf["last5_is_up"] & ((~self.htf_enabled) | w["last5_is_up"])
        red = w_htf["last5_is_down"] & ((~self.htf_enabled) | w["last5_is_down"])
        if self.mode == "I want trending market":
            return green.fillna(True), green.fillna(True)
        if self.mode == "I want sideway market":
            return red.fillna(True), red.fillna(True)
        return green.fillna(True), red.fillna(True)


# ---------------------------------------------------------------------------
# Stochastic filter
# ---------------------------------------------------------------------------
@dataclass
class StochFilter(Filter):
    """Stochastic %K/%D bands filter (long above upper band, short below lower)."""

    k_length: int = 14
    d_length: int = 3
    smooth_k: int = 1
    upper: float = 80.0
    lower: float = 20.0
    resolution: str = ""
    htf_enabled: bool = False
    mode: str = "Filter Mode"
    confirmation_lookback: int = 3
    adaptive: bool = False
    k_cycle_part: float = 0.5
    d_cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "stoch"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled or self.mode != "Filter Mode":
            return true, true
        k, d = self._bands(df, base_tf)
        long = (k > self.upper) & (d > self.upper)
        short = (k < self.lower) & (d < self.lower)
        return long.fillna(True), short.fillna(True)

    def _bands(self, df: DataFrame, base_tf: str) -> tuple[Series, Series]:
        htf_high = _pick(df, "high", self.resolution, base_tf)
        htf_low = _pick(df, "low", self.resolution, base_tf)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        base = ind.stochastic(df, self.k_length, self.d_length, self.smooth_k)
        htf = ind.stochastic(
            DataFrame({"high": htf_high, "low": htf_low, "close": htf_close}),
            self.k_length, self.d_length, self.smooth_k,
        )
        return htf["stoch_k"], htf["stoch_d"]

    def allowed(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        k, d = self._bands(df, base_tf)
        base = ind.stochastic(df, self.k_length, self.d_length, self.smooth_k)
        long = (k > self.upper) & (d > self.upper)
        short = (k < self.lower) & (d < self.lower)
        if self.htf_enabled:
            long = long & (base["stoch_k"] > self.upper) & (base["stoch_d"] > self.upper)
            short = short & (base["stoch_k"] < self.lower) & (base["stoch_d"] < self.lower)
        return long.fillna(False), short.fillna(False)


# ---------------------------------------------------------------------------
# EWO filter
# ---------------------------------------------------------------------------
@dataclass
class EWOFilter(Filter):
    """Elliot Wave Oscillator (SMA fast - SMA slow) sign filter."""

    fast_length: int = 50
    slow_length: int = 200
    resolution: str = ""
    htf_enabled: bool = False

    def __post_init__(self):
        self.key = "ewo"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        base = ind.sma(df["close"], self.fast_length) - ind.sma(df["close"], self.slow_length)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        htf = ind.sma(htf_close, self.fast_length) - ind.sma(htf_close, self.slow_length)
        long = (htf > 0) & ((~self.htf_enabled) | (base > 0))
        short = (htf < 0) & ((~self.htf_enabled) | (base < 0))
        return long.fillna(True), short.fillna(True)


# ---------------------------------------------------------------------------
# Dual MA filter (+ convergence)
# ---------------------------------------------------------------------------
_MA_TYPES = {
    "SMA": ind.sma,
    "EMA": ind.ema,
    "RMA": ind.rma,
    "SMMA": ind.smma,
    "WMA": ind.wma,
    "HMA": ind.hma,
    "DEMA": ind.dema,
    "TEMA": ind.tema,
    "EHMA": ind.ehma,
    "KAMA": ind.kama,
    "VIDYA": ind.vidya,
}


def _ma(df: DataFrame, src: str, length: int, ma_type: str) -> Series:
    func = _MA_TYPES.get(ma_type, ind.ema)
    if ma_type == "VWMA":
        return ind.vwma(df, length)
    return func(df[src], length)


@dataclass
class DualMAFilter(Filter):
    """Dual moving-average trend filter on the HTF close."""

    fast_length: int = 50
    slow_length: int = 200
    fast_type: str = "EMA"
    slow_type: str = "EMA"
    resolution: str = "15"
    adaptive: bool = False
    fast_cycle_part: float = 0.5
    slow_cycle_part: float = 0.5
    convergence_enabled: bool = False

    def __post_init__(self):
        self.key = "dual_ma"

    def _mas(self, df: DataFrame, base_tf: str) -> tuple[Series, Series]:
        htf_close = _pick(df, "close", self.resolution, base_tf)
        frame = DataFrame({"close": htf_close, "volume": df["volume"]})
        fast = _ma(frame, "close", self.fast_length, self.fast_type)
        slow = _ma(frame, "close", self.slow_length, self.slow_type)
        return fast, slow

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        fast, slow = self._mas(df, base_tf)
        above = fast > slow
        below = fast < slow
        if self.convergence_enabled:
            not_conv = ~dual_ma_convergence(fast, slow)
            above = above & not_conv
            below = below & not_conv
        return above.fillna(True), below.fillna(True)


def dual_ma_convergence(fast: Series, slow: Series) -> Series:
    """Pine ``isOut1ConvergingFromDown or isOut1ConvergingFromUp`` state machine."""
    above = (fast > slow).to_numpy(dtype=bool)
    below = (fast < slow).to_numpy(dtype=bool)
    going_up = (fast > fast.shift(5)).fillna(False).to_numpy(dtype=bool)
    going_down = (fast < fast.shift(5)).fillna(False).to_numpy(dtype=bool)
    n = len(fast)
    conv_down = False
    conv_up = False
    out = np.zeros(n, dtype=bool)
    for i in range(n):
        if i > 0 and conv_down and above[i] and not above[i - 1]:
            conv_down = False
        if i > 0 and conv_up and below[i] and not below[i - 1]:
            conv_up = False
        if going_up[i] and below[i]:
            conv_down = True
        if going_down[i] and below[i]:
            conv_down = False
        if going_up[i] and above[i]:
            conv_up = False
        if going_down[i] and above[i]:
            conv_up = True
        out[i] = conv_down or conv_up
    return Series(out, index=fast.index)


# ---------------------------------------------------------------------------
# iTrend filter
# ---------------------------------------------------------------------------
@dataclass
class ItrendFilter(Filter):
    """Ehlers Instantaneous Trendline trigger filter (base hl2, as in Pine)."""

    length: float = 50.0

    def __post_init__(self):
        self.key = "itrend"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        hl2 = (df["high"] + df["low"]) / 2.0
        alpha = 2.0 / (self.length + 1.0)
        it = ind.ehlers_it(hl2, alpha)
        trigger = 2 * it - it.shift(2)
        return (trigger >= it).fillna(True), (trigger < it).fillna(True)


# ---------------------------------------------------------------------------
# Historical volatility filter (+ direction)
# ---------------------------------------------------------------------------
@dataclass
class VolatilityFilter(Filter):
    """Historical volatility regime filter (high vs low volatility modes)."""

    length: int = 33
    avg: int = 180
    sma_length: int = 35
    mode: str = "I want high volatile market"
    resolution: str = "15"
    include_source: bool = True
    include_volume: bool = True
    adaptive: bool = False
    cycle_part: float = 0.5
    sma_cycle_part: float = 0.5
    direction_enabled: bool = False

    def __post_init__(self):
        self.key = "volatility"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        htf_close = _pick(df, "close", self.resolution, base_tf)
        frame = DataFrame(df).assign(close=htf_close)
        hvd = ind.historical_volatility(
            frame, self.length, self.avg, self.sma_length,
            self.include_source, self.include_volume,
        )
        if self.mode == "I want high volatile market":
            allowed = hvd["hv"] > hvd["hv_sma"]
        else:
            allowed = hvd["hv"] < hvd["hv_sma"]
        if self.direction_enabled:
            allowed = allowed & (hvd["hv_sma"] > hvd["hv_sma"].shift(5))
        return allowed.fillna(True), allowed.fillna(True)


# ---------------------------------------------------------------------------
# Holt forecast filter
# ---------------------------------------------------------------------------
@dataclass
class ForecastFilter(Filter):
    """Holt's linear trend forecast: price above forecast is long-allowed."""

    alpha: float = 0.3
    beta: float = 1e-6
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "forecast"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        alpha = self.alpha
        if self.adaptive:
            periods = _adaptive_periods(df, "close", 20, self.cycle_part)
            alpha = Series(2.0 / (periods.to_numpy() + 1.0), index=df.index)
        h = ind.holt(df["close"], alpha, self.beta)
        forecast = h["level"] + h["trend"]
        return (forecast > df["close"]).fillna(True), (forecast < df["close"]).fillna(True)


# ---------------------------------------------------------------------------
# ROC filter
# ---------------------------------------------------------------------------
@dataclass
class ROCFilter(Filter):
    """Rate-of-change sign filter."""

    length: int = 9
    resolution: str = ""
    htf_enabled: bool = False
    mode: str = "Filter Mode"
    confirmation_lookback: int = 3
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "roc"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled or self.mode != "Filter Mode":
            return true, true
        long, short = self.allowed(df, base_tf)
        return long.fillna(True), short.fillna(True)

    def allowed(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        base = ind.roc(df["close"], self.length)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        htf = ind.roc(htf_close, self.length)
        long = (htf >= 0) & ((~self.htf_enabled) | (base >= 0))
        short = (htf < 0) & ((~self.htf_enabled) | (base < 0))
        return long.fillna(False), short.fillna(False)


# ---------------------------------------------------------------------------
# Candlestick pattern filter
# ---------------------------------------------------------------------------
@dataclass
class CandlestickFilter(Filter):
    """Candlestick pattern filter (any pattern in the last ``lookback`` bars)."""

    lookback: int = 3
    mode: str = "Filter Mode"
    confirmation_lookback: int = 3

    def __post_init__(self):
        self.key = "candlestick"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled or self.mode != "Filter Mode":
            return true, true
        pat = ind.candlestick_patterns(df)
        long = pat["cs_long"].rolling(max(1, self.lookback), min_periods=1).max() > 0
        short = pat["cs_short"].rolling(max(1, self.lookback), min_periods=1).max() > 0
        return long.fillna(True), short.fillna(True)

    def allowed(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        pat = ind.candlestick_patterns(df)
        long = pat["cs_long"].rolling(max(1, self.lookback), min_periods=1).max() > 0
        short = pat["cs_short"].rolling(max(1, self.lookback), min_periods=1).max() > 0
        return long.fillna(False), short.fillna(False)


# ---------------------------------------------------------------------------
# RSI filter
# ---------------------------------------------------------------------------
@dataclass
class RSIFilter(Filter):
    """RSI bands filter (long when oversold, short when overbought)."""

    length: int = 6
    upper: float = 60.0
    lower: float = 40.0
    resolution: str = ""
    htf_enabled: bool = False
    adaptive: bool = False
    cycle_part: float = 0.5

    def __post_init__(self):
        self.key = "rsi"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        base = ind.rsi(df, self.length)
        htf_close = _pick(df, "close", self.resolution, base_tf)
        htf = ind.rsi(DataFrame(df).assign(close=htf_close), self.length)
        long = (htf <= self.lower) & ((~self.htf_enabled) | (base <= self.lower))
        short = (htf > self.upper) & ((~self.htf_enabled) | (base > self.upper))
        return long.fillna(True), short.fillna(True)


# ---------------------------------------------------------------------------
# Chop zone filter
# ---------------------------------------------------------------------------
@dataclass
class ChopZoneFilter(Filter):
    """Ehlers chop-zone angle filter (trending vs sideway market modes)."""

    length: int = 30
    mode: str = "I want trending market"
    resolution: str = ""

    def __post_init__(self):
        self.key = "chop_zone"

    def compute(self, df: DataFrame, base_tf: str = "5m") -> tuple[Series, Series]:
        true = Series(True, index=df.index)
        if not self.enabled:
            return true, true
        htf_close = _pick(df, "close", self.resolution, base_tf)
        frame = DataFrame(df).assign(close=htf_close)
        cz = ind.chop_zone(frame, self.length)
        if self.mode == "I want sideway market":
            allowed = cz["choppy"]
        else:
            allowed = cz["trending"]
        return allowed.fillna(True), allowed.fillna(True)


# ---------------------------------------------------------------------------
# Filter combining
# ---------------------------------------------------------------------------
def combine_filter_signals(
    df: DataFrame, filters: Sequence[Filter], base_tf: str = "5m"
) -> tuple[Series, Series]:
    """AND all enabled filters' allowances (Pine ``longFilterSignal``)."""
    long = Series(True, index=df.index)
    short = Series(True, index=df.index)
    for filt in filters:
        if not filt.enabled:
            continue
        df = filt.populate(df, base_tf)
        long = long & df[f"long_{filt.key}"].fillna(True)
        short = short & df[f"short_{filt.key}"].fillna(True)
    return long.fillna(True), short.fillna(True)


# ---------------------------------------------------------------------------
# Confirmation-mode wiring helper
# ---------------------------------------------------------------------------
@dataclass
class ConfirmationFilter:
    """A confirmation-mode filter applied to raw entry/exit signals."""

    long_allowed: Callable[[DataFrame, str], Series] | None = None
    short_allowed: Callable[[DataFrame, str], Series] | None = None
    lookback: int = 3
    enabled: bool = True


def apply_confirmation_gates(
    enter_long: Series,
    enter_short: Series,
    exit_long: Series,
    exit_short: Series,
    filters: Sequence[ConfirmationFilter],
    df: DataFrame,
    base_tf: str = "5m",
) -> tuple[Series, Series, Series, Series]:
    """Re-route raw signals through each confirmation filter's state machine."""
    for filt in filters:
        if not filt.enabled:
            continue
        if filt.long_allowed is not None:
            enter_long = confirmation_gate(enter_long, filt.long_allowed(df, base_tf), filt.lookback)
            exit_long = confirmation_gate(exit_long, filt.long_allowed(df, base_tf), filt.lookback)
        if filt.short_allowed is not None:
            enter_short = confirmation_gate(enter_short, filt.short_allowed(df, base_tf), filt.lookback)
            exit_short = confirmation_gate(exit_short, filt.short_allowed(df, base_tf), filt.lookback)
    return enter_long, enter_short, exit_long, exit_short
