"""
Octopus Nest Strategy.

Ported from the TradingView strategy by simwai. The original work, including the
SlTp library used by the strategy, is licensed under CC BY-NC-SA 4.0:
https://creativecommons.org/licenses/by-nc-sa/4.0/

This is a Freqtrade adaptation. Freqtrade fills entries using its configured
pricing mode, so risk levels are anchored to the actual filled entry price.

Indicators (TTM squeeze, PSAR, higher-timeframe EMA) and the SL/TP risk engine
are computed by the reusable ``components`` package (fully migrated from
``strategy_lib.risk``).
"""

import math
from datetime import datetime

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.exchange.exchange_utils_timeframe import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    IStrategy,
)
from user_data.strategies.components import indicators as ind
from user_data.strategies.components.risk import (
    octopus_duration_exceeded,
    octopus_exit_cross_signal,
    octopus_trade_levels,
)
from user_data.strategies.components.signals import crossed_above, crossed_below


class OctopusNestStrategy(IStrategy):
    """TTM squeeze momentum entries with configurable structural risk management."""

    INTERFACE_VERSION = 3

    # The Pine script defaults to Spot (Long Only). Set this to True and use a
    # futures configuration to enable the translated short-entry branch.
    can_short = True
    enable_shorts = False

    timeframe = "5m"
    ema_timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 700

    # The Pine strategy uses a 25% position size and no independent ROI exit.
    risk_percent_of_equity = 25.0
    minimal_roi = {"0": 100.0}
    # Catastrophic floor only. SL/TP exits are close-cross decisions handled in
    # custom_exit (Pine parity); a mirrored dynamic stoploss would exit intrabar
    # on wick touches before the close confirms, shadowing the EXIT_*_SL tags.
    stoploss = -0.99
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    use_custom_stoploss = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # Market / risk-management inputs from the Pine strategy.
    leverage_value = 1.0
    # Run hyperopt separately for each mode. The conditional optimize flags
    # keep inactive mode-specific dimensions out of the current search.
    sl_tp_mode = "Percentual"
    sl_size_or_atr_multiplier = DecimalParameter(0.5, 6.0, default=2.0, decimals=2, space="sell")
    risk_reward_ratio = DecimalParameter(0.75, 3.0, default=1.05, decimals=2, space="sell")
    my_backup_multiplier = DecimalParameter(
        1.0,
        1.2,
        default=1.1,
        decimals=2,
        space="sell",
        optimize=sl_tp_mode in ("Highest Lowest", "Trailing Highest Lowest"),
    )
    max_trade_duration_days = IntParameter(1, 10, default=7, space="sell")
    high_low_stop_loss_lookback = IntParameter(
        10,
        60,
        default=20,
        space="sell",
        optimize=sl_tp_mode
        in ("Highest Lowest", "Trailing Highest Lowest", "Highest Lowest + ATR"),
    )
    high_low_stop_loss_multiplier = DecimalParameter(
        0.95,
        1.0,
        default=0.98,
        decimals=3,
        space="sell",
        optimize=sl_tp_mode
        in ("Highest Lowest", "Trailing Highest Lowest", "Highest Lowest + ATR"),
    )
    atr_length = IntParameter(
        7,
        28,
        default=14,
        space="sell",
        optimize=sl_tp_mode in ("ATR", "Trailing ATR", "Highest Lowest + ATR"),
    )

    # Trend filter inputs.
    ema_length = IntParameter(50, 200, default=100, space="buy")

    # Squeeze momentum inputs.
    # bb_length / mult_bb / mult_kc only shape the Bollinger/Keltner bands,
    # which are computed for plotting but never read by the entry signal
    # (entries use ema, psar and osc only). Keep them out of the hyperopt
    # search (optimize=False) to shrink the buy space.
    bb_length = IntParameter(15, 30, default=20, space="buy", optimize=False)
    mult_bb = DecimalParameter(1.5, 2.5, default=2.0, decimals=2, space="buy", optimize=False)
    length_kc = IntParameter(15, 30, default=20, space="buy")
    mult_kc = DecimalParameter(1.0, 2.0, default=1.5, decimals=2, space="buy", optimize=False)
    use_true_range = True

    # Classic and adaptive PSAR inputs.
    is_psar_adaptive = False
    psar_start = 0.02
    psar_inc = 0.02
    psar_max = 0.2
    start_a_factor = 0.02
    min_step = 0.0
    max_step = 0.02
    max_a_factor = 0.2
    hilo_mode = "On"
    adapt_mode = "Kaufman"
    adapt_smooth = 5
    flip_filter = 0.0
    min_change = 0.0

    plot_config = {
        "main_plot": {
            "ema": {"color": "#68df99"},
            "psar": {"color": "#f2a654", "type": "scatter"},
            "long_stop_loss": {"color": "#abedc6"},
            "short_stop_loss": {"color": "#ef922e"},
            "long_take_profit": {"color": "#abedc6"},
            "short_take_profit": {"color": "#ef922e"},
        },
        "subplots": {
            "Squeeze Momentum": {"osc": {"color": "#00ffff"}},
            "ATR": {"hann_atr": {"color": "#f2a654"}},
        },
    }

    def _risk_config(self) -> dict:
        """Snapshot of the current SL/TP hyperopt parameters (components parity)."""
        return {
            "mode": self.sl_tp_mode,
            "sl_size_or_atr_multiplier": float(self.sl_size_or_atr_multiplier.value),
            "risk_reward_ratio": float(self.risk_reward_ratio.value),
            "my_backup_multiplier": float(self.my_backup_multiplier.value),
            "max_trade_duration_days": int(self.max_trade_duration_days.value),
            "high_low_stop_loss_lookback": int(self.high_low_stop_loss_lookback.value),
            "high_low_stop_loss_multiplier": float(self.high_low_stop_loss_multiplier.value),
            "atr_length": int(self.atr_length.value),
        }

    def _octopus_levels(self, dataframe: DataFrame, trade: Trade) -> dict | None:
        """Compute full Octopus SL/TP level arrays via components (strategy_lib parity)."""
        if dataframe is None or dataframe.empty:
            return None
        cfg = self._risk_config()
        # Find entry index same as strategy_lib.indicators.find_entry_index
        entry_date = timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
        dates = dataframe["date"]
        # Match strategy_lib: flatnonzero(dates <= entry_date), fallback 0
        dts = pd.to_datetime(dates, utc=True)
        matches = np.flatnonzero((dts <= entry_date).to_numpy())
        entry_index = int(matches[-1]) if len(matches) else 0
        return octopus_trade_levels(
            dataframe,
            float(trade.open_rate),
            entry_index,
            mode=cfg["mode"],
            sl_size_or_atr_multiplier=cfg["sl_size_or_atr_multiplier"],
            sl_size_or_atr_multiplier_short=None,
            risk_reward_ratio=cfg["risk_reward_ratio"],
            my_backup_multiplier=cfg["my_backup_multiplier"],
            max_trade_duration_days=cfg["max_trade_duration_days"],
            high_low_stop_loss_lookback=cfg["high_low_stop_loss_lookback"],
            high_low_stop_loss_multiplier=cfg["high_low_stop_loss_multiplier"],
            atr_length=cfg["atr_length"],
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bb_length = int(self.bb_length.value)
        kc_length = int(self.length_kc.value)
        mult_bb = float(self.mult_bb.value)
        mult_kc = float(self.mult_kc.value)
        atr_length = int(self.atr_length.value)

        # Merge the informative EMA first so the source series below always
        # shares the post-merge dataframe index.
        dataframe = ind.higher_timeframe_ema(
            dataframe,
            metadata,
            self.dp,
            self.timeframe,
            self.ema_timeframe,
            int(self.ema_length.value),
        )

        high = dataframe["high"].to_numpy(dtype=float)
        low = dataframe["low"].to_numpy(dtype=float)
        close = dataframe["close"].to_numpy(dtype=float)

        dataframe["hann_atr"] = ind.hann_atr(dataframe, atr_length)
        kc_atr = ind.hann_atr(dataframe, kc_length) if self.use_true_range else None
        ind.squeeze_bands(
            dataframe,
            bb_length,
            mult_bb,
            kc_length,
            mult_kc,
            use_true_range=self.use_true_range,
            atr=kc_atr,
        )

        if self.is_psar_adaptive:
            market = getattr(self.dp, "market", lambda _pair: None)(metadata["pair"])
            precision = ((market or {}).get("precision") or {}).get("price", 8)
            base_unit = 10.0 ** (-precision) if isinstance(precision, int) else 1e-8
            dataframe["psar"] = ind.adaptive_psar(
                high,
                low,
                close,
                base_unit,
                start_a_factor=self.start_a_factor,
                min_step=self.min_step,
                max_step=self.max_step,
                max_a_factor=self.max_a_factor,
                adapt_smooth=self.adapt_smooth,
                adapt_mode=self.adapt_mode,
                hilo_mode=self.hilo_mode,
                flip_filter=self.flip_filter,
                min_change=self.min_change,
            )
        else:
            dataframe["psar"] = ind.sar(dataframe, self.psar_start, self.psar_inc, self.psar_max)

        return dataframe

    def informative_pairs(self) -> list[tuple[str, str]]:
        if self.ema_timeframe == self.timeframe or not getattr(self, "dp", None):
            return []
        return [(pair, self.ema_timeframe) for pair in self.dp.current_whitelist()]

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_signal = (
            (dataframe["close"] > dataframe["ema"])
            & crossed_above(dataframe["close"], dataframe["psar"])
            & crossed_above(dataframe["osc"], 0.0)
        )
        dataframe.loc[long_signal, ["enter_long", "enter_tag"]] = (1, "ENTER_LONG")

        if self.enable_shorts:
            short_signal = (
                (dataframe["close"] < dataframe["ema"])
                & crossed_below(dataframe["close"], dataframe["psar"])
                & crossed_below(dataframe["osc"], 0.0)
            )
            dataframe.loc[short_signal, ["enter_short", "enter_tag"]] = (1, "ENTER_SHORT")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # SL/TP and the duration exit are evaluated from the live Trade object
        # in custom_exit, preserving the Pine strategy's per-trade state.
        return dataframe

    def _percentual_levels(self, entry_price: float) -> dict[str, float]:
        """Entry-constant SL/TP levels for the Percentual mode (components parity)."""
        percent = float(self.sl_size_or_atr_multiplier.value) / 100.0
        ratio = float(self.risk_reward_ratio.value)
        return {
            "long_stop": entry_price * (1.0 - percent),
            "short_stop": entry_price * (1.0 + percent),
            "long_tp": entry_price * (1.0 + percent * ratio),
            "short_tp": entry_price * (1.0 - percent * ratio),
        }

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 2:
            return None
        current_index = len(dataframe) - 1
        previous_index = current_index - 1
        if self.sl_tp_mode == "Percentual":
            entry_date = timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
            if dataframe["date"].iloc[current_index] <= entry_date:
                return None
            levels = self._percentual_levels(float(trade.open_rate))
            previous_levels = current_levels = levels
        else:
            levels = self._octopus_levels(dataframe, trade)
            if levels is None:
                return None
            entry_index = int(levels["entry_index"][0])
            if current_index <= entry_index:
                return None
            # Inline levels_at to avoid strategy_lib import
            previous_levels = {
                "long_stop": float(levels["long_stop"][previous_index]),
                "short_stop": float(levels["short_stop"][previous_index]),
                "long_tp": float(levels["long_tp"][previous_index]),
                "short_tp": float(levels["short_tp"][previous_index]),
            }
            current_levels = {
                "long_stop": float(levels["long_stop"][current_index]),
                "short_stop": float(levels["short_stop"][current_index]),
                "long_tp": float(levels["long_tp"][current_index]),
                "short_tp": float(levels["short_tp"][current_index]),
            }
        previous_close = float(dataframe["close"].iloc[previous_index])
        current_close = float(dataframe["close"].iloc[current_index])
        signal = octopus_exit_cross_signal(
            previous_close,
            current_close,
            previous_levels,
            current_levels,
            trade.is_short,
        )
        if signal:
            return signal
        direction = "SHORT" if trade.is_short else "LONG"
        if octopus_duration_exceeded(
            trade.open_date_utc, current_time, int(self.max_trade_duration_days.value)
        ):
            return f"EXIT_{direction}_TIME"
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
        """Use the Pine strategy's percentage-of-equity sizing in Freqtrade terms."""
        if math.isfinite(max_stake):
            available = max_stake
        elif self.wallets is not None:
            available = self.wallets.get_available_stake_amount()
        else:
            available = float(self.config.get("dry_run_wallet", proposed_stake))
        stake = available * float(self.risk_percent_of_equity) / 100.0
        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake) if math.isfinite(max_stake) else stake

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
        return min(float(self.leverage_value), max_leverage)
