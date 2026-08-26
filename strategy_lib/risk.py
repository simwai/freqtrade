"""
strategy_lib.risk

Reusable structural risk-management engine for SL/TP strategies.

The level engine computes per-trade stop-loss / take-profit level series for the
same modes as the TradingView "Octopus Nest" strategy (Percentual, ATR, Highest
Lowest, Trailing variants, and Highest Lowest + ATR). Strategies that want this
behaviour only need to:

* build an :class:`SlTpConfig` from their hyperopt parameters,
* own a :class:`TradeLevelsManager`,
* call :func:`exit_cross_signal` / :func:`duration_exceeded` from
  ``custom_exit`` and use :meth:`TradeLevelsManager.current_trade_levels` in
  ``custom_stoploss``.

The module is free of strategy state: levels depend only on the dataframe, the
entry price and the configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from strategy_lib import indicators


# Upper bound for cached per-trade level series in TradeLevelsManager.
_MAX_TRADE_LEVEL_CACHE_ENTRIES = 512


@dataclass
class SlTpConfig:
    """Immutable-ish snapshot of SL/TP parameters for one mode."""

    mode: str = "Percentual"
    sl_size_or_atr_multiplier: float = 2.0
    # Optional independent short-side multiplier for the ATR-family modes. When
    # None the short side uses ``sl_size_or_atr_multiplier``.
    sl_size_or_atr_multiplier_short: float | None = None
    risk_reward_ratio: float = 1.05
    my_backup_multiplier: float = 1.1
    max_trade_duration_days: int = 7
    high_low_stop_loss_lookback: int = 20
    high_low_stop_loss_multiplier: float = 0.98
    atr_length: int = 14
    # When False the level engine leaves the TP series empty so a strategy that
    # manages take-profits via ROI / exit signals / custom_exit is unaffected.
    enable_take_profit: bool = True
    # "Time Cut": tight stop after the trade has been open N minutes.
    time_cut_minutes: int = 0
    time_cut_percent: float = 0.01
    # "Trailing Profit Tier": profit-tiered trailing stop (ClucHAnix BB_RPB_TSL).
    tier_p_hsl: float = -0.08
    tier_p_pf_1: float = 0.011
    tier_p_sl_1: float = 0.011
    tier_p_pf_2: float = 0.064
    tier_p_sl_2: float = 0.062
    # "Entry Candle High Low": buffer applied to the entry candle's high/low.
    entry_candle_buffer: float = 0.02

    def signature(self) -> tuple:
        return (
            self.mode,
            self.sl_size_or_atr_multiplier,
            self.sl_size_or_atr_multiplier_short,
            self.risk_reward_ratio,
            self.my_backup_multiplier,
            self.max_trade_duration_days,
            self.high_low_stop_loss_lookback,
            self.high_low_stop_loss_multiplier,
            self.atr_length,
            self.enable_take_profit,
            self.time_cut_minutes,
            self.time_cut_percent,
            self.tier_p_hsl,
            self.tier_p_pf_1,
            self.tier_p_sl_1,
            self.tier_p_pf_2,
            self.tier_p_sl_2,
            self.entry_candle_buffer,
        )


def percentual_trade_levels(entry_price: float, config: SlTpConfig) -> dict[str, float] | None:
    """Entry-constant SL/TP levels for the Percentual mode (no arrays needed)."""
    if not entry_price or not np.isfinite(entry_price):
        return None
    percent = config.sl_size_or_atr_multiplier / 100.0
    levels = {
        "long_stop": entry_price * (1.0 - percent),
        "short_stop": entry_price * (1.0 + percent),
    }
    if config.enable_take_profit:
        levels["long_tp"] = entry_price * (1.0 + percent * config.risk_reward_ratio)
        levels["short_tp"] = entry_price * (1.0 - percent * config.risk_reward_ratio)
    else:
        levels["long_tp"] = np.nan
        levels["short_tp"] = np.nan
    return levels


def compute_trade_levels(  # noqa: C901
    dataframe: DataFrame,
    entry_price: float,
    entry_index: int,
    config: SlTpConfig,
) -> dict[str, np.ndarray] | None:
    """
    Build full-length SL/TP level arrays for a trade, anchored at ``entry_price``.

    Returns a dict of ``np.ndarray`` (``long_stop``, ``short_stop``, ``long_tp``,
    ``short_tp`` and ``entry_index``) or ``None`` if the levels are undefined.
    """
    if dataframe.empty:
        return None

    close = dataframe["close"].to_numpy(dtype=float)
    low = dataframe["low"].to_numpy(dtype=float)
    high = dataframe["high"].to_numpy(dtype=float)
    if "hann_atr" in dataframe:
        atr = dataframe["hann_atr"].to_numpy(dtype=float)
    else:
        atr = indicators.hann_atr(high, low, close, config.atr_length)

    if entry_index >= len(dataframe) or not np.isfinite(close[entry_index]):
        return None
    if not entry_price or not np.isfinite(entry_price):
        return None

    mode = config.mode
    multiplier = config.sl_size_or_atr_multiplier
    short_multiplier = config.sl_size_or_atr_multiplier_short or multiplier
    ratio = config.risk_reward_ratio
    lookback = config.high_low_stop_loss_lookback
    long_stop = np.full(len(dataframe), np.nan, dtype=float)
    short_stop = np.full(len(dataframe), np.nan, dtype=float)
    long_tp = np.full(len(dataframe), np.nan, dtype=float)
    short_tp = np.full(len(dataframe), np.nan, dtype=float)

    if mode in ("Percentual", "Trailing Percentual"):
        percent = multiplier / 100.0
        temp_long = close * (1.0 - percent)
        temp_short = close * (1.0 + percent)
        entry_long_stop = entry_price * (1.0 - percent)
        entry_short_stop = entry_price * (1.0 + percent)
        if mode == "Percentual":
            long_stop[entry_index:] = entry_long_stop
            short_stop[entry_index:] = entry_short_stop
            if config.enable_take_profit:
                long_tp[entry_index:] = entry_price * (1.0 + percent * ratio)
                short_tp[entry_index:] = entry_price * (1.0 - percent * ratio)
        else:
            temp_long[entry_index] = entry_long_stop
            temp_short[entry_index] = entry_short_stop
            long_stop[entry_index:] = np.maximum.accumulate(temp_long[entry_index:])
            short_stop[entry_index:] = np.minimum.accumulate(temp_short[entry_index:])
            if config.enable_take_profit:
                long_tp[entry_index] = entry_price * (1.0 + percent * ratio)
                short_tp[entry_index] = entry_price * (1.0 - percent * ratio)
                long_tp[entry_index + 1 :] = close[entry_index + 1 :] * (1.0 + percent * ratio)
                short_tp[entry_index + 1 :] = close[entry_index + 1 :] * (1.0 - percent * ratio)

    elif mode in ("ATR", "Trailing ATR"):
        temp_long = close - atr * multiplier
        temp_short = close + atr * short_multiplier
        entry_long_stop = entry_price - atr[entry_index] * multiplier
        entry_short_stop = entry_price + atr[entry_index] * short_multiplier
        if mode == "ATR":
            long_stop[entry_index:] = entry_long_stop
            short_stop[entry_index:] = entry_short_stop
            if config.enable_take_profit:
                long_tp[entry_index:] = entry_price + atr[entry_index] * multiplier * ratio
                short_tp[entry_index:] = entry_price - atr[entry_index] * multiplier * ratio
        else:
            temp_long[entry_index] = entry_long_stop
            temp_short[entry_index] = entry_short_stop
            long_stop[entry_index:] = np.maximum.accumulate(temp_long[entry_index:])
            short_stop[entry_index:] = np.minimum.accumulate(temp_short[entry_index:])
            if config.enable_take_profit:
                long_tp[entry_index] = entry_price + atr[entry_index] * multiplier * ratio
                short_tp[entry_index] = entry_price - atr[entry_index] * multiplier * ratio
                long_tp[entry_index + 1 :] = (
                    close[entry_index + 1 :] + atr[entry_index + 1 :] * multiplier * ratio
                )
                short_tp[entry_index + 1 :] = (
                    close[entry_index + 1 :] - atr[entry_index + 1 :] * multiplier * ratio
                )

    elif mode in ("Highest Lowest", "Trailing Highest Lowest"):
        lowest = pd.Series(low, index=dataframe.index).rolling(lookback).min().to_numpy()
        highest = pd.Series(high, index=dataframe.index).rolling(lookback).max().to_numpy()
        # Backup anchors on the opposite extreme (Pine reference): a fresh
        # breakout extreme still yields a sane stop via the backup multiplier.
        long_backup_stop = np.roll(high, 2)
        short_backup_stop = np.roll(low, 2)
        long_backup_stop[:2] = lowest[:2]
        short_backup_stop[:2] = highest[:2]
        temp_long = np.where(
            lowest == low,
            long_backup_stop * config.my_backup_multiplier,
            lowest * config.high_low_stop_loss_multiplier,
        )
        temp_short = np.where(
            highest == high,
            short_backup_stop * (2.0 - config.my_backup_multiplier),
            highest * (2.0 - config.high_low_stop_loss_multiplier),
        )
        if mode == "Highest Lowest":
            long_stop[entry_index:] = temp_long[entry_index]
            short_stop[entry_index:] = temp_short[entry_index]
        else:
            long_stop[entry_index:] = np.maximum.accumulate(temp_long[entry_index:])
            short_stop[entry_index:] = np.minimum.accumulate(temp_short[entry_index:])
        long_risk = max(entry_price - long_stop[entry_index], np.finfo(float).eps)
        short_risk = max(short_stop[entry_index] - entry_price, np.finfo(float).eps)
        if config.enable_take_profit:
            long_tp[entry_index:] = entry_price + long_risk * ratio
            short_tp[entry_index:] = entry_price - short_risk * ratio

    elif mode == "Highest Lowest + ATR":
        lowest = pd.Series(low, index=dataframe.index).rolling(lookback).min().to_numpy()
        highest = pd.Series(high, index=dataframe.index).rolling(lookback).max().to_numpy()
        atr_buffer = atr * multiplier
        atr_buffer_short = atr * short_multiplier
        level_pad = abs(1.0 - config.high_low_stop_loss_multiplier)
        temp_long = np.maximum((lowest - atr_buffer) * (1.0 - level_pad), 0.0)
        temp_short = (highest + atr_buffer_short) * (1.0 + level_pad)
        long_stop[entry_index:] = np.maximum.accumulate(temp_long[entry_index:])
        short_stop[entry_index:] = np.minimum.accumulate(temp_short[entry_index:])
        long_risk = max(entry_price - long_stop[entry_index], np.finfo(float).eps)
        short_risk = max(short_stop[entry_index] - entry_price, np.finfo(float).eps)
        if config.enable_take_profit:
            long_tp[entry_index:] = entry_price + long_risk * ratio
            short_tp[entry_index:] = entry_price - short_risk * ratio

    elif mode == "Trailing ATR Candle":
        # Anchor the ATR stop on the candle low/high (LuxAlgo style) instead of
        # the close, ratcheting only in the favorable direction.
        temp_long = low - atr * multiplier
        temp_short = high + atr * short_multiplier
        temp_long[entry_index] = entry_price - atr[entry_index] * multiplier
        temp_short[entry_index] = entry_price + atr[entry_index] * short_multiplier
        long_stop[entry_index:] = np.maximum.accumulate(temp_long[entry_index:])
        short_stop[entry_index:] = np.minimum.accumulate(temp_short[entry_index:])
        if config.enable_take_profit:
            long_tp[entry_index:] = entry_price + atr[entry_index] * multiplier * ratio
            short_tp[entry_index:] = entry_price - atr[entry_index] * multiplier * ratio

    elif mode == "Time Cut":
        # Tight stop at ``close * (1 +/- time_cut_percent)`` once the trade has
        # been open at least ``time_cut_minutes`` and is in the red. Before that
        # (or while in profit) the stop is NaN, so the strategy's ``stoploss``
        # attribute acts as the hard loss floor.
        minutes = int(config.time_cut_minutes)
        if minutes > 0 and len(dataframe) > 1:
            try:
                bar_minutes = (
                    dataframe["date"].iloc[1] - dataframe["date"].iloc[0]
                ).total_seconds() / 60.0
            except Exception:
                bar_minutes = 5.0
            if not np.isfinite(bar_minutes) or bar_minutes <= 0:
                bar_minutes = 5.0
            bars = max(1, round(minutes / bar_minutes))
            start = entry_index + bars
            if start < len(dataframe):
                losing_long = close[start:] < entry_price
                losing_short = close[start:] > entry_price
                long_stop[start:] = np.where(
                    losing_long, close[start:] * (1.0 - config.time_cut_percent), np.nan
                )
                short_stop[start:] = np.where(
                    losing_short, close[start:] * (1.0 + config.time_cut_percent), np.nan
                )
        # TP stays NaN: exits are driven by the tight stop / signal exits.

    elif mode == "Trailing Profit Tier":
        # Profit-tiered trailing anchored on the open rate (ClucHAnix BB_RPB_TSL).
        # When the tiered stop is at/above the current profit, fall back to a
        # tight 1% stop (mirrors returning 0.01 from custom_stoploss).
        for i in range(entry_index, len(dataframe)):
            profit = close[i] / entry_price - 1.0
            if profit > config.tier_p_pf_2:
                sl_profit = config.tier_p_sl_2 + (profit - config.tier_p_pf_2)
            elif profit > config.tier_p_pf_1:
                if config.tier_p_pf_2 > config.tier_p_pf_1:
                    sl_profit = config.tier_p_sl_1 + (
                        (profit - config.tier_p_pf_1)
                        * (config.tier_p_sl_2 - config.tier_p_sl_1)
                        / (config.tier_p_pf_2 - config.tier_p_pf_1)
                    )
                else:
                    sl_profit = config.tier_p_sl_2
            else:
                sl_profit = config.tier_p_hsl
            if sl_profit >= profit:
                long_stop[i] = close[i] * (1.0 - 0.01)
                short_stop[i] = close[i] * (1.0 + 0.01)
            else:
                long_stop[i] = entry_price * (1.0 + sl_profit)
                short_stop[i] = entry_price * (1.0 - sl_profit)

    elif mode == "Entry Candle High Low":
        # Stop at the entry candle's high/low with a buffer, floored (long) /
        # capped (short) at the same buffer off the current close. freqtrade's
        # stoploss ratchet keeps the stop from loosening (SuperKeltner style).
        buffer = config.entry_candle_buffer
        base_low = low[entry_index]
        base_high = high[entry_index]
        long_stop[entry_index:] = np.maximum(
            base_low * (1.0 - buffer), close[entry_index:] * (1.0 - buffer)
        )
        short_stop[entry_index:] = np.minimum(
            base_high * (1.0 + buffer), close[entry_index:] * (1.0 + buffer)
        )
        # TP stays NaN: take-profits are managed by ROI / exit signals.

    else:
        return None

    return {
        "entry_index": np.array([entry_index]),
        "long_stop": long_stop,
        "short_stop": short_stop,
        "long_tp": long_tp,
        "short_tp": short_tp,
    }


def levels_at(levels: dict[str, np.ndarray], index: int) -> dict[str, float]:
    """Slice the level arrays at a single bar index."""
    return {
        "long_stop": float(levels["long_stop"][index]),
        "short_stop": float(levels["short_stop"][index]),
        "long_tp": float(levels["long_tp"][index]),
        "short_tp": float(levels["short_tp"][index]),
    }


def exit_cross_signal(
    previous_close: float,
    current_close: float,
    previous_levels: dict[str, float],
    current_levels: dict[str, float],
    is_short: bool,
) -> str | None:
    """
    Detect an SL/TP candle cross against the previous/current level series.

    Returns an exit reason tag (``EXIT_*_TP`` / ``EXIT_*_SL``) or ``None``.
    """
    if is_short:
        stop_crossed = (
            previous_close <= previous_levels["short_stop"]
            and current_close > current_levels["short_stop"]
        )
        take_profit_crossed = (
            previous_close >= previous_levels["short_tp"]
            and current_close < current_levels["short_tp"]
        )
        if take_profit_crossed:
            return "EXIT_SHORT_TP"
        if stop_crossed:
            return "EXIT_SHORT_SL"
        return None

    stop_crossed = (
        previous_close >= previous_levels["long_stop"]
        and current_close < current_levels["long_stop"]
    )
    take_profit_crossed = (
        previous_close <= previous_levels["long_tp"] and current_close > current_levels["long_tp"]
    )
    if take_profit_crossed:
        return "EXIT_LONG_TP"
    if stop_crossed:
        return "EXIT_LONG_SL"
    return None


def duration_exceeded(open_date: datetime, current_time: datetime, max_days: int) -> bool:
    """True if the trade has been open at least ``max_days`` days."""
    return current_time - open_date >= pd.Timedelta(days=max_days)


class TradeLevelsManager:
    """
    Cache-aware facade around :func:`compute_trade_levels`.

    Holds a :class:`SlTpConfig` and caches computed level series per
    ``(pair, trade, dataframe-last-date)``. The cache is invalidated whenever the
    configuration signature changes (e.g. between hyperopt epochs), so a single
    manager can be reused across the strategy's lifetime.
    """

    def __init__(self, config: SlTpConfig):
        self.config = config
        self._signature: tuple | None = None
        self._cache: dict[tuple, dict[str, np.ndarray] | None] = {}

    def invalidate(self) -> None:
        self._signature = None
        self._cache = {}

    def _ensure_signature(self) -> None:
        sig = self.config.signature()
        if sig != self._signature:
            self._signature = sig
            self._cache = {}

    def _evict_cache(self) -> None:
        # Bounds memory in long backtests: dict preserves insertion order, so
        # dropping the oldest half evicts the least recently added trades.
        if len(self._cache) >= _MAX_TRADE_LEVEL_CACHE_ENTRIES:
            for key in list(self._cache)[: len(self._cache) // 2]:
                del self._cache[key]

    def trade_level_series(
        self, dataframe: DataFrame, trade: Trade, timeframe: str
    ) -> dict[str, np.ndarray] | None:
        if dataframe.empty:
            return None
        entry_index = indicators.find_entry_index(dataframe, trade, timeframe)
        return compute_trade_levels(dataframe, float(trade.open_rate), entry_index, self.config)

    def cached_trade_level_series(
        self, pair: str, dataframe: DataFrame, trade: Trade, timeframe: str
    ) -> dict[str, np.ndarray] | None:
        """Level series for ``trade``, cached against the dataframe's last date."""
        self._ensure_signature()
        cache_key = (pair, trade.open_date_utc, dataframe["date"].iloc[-1])
        if cache_key not in self._cache:
            self._evict_cache()
            self._cache[cache_key] = self.trade_level_series(dataframe, trade, timeframe)
        return self._cache[cache_key]

    def current_trade_levels(
        self, pair: str, dataframe: DataFrame, trade: Trade, timeframe: str
    ) -> dict[str, float] | None:
        """Levels at the latest bar for ``trade``."""
        if self.config.mode == "Percentual":
            return percentual_trade_levels(float(trade.open_rate), self.config)
        levels = self.cached_trade_level_series(pair, dataframe, trade, timeframe)
        if levels is None:
            return None
        index = len(dataframe) - 1
        return levels_at(levels, index)
