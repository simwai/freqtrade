"""Unit tests for the Hoffman IRB strategy (Pine -> Freqtrade port).

These exercise the vectorized state machine, the higher-timeframe EMA merge,
the risk-based sizing and the Freqtrade callbacks on synthetic candles.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
import talib.abstract as ta

from freqtrade.strategy import merge_informative_pair, stoploss_from_absolute


try:
    from user_data.strategies.pattern.HoffmanIRBStrategy import HoffmanIRBStrategy, _Setup
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


def _htf_df(dataframe: pd.DataFrame, htf: str = "15min") -> pd.DataFrame:
    return (
        dataframe.set_index("date")
        .resample(htf, origin="start_day", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )


class _FakeDP:
    def __init__(self, dataframe: pd.DataFrame):
        self._df = dataframe
        self._htf = _htf_df(dataframe)

    def current_whitelist(self):
        return ["BTC/USDT:USDT"]

    def get_pair_dataframe(self, pair, timeframe, candle_type=""):
        if timeframe == "15m":
            return self._htf.copy()
        return self._df.copy()

    def get_analyzed_dataframe(self, pair, timeframe):
        return self._df.copy(), datetime(2024, 1, 2, tzinfo=timezone.utc)


def _strategy(df=None) -> HoffmanIRBStrategy:
    strategy = HoffmanIRBStrategy({})
    if df is not None:
        strategy.dp = _FakeDP(df)
    return strategy


def _state_df(count: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=count, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "date": dates,
            "h1": 100.0,
            "l1": 90.0,
            "high": 100.0,
            "low": 90.0,
            "atr": 2.0,
            "irb_bear": False,
            "irb_bull": False,
            "irb_up_trend": True,
            "irb_down_trend": True,
        }
    )


class _StubTrade:
    def __init__(self, is_short=False, open_rate=100.0, enter_tag="irb_long_50"):
        self.pair = "BTC/USDT:USDT"
        self.is_short = is_short
        self.open_rate = open_rate
        self.leverage = 1.0
        self.enter_tag = enter_tag
        self.entry_side = "short" if is_short else "long"
        self.nr_of_successful_entries = 1
        self._data = {}

    def get_custom_data(self, key, default=None):
        return self._data.get(key, default)

    def set_custom_data(self, key, value):
        self._data[key] = value


def _long_setup(
    entry=110.0, stop=90.0, atr=5.0, tag="irb_long_50", target=None, bar=50, date=None
) -> _Setup:
    return _Setup(
        pair="BTC/USDT:USDT",
        tag=tag,
        direction="long",
        bar=bar,
        date=date if date is not None else pd.Timestamp("2024-01-01", tz="UTC"),
        entry=entry,
        stop=stop,
        target=target if target is not None else entry + 1.5 * abs(entry - stop),
        atr=atr,
        qty_valid=True,
    )


# ---------------------------------------------------------------------------
# Strategy defaults
# ---------------------------------------------------------------------------
def test_strategy_defaults():
    strategy = HoffmanIRBStrategy({})
    assert strategy.can_short is True
    assert strategy.leverage("X", None, 100.0, 2.0, 5.0, None, "long") == 1.0
    assert strategy.pct == 45
    assert strategy.max_wait == 20
    assert strategy.require_body is True
    assert strategy.risk_pct == 0.01
    assert strategy.use_tick_pad is True
    assert strategy._param("ema_len") == 20
    assert strategy._param("htf") == "15m"
    assert strategy._param("atr_len") == 14
    assert strategy._param("atr_mult") == 1.5
    assert strategy._param("rr") == 1.5
    assert strategy._param("max_lev") == 5.0


# ---------------------------------------------------------------------------
# Populate paths
# ---------------------------------------------------------------------------
def test_strategy_populates_native_signal_columns():
    dataframe = _candles()
    strategy = _strategy(dataframe)

    result = strategy.populate_indicators(dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    result = strategy.populate_entry_trend(result, {"pair": "BTC/USDT:USDT"})
    result = strategy.populate_exit_trend(result, {"pair": "BTC/USDT:USDT"})

    assert len(result) == len(dataframe)
    required = {
        "o1",
        "h1",
        "l1",
        "c1",
        "ema",
        "atr",
        "htf_ema",
        "irb_bear",
        "irb_bull",
        "irb_up_trend",
        "irb_down_trend",
        "irb_enter_long",
        "irb_enter_short",
        "enter_long",
        "enter_short",
        "exit_long",
        "exit_short",
        "enter_tag",
    }
    assert required.issubset(result.columns)
    for column in ("enter_long", "enter_short", "exit_long", "exit_short"):
        assert result[column].isin([0, 1]).all()


def test_signals_are_causal():
    dataframe = _candles()
    prefix = dataframe.iloc[:400].copy()

    prefix_strategy = _strategy(prefix)
    full_strategy = _strategy(dataframe)

    prefix_result = prefix_strategy.populate_indicators(prefix.copy(), {"pair": "BTC/USDT:USDT"})
    full_result = full_strategy.populate_indicators(dataframe.copy(), {"pair": "BTC/USDT:USDT"})

    for column in ("irb_enter_long", "irb_enter_short", "irb_bear", "irb_bull"):
        assert (
            prefix_result[column].to_numpy() == full_result[column].to_numpy()[: len(prefix)]
        ).all()


# ---------------------------------------------------------------------------
# Higher-timeframe EMA
# ---------------------------------------------------------------------------
def test_htf_ema_uses_previous_completed_htf_bar():
    dataframe = _candles()
    strategy = _strategy(dataframe)
    strategy.ema_len.value = 3
    result = strategy.populate_indicators(dataframe.copy(), {"pair": "BTC/USDT:USDT"})

    inf = _htf_df(dataframe)
    inf_ema = pd.Series(ta.EMA(inf["close"], timeperiod=3), index=inf.index)

    # Expected: the previous completed HTF bar's EMA, merged like the strategy.
    shifted = inf.copy()
    shifted["htf_ema"] = inf_ema.shift(1)
    expected = merge_informative_pair(dataframe[["date"]].copy(), shifted, "5m", "15m", ffill=True)[
        "htf_ema_15m"
    ]

    actual = result["htf_ema"]
    valid = actual.notna() & expected.notna()
    assert np.allclose(actual[valid].to_numpy(), expected[valid].to_numpy(), equal_nan=True)

    # It must genuinely lag one HTF bar (differ from the unshifted merge).
    current = inf.copy()
    current["htf_ema"] = inf_ema
    unshifted = merge_informative_pair(
        dataframe[["date"]].copy(), current, "5m", "15m", ffill=True
    )["htf_ema_15m"]
    assert (result["htf_ema"].to_numpy() != unshifted.to_numpy()).any()


def test_htf_ema_falls_back_to_base_when_timeframe_equals_base():
    dataframe = _candles()
    strategy = _strategy(dataframe)
    strategy.htf.value = "5m"
    result = strategy.populate_indicators(dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    # htf_ema is the base EMA shifted one more bar (previous bar's EMA).
    expected = result["ema"].shift(1)
    valid = result["htf_ema"].notna() & expected.notna()
    assert (result.loc[valid, "htf_ema"] == expected[valid]).all()


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def test_state_machine_resting_order_until_breakout():
    strategy = _strategy()
    df = _state_df()
    df.loc[50, "irb_bear"] = True  # long setup (bearIRB = bullish continuation)
    df.loc[52, "high"] = 101.0  # breakout above h1 (100) + tick pad -> consumed

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    # The resting order is signaled from the setup bar until the breakout bar.
    assert result["irb_enter_long"].iloc[50]
    assert result["irb_enter_long"].iloc[51]
    assert not result["irb_enter_long"].iloc[52]
    assert result["irb_tag"].iloc[50] == "irb_long_50"
    assert result["irb_tag"].iloc[51] == "irb_long_50"
    assert result["irb_enter_short"].sum() == 0


def test_state_machine_short_side():
    strategy = _strategy()
    df = _state_df()
    df.loc[50, "irb_bull"] = True  # short setup
    df.loc[53, "low"] = 89.0  # breakout below l1 (90) - tick pad -> consumed

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_short"].iloc[50]
    assert result["irb_enter_short"].iloc[52]
    assert not result["irb_enter_short"].iloc[53]
    assert result["irb_tag"].iloc[50] == "irb_short_50"


def test_state_machine_expires_after_max_wait():
    strategy = _strategy()
    strategy.max_wait = 3
    df = _state_df()
    df.loc[50, "irb_bear"] = True
    df.loc[55, "high"] = 101.0  # breakout happens after the window expired

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_long"].iloc[53]  # still pending before expiry
    assert not result["irb_enter_long"].iloc[54]  # expired at close of bar 54
    assert not result["irb_enter_long"].iloc[55]  # late breakout does not re-arm


def test_state_machine_trend_death_cancels_pending():
    strategy = _strategy()
    df = _state_df()
    df.loc[50, "irb_bear"] = True
    df.loc[52, "irb_up_trend"] = False  # trend dies at close of bar 52
    df.loc[53, "high"] = 101.0  # breakout after trend death -> no signal

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_long"].iloc[50]
    assert result["irb_enter_long"].iloc[51]
    assert not result["irb_enter_long"].iloc[52]
    assert not result["irb_enter_long"].iloc[53]


def test_state_machine_skips_bad_qty_setup():
    strategy = _strategy()
    strategy.use_tick_pad = False
    df = _state_df()
    df.loc[50, "l1"] = 100.0  # equals h1 -> entry == stop -> degenerate
    df.loc[50, "irb_bear"] = True
    df.loc[52, "high"] = 101.0

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_long"].sum() == 0


def test_new_setup_replaces_pending():
    strategy = _strategy()
    df = _state_df()
    df.loc[50, "irb_bear"] = True  # long setup at h1=100
    df.loc[55, "h1"] = 105.0  # newer long setup at a higher level
    df.loc[55, "irb_bear"] = True
    df.loc[56, "high"] = 104.0  # breaks old level, not the new one
    df.loc[57, "high"] = 106.0  # breaks the new level -> consumed

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_long"].iloc[54]
    assert result["irb_tag"].iloc[54] == "irb_long_50"
    assert result["irb_enter_long"].iloc[56]
    assert result["irb_tag"].iloc[56] == "irb_long_55"
    assert not result["irb_enter_long"].iloc[57]


# ---------------------------------------------------------------------------
# Quantity / risk guard
# ---------------------------------------------------------------------------
def test_qty_guard_rejects_degenerate_setup():
    strategy = _strategy()
    assert not strategy._qty_valid(100.0, 100.0, 1.0)
    assert not strategy._qty_valid(np.nan, 90.0, 1.0)
    assert not strategy._qty_valid(110.0, np.nan, 1.0)
    assert strategy._qty_valid(110.0, 90.0, 1.0)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
def test_custom_entry_price_returns_stop_level():
    strategy = _strategy()
    strategy._pair_cache("BTC/USDT:USDT")["irb_long_50"] = _long_setup()
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert (
        strategy.custom_entry_price("BTC/USDT:USDT", None, current, 100.0, "irb_long_50", "long")
        == 110.0
    )
    # Unknown tag falls back to the proposed rate.
    assert (
        strategy.custom_entry_price("BTC/USDT:USDT", None, current, 100.0, "unknown", "long")
        == 100.0
    )


def test_custom_stake_amount_risk_sizing():
    strategy = _strategy()
    strategy._pair_cache("BTC/USDT:USDT")["irb_long_50"] = _long_setup()
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)

    stake = strategy.custom_stake_amount(
        "BTC/USDT:USDT", current, 110.0, 1000.0, 1.0, 10000.0, 1.0, "irb_long_50", "long"
    )
    # qty_raw = 10000 * 0.01 / 20 = 5.0, qty_max = 10000 * 5 / 110, qty = 5.0, stake = 5 * 110.
    assert stake == pytest.approx(550.0)


def test_custom_stake_amount_zero_when_degenerate():
    strategy = _strategy()
    strategy._pair_cache("BTC/USDT:USDT")["irb_bad"] = _long_setup(entry=100.0, stop=100.0)
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)

    stake = strategy.custom_stake_amount(
        "BTC/USDT:USDT", current, 100.0, 1000.0, 1.0, 10000.0, 1.0, "irb_bad", "long"
    )
    assert stake == 0.0


def test_custom_stoploss_uses_hoffman_stop():
    strategy = _strategy()
    trade = _StubTrade()
    trade.set_custom_data("irb_stop", 89.0)
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)

    stop = strategy.custom_stoploss(
        "BTC/USDT:USDT", trade, current, current_rate=95.0, current_profit=0.0
    )
    assert stop == stoploss_from_absolute(89.0, 95.0, False, 1.0)


def test_custom_exit_triggers_on_target():
    dataframe = _candles()
    dataframe.loc[dataframe.index[-1], "high"] = 112.0
    strategy = _strategy(dataframe)
    trade = _StubTrade()
    trade.set_custom_data("irb_target", 110.0)
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert strategy.custom_exit("BTC/USDT:USDT", trade, current, 100.0, 0.0) == "irb_target"

    short_trade = _StubTrade(is_short=True)
    short_trade.set_custom_data("irb_target", 90.0)
    dataframe.loc[dataframe.index[-1], "low"] = 88.0
    strategy.dp = _FakeDP(dataframe)
    assert strategy.custom_exit("BTC/USDT:USDT", short_trade, current, 100.0, 0.0) == "irb_target"


def test_custom_exit_price_returns_target():
    strategy = _strategy()
    trade = _StubTrade()
    trade.set_custom_data("irb_target", 140.0)
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert (
        strategy.custom_exit_price("BTC/USDT:USDT", trade, current, 130.0, 0.1, "irb_target")
        == 140.0
    )
    assert strategy.custom_exit_price("BTC/USDT:USDT", trade, current, 130.0, 0.1, "other") == 130.0


def test_confirm_trade_entry_rejects_clamped_fills():
    strategy = _strategy()
    strategy._pair_cache("BTC/USDT:USDT")["irb_long_50"] = _long_setup(entry=110.0, stop=90.0)
    strategy._pair_cache("BTC/USDT:USDT")["irb_short_50"] = _Setup(
        pair="BTC/USDT:USDT",
        tag="irb_short_50",
        direction="short",
        bar=50,
        date=pd.Timestamp("2024-01-02", tz="UTC"),
        entry=90.0,
        stop=110.0,
        target=80.0,
        atr=5.0,
        qty_valid=True,
    )
    current = datetime(2024, 1, 2, tzinfo=timezone.utc)

    # A long must never fill below the setup level (clamped pullback fill).
    assert (
        strategy.confirm_trade_entry(
            "BTC/USDT:USDT", "limit", 1.0, 105.0, "GTC", current, "irb_long_50", "long"
        )
        is False
    )
    assert (
        strategy.confirm_trade_entry(
            "BTC/USDT:USDT", "limit", 1.0, 110.0, "GTC", current, "irb_long_50", "long"
        )
        is True
    )

    # A short must never fill above the setup level.
    assert (
        strategy.confirm_trade_entry(
            "BTC/USDT:USDT", "limit", 1.0, 95.0, "GTC", current, "irb_short_50", "short"
        )
        is False
    )
    assert (
        strategy.confirm_trade_entry(
            "BTC/USDT:USDT", "limit", 1.0, 90.0, "GTC", current, "irb_short_50", "short"
        )
        is True
    )


def test_adjust_order_price_cancels_stale_setup():
    strategy = _strategy()
    cache = strategy._pair_cache("BTC/USDT:USDT")
    base_date = pd.Timestamp("2024-01-02", tz="UTC")
    cache["irb_long_50"] = _long_setup(tag="irb_long_50", bar=50, date=base_date)
    cache["irb_long_60"] = _long_setup(
        tag="irb_long_60", entry=115.0, stop=95.0, bar=60, date=base_date
    )
    current = datetime(2024, 1, 2, 0, 10, tzinfo=timezone.utc)

    # The older setup is superseded by a newer one -> cancel.
    assert (
        strategy.adjust_order_price(
            _StubTrade(enter_tag="irb_long_50"),
            None,
            "BTC/USDT:USDT",
            current,
            110.0,
            110.0,
            "irb_long_50",
            "long",
            True,
        )
        is None
    )
    # The newest setup keeps its level.
    assert (
        strategy.adjust_order_price(
            _StubTrade(enter_tag="irb_long_60"),
            None,
            "BTC/USDT:USDT",
            current,
            110.0,
            115.0,
            "irb_long_60",
            "long",
            True,
        )
        == 115.0
    )


# ---------------------------------------------------------------------------
# Fee-distance guard
# ---------------------------------------------------------------------------
def test_fee_filter_disabled_by_default():
    strategy = _strategy()
    assert strategy.min_target_fee_mult == 0.0
    # Guard off: any distance passes.
    assert strategy._fee_filter_ok(100.0, 99.999)
    assert strategy._fee_filter_ok(100.0, 99.0)


def test_fee_filter_rejects_targets_below_fee_threshold():
    strategy = _strategy()
    strategy.min_target_fee_mult = 2.0
    # rr=1.5, fee_rate=0.0005 -> required target distance = 2 * 0.001 * entry.
    strategy.rr.value = 1.5
    # Target distance = 1.5 * 0.1 = 0.15 (0.15% of entry) < 0.2% required.
    assert strategy._fee_filter_ok(100.0, 99.9) is False
    # Target distance = 1.5 * 1.0 = 1.5 (1.5% of entry) >= 0.2% required.
    assert strategy._fee_filter_ok(100.0, 99.0) is True
    # Degenerate input never passes.
    assert strategy._fee_filter_ok(0.0, 99.0) is False
    assert strategy._fee_filter_ok(float("nan"), 99.0) is False


def test_fee_filter_skips_setups_in_state_machine():
    strategy = _strategy()
    strategy.min_target_fee_mult = 2.0
    df = _state_df()
    df.loc[50, "irb_bear"] = True  # h1=100, l1=90 -> huge range, passes the guard
    df.loc[70, "h1"] = 100.0
    df.loc[70, "l1"] = 99.97  # 0.03% range: 1.5R = 0.045% << 0.2% fee threshold
    df.loc[70, "irb_bear"] = True
    df.loc[72, "high"] = 101.0

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    # The wide-range setup is signaled and breaks out; the tiny-range one is not.
    assert result["irb_enter_long"].iloc[50]
    assert not result["irb_enter_long"].iloc[70:75].any()
    assert result["irb_tag"].iloc[50] == "irb_long_50"


def test_fee_filter_applies_on_short_setups():
    strategy = _strategy()
    strategy.min_target_fee_mult = 2.0
    df = _state_df()
    df.loc[50, "irb_bull"] = True  # entry 90-pad, stop 100+pad: wide range
    df.loc[53, "low"] = 89.0

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_short"].iloc[50]
    assert result["irb_tag"].iloc[50] == "irb_short_50"


# ---------------------------------------------------------------------------
# Volatility-regime guard
# ---------------------------------------------------------------------------
def test_vol_regime_disabled_by_default():
    strategy = _strategy()
    assert strategy.vol_regime_pctile_min == 0.0
    assert strategy.vol_regime_window == 500
    # Guard off: any percentile passes (NaN included).
    assert strategy._vol_regime_ok(0.5)
    assert strategy._vol_regime_ok(0.99)
    assert strategy._vol_regime_ok(float("nan"))


def test_vol_regime_skips_low_volatility_setups():
    strategy = _strategy()
    strategy.vol_regime_pctile_min = 0.8
    df = _state_df()
    # Populate the percentile column with a known value at the setup bar
    # (bar 50 -> pctile 0.5, below the 0.8 threshold -> guard should reject).
    df["vol_regime_pctile"] = 0.5
    df.loc[50, "irb_bear"] = True  # wide range, qty/fee guards pass
    df.loc[52, "high"] = 101.0  # breakout -> consume

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    # The setup is rejected: no irb_enter_long anywhere in the breakout window.
    assert not result["irb_enter_long"].iloc[50:75].any()
    assert result["irb_tag"].iloc[50:75].isna().all()


def test_vol_regime_allows_high_volatility_setups():
    strategy = _strategy()
    strategy.vol_regime_pctile_min = 0.8
    df = _state_df()
    df["vol_regime_pctile"] = 0.9
    df.loc[50, "irb_bear"] = True
    df.loc[52, "high"] = 101.0

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_long"].iloc[50]
    assert result["irb_tag"].iloc[50] == "irb_long_50"


def test_vol_regime_treats_warmup_nan_as_not_high_vol():
    strategy = _strategy()
    strategy.vol_regime_pctile_min = 0.8
    df = _state_df()
    # NaN during the rolling window's warmup -> conservative: skip.
    df["vol_regime_pctile"] = float("nan")
    df.loc[50, "irb_bear"] = True
    df.loc[52, "high"] = 101.0

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert not result["irb_enter_long"].iloc[50:75].any()


def test_vol_regime_applies_on_short_setups():
    strategy = _strategy()
    strategy.vol_regime_pctile_min = 0.8
    df = _state_df()
    df["vol_regime_pctile"] = 0.5
    df.loc[50, "irb_bull"] = True  # wide range, short setup
    df.loc[53, "low"] = 89.0

    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert not result["irb_enter_short"].iloc[50:75].any()


# ---------------------------------------------------------------------------
# Consecutive-loss lockout
# ---------------------------------------------------------------------------
def test_loss_streak_lockout_disabled_by_default():
    strategy = _strategy()
    assert strategy.loss_streak_lockout == 0
    assert strategy.loss_streak_cooldown_min == 0
    # No lockout, three losses in a row -> side still open.
    from datetime import datetime, timezone

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    assert strategy._is_side_locked(False, base) is False


def test_loss_streak_lockout_engages_after_threshold():
    from datetime import datetime, timezone

    strategy = _strategy()
    strategy.loss_streak_lockout = 3
    strategy.loss_streak_cooldown_min = 240
    base = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    # Two losses: still open.
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    assert strategy._is_side_locked(False, base) is False
    # Third loss: locked until 16:00 UTC.
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    assert strategy._is_side_locked(False, base) is True
    # 30 minutes later: still locked.
    later = datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc)
    assert strategy._is_side_locked(False, later) is True
    # After 240 minutes: open again.
    after = datetime(2024, 1, 1, 16, 1, tzinfo=timezone.utc)
    assert strategy._is_side_locked(False, after) is False


def test_loss_streak_lockout_resets_on_win():
    from datetime import datetime, timezone

    strategy = _strategy()
    strategy.loss_streak_lockout = 3
    strategy.loss_streak_cooldown_min = 240
    base = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    # Win in between: streak cleared.
    strategy._record_trade_close(0.01, is_short=False, close_time=base)
    # Two more losses: still open (streak restarted at 0).
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    assert strategy._is_side_locked(False, base) is False


def test_loss_streak_lockout_is_per_side():
    from datetime import datetime, timezone

    strategy = _strategy()
    strategy.loss_streak_lockout = 3
    strategy.loss_streak_cooldown_min = 240
    base = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    for _ in range(3):
        strategy._record_trade_close(-0.01, is_short=False, close_time=base)
    # Long is locked, short is not.
    assert strategy._is_side_locked(False, base) is True
    assert strategy._is_side_locked(True, base) is False


def test_loss_streak_lockout_cooldown_expires():
    from datetime import datetime, timezone

    strategy = _strategy()
    strategy.loss_streak_lockout = 3
    strategy.loss_streak_cooldown_min = 240
    # Set the lockout anchored 5 hours ago, so the cooldown has already
    # expired by the time we check.
    ancient = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    for _ in range(3):
        strategy._record_trade_close(-0.01, is_short=False, close_time=ancient)
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert strategy._is_side_locked(False, now) is False


# ---------------------------------------------------------------------------
# Ehlers Super PassBand Filter
# ---------------------------------------------------------------------------
def test_spbf_guard_disabled_by_default():
    strategy = _strategy()
    assert strategy.spbf_length1 == 0
    assert strategy.spbf_length2 == 0
    # Guard off: any value passes (including NaN).
    assert strategy._spbf_ok("long", 1.0, 1.0)
    assert strategy._spbf_ok("long", float("nan"), float("nan"))


def test_spbf_guard_long_only_when_pb_above_rms():
    strategy = _strategy()
    strategy.spbf_length1 = 40
    strategy.spbf_length2 = 60
    # pb > rms: long allowed, short rejected.
    assert strategy._spbf_ok("long", 2.0, 1.0) is True
    assert strategy._spbf_ok("short", 2.0, 1.0) is False


def test_spbf_guard_short_only_when_pb_below_minus_rms():
    strategy = _strategy()
    strategy.spbf_length1 = 40
    strategy.spbf_length2 = 60
    # pb < -rms: short allowed, long rejected.
    assert strategy._spbf_ok("short", -2.0, 1.0) is True
    assert strategy._spbf_ok("long", -2.0, 1.0) is False


def test_spbf_guard_rejects_inside_band():
    strategy = _strategy()
    strategy.spbf_length1 = 40
    strategy.spbf_length2 = 60
    # |pb| <= rms: both directions rejected.
    assert strategy._spbf_ok("long", 0.5, 1.0) is False
    assert strategy._spbf_ok("short", 0.5, 1.0) is False
    assert strategy._spbf_ok("long", -0.5, 1.0) is False
    assert strategy._spbf_ok("short", -0.5, 1.0) is False


def test_spbf_guard_treats_warmup_nan_as_rejected():
    strategy = _strategy()
    strategy.spbf_length1 = 40
    strategy.spbf_length2 = 60
    # NaN during warmup -> conservative: reject.
    assert strategy._spbf_ok("long", float("nan"), 1.0) is False
    assert strategy._spbf_ok("long", 2.0, float("nan")) is False
    assert strategy._spbf_ok("short", -2.0, 0.0) is False  # rms <= 0


def test_spbf_guard_rejects_long_when_short_band_set():
    df = _state_df()
    df["spbf_pb"] = -2.0  # below the lower band
    df["spbf_rms"] = 1.0
    df.loc[50, "irb_bear"] = True  # long setup
    df.loc[52, "high"] = 101.0
    df.loc[52, "low"] = 95.0

    strategy = _strategy()
    strategy.spbf_length1 = 40
    strategy.spbf_length2 = 60
    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert not result["irb_enter_long"].iloc[50:75].any()


def test_spbf_guard_allows_long_when_pb_above_rms():
    df = _state_df()
    df["spbf_pb"] = 2.0  # above the upper band
    df["spbf_rms"] = 1.0
    df.loc[50, "irb_bear"] = True
    df.loc[52, "high"] = 101.0
    df.loc[52, "low"] = 95.0

    strategy = _strategy()
    strategy.spbf_length1 = 40
    strategy.spbf_length2 = 60
    result = strategy._build_signals(df.copy(), "BTC/USDT:USDT")

    assert result["irb_enter_long"].iloc[50]


def test_15m_variant_defaults():
    from user_data.strategies.pattern.HoffmanIRBStrategy15m import HoffmanIRBStrategy15m

    strategy = HoffmanIRBStrategy15m({})
    assert strategy.timeframe == "15m"
    assert strategy._param("htf") == "1h"
    assert strategy.min_target_fee_mult == 2.0
    # Inherited faithful defaults stay untouched.
    assert strategy.pct == 45
    assert strategy.rr.value == 1.5
