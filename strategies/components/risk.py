"""Reusable risk-management components extracted from user_data/strategies.

Compose ``StopLossManager`` / ``ExitManager`` instances on a strategy that
subclasses ``RiskMixin``:

    class MyStrategy(RiskMixin, IStrategy):
        stop_managers = [
            ATRStopManager(atr_length=14, mult=1.5, anchor="entry"),
            HighLowLookbackStopManager(lookback=20, multiplier=0.98),
            TimeCutStopManager(minutes=240, cut=0.01),
        ]
        exit_managers = [DurationExitManager(minutes=720)]
        position_sizer = RiskBasedSizer(risk_per_trade=0.005, stop_distance=0.10)
        leverage_policy = FixedLeverage(5.0)

The mixin then wires ``custom_stoploss``, ``custom_exit``, ``custom_stake_amount``,
``leverage`` and optional partial take-profit (``adjust_trade_position``) for you.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.exchange.exchange_utils_timeframe import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
class StopLossManager(Protocol):
    """Returns an absolute stop price or None."""

    def stop_level(
        self,
        strategy,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        dataframe: DataFrame | None,
    ) -> float | None:
        ...


class ExitManager(Protocol):
    """Returns an exit reason string or None."""

    def check_exit(
        self,
        strategy,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        dataframe: DataFrame | None,
    ) -> str | None:
        ...


def _analyzed_df(strategy, pair: str, dataframe: DataFrame | None) -> DataFrame | None:
    if dataframe is not None and not dataframe.empty:
        return dataframe
    if strategy.dp is None:
        return None
    try:
        frame, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
    except Exception:  # noqa: BLE001
        return None
    return frame if frame is not None and not frame.empty else None


def _entry_ohlc(strategy, pair: str, trade: Trade, dataframe: DataFrame) -> tuple[float, float]:
    """Return (high, low) of the trade's entry candle, cached in trade data."""
    key_high = f"trade_{trade.id}_entry_high"
    key_low = f"trade_{trade.id}_entry_low"
    try:
        high = trade.get_custom_data(key_high)
        low = trade.get_custom_data(key_low)
        if high is not None and low is not None:
            return float(high), float(low)
    except Exception:  # noqa: BLE001, S110
        pass
    trade_date = timeframe_to_prev_date(strategy.timeframe, trade.open_date_utc)
    candles = dataframe.loc[dataframe["date"] == trade_date]
    if candles.empty:
        candles = dataframe.loc[dataframe["date"] <= trade.open_date_utc].tail(1)
    if candles.empty:
        return float(trade.open_rate), float(trade.open_rate)
    high = float(candles.iloc[-1]["high"])
    low = float(candles.iloc[-1]["low"])
    try:
        trade.set_custom_data(key_high, high)
        trade.set_custom_data(key_low, low)
    except Exception:  # noqa: BLE001, S110
        pass
    return high, low


# ---------------------------------------------------------------------------
# Stop loss managers
# ---------------------------------------------------------------------------
class ATRStopManager:
    """ATR-based stop anchored on the entry price or on the latest candle."""

    def __init__(self, atr_length: int = 14, mult: float = 1.5, anchor: str = "entry"):
        self.atr_length = atr_length
        self.mult = mult
        self.anchor = anchor

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None:
            return None
        if "atr" in frame.columns:
            atr_value = frame["atr"].iloc[-1]
        else:
            from .indicators import atr as atr_fn

            atr_value = atr_fn(frame, self.atr_length).iloc[-1]
        if not np.isfinite(atr_value) or atr_value <= 0:
            return None
        if self.anchor == "entry":
            base = trade.open_rate
        elif self.anchor == "candle":
            base = frame["low"].iloc[-1] if not trade.is_short else frame["high"].iloc[-1]
        else:
            base = current_rate
        distance = self.mult * atr_value
        return base + distance if trade.is_short else base - distance


