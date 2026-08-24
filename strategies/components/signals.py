"""Reusable signal-building helpers extracted from user_data/strategies.

All helpers are pure functions on DataFrames and return boolean Series or
mutated DataFrames, so they compose directly inside ``populate_entry_trend`` /
``populate_exit_trend``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import reduce

import numpy as np
import pandas as pd
from pandas import DataFrame, Series


def crossed_above(left: Series, right: Series | float) -> Series:
    """Pine ``ta.crossover``: left rises above right between two candles."""
    previous = right.shift(1) if isinstance(right, Series) else right
    return ((left > right) & (left.shift(1) <= previous)).fillna(False)


def crossed_below(left: Series, right: Series | float) -> Series:
    """Pine ``ta.crossunder``: left drops below right between two candles."""
    previous = right.shift(1) if isinstance(right, Series) else right
    return ((left < right) & (left.shift(1) >= previous)).fillna(False)


def crossed(left: Series, right: Series | float) -> Series:
    """Pine ``ta.cross``: either crossover or crossunder."""
    return (crossed_above(left, right) | crossed_below(left, right)).fillna(False)


def combine(conditions: Iterable[Series], mode: str = "OR") -> Series:
    """Reduce a list of boolean Series to one mask (``OR`` or ``AND``)."""
    conditions = [c.fillna(False).astype(bool) for c in conditions if c is not None]
    if not conditions:
        return pd.Series(False, index=pd.Index([]))
    if len(conditions) == 1:
        return conditions[0]
    op = (lambda x, y: x | y) if mode.upper() == "OR" else (lambda x, y: x & y)
    return reduce(op, conditions)


def apply_conditions(
    df: DataFrame,
    conditions: Sequence[tuple[Series, str]],
    *,
    column: str = "enter_long",
    tag_column: str = "enter_tag",
) -> DataFrame:
    """Set ``column`` = 1 and optionally ``tag_column`` per condition.

    ``conditions`` is a list of ``(mask, tag_or_None)`` pairs. Masks are OR'ed
    into ``column``; tags are written per-mask so backtests keep each entry's
    origin.
    """
    total: Series | None = None
    for mask, tag in conditions:
        mask = mask.fillna(False).astype(bool)
        df.loc[mask, column] = 1
        if tag and tag_column and tag_column in df.columns:
            df.loc[mask, tag_column] = tag
        total = mask if total is None else (total | mask)
    if total is not None:
        df.loc[~total, column] = df[column].fillna(0)
    return df


def suppress_same_candle_exit(
    df: DataFrame, entry: str = "enter_long", exit_: str = "exit_long"
) -> DataFrame:
    """Clear an exit signal on candles that also produce an entry signal."""
    if entry in df.columns and exit_ in df.columns:
        df.loc[df[entry] == 1, exit_] = 0
    return df


# ---------------------------------------------------------------------------
# Volume / pump protection filters (BigZ06 / BigZ07 / Nostalgia family)
# ---------------------------------------------------------------------------
def volume_pump_drop_filter(
    df: DataFrame,
    pump_mult: float = 0.4,
    drop_mult: float = 3.8,
    lookback: int = 48,
    volume_col: str = "volume",
) -> tuple[Series, Series]:
    """Nostalgia-style volume regime guards.

    ``pump_ok`` is True when the slow volume mean is relatively flat (no fresh
    pump); ``drop_ok`` is True when the latest volume dropped vs the previous
    candle (no volume spike). Both must be True for dip-buying entries.
    """
    slow = df[volume_col].rolling(window=lookback).mean()
    pump_ok = (slow > slow.shift(lookback) * pump_mult) & (
        slow * pump_mult < slow.shift(lookback)
    )
    drop_ok = df[volume_col] < df[volume_col].shift() * drop_mult
    return pump_ok.fillna(False), drop_ok.fillna(False)


def volume_mean_filter(df: DataFrame, length: int = 48, volume_col: str = "volume") -> Series:
    return df[volume_col].rolling(window=length).mean()


def safe_pump(
    df: DataFrame,
    length: int,
    thresh: float,
    pull_thresh: float,
    oc_pct_col: str | None = None,
) -> Series:
    """Entry-after-pump safety: low open->close change OR pulled back enough."""
    from . import indicators

    oc_pct = df[oc_pct_col] if oc_pct_col else indicators.range_percent_change(df, length, "OC")
    maxgap = indicators.range_maxgap(df, length)
    height = indicators.range_height(df, length)
    return (oc_pct < thresh) | (maxgap / pull_thresh > height)


def safe_dips(
    df: DataFrame,
    thresh_0: float,
    thresh_2: float,
    thresh_12: float,
    thresh_144: float,
) -> Series:
    """Dip safety: top-percentage-change below thresholds at multiple lookbacks."""
    from . import indicators

    return (
        (indicators.top_percent_change(df, 0) < thresh_0)
        & (indicators.top_percent_change(df, 2) < thresh_2)
        & (indicators.top_percent_change(df, 12) < thresh_12)
        & (indicators.top_percent_change(df, 144) < thresh_144)
    )


# ---------------------------------------------------------------------------
# Regime helpers
# ---------------------------------------------------------------------------
def trend_filter(
    df: DataFrame, close_col: str = "close", ma_col: str = "ema", above: bool = True
) -> Series:
    return df[close_col] > df[ma_col] if above else df[close_col] < df[ma_col]


def htf_bull_bear(
    df: DataFrame,
    ppo_col: str = "ppo_1h",
    signal_col: str = "ppo_signal_1h",
    vwap_col: str = "vwap_1h",
    close_col: str = "close",
) -> tuple[Series, Series]:
    """Higher-timeframe bull/bear regime: PPO sign/alignment + price vs VWAP."""
    ppo_series = df[ppo_col]
    signal = df[signal_col]
    bull = (ppo_series > 0) & (ppo_series > signal) & (df[close_col] > df[vwap_col])
    bear = (ppo_series < 0) & (ppo_series < signal) & (df[close_col] < df[vwap_col])
    return bull.fillna(False), bear.fillna(False)


def tag_conditions(
    masks: dict[str, Series], prefix: str = "enter"
) -> list[tuple[Series, str]]:
    """Convert ``{name: mask}`` to the ``[(mask, f"{prefix}_{name}")]`` format."""
    return [(mask, f"{prefix}_{name}") for name, mask in masks.items()]


# ---------------------------------------------------------------------------
# Pine Strategy Template order-management helpers (vectorized)
# ---------------------------------------------------------------------------
def bar_delay_signal(signal: Series, delay_length: int = 1) -> Series:
    """Pine ``entryBarDelay``: re-emit a signal ``delay_length`` bars after the
    last signal bar."""
    signal = signal.fillna(False).astype(bool)
    delay_length = max(1, int(delay_length))
    idx = np.flatnonzero(signal.to_numpy())
    out = np.zeros(len(signal), dtype=bool)
    if len(idx):
        for j in idx:
            target = j + delay_length
            if target < len(out):
                out[target] = True
    return Series(out, index=signal.index)


def entry_delay_signal(signal: Series, delay: int = 1) -> Series:
    """Pine ``entryDelay``: emit once the signal has been True for
    ``delay + 1`` consecutive bars."""
    signal = signal.fillna(False).astype(bool)
    delay = max(1, int(delay))
    groups = (~signal).cumsum()
    run = signal.groupby(groups).cumsum()
    return (run == (delay + 1)).fillna(False)


def entries_per_cycle_gate(
    enter_long: Series, enter_short: Series, entries_per_cycle: int = 1
) -> tuple[Series, Series]:
    """Pine ``entriesPerCycle``: block repeats on one side until the opposite
    side signals. Returns ``(enter_long, enter_short)`` with repeats removed."""
    enter_long = enter_long.fillna(False).astype(bool)
    enter_short = enter_short.fillna(False).astype(bool)
    n = len(enter_long)
    entries_per_cycle = max(1, int(entries_per_cycle))
    blocked: str | None = None
    long_out = np.zeros(n, dtype=bool)
    short_out = np.zeros(n, dtype=bool)
    long_count = 0
    short_count = 0
    for i in range(n):
        if enter_short[i] and blocked != "short":
            short_count += 1
        if enter_long[i] and blocked != "long":
            long_count += 1
        # Pine blocks on the (entriesPerCycle + 1)-th consecutive signal.
        if short_count >= entries_per_cycle + 1 and enter_short[i]:
            blocked = "short"
            short_count = 0
        if long_count >= entries_per_cycle + 1 and enter_long[i]:
            blocked = "long"
            long_count = 0
        if enter_short[i]:
            long_count = 0
            if blocked == "long":
                blocked = None
        if enter_long[i]:
            short_count = 0
            if blocked == "short":
                blocked = None
        long_out[i] = enter_long[i] and blocked != "long"
        short_out[i] = enter_short[i] and blocked != "short"
    return Series(long_out, index=enter_long.index), Series(short_out, index=enter_short.index)


def exit_on_opposite_entry(
    enter_long: Series,
    enter_short: Series,
    exit_long: Series,
    exit_short: Series,
    exit_enabled: bool = True,
    block_opposite: bool = False,
) -> tuple[Series, Series, Series, Series]:
    """Pine ``isExitOnOppositeEntryEnabled``: an opposite entry signal forces an
    exit of the current side. Optionally blocks that opposite entry when the
    current side already had an exit signal (position gating — e.g. blocking a
    fresh entry on the same candle as an exit — is handled in
    ``confirm_trade_entry`` where the open position is known)."""
    enter_long = enter_long.fillna(False).astype(bool)
    enter_short = enter_short.fillna(False).astype(bool)
    exit_long = exit_long.fillna(False).astype(bool)
    exit_short = exit_short.fillna(False).astype(bool)
    if not exit_enabled:
        return enter_long, enter_short, exit_long, exit_short
    orig_exit_long = exit_long.copy()
    orig_exit_short = exit_short.copy()
    exit_long = exit_long | enter_short
    exit_short = exit_short | enter_long
    if block_opposite:
        enter_short = enter_short & ~orig_exit_long
        enter_long = enter_long & ~orig_exit_short
    return enter_long, enter_short, exit_long, exit_short


def suppress_same_side(signal: Series) -> Series:
    """Only keep the first bar of consecutive signal runs."""
    signal = signal.fillna(False).astype(bool)
    return signal & ~signal.shift(1).fillna(False)
