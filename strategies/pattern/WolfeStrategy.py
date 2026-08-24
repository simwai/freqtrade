"""Causal Freqtrade approximation of the Trendoscope Wolfe strategy.

The TradingView source uses MPL-2.0 licensed Trendoscope libraries.  This port
keeps the original attribution and translates the signal and bracket logic to
Freqtrade's completed-candle and limit-order callbacks.

Freqtrade does not expose Pine's per-pattern stop-entry orders or pyramiding,
so entries are represented by adjustable limit orders.  ``WolfeSpotStrategy``
is long-only and ``WolfeFuturesShortStrategy`` is short-only with leverage
limited to 2x.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import numpy as np
from pandas import DataFrame

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    BooleanParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
    stoploss_from_absolute,
)


@dataclass(frozen=True)
class _Pivot:
    value: float
    bar: int
    direction: int
    level: int = 0


@dataclass
class _Pattern:
    key: str
    side: str
    pivots: tuple[_Pivot, _Pivot, _Pivot, _Pivot, _Pivot]
    entry: float
    stop: float
    target: float
    expiry: int
    created_bar: int
    level: int
    status: int = 0


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _is_limit_entry(side: str, close: float, entry: float) -> bool:
    """Return whether the Pine order would have been a supported limit order."""

    direction = 1 if side == "long" else -1
    return close * direction > entry * direction


def _pattern_risk_reward(pattern: _Pattern) -> float:
    risk = abs(pattern.entry - pattern.stop)
    return abs(pattern.entry - pattern.target) / risk if risk > 0 else 0.0


def _valid_bracket(side: str, entry: float, stop: float, target: float) -> bool:
    if side == "long":
        return stop < entry < target
    return target < entry < stop


def _line_price(
    start_bar: int, start_price: float, end_bar: int, end_price: float, bar: int
) -> float:
    """Return a line value, matching TradingView's line.get_price()."""

    if end_bar == start_bar:
        return float("nan")
    return float(
        start_price + (end_price - start_price) * (bar - start_bar) / (end_bar - start_bar)
    )


def _pivot_key(pivots: tuple[_Pivot, _Pivot, _Pivot, _Pivot, _Pivot], side: str) -> str:
    # Five bar indexes keep enter_tag well below Freqtrade's 100 character limit.
    return f"wolfe_{side[0]}_" + "_".join(str(pivot.bar) for pivot in pivots)


def _add_pivot(pivots: list[_Pivot], pivot: _Pivot, max_pivots: int) -> None:
    """Insert a pivot at the front of a newest-first pivot list."""

    direction = _sign(pivot.direction)
    if not direction:
        return

    if pivots and _sign(pivots[0].direction) == direction:
        # The Pine implementation normally removes the old same-direction
        # pivot first.  Keep the helper defensive for malformed OHLC input.
        if direction * pivot.value > direction * pivots[0].value:
            pivots[0] = replace(pivot, direction=direction)
        return

    if len(pivots) >= 2 and direction * pivot.value > direction * pivots[1].value:
        direction *= 2

    pivots.insert(0, replace(pivot, direction=direction))
    del pivots[max_pivots:]


def _next_level(pivots: list[_Pivot], max_pivots: int) -> list[_Pivot]:  # noqa: C901
    """Translate rzigzag.nextlevel() for a newest-first pivot list."""

    result: list[_Pivot] = []
    bullish: list[_Pivot] = []
    bearish: list[_Pivot] = []

    def add_level_pivot(pivot: _Pivot) -> None:
        direction = _sign(pivot.direction)
        if not direction:
            return
        if result and _sign(result[0].direction) == direction:
            return
        if len(result) >= 2 and direction * pivot.value > direction * result[1].value:
            direction *= 2
        result.insert(0, replace(pivot, direction=direction, level=pivot.level))
        del result[max_pivots:]

    for original in reversed(pivots):
        row = replace(original, direction=original.direction, level=original.level + 1)
        raw_direction = row.direction
        direction = _sign(raw_direction)
        value = row.value

        if result:
            last_direction = _sign(result[0].direction)
            last_pivot = result[0].value

            if abs(raw_direction) == 2:
                if last_direction == direction:
                    if raw_direction * last_pivot < raw_direction * value:
                        result.pop(0)
                    else:
                        temporary = bearish if direction > 0 else bullish
                        if temporary:
                            add_level_pivot(temporary[0])
                        else:
                            continue
                else:
                    first = bullish if direction > 0 else bearish
                    second = bearish if direction > 0 else bullish
                    if first and second and direction * first[0].value > direction * value:
                        add_level_pivot(first[0])
                        add_level_pivot(second[0])

                add_level_pivot(row)
                bullish.clear()
                bearish.clear()
            else:
                temporary = bullish if direction > 0 else bearish
                if temporary:
                    if direction * value > direction * temporary[0].value:
                        temporary.clear()
                        temporary.append(row)
                else:
                    temporary.append(row)
        elif abs(raw_direction) == 2:
            add_level_pivot(row)

    # The Pine library discards a recursive level when it did not reduce the
    # number of pivots.  This also prevents repeatedly scanning the base level.
    return [] if len(result) >= len(pivots) else result