class ATRTrailingManager:
    """Trailing stop: lowest low - mult*ATR (long) / highest high + mult*ATR (short)."""

    def __init__(self, atr_length: int = 14, mult: float = 2.5, lookback: int = 10):
        self.atr_length = atr_length
        self.mult = mult
        self.lookback = lookback

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None:
            return None
        from .indicators import atr as atr_fn

        atr_value = atr_fn(frame, self.atr_length).iloc[-1]
        if not np.isfinite(atr_value) or atr_value <= 0:
            return None
        if trade.is_short:
            base = frame["high"].rolling(self.lookback, min_periods=1).max().iloc[-1]
            return base + self.mult * atr_value
        base = frame["low"].rolling(self.lookback, min_periods=1).min().iloc[-1]
        return base - self.mult * atr_value


class TrailingATRStopManager:
    """Entry-anchored trailing ATR stop (strategy_lib "Trailing ATR" parity).

    Ratchets ``close - atr*mult_long`` (long) / ``close + atr*mult_short``
    (short) from the entry rate, keeping separate long/short multipliers. Uses
    the Hann-window ATR over the full analyzed frame, exactly like the
    strategy_lib ``compute_trade_levels`` "Trailing ATR" mode.
    """

    def __init__(self, atr_length: int = 14, mult_long: float = 3.0, mult_short: float = 3.0):
        self.atr_length = atr_length
        self.mult_long = mult_long
        self.mult_short = mult_short

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None or frame.empty:
            return None
        entry_sub = _since_entry(frame, strategy, trade)
        if entry_sub.empty:
            return None
        from .indicators import hann_atr

        atr = hann_atr(frame, self.atr_length).to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)
        entry_index = len(frame) - len(entry_sub)
        if entry_index >= len(frame):
            return None
        entry_price = float(trade.open_rate)
        if not np.isfinite(close[entry_index]) or not np.isfinite(atr[entry_index]):
            return None
        if trade.is_short:
            temp = close + atr * self.mult_short
            temp[entry_index] = entry_price + atr[entry_index] * self.mult_short
            stop = float(np.minimum.accumulate(temp[entry_index:])[-1])
        else:
            temp = close - atr * self.mult_long
            temp[entry_index] = entry_price - atr[entry_index] * self.mult_long
            stop = float(np.maximum.accumulate(temp[entry_index:])[-1])
        if not np.isfinite(stop) or stop <= 0.0:
            return None
        return stop


class PercentStopManager:
    """Fixed percentage stop anchored on the entry price."""

    def __init__(self, percent: float = 0.05):
        self.percent = percent

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        if trade.is_short:
            return trade.open_rate * (1 + self.percent)
        return trade.open_rate * (1 - self.percent)


class EntryCandleHLStopManager:
    """Stop based on the entry candle's high/low plus a buffer."""

    def __init__(self, buffer: float = 0.02):
        self.buffer = buffer

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None:
            return None
        entry_high, entry_low = _entry_ohlc(strategy, pair, trade, frame)
        if trade.is_short:
            return max(entry_high * (1 + self.buffer), current_rate * (1 + self.buffer))
        return min(entry_low * (1 - self.buffer), current_rate * (1 - self.buffer))


class HighLowLookbackStopManager:
    """Stop from the trailing low/high with a multiplier and a backup multiplier
    used when the current candle prints a new extreme (BigZ08 / Octopus style)."""

    def __init__(
        self,
        lookback: int = 20,
        multiplier: float = 0.98,
        backup_multiplier: float = 1.0,
    ):
        self.lookback = max(1, lookback)
        self.multiplier = multiplier
        self.backup = backup_multiplier

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None:
            return None
        if trade.is_short:
            highest = frame["high"].rolling(self.lookback).max()
            current_high = frame["high"]
            level = highest.mask(current_high.eq(highest), current_high * (2 - self.backup))
            level = level.mask(current_high.ne(highest), highest * (2 - self.multiplier))
            return float(level.iloc[-1])
        lowest = frame["low"].rolling(self.lookback).min()
        current_low = frame["low"]
        level = lowest.mask(current_low.eq(lowest), current_low * self.backup)
        level = level.mask(current_low.ne(lowest), lowest * self.multiplier)
        return float(level.iloc[-1])


