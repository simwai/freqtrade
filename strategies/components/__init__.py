"""Reusable freqtrade strategy components extracted from user_data/strategies.

Layout:
    indicators     Vectorized technical indicators (supertrend, wavetrend, NW,
                   VIX fix, chop, MFI, CMF, swing detection, ...).
    ehlers         Vectorized port of the Pine ``simwai/ehlers/2`` library
                   (normalize, fisherize, get_alpha, dominant-cycle helpers).
    filters        Pine Strategy Template filters: FIR, PSAR, MFI, Chaikin,
                   CMO, CMF, Aroon (+sidetrend), Woodies CCI, Stoch, EWO,
                   Dual-MA (+convergence), iTrend, Historical Vol, Holt
                   forecast, ROC, Candlestick, RSI, Chop Zone + confirmation
                   state-machine gates.
    signals        Entry/exit signal builders (crosses, condition combiners,
                   volume pump/dip filters, HTF regime helpers, order-mgmt
                   helpers such as entry/bar delays and per-cycle gates).
    risk           Risk-management mixins: stop-loss managers, take-profit /
                   duration exits, position sizing, leverage, partial TP, plus
                   the Pine SL managers and ``PineRiskMixin``.
    exit_levels    Pine take-profit levels, partial reduces and special exits.
    strategy_base  ComponentStrategy base class + higher-timeframe helpers.

Example:

    from components.filters import MFIFilter, RSIFilter, combine_filter_signals
    from components.exit_levels import (percent_tp_levels, SpecialExitManager)
    from components.risk import (PineRiskMixin, PinePercentStopManager,
                                 ATREntryStopManager)
    from components.strategy_base import ComponentStrategy
    from components.signals import crossed_above

    class MyStrategy(PineRiskMixin, ComponentStrategy):
        filters = [MFIFilter(enabled=True), RSIFilter(enabled=True)]
        sl_level_sets = [percent_tp_levels(0, 0, [5], [1.0], ["sl"])]
        tp_level_sets = [percent_tp_levels(0, 0, [5, 10], [0.5, 0.5], ["t1", "t2"])]

        def populate_entry_trend(self, dataframe, metadata):
            long_filter, short_filter = combine_filter_signals(dataframe, self.filters)
            dataframe["enter_long"] = crossed_above(dataframe["wt1"], dataframe["wt2"]).astype(int)
            dataframe.loc[dataframe["enter_long"] == 1, "enter_long"] = long_filter.astype(int)
            return dataframe
"""

from . import ehlers, exit_levels, filters, indicators, risk, signals, strategy_base

__all__ = ["ehlers", "exit_levels", "filters", "indicators", "risk", "signals", "strategy_base"]
