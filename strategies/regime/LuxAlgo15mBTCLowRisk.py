from datetime import datetime

import numpy as np
from pandas import DataFrame

import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute
from strategy_lib import risk as sl_risk
from strategy_lib.risk import SlTpConfig, TradeLevelsManager


class LuxAlgo15mBTCLowRisk(IStrategy):
    timeframe = "15m"
    can_short = False
    startup_candle_count: int = 250

    # Hard stop fallback
    stoploss = -0.10
    use_custom_stoploss = True

    # Let winners run
    minimal_roi = {
        "0": 0.20,
        "480": 0.10,
        "720": 0,
    }

    max_open_trades = 1

    # Parameters
    ema_fast = 21
    ema_slow = 55
    ema_trend = 200
    rsi_length = 14
    rsi_entry_long = 40
    rsi_entry_short = 60
    rsi_exit_long = 65
    rsi_exit_short = 35
    atr_length = 14
    atr_stop_mult = 1.5
    atr_trail_mult = 2.5
    volume_filter_mult = 1.2
    ppo_fast = 12
    ppo_slow = 26
    ppo_signal = 9
    sweep_lookback = 20
    vwap_lookback = 24

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=self.ema_trend)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_length)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_length)
        dataframe["volume_sma"] = dataframe["volume"].rolling(20).mean()

        # Prior N-bar low/high for liquidity-sweep detection
        dataframe["prior_low"] = dataframe["low"].shift(1).rolling(self.sweep_lookback).min()
        dataframe["prior_high"] = dataframe["high"].shift(1).rolling(self.sweep_lookback).max()

        # --- Higher timeframe (1h): jdehorty MTF momentum + LuxAlgo VWAP anchor ---
        if self.dp:
            informative_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
            ema_f = ta.EMA(informative_1h, timeperiod=self.ppo_fast)
            ema_s = ta.EMA(informative_1h, timeperiod=self.ppo_slow)
            informative_1h["ppo_1h"] = 100 * (ema_f - ema_s) / ema_s
            informative_1h["ppo_signal_1h"] = ta.EMA(
                informative_1h, timeperiod=self.ppo_signal, price="ppo_1h"
            )

            pv = informative_1h["close"] * informative_1h["volume"]
            informative_1h["vwap_1h"] = (
                pv.rolling(self.vwap_lookback).sum() / informative_1h["volume"].rolling(
                    self.vwap_lookback
                ).sum()
            )
            informative_1h = informative_1h[
                ["date", "ppo_1h", "ppo_signal_1h", "vwap_1h"]
            ].rename(columns={"date": "date_inf"})
            dataframe = merge_informative_pair(
                dataframe,
                informative_1h,
                self.timeframe,
                "1h",
                ffill=True,
                date_column="date_inf",
            )
            dataframe["ppo_1h"] = dataframe["ppo_1h_1h"].ffill()
            dataframe["ppo_signal_1h"] = dataframe["ppo_signal_1h_1h"].ffill()
            dataframe["vwap_1h"] = dataframe["vwap_1h_1h"].ffill()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Higher-timeframe momentum regime (jdehorty: MTF confirmation)
        htf_bull = (
            (dataframe["ppo_1h"] > 0)
            & (dataframe["ppo_1h"] > dataframe["ppo_signal_1h"])
            & (dataframe["close"] > dataframe["vwap_1h"])
        )
        htf_bear = (
            (dataframe["ppo_1h"] < 0)
            & (dataframe["ppo_1h"] < dataframe["ppo_signal_1h"])
            & (dataframe["close"] < dataframe["vwap_1h"])
        )

        # Momentum structure (LuxAlgo trend-pullback)
        ema_rising = dataframe["ema_fast"] > dataframe["ema_fast"].shift(1)

        # Pullback into the fast EMA mean that REVERSES (dip then reclaim).
        # LuxAlgo pullback: price touches the mean and closes back above it.
        pullback_long = (
            (dataframe["low"] <= dataframe["ema_fast"])  # dipped into the mean
            & (dataframe["close"] > dataframe["ema_fast"])  # and reclaimed it
            & (dataframe["close"] > dataframe["open"])  # bullish candle
        )
        pullback_short = (
            (dataframe["high"] >= dataframe["ema_fast"])
            & (dataframe["close"] < dataframe["ema_fast"])
            & (dataframe["close"] < dataframe["open"])
        )

        # Oversold/overbought RSI confirmation (must be turning)
        rsi_pullback_long = (
            (dataframe["rsi"] < self.rsi_entry_long)
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
        )
        rsi_pullback_short = (
            (dataframe["rsi"] > self.rsi_entry_short)
            & (dataframe["rsi"] < dataframe["rsi"].shift(1))
        )

        # Liquidity sweep + full reclaim (algoalpha / LuxAlgo SMC)
        sweep_long = (
            (dataframe["low"] < dataframe["prior_low"])
            & (dataframe["close"] > dataframe["ema_fast"])
            & (dataframe["close"] > dataframe["prior_low"])
        )
        sweep_short = (
            (dataframe["high"] > dataframe["prior_high"])
            & (dataframe["close"] < dataframe["ema_fast"])
            & (dataframe["close"] < dataframe["prior_high"])
        )

        vol_ok = dataframe["volume"] > self.volume_filter_mult * dataframe["volume_sma"]

        long_condition = (
            htf_bull
            & (dataframe["close"] > dataframe["ema_trend"])
            & (dataframe["ema_fast"] > dataframe["ema_slow"])
            & ema_rising
            & (pullback_long | rsi_pullback_long | sweep_long)
            & vol_ok
        )
        short_condition = (
            htf_bear
            & (dataframe["close"] < dataframe["ema_trend"])
            & (dataframe["ema_fast"] < dataframe["ema_slow"])
            & (~ema_rising)
            & (pullback_short | rsi_pullback_short | sweep_short)
            & vol_ok
        )
        dataframe.loc[long_condition, "enter_long"] = 1
        dataframe.loc[short_condition, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        exit_long_condition = (
            qtpylib.crossed_above(dataframe["rsi"], self.rsi_exit_long)
            | qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"])
        )
        exit_short_condition = (
            qtpylib.crossed_below(dataframe["rsi"], self.rsi_exit_short)
            | qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
        )
        dataframe.loc[exit_long_condition, "exit_long"] = 1
        dataframe.loc[exit_short_condition, "exit_short"] = 1
        # Never exit on the same candle a new entry is signalled (freqtrade would reject the entry)
        if "enter_long" in dataframe.columns:
            dataframe.loc[dataframe["enter_long"] == 1, "exit_long"] = 0
        if "enter_short" in dataframe.columns:
            dataframe.loc[dataframe["enter_short"] == 1, "exit_short"] = 0
        return dataframe

    def _risk_config(self) -> SlTpConfig:
        """Trailing ATR stop via the shared strategy_lib.risk engine.

        The ``Trailing ATR Candle`` mode anchors the stop on the candle low/high
        (``low - atr * mult`` long / ``high + atr * mult`` short), ratcheting only
        in the favorable direction. Take-profits stay disabled: winners run to the
        ROI table / exit signals.
        """
        return SlTpConfig(
            mode="Trailing ATR Candle",
            sl_size_or_atr_multiplier=float(self.atr_trail_mult),
            atr_length=int(self.atr_length),
            enable_take_profit=False,
        )

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float:
        config = self._risk_config()
        manager = getattr(self, "_risk_manager", None)
        if manager is None:
            manager = TradeLevelsManager(config)
            self._risk_manager = manager
        else:
            manager.config = config
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        levels = manager.current_trade_levels(pair, dataframe, trade, self.timeframe)
        if levels is None:
            return self.stoploss
        stop = levels["short_stop"] if trade.is_short else levels["long_stop"]
        if not np.isfinite(stop) or stop <= 0.0:
            return self.stoploss
        return stoploss_from_absolute(
            stop, current_rate, is_short=trade.is_short, leverage=trade.leverage
        )