class TimeCutStopManager:
    """Time-based cut of losing trades (CombinedBinHClucAndMADV3 style)."""

    def __init__(self, minutes: int = 240, cut: float = 0.01, wait: float = 0.99):
        self.minutes = minutes
        self.cut = cut
        self.wait = wait

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        # minutes <= 0 disables the cut (strategy_lib "Time Cut" parity).
        if self.minutes <= 0:
            return None
        if current_profit < 0 and (
            current_time - timedelta(minutes=self.minutes) >= trade.open_date_utc
        ):
            if trade.is_short:
                return current_rate * (1 + self.cut)
            return current_rate * (1 - self.cut)
        return None


class ProfitTieredTrailingManager:
    """Profit-tiered trailing stop (ClucHAnix BB_RPB_TSL).

    ``pHSL`` hard stop profit, linear interpolation between ``(pPF_1, pSL_1)``
    and ``(pPF_2, pSL_2)``, then trailing one-for-one above ``pPF_2``.
    """

    def __init__(
        self,
        pHSL: float = -0.08,
        pPF_1: float = 0.011,
        pSL_1: float = 0.011,
        pPF_2: float = 0.064,
        pSL_2: float = 0.062,
    ):
        self.pHSL = pHSL
        self.pPF_1 = pPF_1
        self.pSL_1 = pSL_1
        self.pPF_2 = pPF_2
        self.pSL_2 = pSL_2

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        if current_profit > self.pPF_2:
            sl_profit = self.pSL_2 + (current_profit - self.pPF_2)
        elif current_profit > self.pPF_1:
            sl_profit = self.pSL_1 + (current_profit - self.pPF_1) * (self.pSL_2 - self.pSL_1) / (
                self.pPF_2 - self.pPF_1
            )
        else:
            sl_profit = self.pHSL
        if sl_profit >= current_profit:
            return None
        leverage = max(float(getattr(trade, "leverage", 1.0) or 1.0), 1.0)
        offset = sl_profit / leverage
        if trade.is_short:
            return trade.open_rate * (1 - offset)
        return trade.open_rate * (1 + offset)


