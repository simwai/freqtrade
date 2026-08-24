"""Reference strategy composing the Pine "Strategy Template v2.1" components.

The template's webhook / signal-transmission layer is intentionally dropped.
Every other building block is ported and wired here so a new freqtrade strategy
can subclass this class and only override :meth:`base_entry_signal` /
:meth:`base_exit_signal` (or set ``base_signal_enabled = False`` and drive
entries with ``/forceenter``).

All filters default to DISABLED exactly like Pine. ``can_short`` defaults to
``False`` (long-only) and can be flipped on a futures config.

Usage:
    freqtrade backtesting --strategy StrategyTemplateV21 -c <config.json>
    freqtrade trade       --strategy StrategyTemplateV21 -c <config.json>

Fidelity notes (see components docstrings):
    * Entry/exit signals fill at the next candle open; SL levels fill intrabar
      at the stop price via custom_stoploss (no Pine bar magnifier).
    * Partial reduces run through ``adjust_trade_position`` (one level per
      candle).
    * Trailing stops act as full-exit hard stops (Pine reduces partially).
    * No Pine ``backtest_fill_limits_assumption`` equivalent: freqtrade never
      fills both an SL and a TP on the same candle. Validate on aggregate
      metrics rather than trade-by-trade parity with the Pine magnifier.
"""

from datetime import datetime
from typing import List, Optional

import pandas as pd
from pandas import DataFrame, Series

from freqtrade.persistence import LocalTrade, Trade
from freqtrade.strategy import merge_informative_pair

from user_data.strategies.components import exit_levels as EL
from user_data.strategies.components import filters as F
from user_data.strategies.components import indicators as ind
from user_data.strategies.components import signals as S
from user_data.strategies.components.risk import PineRiskMixin
from user_data.strategies.components.strategy_base import ComponentStrategy