def _rolling_extreme(values: np.ndarray, bar: int, length: int, high: bool) -> tuple[float, int]:
    start = max(0, bar - length + 1)
    window = values[start : bar + 1]
    if high:
        offset = int(np.nanargmax(window))
    else:
        offset = int(np.nanargmin(window))
    return float(window[offset]), start + offset


def _base_zigzag(
    dataframe: DataFrame, length: int, max_pivots: int
) -> tuple[list[list[_Pivot]], list[bool], list[bool]]:
    """Build the causal base zigzag after each candle."""

    highs = dataframe["high"].to_numpy(dtype=float)
    lows = dataframe["low"].to_numpy(dtype=float)
    snapshots: list[list[_Pivot]] = []
    new_flags: list[bool] = []
    double_flags: list[bool] = []
    pivots: list[_Pivot] = []

    for bar in range(len(dataframe)):
        if not np.isfinite(highs[bar]) or not np.isfinite(lows[bar]):
            snapshots.append(list(pivots))
            new_flags.append(False)
            double_flags.append(False)
            continue

        high_value, high_bar = _rolling_extreme(highs, bar, length, high=True)
        low_value, low_bar = _rolling_extreme(lows, bar, length, high=False)
        pivot_direction = _sign(pivots[0].direction) if pivots else 1
        distance = bar - pivots[0].bar if pivots else 0

        force_double = False
        if len(pivots) > 1:
            previous_value = pivots[1].value
            force_double = (
                pivot_direction == 1
                and low_bar == bar
                and low_value < previous_value
            ) or (
                pivot_direction == -1
                and high_bar == bar
                and high_value > previous_value
            )

        overflow = distance >= length
        new_pivot = False
        double_pivot = False

        extreme_in_direction = (pivot_direction == 1 and high_bar == bar) or (
            pivot_direction == -1 and low_bar == bar
        )
        if extreme_in_direction and pivots:
            value = high_value if pivot_direction == 1 else low_value
            current = pivots[0]
            if value * current.direction > current.value * current.direction:
                pivots.pop(0)
                _add_pivot(pivots, _Pivot(value, bar, pivot_direction), max_pivots)
                new_pivot = True

        inverse_extreme = (pivot_direction == 1 and low_bar == bar) or (
            pivot_direction == -1 and high_bar == bar
        )
        if inverse_extreme and (not new_pivot or force_double):
            value = low_value if pivot_direction == 1 else high_value
            _add_pivot(pivots, _Pivot(value, bar, -pivot_direction), max_pivots)
            double_pivot = new_pivot
            new_pivot = True

        if overflow and not new_pivot:
            if pivot_direction == 1:
                _add_pivot(pivots, _Pivot(low_value, low_bar, -pivot_direction), max_pivots)
            else:
                _add_pivot(pivots, _Pivot(high_value, high_bar, -pivot_direction), max_pivots)
            new_pivot = True

        snapshots.append(list(pivots))
        new_flags.append(new_pivot)
        double_flags.append(double_pivot)

    return snapshots, new_flags, double_flags