class SwingStopManager:
    """Swing low/high stop with ATR buffer, plus TP1 break-even / TP2 trailing
    state driven through the trade's custom data (GkdAdaptive family)."""

    def __init__(self, atr_buffer: float = 0.5, sl_atr: float = 1.5):
        self.atr_buffer = atr_buffer
        self.sl_atr = sl_atr

    def stop_level(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        atr_value = strategy._trade_atr_value(pair, trade)
        if atr_value is None:
            return None
        swing_low = strategy._trade_float(trade.get_custom_data("swing_low_price"))
        swing_high = strategy._trade_float(trade.get_custom_data("swing_high_price"))

        atr_stop = (
            trade.open_rate + self.sl_atr * atr_value
            if trade.is_short
            else trade.open_rate - self.sl_atr * atr_value
        )
        if swing_high is not None and trade.is_short:
            stop = swing_high + self.atr_buffer * atr_value
            if stop <= current_rate:
                stop = atr_stop
        elif swing_low is not None and not trade.is_short:
            stop = swing_low - self.atr_buffer * atr_value
            if stop >= current_rate:
                stop = atr_stop
        else:
            stop = atr_stop

        if trade.get_custom_data("tp1_hit"):
            stop = trade.open_rate
        if trade.get_custom_data("tp2_hit"):
            if trade.is_short:
                move = 0.5 * (trade.open_rate - (swing_low or trade.open_rate))
                stop = trade.open_rate + move
            else:
                move = 0.5 * ((swing_high or trade.open_rate) - trade.open_rate)
                stop = trade.open_rate - move
            trail_offset = self.atr_buffer * atr_value
            stop = (
                min(stop, current_rate + trail_offset)
                if trade.is_short
                else max(stop, current_rate - trail_offset)
            )
        valid = stop > current_rate if trade.is_short else stop < current_rate
        return stop if valid else None


# ---------------------------------------------------------------------------
# Exit managers (custom_exit)
# ---------------------------------------------------------------------------
class DurationExitManager:
    """Exit after a maximum trade duration."""

    def __init__(self, minutes: int = 720, tag: str = "max_duration"):
        self.minutes = minutes
        self.tag = tag

    def check_exit(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        if current_time - trade.open_date_utc >= timedelta(minutes=self.minutes):
            return self.tag
        return None


class ProfitTargetExitManager:
    """Exit when profit reaches a target (simple take profit)."""

    def __init__(self, profit: float = 0.05, tag: str = "profit_target"):
        self.profit = profit
        self.tag = tag

    def check_exit(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        return self.tag if current_profit >= self.profit else None


class VolumeSpikeExitManager:
    """Exit on a volume spike at the top of a band (BigZ06Original style)."""

    def __init__(self, volume_ratio: float = 1.5, tag: str = "volume_spike"):
        self.volume_ratio = volume_ratio
        self.tag = tag

    def check_exit(
        self, strategy, pair, trade, current_time, current_rate, current_profit,
        dataframe,
    ):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None or len(frame) < 2:
            return None
        last = frame.iloc[-1]
        prev = frame.iloc[-2]
        if "bb_upperband" not in frame.columns:
            return None
        if last["high"] > last["bb_upperband"] and (
            last["volume"] > prev["volume"] * self.volume_ratio
        ):
            return self.tag
        return None


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------
class PositionSizer(Protocol):
    def stake(
        self,
        strategy,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        side: str,
    ) -> float:
        ...


class PercentEquitySizer:
    """Stake a fixed percentage of available equity (Octopus style)."""

    def __init__(self, percent: float = 25.0):
        self.percent = percent

    def stake(
        self, strategy, pair, current_time, current_rate, proposed_stake,
        min_stake, max_stake, leverage, side,
    ):
        if math.isfinite(max_stake):
            available = max_stake
        elif strategy.wallets is not None:
            available = strategy.wallets.get_available_stake_amount()
        else:
            available = float(strategy.config.get("dry_run_wallet", proposed_stake))
        stake = available * self.percent / 100.0
        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake) if math.isfinite(max_stake) else stake


class RiskBasedSizer:
    """Size the position so that a fixed wallet fraction is risked per trade."""

    def __init__(self, risk_per_trade: float = 0.005, stop_distance: float = 0.10):
        self.risk_per_trade = risk_per_trade
        self.stop_distance = stop_distance

    def stake(
        self, strategy, pair, current_time, current_rate, proposed_stake,
        min_stake, max_stake, leverage, side,
    ):
        risk_stake = max_stake * self.risk_per_trade / (
            self.stop_distance * max(leverage, 1.0)
        )
        if min_stake is not None:
            risk_stake = max(risk_stake, min_stake)
        return min(risk_stake, max_stake)


class VolatilitySizer:
    """Scale the stake down when realized volatility is elevated."""

    def __init__(
        self,
        vol_col: str = "vol_ratio",
        high: float = 1.5,
        mid: float = 1.2,
        high_scale: float = 0.5,
        mid_scale: float = 0.75,
    ):
        self.vol_col = vol_col
        self.high = high
        self.mid = mid
        self.high_scale = high_scale
        self.mid_scale = mid_scale

    def stake(
        self, strategy, pair, current_time, current_rate, proposed_stake,
        min_stake, max_stake, leverage, side,
    ):
        frame, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
        if frame is not None and not frame.empty and self.vol_col in frame.columns:
            vol_ratio = frame[self.vol_col].iloc[-1]
            if vol_ratio > self.high:
                return proposed_stake * self.high_scale
            if vol_ratio > self.mid:
                return proposed_stake * self.mid_scale
        return proposed_stake


# ---------------------------------------------------------------------------
# Leverage policies
# ---------------------------------------------------------------------------
class LeveragePolicy(Protocol):
    def leverage(self, proposed_leverage: float, max_leverage: float) -> float:
        ...


class FixedLeverage:
    def __init__(self, value: float = 3.0):
        self.value = value

    def leverage(self, proposed_leverage: float, max_leverage: float) -> float:
        return min(float(self.value), max_leverage)


class MaxLeveragePolicy:
    def leverage(self, proposed_leverage: float, max_leverage: float) -> float:
        return max_leverage


class DefaultLeveragePolicy:
    def leverage(self, proposed_leverage: float, max_leverage: float) -> float:
        return proposed_leverage


# ---------------------------------------------------------------------------
# Partial take-profit configuration
# ---------------------------------------------------------------------------
class PartialTPSpec:
    """3-level partial take profit (50% / 25% / 25%)."""

    def __init__(
        self,
        mode: str = "atr",
        atr_length: int = 14,
        multipliers: tuple[float, float, float] = (1.0, 2.0, 3.0),
        weights: tuple[float, float, float] = (0.5, 0.25, 0.25),
    ):
        self.mode = mode  # "atr" or "swing"
        self.atr_length = atr_length
        self.multipliers = multipliers
        self.weights = weights

    def levels(self, strategy, pair, trade, current_rate: float) -> list[float] | None:
        atr_value = strategy._trade_atr_value(pair, trade)
        if atr_value is None:
            return None
        entry = trade.open_rate
        sign = -1.0 if trade.is_short else 1.0
        if self.mode == "swing":
            swing_low = strategy._trade_float(trade.get_custom_data("swing_low_price"))
            swing_high = strategy._trade_float(trade.get_custom_data("swing_high_price"))
            if swing_low is None or swing_high is None:
                return [entry + sign * m * atr_value for m in self.multipliers]
            if trade.is_short:
                return [entry - 0.5 * (entry - swing_low), swing_low, swing_low - atr_value]
            return [entry + 0.5 * (swing_high - entry), swing_high, swing_high + atr_value]
        return [entry + sign * m * atr_value for m in self.multipliers]


# ---------------------------------------------------------------------------
# RiskMixin
# ---------------------------------------------------------------------------
class RiskMixin:
    """IStrategy mixin wiring stoploss / exit / sizing / leverage / partial TP.

    Subclasses declare ``stop_managers``, ``exit_managers``, ``position_sizer``,
    ``leverage_policy`` and optionally ``partial_tp``. Override any of the
    composed methods for full control.
    """

    stop_managers: list[StopLossManager] = []
    exit_managers: list[ExitManager] = []
    position_sizer: PositionSizer | None = None
    leverage_policy: LeveragePolicy | None = None
    partial_tp: PartialTPSpec | None = None

    @staticmethod
    def _trade_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def _trade_atr_value(self, pair: str, trade: Trade) -> float | None:
        atr_value = self._trade_float(trade.get_custom_data("atr_entry"))
        if atr_value is not None and atr_value > 0:
            return atr_value
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if frame is None or frame.empty or "atr" not in frame.columns:
            return None
        value = self._trade_float(frame.iloc[-1].get("atr"))
        return value if value and value > 0 else None

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float | None:
        frame = None
        levels: list[float] = []
        for manager in self.stop_managers:
            if frame is None and self.dp is not None:
                frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            try:
                level = manager.stop_level(
                    self, pair, trade, current_time, current_rate, current_profit, frame
                )
            except Exception:  # noqa: BLE001
                level = None
            if level is not None and np.isfinite(level) and level > 0:
                levels.append(float(level))
        if not levels:
            return self.stoploss
        if trade.is_short:
            stop = min(levels)
            if stop <= current_rate:
                return self.stoploss
        else:
            stop = max(levels)
            if stop >= current_rate:
                return self.stoploss
        return stoploss_from_absolute(
            stop, current_rate, is_short=trade.is_short, leverage=trade.leverage
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        frame = None
        for manager in self.exit_managers:
            if frame is None and self.dp is not None:
                frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            try:
                reason = manager.check_exit(
                    self, pair, trade, current_time, current_rate, current_profit, frame
                )
            except Exception:  # noqa: BLE001
                reason = None
            if reason:
                return reason
        return None

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
        **kwargs,
    ) -> float:
        if self.position_sizer is None:
            return proposed_stake
        return self.position_sizer.stake(
            self, pair, current_time, current_rate, proposed_stake, min_stake,
            max_stake, leverage, side,
        )

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        if self.leverage_policy is None:
            return proposed_leverage
        return self.leverage_policy.leverage(proposed_leverage, max_leverage)

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        **kwargs,
    ) -> float | None:
        if self.partial_tp is None:
            return None
        levels = self.partial_tp.levels(self, trade.pair, trade, current_rate)
        if levels is None:
            return None
        stake_amount = float(trade.stake_amount)
        weights = self.partial_tp.weights
        tags = ["tp1_hit", "tp2_hit", "tp3_hit"]
        previous_hit = True
        for index, (level, weight, tag) in enumerate(zip(levels, weights, tags, strict=True)):
            hit = trade.get_custom_data(tag)
            if not previous_hit and not hit:
                continue
            if hit:
                previous_hit = True
                continue
            reached = (
                current_rate >= level if not trade.is_short else current_rate <= level
            )
            if not reached:
                break
            trade.set_custom_data(tag, True)
            return -(stake_amount * weight)
        return None

    def order_filled(
        self, pair: str, trade: Trade, order, current_time: datetime, **kwargs,
    ) -> None:
        if self.partial_tp is None or getattr(order, "ft_order_side", None) != trade.entry_side:
            return
        if trade.get_custom_data("atr_entry") is not None:
            return
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if frame is None or frame.empty:
            return
        candle = frame.iloc[-1]
        try:
            eligible = frame.loc[frame["date"] <= pd.Timestamp(current_time)]
            if not eligible.empty:
                candle = eligible.iloc[-1]
        except (TypeError, ValueError):
            pass
        if "atr" in candle and pd.notna(candle["atr"]) and float(candle["atr"]) > 0:
            trade.set_custom_data("atr_entry", float(candle["atr"]))
        for key in ("last_swing_low", "last_swing_high"):
            if key in candle and pd.notna(candle[key]):
                trade.set_custom_data(
                    "swing_low_price" if key.endswith("low") else "swing_high_price",
                    float(candle[key]),
                )


# ---------------------------------------------------------------------------
# Pine Strategy Template stop-loss managers
# ---------------------------------------------------------------------------
def _atr_smoothed(frame: DataFrame, length: int, smoothing: str) -> pd.Series:
    from .indicators import atr as atr_fn

    length = max(1, int(length))
    tr = ind_true_range(frame)
    if smoothing == "SMA":
        return ind_sma(tr, length)
    if smoothing == "EMA":
        return ind_ema(tr, length)
    if smoothing == "WMA":
        return ind_wma(tr, length)
    return ind_rma(tr, length)


def ind_true_range(frame: DataFrame) -> pd.Series:
    from .indicators import true_range

    return true_range(frame)


def ind_rma(series, length):
    from .indicators import rma

    return rma(series, length)


def ind_sma(series, length):
    from .indicators import sma

    return sma(series, length)


def ind_ema(series, length):
    from .indicators import ema

    return ema(series, length)


def ind_wma(series, length):
    from .indicators import wma

    return wma(series, length)


def _trade_float(value) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _since_entry(frame: DataFrame, strategy, trade: Trade) -> DataFrame:
    entry_date = timeframe_to_prev_date(strategy.timeframe, trade.open_date_utc)
    sub = frame.loc[frame["date"] >= entry_date]
    return sub if not sub.empty else frame


class PinePercentStopManager:
    """Pine percentual SL: ``entry * (1 -/+ pct%)``."""

    def __init__(self, percent_long: float = 5.0, percent_short: float = 5.0):
        self.percent_long = percent_long
        self.percent_short = percent_short

    def stop_level(self, strategy, pair, trade, current_time, current_rate, current_profit, dataframe):
        if trade.is_short:
            return trade.open_rate * (1 + self.percent_short / 100.0)
        return trade.open_rate * (1 - self.percent_long / 100.0)


class TrailingPercentStopManager:
    """Pine trailing % SL with an optional activation price.

    The trail ratchets to ``max(low[1] * (1 - pct%))`` since entry (long). When
    ``activation_enabled`` the trail only starts after the close crosses the
    activation price (``entry_high * (1 + act%)``).
    """

    def __init__(
        self,
        percent_long: float = 1.5,
        percent_short: float = 1.5,
        activation_enabled: bool = True,
        activation_percent: float = 2.0,
    ):
        self.percent_long = percent_long
        self.percent_short = percent_short
        self.activation_enabled = activation_enabled
        self.activation_percent = activation_percent

    def stop_level(self, strategy, pair, trade, current_time, current_rate, current_profit, dataframe):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None or frame.empty:
            return None
        sub = _since_entry(frame, strategy, trade)
        if sub.empty:
            return None
        if self.activation_enabled:
            entry_high = _trade_float(trade.get_custom_data("entry_high"))
            entry_low = _trade_float(trade.get_custom_data("entry_low"))
            if trade.is_short:
                activation = (entry_low if entry_low else sub["low"].iloc[0]) * (
                    1 - self.activation_percent / 100.0
                )
                triggered = bool((sub["close"] <= activation).any())
            else:
                activation = (entry_high if entry_high else sub["high"].iloc[0]) * (
                    1 + self.activation_percent / 100.0
                )
                triggered = bool((sub["close"] >= activation).any())
            if not triggered:
                return None
        if trade.is_short:
            trail = (sub["high"].shift(1) * (1 + self.percent_short / 100.0)).cummax()
        else:
            trail = (sub["low"].shift(1) * (1 - self.percent_long / 100.0)).cummax()
        level = float(trail.iloc[-1])
        return level if np.isfinite(level) else None


class ATREntryStopManager:
    """Pine ATR SL anchored on the entry candle's low/high."""

    def __init__(self, atr_length: int = 5, mult: float = 1.5, smoothing: str = "RMA"):
        self.atr_length = atr_length
        self.mult = mult
        self.smoothing = smoothing

    def stop_level(self, strategy, pair, trade, current_time, current_rate, current_profit, dataframe):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None or frame.empty:
            return None
        atr_value = float(_atr_smoothed(frame, self.atr_length, self.smoothing).iloc[-1])
        if not np.isfinite(atr_value) or atr_value <= 0:
            return None
        entry_low = _trade_float(trade.get_custom_data("entry_low"))
        entry_high = _trade_float(trade.get_custom_data("entry_high"))
        if trade.is_short:
            base = entry_high if entry_high else float(frame["high"].iloc[-1])
            return base + atr_value * self.mult
        base = entry_low if entry_low else float(frame["low"].iloc[-1])
        return base - atr_value * self.mult


class TrailingATRStopManager:
    """Pine trailing ATR SL: ratchet ``max(low[2] - atr*mult)`` since entry."""

    def __init__(self, atr_length: int = 5, mult: float = 1.5, smoothing: str = "RMA"):
        self.atr_length = atr_length
        self.mult = mult
        self.smoothing = smoothing

    def stop_level(self, strategy, pair, trade, current_time, current_rate, current_profit, dataframe):
        frame = _analyzed_df(strategy, pair, dataframe)
        if frame is None or frame.empty:
            return None
        atr_value = _atr_smoothed(frame, self.atr_length, self.smoothing)
        sub = _since_entry(frame, strategy, trade)
        if sub.empty:
            return None
        if trade.is_short:
            trail = (sub["high"].shift(2) + atr_value * self.mult).cummax()
        else:
            trail = (sub["low"].shift(2) - atr_value * self.mult).cummax()
        level = float(trail.iloc[-1])
        return level if np.isfinite(level) else None


class PineRiskMixin:
    """Risk mixin wiring the template's SL levels, partial reduces, special
    exits and per-trade anchors onto a strategy.

    Compose:

        class MyStrategy(PineRiskMixin, ComponentStrategy):
            sl_level_sets = [...]      # list of exit_levels.PartialTP (stops)
            tp_level_sets = [...]      # list of exit_levels.PartialTP (targets)
            special_exit_manager = exit_levels.SpecialExitManager(...)

    ``custom_stoploss`` hard-stops at the furthest SL level (partial reduces at
    the nearer SL levels run first via ``adjust_trade_position``); ``self.stoploss``
    acts as the hard loss floor.
    """

    sl_level_sets: list = []
    tp_level_sets: list = []
    stop_managers: list = []
    special_exit_manager = None

    def build_level_sets(self, trade: Trade) -> tuple[list, list]:
        """Return ``(sl_level_sets, tp_level_sets)`` for the trade. Override in
        strategies to build Pine-style levels from the entry rate / ATR."""
        return self.sl_level_sets, self.tp_level_sets

    def _sl_prices(self, trade: Trade) -> list[float]:
        sl_sets, _ = self.build_level_sets(trade)
        prices = []
        for level_set in sl_sets:
            for level in getattr(level_set, "levels", []):
                if level.price is not None and level.price > 0:
                    prices.append(float(level.price))
        return prices

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float | None:
        frame = None
        if self.dp is not None:
            try:
                frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            except Exception:
                frame = None

        # Dynamic (trailing) stops take precedence and act as a full-exit hard stop.
        manager_levels = []
        for manager in self.stop_managers:
            try:
                level = manager.stop_level(
                    self, pair, trade, current_time, current_rate, current_profit, frame
                )
            except Exception:
                level = None
            if level is not None and np.isfinite(level) and level > 0:
                manager_levels.append(float(level))

        partial_prices = self._sl_prices(trade)
        if trade.is_short:
            valid = [s for s in manager_levels if s > current_rate]
            if valid:
                stop = min(valid)
            elif partial_prices:
                stop = max(partial_prices)
            else:
                return self.stoploss
            if stop <= current_rate:
                return self.stoploss
        else:
            valid = [s for s in manager_levels if s < current_rate]
            if valid:
                stop = max(valid)
            elif partial_prices:
                stop = min(partial_prices)
            else:
                return self.stoploss
            if stop >= current_rate:
                return self.stoploss
        if not np.isfinite(stop) or stop <= 0:
            return self.stoploss
        return stoploss_from_absolute(
            stop, current_rate, is_short=trade.is_short, leverage=trade.leverage
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        if self.special_exit_manager is None:
            return None
        frame = None
        if self.dp is not None:
            try:
                frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            except Exception:
                frame = None
        try:
            return self.special_exit_manager.check_exit(
                self, trade, current_time, current_rate, current_profit, frame
            )
        except Exception:
            return None

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        **kwargs,
    ) -> float | None:
        sl_sets, tp_sets = self.build_level_sets(trade)
        for level_set in [*tp_sets, *sl_sets]:
            try:
                hit = level_set.new_hit(trade, current_rate, trade.is_short)
            except Exception:
                hit = None
            if hit:
                reduce_ratio, _tag = hit
                return -(float(trade.stake_amount) * reduce_ratio)
        return None

    def order_filled(
        self, pair: str, trade: Trade, order, current_time: datetime, **kwargs,
    ) -> None:
        if getattr(order, "ft_order_side", None) != trade.entry_side:
            return
        if self.dp is None:
            return
        try:
            frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return
        if frame is None or frame.empty:
            return
        candle = frame.iloc[-1]
        try:
            eligible = frame.loc[frame["date"] <= pd.Timestamp(current_time)]
            if not eligible.empty:
                candle = eligible.iloc[-1]
        except (TypeError, ValueError):
            pass
        trade.set_custom_data("entry_close", float(candle["close"]))
        trade.set_custom_data("entry_high", float(candle["high"]))
        trade.set_custom_data("entry_low", float(candle["low"]))
        if "atr" in candle and pd.notna(candle["atr"]) and float(candle["atr"]) > 0:
            trade.set_custom_data("atr_entry", float(candle["atr"]))
