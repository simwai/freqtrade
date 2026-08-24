"""Freqtrade port of the TradingView "Hoffman IRB hardened NR" strategy.

The Pine original trades an inside-range bar (IRB) after a confirmed trend,
enters with a stop order once price breaks the IRB range, and manages the trade
with a Hoffman stop (the opposite side of the IRB) plus a fixed risk/reward
limit.  Every signal uses the *confirmed* (already closed) bar, so there is no
repainting.

Freqtrade's entry signals are shifted by one candle and its backtester fills a
limit order at the requested price whenever that price is inside the candle's
range.  This port therefore keeps a *resting* stop order at the IRB breakout
level: the signal is emitted on every bar the setup is pending, so the order
exists during the bar where price first trades through the level and fills there
at the stop price.  ``confirm_trade_entry`` rejects clamped fill prices that
would open the trade on the wrong side of the Hoffman stop.

Approximations vs. the Pine source:

* ``syminfo.pointvalue`` is ``1.0`` for crypto.
* ``syminfo.mintick`` is approximated (``1e-8``); the tick pad shifts the
  entry / Hoffman stop by one tick when ``use_tick_pad`` is enabled.
* Pine computes the risk-based quantity on the setup bar using
  ``strategy.equity``; freqtrade computes it at order creation from the
  available wallet balance.
* Gap-open fills settle at the stop price rather than at the gap open, and
  same-candle stop/target conflicts resolve in favour of the stop loss.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
    merge_informative_pair,
    stoploss_from_absolute,
)


@dataclass(frozen=True)
class _Setup:
    """Snapshot of one pending IRB setup, referenced by the entry tag."""

    pair: str
    tag: str
    direction: str  # "long" / "short"
    bar: int
    date: datetime
    entry: float
    stop: float
    target: float
    atr: float
    qty_valid: bool


class HoffmanIRBStrategy(IStrategy):
    """Hoffman IRB breakout strategy for isolated futures (long + short)."""

    INTERFACE_VERSION = 3
    can_short = True

    timeframe = "5m"
    startup_candle_count = 400
    process_only_new_candles = True

    minimal_roi: dict[str, float] = {}
    stoploss = -0.99
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False

    # --- Pine inputs kept at their defaults (not hyperoptable) -----------
    pct = 45             # inventory % of the range
    max_wait = 20        # max bars to break the IRB
    require_body = True  # require the body to be inside the inventory range
    risk_pct = 0.01      # fraction of equity risked per trade
    use_tick_pad = True  # pad entry / stop by one tick

    # --- Hyperoptable parameters ------------------------------------------
    ema_len = IntParameter(13, 21, default=20, space="buy", optimize=True, load=True)
    htf = CategoricalParameter(
        ["15m", "30m", "1h"], default="15m", space="buy", optimize=True, load=True
    )
    atr_len = CategoricalParameter(
        [5, 6, 13, 14], default=14, space="buy", optimize=True, load=True
    )
    atr_mult = CategoricalParameter(
        [0.5, 1.0, 1.5], default=1.5, space="buy", optimize=True, load=True
    )
    rr = DecimalParameter(0.1, 1.5, default=1.5, decimals=1, space="buy", optimize=True, load=True)
    max_lev = DecimalParameter(1.0, 5.0, default=5.0, decimals=1, space="buy", optimize=True, load=True)

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    unfilledtimeout = {"entry": 100000, "exit": 100000, "unit": "minutes"}

    plot_config = {
        "main_plot": {
            "ema": {"color": "#2e86de"},
            "htf_ema": {"color": "#f2a654"},
        },
    }

    _setup_cache: dict[str, dict[str, _Setup]]

    # ------------------------------------------------------------------
    # Parameter / cache helpers
    # ------------------------------------------------------------------
    def _param(self, name: str) -> Any:
        value = getattr(self, name)
        return getattr(value, "value", value)

    def _cache(self) -> dict[str, dict[str, _Setup]]:
        if not hasattr(self, "_setup_cache"):
            self._setup_cache = {}
        return self._setup_cache

    def _pair_cache(self, pair: str) -> dict[str, _Setup]:
        return self._cache().setdefault(pair, {})

    def _latest_setup(self, pair: str) -> _Setup | None:
        setups = self._pair_cache(pair)
        if not setups:
            return None
        return max(setups.values(), key=lambda setup: setup.bar)

    def _tick(self) -> float:
        return 1e-8

    @staticmethod
    def _trade_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------
    def informative_pairs(self) -> list[tuple[str, str]]:
        htf = str(self._param("htf"))
        if htf == self.timeframe or getattr(self, "dp", None) is None:
            return []
        return [(pair, htf) for pair in self.dp.current_whitelist()]

    def _merge_htf_ema(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Merge the previous completed HTF EMA (Pine ``ema(close)[1]``).

        The informative EMA is shifted by one HTF bar so that each base candle
        sees the HTF bar *before* the one that is completing at its close.
        """
        htf = str(self._param("htf"))
        ema_len = int(self._param("ema_len"))
        if htf == self.timeframe or getattr(self, "dp", None) is None:
            dataframe["htf_ema"] = dataframe["ema"].shift(1)
            return dataframe
        try:
            informative = self.dp.get_pair_dataframe(metadata["pair"], htf)
            if informative is None or informative.empty:
                raise ValueError("empty higher-timeframe dataframe")
            informative = informative[["date", "open", "high", "low", "close", "volume"]].copy()
            informative["htf_ema"] = ta.EMA(informative["close"], timeperiod=ema_len)
            informative["htf_ema"] = informative["htf_ema"].shift(1)
            dataframe = merge_informative_pair(
                dataframe, informative, self.timeframe, htf, ffill=True
            )
            dataframe["htf_ema"] = dataframe[f"htf_ema_{htf}"]
        except (KeyError, ValueError, AttributeError):
            dataframe["htf_ema"] = dataframe["ema"].shift(1)
        return dataframe

    def _qty_valid(self, entry: float, stop: float, atr: float) -> bool:
        if not (np.isfinite(entry) and np.isfinite(stop)):
            return False
        irb_dist = abs(entry - stop)
        if irb_dist < self._tick():
            return False
        atr_value = atr if np.isfinite(atr) else 0.0
        dist = max(irb_dist, atr_value * float(self._param("atr_mult")))
        return dist > 0.0

    def _build_signals(self, dataframe: DataFrame, pair: str) -> DataFrame:  # noqa: C901
        """Pending-order state machine + resting-order entry signals.

        Mirrors the Pine ``pendHi/pendLo/pendDir/pendBar/pendQty`` lifecycle:
        a setup is created at the close of its bar and a *resting* stop order at
        ``entry`` stays active until it fills, expires (``max_wait``), turns
        trend-dead or is replaced by a newer setup.

        Because freqtrade's entry signals are shifted by one candle, the signal
        is emitted on **every** bar the setup is pending: the order created from
        bar ``i`` exists during bar ``i + 1``, so it fills at the stop level on
        the first bar whose range trades through it (the Pine breakout bar).  The
        setup is consumed on that same bar to avoid re-entering after the fill.
        """
        h1 = dataframe["h1"].to_numpy(dtype=float)
        l1 = dataframe["l1"].to_numpy(dtype=float)
        high = dataframe["high"].to_numpy(dtype=float)
        low = dataframe["low"].to_numpy(dtype=float)
        atr = dataframe["atr"].to_numpy(dtype=float)
        bear_irb = dataframe["irb_bear"].to_numpy(dtype=bool)
        bull_irb = dataframe["irb_bull"].to_numpy(dtype=bool)
        up_trend = dataframe["irb_up_trend"].to_numpy(dtype=bool)
        down_trend = dataframe["irb_down_trend"].to_numpy(dtype=bool)
        dates = dataframe["date"].to_numpy()

        n = len(dataframe)
        enter_long = np.zeros(n, dtype=bool)
        enter_short = np.zeros(n, dtype=bool)
        tags = np.full(n, None, dtype=object)

        pad = self._tick() if self.use_tick_pad else 0.0
        rr = float(self._param("rr"))
        cache = self._pair_cache(pair)
        max_wait = int(self.max_wait)

        active: _Setup | None = None  # pending order active from the next bar

        for index in range(n):
            # 1. A new setup at the close of this bar replaces the pending order.
            new_pend = active
            if np.isfinite(h1[index]) and np.isfinite(l1[index]):
                if bear_irb[index] and up_trend[index]:
                    entry = h1[index] + pad
                    stop = l1[index] - pad
                    valid = self._qty_valid(entry, stop, atr[index])
                    tag = f"irb_long_{index}"
                    new_pend = _Setup(
                        pair=pair,
                        tag=tag,
                        direction="long",
                        bar=index,
                        date=dates[index],
                        entry=entry,
                        stop=stop,
                        target=entry + rr * abs(entry - stop),
                        atr=atr[index] if np.isfinite(atr[index]) else float("nan"),
                        qty_valid=valid,
                    )
                    cache[tag] = new_pend
                elif bull_irb[index] and down_trend[index]:
                    entry = l1[index] - pad
                    stop = h1[index] + pad
                    valid = self._qty_valid(entry, stop, atr[index])
                    tag = f"irb_short_{index}"
                    new_pend = _Setup(
                        pair=pair,
                        tag=tag,
                        direction="short",
                        bar=index,
                        date=dates[index],
                        entry=entry,
                        stop=stop,
                        target=entry - rr * abs(stop - entry),
                        atr=atr[index] if np.isfinite(atr[index]) else float("nan"),
                        qty_valid=valid,
                    )
                    cache[tag] = new_pend

            # 2. Cancel checks at the close of this bar (expiry / trend / qty).
            if new_pend is not None:
                expired = (index - new_pend.bar) > max_wait
                trend_dead = (new_pend.direction == "long" and not up_trend[index]) or (
                    new_pend.direction == "short" and not down_trend[index]
                )
                if expired or trend_dead or not new_pend.qty_valid:
                    new_pend = None

            # 3. A breakout on this bar consumes the pending: the resting order
            #    created from the previous bar's signal fills at the stop level.
            if new_pend is not None and new_pend.qty_valid and index > new_pend.bar:
                if new_pend.direction == "long" and np.isfinite(high[index]) and high[index] >= new_pend.entry:
                    new_pend = None
                elif (
                    new_pend.direction == "short"
                    and np.isfinite(low[index])
                    and low[index] <= new_pend.entry
                ):
                    new_pend = None

            # 4. Emit the resting order for the pending setup (fills on the next bar).
            if new_pend is not None and new_pend.qty_valid:
                if new_pend.direction == "long":
                    enter_long[index] = True
                else:
                    enter_short[index] = True
                tags[index] = new_pend.tag

            active = new_pend

        dataframe["irb_enter_long"] = enter_long
        dataframe["irb_enter_short"] = enter_short
        dataframe["irb_tag"] = tags
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Confirmed-bar series (Pine ``*[1]`` / ``c1``).
        dataframe["o1"] = dataframe["open"].shift(1)
        dataframe["h1"] = dataframe["high"].shift(1)
        dataframe["l1"] = dataframe["low"].shift(1)
        dataframe["c1"] = dataframe["close"].shift(1)
        dataframe["ema"] = pd.Series(
            ta.EMA(dataframe["close"], timeperiod=int(self._param("ema_len"))), index=dataframe.index
        ).shift(1)
        dataframe["atr"] = pd.Series(
            ta.ATR(
                dataframe["high"], dataframe["low"], dataframe["close"],
                timeperiod=int(self._param("atr_len")),
            ),
            index=dataframe.index,
        ).shift(1)
        dataframe = self._merge_htf_ema(dataframe, metadata)

        rng = dataframe["h1"] - dataframe["l1"]
        inv = self.pct / 100.0
        body = (dataframe["c1"] - dataframe["o1"]).abs()
        ok = (rng > 0) & ((not self.require_body) | (body < inv * rng))
        dataframe["irb_bear"] = ok & (dataframe["o1"] < dataframe["h1"] - inv * rng) & (
            dataframe["c1"] < dataframe["h1"] - inv * rng
        )
        dataframe["irb_bull"] = ok & (dataframe["o1"] > dataframe["l1"] + inv * rng) & (
            dataframe["c1"] > dataframe["l1"] + inv * rng
        )
        dataframe["irb_up_trend"] = (dataframe["c1"] > dataframe["ema"]) & (
            dataframe["c1"] > dataframe["htf_ema"]
        )
        dataframe["irb_down_trend"] = (dataframe["c1"] < dataframe["ema"]) & (
            dataframe["c1"] < dataframe["htf_ema"]
        )
        return self._build_signals(dataframe, metadata["pair"])

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None
        long_signal = dataframe["irb_enter_long"].fillna(False).astype(bool)
        short_signal = dataframe["irb_enter_short"].fillna(False).astype(bool)
        dataframe.loc[long_signal, "enter_long"] = 1
        dataframe.loc[short_signal, "enter_short"] = 1
        dataframe.loc[long_signal, "enter_tag"] = dataframe.loc[long_signal, "irb_tag"]
        dataframe.loc[short_signal, "enter_tag"] = dataframe.loc[short_signal, "irb_tag"]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    # ------------------------------------------------------------------
    # Entry handling
    # ------------------------------------------------------------------
    def _setup_by_tag(self, pair: str, entry_tag: str | None) -> _Setup | None:
        return self._pair_cache(pair).get(str(entry_tag or ""))

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
        setup = self._setup_by_tag(pair, entry_tag)
        if setup is None:
            return proposed_rate
        return float(setup.entry)

    def _trend_ok(self, setup: _Setup, candle: Any) -> bool:
        if setup.direction == "long":
            return bool(candle.get("irb_up_trend", False))
        return bool(candle.get("irb_down_trend", False))

    def _last_candle(self, pair: str) -> tuple[DataFrame, Any] | None:
        if not getattr(self, "dp", None):
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        return dataframe, dataframe.iloc[-1]

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
        setup = self._setup_by_tag(pair, entry_tag)
        if setup is None:
            return None
        # A newer setup replaces this pending order (Pine f_cancelPend).
        latest = self._latest_setup(pair)
        if latest is not None and latest.bar > setup.bar:
            return None
        # Expiry: max bars to break the IRB.
        elapsed = pd.Timestamp(current_time) - pd.Timestamp(setup.date)
        if elapsed > pd.Timedelta(minutes=self.max_wait * timeframe_to_minutes(self.timeframe)):
            return None
        # Trend death on the confirmed series cancels the pending order.
        candle_data = self._last_candle(pair)
        if candle_data is not None and not self._trend_ok(setup, candle_data[1]):
            return None
        return float(setup.entry)

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> bool:
        setup = self._setup_by_tag(pair, entry_tag)
        if setup is None:
            return True
        if not setup.qty_valid:
            return False
        # Freqtrade clamps limit-entry prices to the creation candle's range
        # and rounds them to the exchange precision, so ``rate`` is the actual
        # fill price.  A long entry must never fill below the setup level (a
        # short one never above), otherwise the trade would open with the
        # Hoffman stop on the wrong side.  Compare with a one-tick tolerance to
        # absorb the precision rounding; rejected setups stay pending and are
        # re-signaled on later bars.
        tick = self._tick()
        if setup.direction == "long" and rate < setup.entry - tick:
            return False
        if setup.direction == "short" and rate > setup.entry + tick:
            return False
        return True

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
        setup = self._setup_by_tag(pair, entry_tag)
        if setup is None:
            return proposed_stake
        entry = float(setup.entry)
        stop = float(setup.stop)
        irb_dist = abs(entry - stop)
        if irb_dist < self._tick() or entry <= 0:
            return 0.0
        atr_value = setup.atr if math.isfinite(setup.atr) else 0.0
        dist = max(irb_dist, atr_value * float(self._param("atr_mult")))
        if dist <= 0:
            return 0.0
        equity = (
            max_stake
            if math.isfinite(max_stake) and max_stake > 0
            else float(self.config.get("dry_run_wallet", proposed_stake))
        )
        # Pine f_qty: quantity in base units, capped by notional / equity.
        qty_raw = equity * self.risk_pct / dist
        qty_max = equity * float(self._param("max_lev")) / entry
        qty = min(qty_raw, qty_max)
        stake = qty * entry
        if not math.isfinite(stake) or stake <= 0:
            return 0.0
        if math.isfinite(max_stake):
            stake = min(stake, max_stake)
        return stake

    def order_filled(
        self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs: Any
    ) -> None:
        if order.ft_order_side != trade.entry_side or trade.nr_of_successful_entries != 1:
            return
        setup = self._setup_by_tag(pair, trade.enter_tag)
        if setup is None:
            return
        trade.set_custom_data("irb_stop", float(setup.stop))
        trade.set_custom_data("irb_target", float(setup.target))

    # ------------------------------------------------------------------
    # Exits
    # ------------------------------------------------------------------
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
        return 1.0

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
        stop = self._trade_float(trade.get_custom_data("irb_stop"))
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
        target = self._trade_float(trade.get_custom_data("irb_target"))
        candle_data = self._last_candle(pair)
        if target is None or candle_data is None:
            return None
        _, candle = candle_data
        if trade.is_short and float(candle["low"]) <= target:
            return "irb_target"
        if not trade.is_short and float(candle["high"]) >= target:
            return "irb_target"
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
        if exit_tag == "irb_target":
            target = self._trade_float(trade.get_custom_data("irb_target"))
            if target is not None:
                return target
        return proposed_rate