def _find_pattern(
    pivots: list[_Pivot],
    start: int,
    bar: int,
    side: str,
    level: int,
    min_risk_reward: float,
) -> _Pattern | None:
    if len(pivots) < start + 5:
        return None

    p5, p4, p3, p2, p1 = pivots[start : start + 5]
    last_direction = p5.direction
    if (side == "long" and last_direction >= 0) or (side == "short" and last_direction <= 0):
        return None

    if last_direction > 0:
        basic_condition = (
            p2.value < min(p1.value, p3.value, p4.value, p5.value)
            and p5.value > max(p1.value, p2.value, p3.value, p4.value)
            and p1.value < p3.value
            and p1.value > p4.value
        )
    else:
        basic_condition = (
            p2.value > max(p1.value, p3.value, p4.value, p5.value)
            and p5.value < min(p1.value, p2.value, p3.value, p4.value)
            and p1.value > p3.value
            and p1.value < p4.value
        )
    if not basic_condition:
        return None

    l2_at_p1 = _line_price(p2.bar, p2.value, p4.bar, p4.value, p1.bar)
    l2_at_p5 = _line_price(p2.bar, p2.value, p4.bar, p4.value, p5.bar)
    l1_at_p5 = p5.value
    if not all(np.isfinite(value) for value in (l2_at_p1, l2_at_p5)):
        return None

    contracting = abs(p1.value - l2_at_p1) > abs(l1_at_p5 - l2_at_p5)
    non_triangle = _sign(p1.value - p5.value) == _sign(l2_at_p1 - l2_at_p5)
    if not (contracting and non_triangle):
        return None

    width = abs(p5.bar - p1.bar)
    closing_bar: int | None = None
    closing_price: float | None = None
    for candidate_bar in range(p5.bar, p5.bar + min(500, 2 * width) + 1):
        l1 = _line_price(p1.bar, p1.value, p5.bar, p5.value, candidate_bar)
        l2 = _line_price(p2.bar, p2.value, p4.bar, p4.value, candidate_bar)
        if np.isfinite(l1) and np.isfinite(l2) and last_direction * (l1 - l2) <= 0:
            closing_bar = candidate_bar
            closing_price = (l1 + l2) / 2.0
            break

    if closing_bar is None or closing_price is None:
        return None

    entry = _line_price(p2.bar, p2.value, p4.bar, p4.value, bar + 1)
    # Pine's EPA target is the projection of point 1 through point 4, not the
    # lower/upper wedge boundary used to find the convergence point.
    target = _line_price(p1.bar, p1.value, p4.bar, p4.value, closing_bar)
    if not all(np.isfinite(value) for value in (entry, target, closing_price)):
        return None

    trade_direction = 1 if entry > closing_price else -1 if entry < closing_price else 0
    risk = abs(entry - closing_price)
    reward = abs(entry - target)
    if (
        not _valid_bracket(side, entry, closing_price, target)
        or not trade_direction
        or risk <= 0
        or reward / risk < min_risk_reward
    ):
        return None

    chronological = (p1, p2, p3, p4, p5)
    return _Pattern(
        key=_pivot_key(chronological, side),
        side=side,
        pivots=chronological,
        entry=entry,
        stop=closing_price,
        target=target,
        expiry=closing_bar,
        created_bar=bar,
        level=level,
    )


