"""Unit tests for the Pine Strategy Template components (v2.1 port).

These tests exercise the reusable building blocks on synthetic candles:
MA/Ehlers indicators, filter indicators, the filter framework (including the
confirmation state machine), the risk / exit-level managers, order-management
helpers and the reference ``StrategyTemplateV21`` compose path.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest


try:
    from user_data.strategies.components import (
        ehlers,
        exit_levels,
        filters,
        indicators,
        risk,
        signals,
    )
    from user_data.strategies.demo.StrategyTemplateV21 import StrategyTemplateV21
except ModuleNotFoundError:
    pytest.skip("user_data strategies are not available", allow_module_level=True)


def _candles(count: int = 900) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=count, freq="5min", tz="UTC")
    movement = np.sin(np.arange(count) / 17.0) * 0.3
    movement += np.random.default_rng(7).normal(0.0, 0.1, count)
    close = 100.0 + np.cumsum(movement)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close + 0.1,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "volume": 100.0 + np.abs(np.random.default_rng(2).normal(0.0, 50.0, count)),
        }
    )


def _strategy() -> StrategyTemplateV21:
    df = _candles()

    class FakeDP:
        def current_whitelist(self):
            return ["BTC/USDT"]

        def get_pair_dataframe(self, pair, timeframe):
            return df.copy()

    strategy = StrategyTemplateV21({})
    strategy.dp = FakeDP()
    return strategy


# ---------------------------------------------------------------------------
# MA library
# ---------------------------------------------------------------------------
def test_ma_library_finite():
    series = pd.Series(np.sin(np.arange(300) / 15.0) + 100.0)
    for fn in (
        indicators.wma,
        indicators.hma,
        indicators.dema,
        indicators.ehma,
        indicators.kama,
        indicators.vidya,
    ):
        out = fn(series, 10)
        assert len(out) == len(series)
        assert np.isfinite(out.dropna()).all()
    df = pd.DataFrame({"close": series, "volume": 100.0})
    assert np.isfinite(indicators.vwma(df, 10).dropna()).all()
    assert np.isfinite(indicators.cmo(series, 14).dropna()).all()


# ---------------------------------------------------------------------------
# Ehlers library
# ---------------------------------------------------------------------------
def test_ehlers_library_finite():
    series = pd.Series(np.sin(np.arange(400) / 15.0) + 100.0)
    assert np.isfinite(ehlers.normalize(series)).all()
    assert np.isfinite(ehlers.fisherize(pd.Series([0.5]))).all()
    for fn in (
        ehlers.get_median_dc,
        ehlers.get_iq_dc,
        ehlers.get_hilbert_dc,
        ehlers.get_bandpass_dc,
        ehlers.get_hd_dc,
        ehlers.get_cyber_cycle,
    ):
        out = fn(series)
        assert len(out) == len(series)
        assert out.min() >= 1 and out.max() <= 34
    assert np.isfinite(ehlers.do_hann_window(series, 9).dropna()).all()
    assert np.isfinite(ehlers.do_kalman(series)).all()
    assert np.isfinite(ehlers.do_net(series, 10)).all()


# ---------------------------------------------------------------------------
# Filter indicators
# ---------------------------------------------------------------------------
def test_filter_indicators():
    df = _candles(600)
    assert np.isfinite(indicators.fir(df["close"], 20, 20, "Square").dropna()).all()
    assert np.isfinite(indicators.chaikin_volatility(df, 21, 34).dropna()).all()
    bands = indicators.aroon_upper_lower(df, 10)
    assert ((bands["upper"] >= 0) & (bands["upper"] <= 100)).all()
    assert ((bands["lower"] >= 0) & (bands["lower"] <= 100)).all()
    assert len(indicators.aroon_sidetrend(bands)) == len(df)
    w = indicators.woodies_cci(df, 7)
    assert {"last5_is_down", "last5_is_up"} <= set(w.columns)
    st = indicators.stochastic(df, 14, 3, 1)
    assert {"stoch_k", "stoch_d"} <= set(st.columns)
    assert np.isfinite(indicators.roc(df["close"], 9).dropna()).all()
    hv = indicators.fhv(df["close"], 33, 180)
    assert np.isfinite(hv.dropna()).all()
    assert indicators.fhvp(hv, 180).between(0, 100).all()
    holt = indicators.holt(df["close"], 0.3, 1e-6)
    assert {"level", "trend", "forecast"} <= set(holt.columns)
    cz = indicators.chop_zone(df, 30)
    assert {"angle", "trending", "choppy"} <= set(cz.columns)
    assert np.isfinite(indicators.zscore(df["close"], 20).dropna()).all()
    pat = indicators.candlestick_patterns(df)
    assert {"cs_long", "cs_short"} <= set(pat.columns)


# ---------------------------------------------------------------------------
# Filter framework
# ---------------------------------------------------------------------------
ALL_FILTER_CLASSES = [
    filters.FIRFilter,
    filters.PSARFilter,
    filters.MFIFilter,
    filters.ChaikinFilter,
    filters.CMOFilter,
    filters.CMFFilter,
    filters.AroonFilter,
    filters.AroonSidetrendFilter,
    filters.WoodiesCCIFilter,
    filters.StochFilter,
    filters.EWOFilter,
    filters.DualMAFilter,
    filters.ItrendFilter,
    filters.VolatilityFilter,
    filters.ForecastFilter,
    filters.ROCFilter,
    filters.CandlestickFilter,
    filters.RSIFilter,
    filters.ChopZoneFilter,
]


def test_all_filters_default_true_when_disabled():
    df = _candles()
    long_sig, short_sig = filters.combine_filter_signals(df, [])
    assert long_sig.all() and short_sig.all()


def test_each_filter_produces_boolean_columns():
    df = _candles()
    for cls in ALL_FILTER_CLASSES:
        filt = cls(enabled=True)
        long_allowed, short_allowed = filt.compute(df)
        assert len(long_allowed) == len(df)
        assert long_allowed.dtype == bool
        assert short_allowed.dtype == bool


def test_combine_filter_signals():
    df = _candles()
    active_filters = [filters.MFIFilter(enabled=True), filters.RSIFilter(enabled=True)]
    long_sig, short_sig = filters.combine_filter_signals(df, active_filters)
    assert long_sig.dtype == bool and short_sig.dtype == bool
    assert "long_mfi" in df.columns and "short_mfi" in df.columns


def test_confirmation_gate():
    raw = pd.Series([False, True, False, False, False, False, False])
    allowed = pd.Series([False, False, False, True, False, False, False])
    gated = filters.confirmation_gate(raw, allowed, lookback=3)
    # Signal on bar 1, confirmation appears on bar 3 (within lookback).
    assert gated.iloc[3] == True  # noqa: E712
    assert not gated.iloc[1] and not gated.iloc[2]


def test_apply_confirmation_gates():
    df = _candles()
    raw = pd.Series(False, index=df.index)
    raw.iloc[100] = True
    conf = [
        filters.ConfirmationFilter(
            long_allowed=lambda d, t: filters.PSARFilter().allowed(d, t)[0],
            short_allowed=lambda d, t: filters.PSARFilter().allowed(d, t)[1],
            lookback=3,
        )
    ]
    el, _es, _xl, _xs = filters.apply_confirmation_gates(raw, raw, raw, raw, conf, df)
    assert len(el) == len(df)


# ---------------------------------------------------------------------------
# Risk managers / exit levels
# ---------------------------------------------------------------------------
class _StubTrade:
    def __init__(self, is_short=False, open_rate=100.0):
        self.pair = "BTC/USDT"
        self.is_short = is_short
        self.open_rate = open_rate
        self.leverage = 1.0
        self.stake_amount = 1000.0
        self.open_date_utc = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self._data = {"entry_high": 101.0, "entry_low": 99.0}

    def get_custom_data(self, key, default=None):
        return self._data.get(key, default)

    def set_custom_data(self, key, value):
        self._data[key] = value


def test_percent_sl_manager():
    trade = _StubTrade(False, 100.0)
    manager = risk.PinePercentStopManager(5.0, 5.0)
    assert manager.stop_level(None, "x", trade, None, 100.0, 0.0, None) == 95.0
    short = _StubTrade(True, 100.0)
    assert manager.stop_level(None, "x", short, None, 100.0, 0.0, None) == 105.0


def test_atr_entry_sl_manager():
    df = _candles()
    trade = _StubTrade(False, 100.0)
    manager = risk.ATREntryStopManager(5, 1.5, "RMA")
    level = manager.stop_level(None, "x", trade, None, 100.0, 0.0, df)
    assert level is not None and level < 100.0


def test_partial_tp_progression():
    trade = _StubTrade(False, 100.0)
    tp = exit_levels.percent_tp_levels(100.0, False, [3, 6, 9], [0.25, 0.25, 0.25], ["a", "b", "c"])
    assert tp.new_hit(trade, 101.0, False) is None
    assert tp.new_hit(trade, 103.5, False) == (0.25, "a")
    assert tp.new_hit(trade, 103.5, False) is None  # already consumed
    assert tp.new_hit(trade, 106.5, False) == (0.25, "b")
    assert not tp.all_hit(trade)
    assert tp.new_hit(trade, 109.5, False) == (0.25, "c")
    assert tp.all_hit(trade)


# ---------------------------------------------------------------------------
# Order-management helpers
# ---------------------------------------------------------------------------
def test_bar_delay_signal():
    raw = pd.Series([True, False, False, False, False])
    delayed = signals.bar_delay_signal(raw, 2)
    assert delayed.iloc[2] == True  # noqa: E712
    assert not delayed.iloc[0] and not delayed.iloc[1]


def test_entry_delay_signal():
    raw = pd.Series([False, True, True, True, False])
    out = signals.entry_delay_signal(raw, 2)
    assert out.iloc[3] == True  # noqa: E712  (3rd consecutive True bar)
    assert not out.iloc[1] and not out.iloc[2]


def test_entries_per_cycle_gate():
    long_sig = pd.Series([True, True, True, False, True])
    short_sig = pd.Series([False, False, False, True, False])
    long_out, _short_out = signals.entries_per_cycle_gate(long_sig, short_sig, 2)
    assert long_out.iloc[0] and long_out.iloc[1]
    assert not long_out.iloc[2]  # blocked after 2
    assert long_out.iloc[4]  # unblocked by the short signal


def test_exit_on_opposite_entry():
    long_sig = pd.Series([True, False, False])
    short_sig = pd.Series([False, True, False])
    exit_long = pd.Series([False, False, False])
    _el, es, xl, _xs = signals.exit_on_opposite_entry(long_sig, short_sig, exit_long, exit_long)
    assert xl.iloc[1] == True  # noqa: E712  (short entry forces long exit)
    assert es.iloc[1] == True  # noqa: E712  (entry itself is not blocked here)
    # Blocking only when the current side already had an exit signal.
    exit_long2 = pd.Series([False, True, False])
    _el, es, xl, _xs = signals.exit_on_opposite_entry(
        long_sig, short_sig, exit_long2, exit_long2, block_opposite=True
    )
    assert not es.iloc[1]  # opposite entry blocked (existing long exit)


# ---------------------------------------------------------------------------
# Reference strategy compose path
# ---------------------------------------------------------------------------
def test_strategy_populate_paths():
    strategy = _strategy()
    df = _candles()
    result = strategy.populate_indicators(df.copy(), {"pair": "BTC/USDT"})
    required = {"atr", "long_filter_signal", "short_filter_signal"}
    assert required.issubset(result.columns)

    result = strategy.populate_entry_trend(result, {"pair": "BTC/USDT"})
    result = strategy.populate_exit_trend(result, {"pair": "BTC/USDT"})
    for col in ("enter_long", "enter_short", "exit_long", "exit_short"):
        assert col in result.columns
        assert result[col].isin([0, 1]).all()
    assert result["enter_short"].sum() == 0  # long-only by default


def test_strategy_with_filters_enabled():
    strategy = _strategy()
    strategy.filter_mfi_enabled = True
    strategy.filter_rsi_enabled = True
    df = _candles()
    result = strategy.populate_indicators(df.copy(), {"pair": "BTC/USDT"})
    result = strategy.populate_entry_trend(result, {"pair": "BTC/USDT"})
    assert "enter_long" in result.columns
    assert len(result) == len(df)


def test_strategy_build_level_sets():
    strategy = _strategy()
    strategy.sl_percentual_enabled = True
    strategy.tp_percentual_enabled = True
    trade = _StubTrade(False, 100.0)
    sl_sets, tp_sets = strategy.build_level_sets(trade)
    assert len(sl_sets) == 1 and len(sl_sets[0].levels) == 3
    assert len(tp_sets) == 1 and len(tp_sets[0].levels) == 3
    assert sl_sets[0].levels[0].price < 100.0
    assert tp_sets[0].levels[0].price > 100.0
