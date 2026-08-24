"""Pine Strategy Template take-profit levels, partial reduces and special exits.

The template closes a fraction of the position at each TP level (``reduce%``)
and lets the stoploss or an exit signal close the remainder. In freqtrade:

* partial reduces      -> :meth:`freqtrade.strategy.IStrategy.adjust_trade_position`
* full exits (signals) -> ``custom_exit``
* special exits        -> ``custom_exit`` (MA cross / PSAR / Bars / Z-score) or
                          a price-trailing stop (Tick)
* stoploss             -> ``custom_stoploss`` (see ``components.risk``)

``PartialTP`` keeps the per-level hit state in the trade's custom data
(``tp_<tag>_hit``), so the same machinery works in backtesting and dry/live
runs. Level targets are absolute prices; builders produce them from the entry
rate / ATR / swing high-low like the Pine code does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

from . import indicators as ind


def _trade_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


# ---------------------------------------------------------------------------
# Partial take-profit levels
# ---------------------------------------------------------------------------
@dataclass
class TPLevel:
    """One take-profit level: absolute target price + reduce fraction."""

    price: float
    reduce: float  # fraction of the position to close, e.g. 0.25
    tag: str = "tp"


@dataclass
class PartialTP:
    """Ordered TP levels with per-trade hit tracking via custom data."""

    levels: list[TPLevel] = field(default_factory=list)

    def hit_states(self, trade: Trade) -> list[bool]:
        return [bool(trade.get_custom_data(f"tp_{level.tag}_hit", False)) for level in self.levels]

    def is_hit(self, trade: Trade, current_rate: float, is_short: bool) -> bool:
        for level, hit in zip(self.levels, self.hit_states(trade)):
            if hit:
                continue
            if not is_short and current_rate >= level.price:
                return True
            if is_short and current_rate <= level.price:
                return True
        return False

    def new_hit(self, trade: Trade, current_rate: float, is_short: bool) -> tuple[float, str] | None:
        """Return ``(reduce_ratio, tag)`` for the first freshly-reached level."""
        for level, hit in zip(self.levels, self.hit_states(trade)):
            if hit:
                continue
            reached = current_rate >= level.price if not is_short else current_rate <= level.price
            if not reached:
                break
            trade.set_custom_data(f"tp_{level.tag}_hit", True)
            return level.reduce, level.tag
        return None

    def all_hit(self, trade: Trade) -> bool:
        return all(self.hit_states(trade))


def _analyzed_df(strategy: IStrategy, pair: str) -> DataFrame | None:
    if strategy.dp is None:
        return None
    try:
        frame, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
    except Exception:
        return None
    return frame if frame is not None and not frame.empty else None


# ---------------------------------------------------------------------------
# Level builders (mirror the Pine calculations)
# ---------------------------------------------------------------------------
def percent_tp_levels(
    open_rate: float,
    is_short: bool,
    pcts: Sequence[float],
    reduces: Sequence[float],
    tags: Sequence[str],
) -> PartialTP:
    """Percent TP levels anchored on the entry rate (``longPercentualTakeProfit``)."""
    sign = -1.0 if is_short else 1.0
    levels = [
        TPLevel(price=open_rate * (1 + sign * pct / 100.0), reduce=reduce, tag=tag)
        for pct, reduce, tag in zip(pcts, reduces, tags)
    ]
    return PartialTP(levels)


def atr_tp_levels(
    strategy: IStrategy,
    pair: str,
    trade: Trade,
    atr_value: float,
    multipliers: Sequence[float],
    reduces: Sequence[float],
    tags: Sequence[str],
) -> PartialTP:
    """ATR TP levels: ``entry ± atr * mult`` (``longAtrTakeProfit``)."""
    sign = -1.0 if trade.is_short else 1.0
    levels = [
        TPLevel(price=trade.open_rate + sign * atr_value * mult, reduce=reduce, tag=tag)
        for mult, reduce, tag in zip(multipliers, reduces, tags)
    ]
    return PartialTP(levels)


def highlow_tp_levels(
    strategy: IStrategy,
    pair: str,
    trade: Trade,
    current_rate: float,
    lookback: int,
    multiplier: float,
    backup_multiplier: float,
    reduce: float,
    tag: str = "hl_tp",
) -> PartialTP | None:
    """High-low TP: ``highest(high, n) * multiplier`` (with backup level when
    the current bar prints a new extreme)."""
    frame = _analyzed_df(strategy, pair)
    if frame is None or len(frame) == 0:
        return None
    if trade.is_short:
        lowest = frame["low"].rolling(lookback).min().iloc[-1]
        current_low = frame["low"].iloc[-1]
        if current_low == lowest:
            price = current_low * (1 - (backup_multiplier - 1))
        else:
            price = lowest * (1 - (multiplier - 1))
    else:
        highest = frame["high"].rolling(lookback).max().iloc[-1]
        current_high = frame["high"].iloc[-1]
        if current_high == highest:
            price = current_high * backup_multiplier
        else:
            price = highest * multiplier
    return PartialTP([TPLevel(price=price, reduce=reduce, tag=tag)])


def auto_rr_tp_levels(
    strategy: IStrategy,
    pair: str,
    trade: Trade,
    current_rate: float,
    stop_price: float,
    rr_ratio: float,
    reduce: float,
    tag: str = "auto_rr",
) -> PartialTP | None:
    """Automatic high-low TP from the stop distance: ``entry ± risk * rr``."""
    if stop_price is None or stop_price <= 0:
        return None
    if trade.is_short:
        risk = (stop_price - trade.open_rate) / trade.open_rate
        price = trade.open_rate * (1 - risk * rr_ratio)
    else:
        risk = (trade.open_rate - stop_price) / trade.open_rate
        price = trade.open_rate * (1 + risk * rr_ratio)
    return PartialTP([TPLevel(price=price, reduce=reduce, tag=tag)])


# ---------------------------------------------------------------------------
# Special exits (custom_exit)
# ---------------------------------------------------------------------------
@dataclass
class SpecialExitManager:
    """MA cross / PSAR cross / Bars / Z-score full exits (Pine special exits).

    ``ma_exit`` uses a higher-timeframe MA (defaults to base close when the
    resolution is empty). ``no_loss`` requires the trade to be in profit.
    """

    special: str = "None"
    ma_type: str = "EMA"
    ma_length: int = 35
    ma_resolution: str = ""
    ma_no_loss: bool = False
    sar_start: float = 0.04
    sar_increment: float = 0.04
    sar_maximum: float = 0.215
    bars_amount: int = 5
    zscore_length: int = 20
    zscore_stddev: float = 2.0

    def check_exit(
        self,
        strategy: IStrategy,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        dataframe: DataFrame | None,
    ) -> str | None:
        if self.special == "MA":
            return self._check_ma(trade, current_rate, current_profit, dataframe)
        if self.special == "PSAR":
            return self._check_sar(trade, current_rate, dataframe)
        if self.special == "Bars":
            return self._check_bars(trade)
        if self.special == "Z-score":
            return self._check_zscore(trade, current_rate, dataframe)
        if self.special == "Tick":
            return None  # handled as a trailing stop in custom_stoploss
        return None

    def _frame(self, strategy: IStrategy, pair: str, dataframe: DataFrame | None) -> DataFrame | None:
        if dataframe is not None and not dataframe.empty:
            return dataframe
        return _analyzed_df(strategy, pair)

    def _check_ma(self, trade, current_rate, current_profit, dataframe) -> str | None:
        frame = self._frame(None, trade.pair, dataframe)
        if frame is None or len(frame) < self.ma_length + 3:
            return None
        close = frame["close"]
        chosen = ind.ema(close, self.ma_length)
        if self.ma_type == "SMA":
            chosen = ind.sma(close, self.ma_length)
        elif self.ma_type == "WMA":
            chosen = ind.wma(close, self.ma_length)
        elif self.ma_type == "HMA":
            chosen = ind.hma(close, self.ma_length)
        elif self.ma_type == "RMA":
            chosen = ind.rma(close, self.ma_length)
        elif self.ma_type == "DEMA":
            chosen = ind.dema(close, self.ma_length)
        elif self.ma_type == "TEMA":
            chosen = ind.tema(close, self.ma_length)
        last = close.iloc[-1]
        prev = close.iloc[-2]
        ma_last = chosen.iloc[-1]
        ma_prev = chosen.iloc[-2]
        if not pd.notna(ma_last):
            return None
        crossed = (last >= ma_last and prev < ma_prev) or (last <= ma_last and prev > ma_prev)
        if crossed and (not self.ma_no_loss or current_profit > 0):
            return "ma_special_exit"
        return None

    def _check_sar(self, trade, current_rate, dataframe) -> str | None:
        frame = self._frame(None, trade.pair, dataframe)
        if frame is None or len(frame) < 3:
            return None
        sar = ind.sar(frame, self.sar_start, self.sar_increment, self.sar_maximum)
        last_close = frame["close"].iloc[-1]
        prev_close = frame["close"].iloc[-2]
        sar_last = sar.iloc[-1]
        sar_prev = sar.iloc[-2]
        if not pd.notna(sar_last):
            return None
        if trade.is_short and prev_close >= sar_prev and last_close < sar_last:
            return "sar_special_exit"
        if not trade.is_short and prev_close <= sar_prev and last_close > sar_last:
            return "sar_special_exit"
        return None

    def _check_bars(self, trade) -> str | None:
        count = (trade.get_custom_data("bars_exit_count", 0) or 0) + 1
        trade.set_custom_data("bars_exit_count", count)
        if count >= self.bars_amount:
            trade.set_custom_data("bars_exit_count", 0)
            return "bars_special_exit"
        return None

    def _check_zscore(self, trade, current_rate, dataframe) -> str | None:
        frame = self._frame(None, trade.pair, dataframe)
        if frame is None or len(frame) < self.zscore_length + 3:
            return None
        z = ind.zscore(frame["close"], self.zscore_length)
        last = z.iloc[-1]
        prev = z.iloc[-2]
        upper = self.zscore_stddev
        lower = -1.0 * self.zscore_stddev
        if trade.is_short and prev >= lower and last < lower:
            return "zscore_special_exit"
        if not trade.is_short and prev <= upper and last > upper:
            return "zscore_special_exit"
        return None