class _WolfeMixin:
    """Shared detector and Freqtrade callback implementation."""

    wolfe_side = "long"
    zigzag_length = IntParameter(8, 16, default=8, space="buy", optimize=True, load=True)
    zigzag_depth = 250
    min_level = 0
    min_risk_reward = DecimalParameter(
        1.5, 2.5, default=1.5, decimals=1, space="buy", optimize=True, load=True
    )
    avoid_overlap = BooleanParameter(default=True, space="buy", optimize=True, load=True)
    max_patterns = IntParameter(1, 3, default=3, space="buy", optimize=True, load=True)
    wolfe_entry_mode = "limit"

    _pattern_cache: dict[str, dict[str, _Pattern]]

    def _cache(self) -> dict[str, dict[str, _Pattern]]:
        if not hasattr(self, "_pattern_cache"):
            self._pattern_cache = {}
        return self._pattern_cache

    def _line_entry(self, pattern: _Pattern, bar: int) -> float:
        _, p2, _, p4, _ = pattern.pivots
        return _line_price(
            p2.bar,
            p2.value,
            p4.bar,
            p4.value,
            bar + 1,
        )

    def _pattern_invalid(
        self, pattern: _Pattern, candle: Any, bar: int, check_triggered_stop: bool = True
    ) -> bool:
        direction = 1 if pattern.side == "long" else -1
        target_value = float(candle["high"] if direction > 0 else candle["low"])
        if target_value * direction > pattern.target * direction:
            return True
        if (
            check_triggered_stop
            and pattern.status == 1
            and float(candle["close"]) * direction < pattern.stop
        ):
            return True
        if not check_triggered_stop:
            return bar > pattern.expiry
        return pattern.status == 0 and bar > pattern.expiry

    def _build_wolfe_columns(  # noqa: C901
        self, dataframe: DataFrame, pair: str
    ) -> DataFrame:
        dataframe = dataframe.copy()
        snapshots, new_flags, double_flags = _base_zigzag(
            dataframe, max(3, int(self.zigzag_length.value)), max(50, int(self.zigzag_depth))
        )
        patterns: dict[str, _Pattern] = {}
        active: dict[str, _Pattern] = {}
        signal_keys: list[str | None] = [None] * len(dataframe)
        selected_keys: list[str | None] = [None] * len(dataframe)
        entries = np.full(len(dataframe), np.nan)
        stops = np.full(len(dataframe), np.nan)
        targets = np.full(len(dataframe), np.nan)
        expiries = np.full(len(dataframe), np.nan)
        levels = np.full(len(dataframe), np.nan)
        rejected_stop_entries = np.zeros(len(dataframe), dtype=int)
        rejected_rr = np.zeros(len(dataframe), dtype=int)
        rejected_overlap = np.zeros(len(dataframe), dtype=int)
        rejected_geometry = np.zeros(len(dataframe), dtype=int)
        expired_patterns = np.zeros(len(dataframe), dtype=int)

        for bar, pivots in enumerate(snapshots):
            if new_flags[bar]:
                levels_to_scan: list[list[_Pivot]] = [pivots]
                level = 1
                while levels_to_scan[-1]:
                    next_pivots = _next_level(levels_to_scan[-1], max(50, int(self.zigzag_depth)))
                    if not next_pivots:
                        break
                    levels_to_scan.append(next_pivots)
                    level += 1

                for current_level, level_pivots in enumerate(levels_to_scan, start=1):
                    if current_level < int(self.min_level):
                        continue
                    starts = [0]
                    if double_flags[bar]:
                        starts.append(1)
                    for start in starts:
                        candidate = _find_pattern(
                            level_pivots,
                            start,
                            bar,
                            self.wolfe_side,
                            current_level,
                            0.0,
                        )
                        if candidate is None or candidate.key in patterns:
                            continue
                        if _pattern_risk_reward(candidate) < float(self.min_risk_reward.value):
                            rejected_rr[bar] += 1
                            continue
                        candidate_is_limit = _is_limit_entry(
                            candidate.side, float(dataframe.iloc[bar]["close"]), candidate.entry
                        )
                        if self.wolfe_entry_mode == "limit" and not candidate_is_limit:
                            rejected_stop_entries[bar] += 1
                            continue

                        candidate_bars = tuple(pivot.bar for pivot in candidate.pivots)
                        duplicate = False
                        for existing in active.values():
                            existing_bars = tuple(pivot.bar for pivot in existing.pivots)
                            common = sum(
                                left == right
                                for left, right in zip(candidate_bars, existing_bars, strict=True)
                            )
                            overlaps = (
                                candidate_bars[0] >= existing_bars[0]
                                and candidate_bars[0] <= existing_bars[4]
                            )
                            if common >= 3 or (self.avoid_overlap.value and overlaps):
                                rejected_overlap[bar] += 1
                                duplicate = True
                                break
                        if duplicate:
                            continue

                        patterns[candidate.key] = candidate
                        active[candidate.key] = candidate
                        if self.wolfe_entry_mode == "limit" or candidate_is_limit:
                            signal_keys[bar] = candidate.key

                        if len(active) > int(self.max_patterns.value):
                            oldest_key = min(
                                active, key=lambda pattern_key: active[pattern_key].created_bar
                            )
                            active.pop(oldest_key, None)

            candle = dataframe.iloc[bar]
            for key in list(active):
                pattern = active[key]
                if self._pattern_invalid(pattern, candle, bar):
                    if pattern.status == 0 and bar > pattern.expiry:
                        expired_patterns[bar] += 1
                    active.pop(key)
                    continue

                if pattern.status == 0:
                    current_entry = self._line_entry(pattern, bar)
                    if np.isfinite(current_entry):
                        pattern.entry = float(current_entry)
                    if not _valid_bracket(
                        pattern.side, pattern.entry, pattern.stop, pattern.target
                    ):
                        rejected_geometry[bar] += 1
                        active.pop(key)
                        continue
                    if self.wolfe_entry_mode == "limit" and not _is_limit_entry(
                        pattern.side, float(candle["close"]), pattern.entry
                    ):
                        rejected_stop_entries[bar] += 1
                        active.pop(key)
                        continue
                    direction = 1 if pattern.side == "long" else -1
                    if float(candle["high"] if direction > 0 else candle["low"]) * direction > (
                        pattern.entry * direction
                    ):
                        pattern.status = 1
                        if self.wolfe_entry_mode == "market" and signal_keys[bar] is None:
                            signal_keys[bar] = key

            if signal_keys[bar] is not None and signal_keys[bar] not in active:
                signal_keys[bar] = None

            candidates = list(active.values())
            if candidates:
                # Freqtrade normally permits one position per pair.  The newest
                # valid pattern is therefore the one exposed as the current order.
                pattern = max(candidates, key=lambda item: item.created_bar)
                selected_keys[bar] = pattern.key
                entries[bar] = pattern.entry
                stops[bar] = pattern.stop
                targets[bar] = pattern.target
                expiries[bar] = pattern.expiry
                levels[bar] = pattern.level

        self._cache()[pair] = patterns
        dataframe["wolfe_pattern"] = selected_keys
        dataframe["wolfe_signal"] = signal_keys
        dataframe["wolfe_entry"] = entries
        dataframe["wolfe_stop"] = stops
        dataframe["wolfe_target"] = targets
        dataframe["wolfe_expiry"] = expiries
        dataframe["wolfe_level"] = levels
        dataframe["wolfe_pivot_count"] = [len(pivots) for pivots in snapshots]
        dataframe["wolfe_rejected_stop_entry"] = rejected_stop_entries
        dataframe["wolfe_rejected_rr"] = rejected_rr
        dataframe["wolfe_rejected_overlap"] = rejected_overlap
        dataframe["wolfe_rejected_geometry"] = rejected_geometry
        dataframe["wolfe_expired"] = expired_patterns
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._build_wolfe_columns(dataframe, metadata["pair"])

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None
        signal = dataframe["wolfe_signal"].notna()
        entry_column = "enter_long" if self.wolfe_side == "long" else "enter_short"
        dataframe.loc[signal, entry_column] = 1
        dataframe.loc[signal, "enter_tag"] = dataframe.loc[signal, "wolfe_signal"]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    def _last_candle(self, pair: str) -> tuple[DataFrame, Any] | None:
        if not getattr(self, "dp", None):
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None
        return dataframe, dataframe.iloc[-1]

    def _trade_pattern(self, pair: str, trade: Trade) -> _Pattern | None:
        tag = str(trade.enter_tag or "")
        return self._cache().get(pair, {}).get(tag)

    def custom_entry_price(
        self,
        pair: str,
        trade: Trade | None,
        current_time: datetime,
        proposed_rate: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        pattern = self._cache().get(pair, {}).get(str(entry_tag or ""))
        candle_data = self._last_candle(pair)
        if pattern is None or candle_data is None:
            return proposed_rate
        dataframe, _ = candle_data
        entry = self._line_entry(pattern, len(dataframe) - 1)
        return float(entry) if np.isfinite(entry) else proposed_rate

    def adjust_order_price(
        self,
        trade: Trade,
        order: Order | None,
        pair: str,
        current_time: datetime,
        proposed_rate: float,
        current_order_rate: float,
        entry_tag: str | None,
        side: str,
        is_entry: bool,
        **kwargs: Any,
    ) -> float | None:
        if not is_entry:
            return current_order_rate
        pattern = self._cache().get(pair, {}).get(str(entry_tag or ""))
        candle_data = self._last_candle(pair)
        if pattern is None or candle_data is None:
            return None
        dataframe, candle = candle_data
        bar = len(dataframe) - 1
        if self._pattern_invalid(pattern, candle, bar, check_triggered_stop=False):
            return None
        entry = self._line_entry(pattern, bar)
        if not np.isfinite(entry) or not _is_limit_entry(
            pattern.side, float(candle["close"]), entry
        ):
            return None
        return float(entry)

    def check_entry_timeout(
        self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs: Any
    ) -> bool:
        pattern = self._trade_pattern(pair, trade)
        candle_data = self._last_candle(pair)
        if pattern is None or candle_data is None:
            return True
        dataframe, candle = candle_data
        return self._pattern_invalid(
            pattern, candle, len(dataframe) - 1, check_triggered_stop=False
        ) or not _is_limit_entry(pattern.side, float(candle["close"]), order.price)

    def order_filled(
        self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs: Any
    ) -> None:
        if order.ft_order_side != trade.entry_side or trade.nr_of_successful_entries != 1:
            return
        pattern = self._trade_pattern(pair, trade)
        if pattern is None:
            return
        trade.set_custom_data("wolfe_entry", float(order.safe_price))
        trade.set_custom_data("wolfe_stop", float(pattern.stop))
        trade.set_custom_data("wolfe_target", float(pattern.target))
        trade.set_custom_data("wolfe_expiry", int(pattern.expiry))
        trade.set_custom_data("wolfe_level", int(pattern.level))

    def _trade_level(self, pair: str, trade: Trade, key: str) -> float | None:
        value = trade.get_custom_data(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        pattern = self._trade_pattern(pair, trade)
        if pattern is None:
            return None
        return float(getattr(pattern, key.removeprefix("wolfe_")))

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
        if current_rate <= 0:
            return None
        stop = self._trade_level(pair, trade, "wolfe_stop")
        if stop is None or stop <= 0:
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
        target = self._trade_level(pair, trade, "wolfe_target")
        candle_data = self._last_candle(pair)
        if target is None or candle_data is None:
            return None
        _, candle = candle_data
        if trade.is_short and float(candle["low"]) <= target:
            return "wolfe_target"
        if not trade.is_short and float(candle["high"]) >= target:
            return "wolfe_target"
        return None

    def custom_exit_price(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        proposed_rate: float,
        current_profit: float,
        exit_tag: str | None,
        **kwargs: Any,
    ) -> float:
        if exit_tag == "wolfe_target":
            target = self._trade_level(pair, trade, "wolfe_target")
            if target is not None:
                return target
        return proposed_rate


class WolfeSpotStrategy(_WolfeMixin, IStrategy):
    """Long-only Wolfe strategy for spot markets."""

    INTERFACE_VERSION = 3
    can_short = False
    wolfe_side = "long"
    timeframe = "5m"
    startup_candle_count = 300
    stoploss = -0.99
    minimal_roi: dict[str, float] = {}
    use_custom_stoploss = True
    use_exit_signal = True
    process_only_new_candles = True
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    unfilledtimeout = {"entry": 100000, "exit": 100000, "unit": "minutes"}


class WolfeFuturesShortStrategy(_WolfeMixin, IStrategy):
    """Short-only Wolfe strategy for isolated futures, limited to 2x leverage."""

    INTERFACE_VERSION = 3
    can_short = True
    wolfe_side = "short"
    timeframe = "5m"
    startup_candle_count = 300
    stoploss = -0.99
    minimal_roi: dict[str, float] = {}
    use_custom_stoploss = True
    use_exit_signal = True
    process_only_new_candles = True
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    unfilledtimeout = {"entry": 100000, "exit": 100000, "unit": "minutes"}

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        return min(2.0, max(1.0, max_leverage))


class WolfeFuturesShortMarketStrategy(WolfeFuturesShortStrategy):
    """Diagnostic variant that approximates all entries with market orders."""

    wolfe_entry_mode = "market"
    order_types = {
        "entry": "market",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