class StrategyTemplateV21(PineRiskMixin, ComponentStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    startup_candle_count: int = 300
    process_only_new_candles = True

    use_exit_signal = True
    use_custom_stoploss = True
    position_adjustment_enable = True
    can_short = False

    minimal_roi = {"0": 100}
    stoploss = -0.25

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # ------------------------------------------------------------------
    # Base signal (override in a subclass). Placeholder: RSI dip/scalp.
    # ------------------------------------------------------------------
    base_signal_enabled = True
    base_rsi_length = 14
    base_long_enter_rsi = 30.0
    base_long_exit_rsi = 65.0
    base_short_enter_rsi = 70.0
    base_short_exit_rsi = 35.0

    # ------------------------------------------------------------------
    # Order management (Pine defaults)
    # ------------------------------------------------------------------
    multiple_entries_enabled = True
    entry_delay_enabled = False
    entry_delay = 1
    entry_bar_delay_enabled = False
    entry_bar_delay_length = 1
    entries_per_cycle_enabled = True
    entries_per_cycle = 1
    exit_on_opposite_enabled = True
    block_opposite_enabled = True
    loss_cutter_enabled = False

    # ------------------------------------------------------------------
    # Stop loss configuration (Pine "SL" groups)
    # ------------------------------------------------------------------
    # Percentual SL (3 levels, partial reduces)
    sl_percentual_enabled = False
    sl_percentual_reducing = False
    long_sl1_percent = 5.0
    short_sl1_percent = 5.0
    long_sl1_reduce = 5.0
    short_sl1_reduce = 5.0
    long_sl2_percent = 5.0
    short_sl2_percent = 5.0
    long_sl2_reduce = 5.0
    short_sl2_reduce = 5.0
    long_sl3_percent = 5.0
    short_sl3_percent = 5.0
    long_sl3_reduce = 5.0
    short_sl3_reduce = 5.0
    # ATR stop loss
    sl_atr_enabled = False
    sl_atr_length = 5
    sl_atr_multiplier = 1.5
    sl_atr_smoothing = "RMA"
    sl_atr_reducing = False
    long_sl_atr_reduce = 5.0
    short_sl_atr_reduce = 5.0
    # High-Low stop loss
    sl_high_low_enabled = False
    sl_high_low_multiplier = 0.95
    sl_high_low_backup_multiplier = 0.95
    sl_high_low_lookback = 20
    sl_high_low_reducing = False
    long_sl_high_low_reduce = 5.0
    short_sl_high_low_reduce = 5.0
    # Trailing percentual SL (full-exit hard stop)
    sl_trailing_percentual_enabled = False
    long_sl_trailing_percent = 1.5
    short_sl_trailing_percent = 1.5
    sl_trailing_activation_enabled = True
    sl_trailing_activation_percent = 2.0
    # Trailing ATR SL (full-exit hard stop)
    sl_trailing_atr_enabled = False
    sl_trailing_atr_length = 5
    sl_trailing_atr_multiplier = 1.5
    sl_trailing_atr_smoothing = "RMA"
    # New order on stop loss
    new_order_on_stop_loss_enabled = False

    # ------------------------------------------------------------------
    # Take profit configuration (Pine "TP" groups) — partial reduces
    # ------------------------------------------------------------------
    tp_percentual_enabled = False
    tp_percentual_reducing = False
    long_tp1_percent = 5.0
    short_tp1_percent = 5.0
    long_tp1_reduce = 5.0
    short_tp1_reduce = 5.0
    long_tp2_percent = 5.0
    short_tp2_percent = 5.0
    long_tp2_reduce = 5.0
    short_tp2_reduce = 5.0
    long_tp3_percent = 5.0
    short_tp3_percent = 5.0
    long_tp3_reduce = 5.0
    short_tp3_reduce = 5.0
    tp_atr_enabled = False
    tp_atr_length = 5
    tp_atr_multiplier = 3.0
    tp_atr_smoothing = "RMA"
    tp_atr_reducing = False
    long_tp_atr_reduce = 5.0
    short_tp_atr_reduce = 5.0
    tp_high_low_enabled = False
    tp_high_low_multiplier = 1.1
    tp_high_low_backup_multiplier = 1.1
    tp_high_low_lookback = 20
    tp_high_low_reducing = False
    long_tp_high_low_reduce = 5.0
    short_tp_high_low_reduce = 5.0
    tp_auto_high_low_enabled = False
    tp_auto_high_low_ratio = 2.0
    tp_auto_high_low_reducing = False
    long_tp_auto_high_low_reduce = 5.0
    short_tp_auto_high_low_reduce = 5.0
    # Trailing percentual TP (full-exit hard take)
    tp_trailing_percentual_enabled = False
    long_tp_trailing_percent = 0.5
    short_tp_trailing_percent = 0.5

    # ------------------------------------------------------------------
    # Special exit (Pine "Special Exit" group)
    # ------------------------------------------------------------------
    special_exit = "None"  # MA | PSAR | Tick | Bars | Z-score | None
    ma_exit_type = "EMA"
    ma_exit_length = 35
    ma_exit_no_loss = False
    tick_exit_points = 1
    tick_exit_offset = 0
    bars_exit_amount = 5
    zscore_exit_length = 20
    zscore_exit_stddev = 2.0

    # ------------------------------------------------------------------
    # Filters (all default OFF, matching Pine)
    # ------------------------------------------------------------------
    filter_fir_enabled = False
    filter_fir_length = 20
    filter_fir_harmonics = 20
    filter_fir_wave_type = "Square"
    filter_fir_resolution = ""
    filter_fir_htf = False

    filter_sar_enabled = False
    filter_sar_start = 0.04
    filter_sar_increment = 0.04
    filter_sar_maximum = 0.215
    filter_sar_resolution = ""
    filter_sar_htf = False
    filter_sar_mode = "Filter Mode"
    filter_sar_confirmation_lookback = 3

    filter_mfi_enabled = False
    filter_mfi_length = 12
    filter_mfi_upper = 80.0
    filter_mfi_lower = 20.0
    filter_mfi_resolution = ""
    filter_mfi_htf = False
    filter_mfi_mode = "Filter Mode"
    filter_mfi_lookback = 3
    filter_mfi_confirmation_lookback = 3
    filter_mfi_adaptive = False
    filter_mfi_cycle_part = 0.5

    filter_chaikin_enabled = False
    filter_chaikin_length = 21
    filter_chaikin_roc_length = 34
    filter_chaikin_resolution = ""
    filter_chaikin_htf = False

    filter_cmo_enabled = False
    filter_cmo_length = 120
    filter_cmo_resolution = ""
    filter_cmo_htf = False

    filter_cmf_enabled = False
    filter_cmf_length = 21
    filter_cmf_resolution = ""
    filter_cmf_htf = False

    filter_aroon_enabled = False
    filter_aroon_length = 10
    filter_aroon_resolution = ""
    filter_aroon_sidetrend_enabled = False
    filter_aroon_sidetrend_mode = "I want trending market"

    filter_woci_enabled = False
    filter_woci_length = 7
    filter_woci_mode = "I want up or down trend"
    filter_woci_resolution = ""
    filter_woci_htf = False

    filter_stoch_enabled = False
    filter_stoch_k_length = 14
    filter_stoch_d_length = 3
    filter_stoch_smooth_k = 1
    filter_stoch_upper = 80.0
    filter_stoch_lower = 20.0
    filter_stoch_resolution = ""
    filter_stoch_htf = False
    filter_stoch_mode = "Filter Mode"
    filter_stoch_confirmation_lookback = 3

    filter_ewo_enabled = False
    filter_ewo_fast_length = 50
    filter_ewo_slow_length = 200
    filter_ewo_resolution = ""
    filter_ewo_htf = False

    filter_dual_ma_enabled = False
    filter_dual_ma_fast_length = 50
    filter_dual_ma_slow_length = 200
    filter_dual_ma_fast_type = "EMA"
    filter_dual_ma_slow_type = "EMA"
    filter_dual_ma_resolution = "15"
    filter_dual_ma_convergence_enabled = False

    filter_itrend_enabled = False
    filter_itrend_length = 50.0

    filter_volatility_enabled = False
    filter_volatility_length = 33
    filter_volatility_avg = 180
    filter_volatility_sma_length = 35
    filter_volatility_mode = "I want high volatile market"
    filter_volatility_resolution = "15"
    filter_volatility_include_source = True
    filter_volatility_include_volume = True
    filter_volatility_direction_enabled = False

    filter_forecast_enabled = False
    filter_forecast_alpha = 0.3
    filter_forecast_beta = 0.000001

    filter_roc_enabled = False
    filter_roc_length = 9
    filter_roc_resolution = ""
    filter_roc_htf = False
    filter_roc_mode = "Filter Mode"
    filter_roc_confirmation_lookback = 3

    filter_candlestick_enabled = False
    filter_candlestick_lookback = 3
    filter_candlestick_mode = "Filter Mode"
    filter_candlestick_confirmation_lookback = 3

    filter_rsi_enabled = False
    filter_rsi_length = 6
    filter_rsi_upper = 60.0
    filter_rsi_lower = 40.0
    filter_rsi_resolution = ""
    filter_rsi_htf = False

    filter_chop_zone_enabled = False
    filter_chop_zone_length = 30
    filter_chop_zone_mode = "I want trending market"
    filter_chop_zone_resolution = ""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self._long_filter_signal: Series | None = None
        self._short_filter_signal: Series | None = None
        self._last_trade: str | None = None

    # ------------------------------------------------------------------
    # Base signal hooks — override in a subclass
    # ------------------------------------------------------------------
    def base_entry_signal(self, dataframe: DataFrame, side: str) -> Series:
        """Raw entry signal (before filters). Override for your own logic."""
        if not self.base_signal_enabled:
            return Series(False, index=dataframe.index)
        rsi = ind.rsi(dataframe, self.base_rsi_length)
        if side == "long":
            return rsi < self.base_long_enter_rsi
        return rsi > self.base_short_enter_rsi

    def base_exit_signal(self, dataframe: DataFrame, side: str) -> Series:
        """Raw exit signal (before filters). Override for your own logic."""
        if not self.base_signal_enabled:
            return Series(False, index=dataframe.index)
        rsi = ind.rsi(dataframe, self.base_rsi_length)
        if side == "long":
            return rsi > self.base_long_exit_rsi
        return rsi < self.base_short_exit_rsi

    # ------------------------------------------------------------------
    # Filter construction
    # ------------------------------------------------------------------
    def build_filters(self) -> List[F.Filter]:
        return [
            F.FIRFilter(
                enabled=self.filter_fir_enabled, length=self.filter_fir_length,
                harmonics=self.filter_fir_harmonics, wave_type=self.filter_fir_wave_type,
                resolution=self.filter_fir_resolution, htf_enabled=self.filter_fir_htf,
            ),
            F.PSARFilter(
                enabled=self.filter_sar_enabled, start=self.filter_sar_start,
                increment=self.filter_sar_increment, maximum=self.filter_sar_maximum,
                resolution=self.filter_sar_resolution, htf_enabled=self.filter_sar_htf,
                mode=self.filter_sar_mode, confirmation_lookback=self.filter_sar_confirmation_lookback,
            ),
            F.MFIFilter(
                enabled=self.filter_mfi_enabled, length=self.filter_mfi_length,
                upper=self.filter_mfi_upper, lower=self.filter_mfi_lower,
                resolution=self.filter_mfi_resolution, htf_enabled=self.filter_mfi_htf,
                mode=self.filter_mfi_mode, lookback=self.filter_mfi_lookback,
                confirmation_lookback=self.filter_mfi_confirmation_lookback,
                adaptive=self.filter_mfi_adaptive, cycle_part=self.filter_mfi_cycle_part,
            ),
            F.ChaikinFilter(
                enabled=self.filter_chaikin_enabled, length=self.filter_chaikin_length,
                roc_length=self.filter_chaikin_roc_length, resolution=self.filter_chaikin_resolution,
                htf_enabled=self.filter_chaikin_htf,
            ),
            F.CMOFilter(
                enabled=self.filter_cmo_enabled, length=self.filter_cmo_length,
                resolution=self.filter_cmo_resolution, htf_enabled=self.filter_cmo_htf,
            ),
            F.CMFFilter(
                enabled=self.filter_cmf_enabled, length=self.filter_cmf_length,
                resolution=self.filter_cmf_resolution, htf_enabled=self.filter_cmf_htf,
            ),
            F.AroonFilter(
                enabled=self.filter_aroon_enabled, length=self.filter_aroon_length,
                resolution=self.filter_aroon_resolution,
            ),
            F.AroonSidetrendFilter(
                enabled=self.filter_aroon_sidetrend_enabled,
                sidetrend_mode=self.filter_aroon_sidetrend_mode,
                resolution=self.filter_aroon_resolution,
            ),
            F.WoodiesCCIFilter(
                enabled=self.filter_woci_enabled, length=self.filter_woci_length,
                mode=self.filter_woci_mode, resolution=self.filter_woci_resolution,
                htf_enabled=self.filter_woci_htf,
            ),
            F.StochFilter(
                enabled=self.filter_stoch_enabled, k_length=self.filter_stoch_k_length,
                d_length=self.filter_stoch_d_length, smooth_k=self.filter_stoch_smooth_k,
                upper=self.filter_stoch_upper, lower=self.filter_stoch_lower,
                resolution=self.filter_stoch_resolution, htf_enabled=self.filter_stoch_htf,
                mode=self.filter_stoch_mode,
                confirmation_lookback=self.filter_stoch_confirmation_lookback,
            ),
            F.EWOFilter(
                enabled=self.filter_ewo_enabled, fast_length=self.filter_ewo_fast_length,
                slow_length=self.filter_ewo_slow_length, resolution=self.filter_ewo_resolution,
                htf_enabled=self.filter_ewo_htf,
            ),
            F.DualMAFilter(
                enabled=self.filter_dual_ma_enabled, fast_length=self.filter_dual_ma_fast_length,
                slow_length=self.filter_dual_ma_slow_length, fast_type=self.filter_dual_ma_fast_type,
                slow_type=self.filter_dual_ma_slow_type, resolution=self.filter_dual_ma_resolution,
                convergence_enabled=self.filter_dual_ma_convergence_enabled,
            ),
            F.ItrendFilter(enabled=self.filter_itrend_enabled, length=self.filter_itrend_length),
            F.VolatilityFilter(
                enabled=self.filter_volatility_enabled, length=self.filter_volatility_length,
                avg=self.filter_volatility_avg, sma_length=self.filter_volatility_sma_length,
                mode=self.filter_volatility_mode, resolution=self.filter_volatility_resolution,
                include_source=self.filter_volatility_include_source,
                include_volume=self.filter_volatility_include_volume,
                direction_enabled=self.filter_volatility_direction_enabled,
            ),
            F.ForecastFilter(
                enabled=self.filter_forecast_enabled, alpha=self.filter_forecast_alpha,
                beta=self.filter_forecast_beta,
            ),
            F.ROCFilter(
                enabled=self.filter_roc_enabled, length=self.filter_roc_length,
                resolution=self.filter_roc_resolution, htf_enabled=self.filter_roc_htf,
                mode=self.filter_roc_mode,
                confirmation_lookback=self.filter_roc_confirmation_lookback,
            ),
            F.CandlestickFilter(
                enabled=self.filter_candlestick_enabled, lookback=self.filter_candlestick_lookback,
                mode=self.filter_candlestick_mode,
                confirmation_lookback=self.filter_candlestick_confirmation_lookback,
            ),
            F.RSIFilter(
                enabled=self.filter_rsi_enabled, length=self.filter_rsi_length,
                upper=self.filter_rsi_upper, lower=self.filter_rsi_lower,
                resolution=self.filter_rsi_resolution, htf_enabled=self.filter_rsi_htf,
            ),
            F.ChopZoneFilter(
                enabled=self.filter_chop_zone_enabled, length=self.filter_chop_zone_length,
                mode=self.filter_chop_zone_mode, resolution=self.filter_chop_zone_resolution,
            ),
        ]

    def _confirmation_filters(self) -> List[F.ConfirmationFilter]:
        """Confirmation-mode filters (PSAR/MFI/Stoch/ROC/Candlestick)."""
        out: List[F.ConfirmationFilter] = []
        for filt in self.build_filters():
            if isinstance(filt, F.PSARFilter) and filt.mode != "Filter Mode":
                out.append(F.ConfirmationFilter(
                    long_allowed=lambda d, t, f=filt: f.allowed(d, t)[0],
                    short_allowed=lambda d, t, f=filt: f.allowed(d, t)[1],
                    lookback=filt.confirmation_lookback, enabled=True,
                ))
            elif isinstance(filt, F.MFIFilter) and filt.mode != "Filter Mode":
                out.append(F.ConfirmationFilter(
                    long_allowed=lambda d, t, f=filt: f.allowed(d, t)[0],
                    short_allowed=lambda d, t, f=filt: f.allowed(d, t)[1],
                    lookback=filt.confirmation_lookback, enabled=True,
                ))
            elif isinstance(filt, F.StochFilter) and filt.mode != "Filter Mode":
                out.append(F.ConfirmationFilter(
                    long_allowed=lambda d, t, f=filt: f.allowed(d, t)[0],
                    short_allowed=lambda d, t, f=filt: f.allowed(d, t)[1],
                    lookback=filt.confirmation_lookback, enabled=True,
                ))
            elif isinstance(filt, F.ROCFilter) and filt.mode != "Filter Mode":
                out.append(F.ConfirmationFilter(
                    long_allowed=lambda d, t, f=filt: f.allowed(d, t)[0],
                    short_allowed=lambda d, t, f=filt: f.allowed(d, t)[1],
                    lookback=filt.confirmation_lookback, enabled=True,
                ))
            elif isinstance(filt, F.CandlestickFilter) and filt.mode != "Filter Mode":
                out.append(F.ConfirmationFilter(
                    long_allowed=lambda d, t, f=filt: f.allowed(d, t)[0],
                    short_allowed=lambda d, t, f=filt: f.allowed(d, t)[1],
                    lookback=filt.confirmation_lookback, enabled=True,
                ))
        return out

    # ------------------------------------------------------------------
    # Informative (HTF) pairs
    # ------------------------------------------------------------------
    def _resolutions(self) -> set[str]:
        resolutions = set()
        for filt in self.build_filters():
            if not filt.enabled:
                continue
            res = F.normalize_resolution(getattr(filt, "resolution", ""))
            if res and res != self.timeframe:
                resolutions.add(res)
        return resolutions

    def informative_pairs(self) -> List:
        return [(pair, resolution) for resolution in self._resolutions()
                for pair in self.dp.current_whitelist()]

    # ------------------------------------------------------------------
    # populate_indicators / entry / exit
    # ------------------------------------------------------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for HTF informatives."
        for resolution in sorted(self._resolutions()):
            informative = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=resolution)
            dataframe = merge_informative_pair(
                dataframe, informative, self.timeframe, resolution, ffill=True
            )
        dataframe["atr"] = ind.atr(dataframe, 14)
        long_filter, short_filter = F.combine_filter_signals(
            dataframe, self.build_filters(), self.timeframe
        )
        self._long_filter_signal = long_filter.fillna(True)
        self._short_filter_signal = short_filter.fillna(True)
        dataframe["long_filter_signal"] = self._long_filter_signal.astype(bool)
        dataframe["short_filter_signal"] = self._short_filter_signal.astype(bool)
        return dataframe

    def _process_signals(self, dataframe: DataFrame) -> None:
        enter_long = self.base_entry_signal(dataframe, "long")
        enter_short = self.base_entry_signal(dataframe, "short")
        exit_long = self.base_exit_signal(dataframe, "long")
        exit_short = self.base_exit_signal(dataframe, "short")

        # Confirmation-mode filters gate the raw signals.
        enter_long, enter_short, exit_long, exit_short = F.apply_confirmation_gates(
            enter_long, enter_short, exit_long, exit_short,
            self._confirmation_filters(), dataframe, self.timeframe,
        )

        # Exit on opposite entry. Position-level blocking of a fresh opposite
        # entry is enforced in confirm_trade_entry (the open trade is known there).
        enter_long, enter_short, exit_long, exit_short = S.exit_on_opposite_entry(
            enter_long, enter_short, exit_long, exit_short,
            self.exit_on_opposite_enabled, block_opposite=False,
        )

        # Entry delays.
        if self.entry_bar_delay_enabled and not self.entry_delay_enabled:
            enter_long = S.bar_delay_signal(enter_long, self.entry_bar_delay_length)
            enter_short = S.bar_delay_signal(enter_short, self.entry_bar_delay_length)
        elif self.entry_delay_enabled and not self.entry_bar_delay_enabled:
            enter_long = S.entry_delay_signal(enter_long, self.entry_delay)
            enter_short = S.entry_delay_signal(enter_short, self.entry_delay)

        # Max entries per side per cycle.
        if self.entries_per_cycle_enabled:
            enter_long, enter_short = S.entries_per_cycle_gate(
                enter_long, enter_short, self.entries_per_cycle
            )

        self._enter_long = enter_long & self._long_filter_signal
        self._enter_short = enter_short & self._short_filter_signal
        self._exit_long = exit_long
        self._exit_short = exit_short

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._process_signals(dataframe)
        dataframe["enter_long"] = self._enter_long.astype(int)
        dataframe["enter_short"] = self._enter_short.astype(int)
        if not self.can_short:
            dataframe["enter_short"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        exit_filter_long = dataframe["short_filter_signal"] if self.are_exits_filtered else True
        exit_filter_short = dataframe["long_filter_signal"] if self.are_exits_filtered else True
        self._exit_long = self._exit_long & exit_filter_long
        self._exit_short = self._exit_short & exit_filter_short
        dataframe["exit_long"] = self._exit_long.astype(int)
        dataframe["exit_short"] = self._exit_short.astype(int)
        if not self.can_short:
            dataframe["exit_short"] = 0
        return dataframe

    @property
    def are_exits_filtered(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # SL / TP level construction (Pine reduce engines)
    # ------------------------------------------------------------------
    def build_level_sets(self, trade: Trade) -> tuple[list, list]:
        sl_sets: list = []
        tp_sets: list = []
        entry = trade.open_rate
        is_short = trade.is_short

        def pct(prefix: str, percent_attr: str) -> float:
            return getattr(self, f"long_{percent_attr}" if not is_short else f"short_{percent_attr}")

        # Percentual SL levels (partial reduces).
        if self.sl_percentual_enabled:
            levels = []
            for idx, (pct_attr, reduce_attr) in enumerate(
                [("sl1_percent", "sl1_reduce"), ("sl2_percent", "sl2_reduce"), ("sl3_percent", "sl3_reduce")]
            ):
                percent = pct("", pct_attr)
                reduce = getattr(self, f"long_{reduce_attr}" if not is_short else f"short_{reduce_attr}")
                sign = 1.0 if is_short else -1.0
                levels.append(EL.TPLevel(
                    price=entry * (1 + sign * percent / 100.0),
                    reduce=reduce / 100.0 if self.sl_percentual_reducing else 0.0,
                    tag=f"slp{idx + 1}",
                ))
            if levels:
                sl_sets.append(EL.PartialTP(levels))

        # ATR SL level.
        if self.sl_atr_enabled:
            atr_value = self._trade_atr_value(trade)
            if atr_value:
                sign = 1.0 if is_short else -1.0
                reduce = getattr(self, "long_sl_atr_reduce" if not is_short else "short_sl_atr_reduce")
                sl_sets.append(EL.PartialTP([EL.TPLevel(
                    price=entry + sign * atr_value * self.sl_atr_multiplier,
                    reduce=reduce / 100.0 if self.sl_atr_reducing else 0.0,
                    tag="slatr",
                )]))

        # High-Low SL level.
        if self.sl_high_low_enabled:
            level = EL.highlow_tp_levels(
                self, trade.pair, trade, trade.open_rate, self.sl_high_low_lookback,
                self.sl_high_low_multiplier, self.sl_high_low_backup_multiplier,
                reduce=(getattr(self, "long_sl_high_low_reduce" if not is_short else "short_sl_high_low_reduce") / 100.0)
                if self.sl_high_low_reducing else 0.0,
                tag="slhl",
            )
            if level is not None:
                # HL stop levels sit below price; keep the furthest as hard floor.
                level.levels[0].price = min(level.levels[0].price, entry) if not is_short else max(level.levels[0].price, entry)
                sl_sets.append(level)

        # Percentual TP levels (partial reduces).
        if self.tp_percentual_enabled:
            levels = []
            for idx, (pct_attr, reduce_attr) in enumerate(
                [("tp1_percent", "tp1_reduce"), ("tp2_percent", "tp2_reduce"), ("tp3_percent", "tp3_reduce")]
            ):
                percent = pct("", pct_attr)
                reduce = getattr(self, f"long_{reduce_attr}" if not is_short else f"short_{reduce_attr}")
                sign = -1.0 if is_short else 1.0
                levels.append(EL.TPLevel(
                    price=entry * (1 + sign * percent / 100.0),
                    reduce=reduce / 100.0 if self.tp_percentual_reducing else 0.0,
                    tag=f"tpp{idx + 1}",
                ))
            if levels:
                tp_sets.append(EL.PartialTP(levels))

        # ATR TP level.
        if self.tp_atr_enabled:
            atr_value = self._trade_atr_value(trade)
            if atr_value:
                sign = -1.0 if is_short else 1.0
                tp_sets.append(EL.PartialTP([EL.TPLevel(
                    price=entry + sign * atr_value * self.tp_atr_multiplier,
                    reduce=(getattr(self, "long_tp_atr_reduce" if not is_short else "short_tp_atr_reduce") / 100.0)
                    if self.tp_atr_reducing else 0.0,
                    tag="tpatr",
                )]))

        # High-Low TP level.
        if self.tp_high_low_enabled:
            level = EL.highlow_tp_levels(
                self, trade.pair, trade, trade.open_rate, self.tp_high_low_lookback,
                self.tp_high_low_multiplier, self.tp_high_low_backup_multiplier,
                reduce=(getattr(self, "long_tp_high_low_reduce" if not is_short else "short_tp_high_low_reduce") / 100.0)
                if self.tp_high_low_reducing else 0.0,
                tag="tphl",
            )
            if level is not None:
                tp_sets.append(level)

        # Automatic high-low TP (risk-reward) — needs the current stop.
        if self.tp_auto_high_low_enabled:
            stop_price = None
            for level_set in sl_sets:
                for level in level_set.levels:
                    stop_price = level.price
            if stop_price:
                level = EL.auto_rr_tp_levels(
                    self, trade.pair, trade, trade.open_rate, stop_price,
                    self.tp_auto_high_low_ratio,
                    reduce=(getattr(self, "long_tp_auto_high_low_reduce" if not is_short else "short_tp_auto_high_low_reduce") / 100.0)
                    if self.tp_auto_high_low_reducing else 0.0,
                    tag="tprr",
                )
                if level is not None:
                    tp_sets.append(level)

        return sl_sets, tp_sets

    def _trade_atr_value(self, trade: Trade) -> float | None:
        atr_value = trade.get_custom_data("atr_entry")
        if atr_value is not None and float(atr_value) > 0:
            return float(atr_value)
        if self.dp is not None:
            try:
                frame, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
                if frame is not None and "atr" in frame.columns:
                    value = frame["atr"].iloc[-1]
                    if value is not None and pd.notna(value) and float(value) > 0:
                        return float(value)
            except Exception:
                pass
        return None

    @property
    def stop_managers(self) -> List:
        managers = []
        if self.sl_trailing_percentual_enabled:
            from user_data.strategies.components.risk import TrailingPercentStopManager
            managers.append(TrailingPercentStopManager(
                percent_long=self.long_sl_trailing_percent,
                percent_short=self.short_sl_trailing_percent,
                activation_enabled=self.sl_trailing_activation_enabled,
                activation_percent=self.sl_trailing_activation_percent,
            ))
        if self.sl_trailing_atr_enabled:
            from user_data.strategies.components.risk import TrailingATRStopManager
            managers.append(TrailingATRStopManager(
                atr_length=self.sl_trailing_atr_length,
                mult=self.sl_trailing_atr_multiplier,
                smoothing=self.sl_trailing_atr_smoothing,
            ))
        return managers

    @property
    def special_exit_manager(self) -> EL.SpecialExitManager | None:
        if self.special_exit in ("None", "Tick"):
            return EL.SpecialExitManager(special=self.special_exit)
        return EL.SpecialExitManager(
            special=self.special_exit,
            ma_type=self.ma_exit_type,
            ma_length=self.ma_exit_length,
            ma_no_loss=self.ma_exit_no_loss,
            bars_amount=self.bars_exit_amount,
            zscore_length=self.zscore_exit_length,
            zscore_stddev=self.zscore_exit_stddev,
        )

    # ------------------------------------------------------------------
    # Stateful order management (confirm hooks)
    # ------------------------------------------------------------------
    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        # Multiple entries disabled -> block while already in the pair.
        if not self.multiple_entries_enabled and self.dp is not None:
            open_trades = LocalTrade.get_trades_proxy(pair=pair, is_open=True)
            if open_trades:
                return False
        # Block opposite entry while a trade is open in the other direction
        # (Pine ``isOppositeEntryBlockedEnabled``).
        if self.block_opposite_enabled and self.exit_on_opposite_enabled and self.dp is not None:
            opposite_side = "short" if side == "long" else "long"
            open_trades = LocalTrade.get_trades_proxy(pair=pair, is_open=True)
            for trade in open_trades:
                if (trade.is_short and opposite_side == "short") or (
                    not trade.is_short and opposite_side == "long"
                ):
                    return False
        # Loss cutter: block repeats of the side that just lost.
        if self.loss_cutter_enabled and self._last_trade == side:
            return False
        return True

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        if exit_reason in ("exit_signal", "custom_exit"):
            self._last_trade = "long" if not trade.is_short else "short"
        return True
