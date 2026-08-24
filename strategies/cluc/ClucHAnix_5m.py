import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import (
    merge_informative_pair,
    DecimalParameter,
    stoploss_from_absolute,
    RealParameter,
)
from strategy_lib.risk import SlTpConfig, TradeLevelsManager
from pandas import DataFrame, Series
from datetime import datetime


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - rolling_std * num_of_std
    return (np.nan_to_num(rolling_mean), np.nan_to_num(lower_band))


def ha_typical_price(bars):
    res = (bars["ha_high"] + bars["ha_low"] + bars["ha_close"]) / 3.0
    return Series(index=bars.index, data=res)


class ClucHAnix_5m(IStrategy):
    INTERFACE_VERSION = 3
    "\n    PASTE OUTPUT FROM HYPEROPT HERE\n    Can be overridden for specific sub-strategies (stake currencies) at the bottom.\n    "
    # hypered params
    buy_params = {
        "bbdelta_close": 0.01889,
        "bbdelta_tail": 0.72235,
        "close_bblower": 0.0127,
        "closedelta_close": 0.00916,
        "rocr_1h": 0.79492,
    }
    # Sell hyperspace params:
    # custom stoploss params, come from BB_RPB_TSL
    # sell signal params
    sell_params = {
        "pHSL": -0.08,
        "pPF_1": 0.011,
        "pPF_2": 0.064,
        "pSL_1": 0.011,
        "pSL_2": 0.062,
        "sell_fisher": 0.39075,
        "sell_bbmiddle_close": 0.99754,
    }
    # ROI table:
    minimal_roi = {"0": 100}
    # Stoploss:
    stoploss = -0.10
    # Trailing stop:
    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.012
    trailing_only_offset_is_reached = False
    "\n    END HYPEROPT\n    "
    timeframe = "5m"
    # Make sure these match or are not overridden in config
    use_exit_signal = True
    exit_profit_only = True
    ignore_roi_if_entry_signal = False
    # Custom stoploss
    use_custom_stoploss = True
    process_only_new_candles = True
    startup_candle_count = 168
    risk_per_trade = 0.005
    risk_stop_distance = 0.10
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "emergency_exit": "limit",
        "force_entry": "limit",
        "force_exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_limit_ratio": 0.99,
    }
    # buy params
    rocr_1h = RealParameter(0.5, 1.0, default=0.54904, space="buy", optimize=True)
    bbdelta_close = RealParameter(
        0.0005, 0.02, default=0.01965, space="buy", optimize=True
    )
    closedelta_close = RealParameter(
        0.0005, 0.02, default=0.00556, space="buy", optimize=True
    )
    bbdelta_tail = RealParameter(0.7, 1.0, default=0.95089, space="buy", optimize=True)
    close_bblower = RealParameter(
        0.0005, 0.02, default=0.00799, space="buy", optimize=True
    )
    # sell params
    sell_fisher = RealParameter(0.1, 0.5, default=0.38414, space="sell", optimize=True)
    sell_bbmiddle_close = RealParameter(
        0.97, 1.1, default=1.07634, space="sell", optimize=True
    )
    # hard stoploss profit
    pHSL = DecimalParameter(
        -0.15, -0.04, default=-0.08, decimals=3, space="sell", load=True
    )
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(
        0.008, 0.02, default=0.016, decimals=3, space="sell", load=True
    )
    pSL_1 = DecimalParameter(
        0.008, 0.02, default=0.011, decimals=3, space="sell", load=True
    )
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(
        0.04, 0.1, default=0.08, decimals=3, space="sell", load=True
    )
    pSL_2 = DecimalParameter(
        0.02, 0.07, default=0.04, decimals=3, space="sell", load=True
    )

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, "1h") for pair in pairs]
        return informative_pairs

    # come from BB_RPB_TSL

    def _risk_config(self) -> SlTpConfig:
        """Profit-tiered trailing stop via the shared strategy_lib.risk engine.

        Between ``pPF_1`` and ``pPF_2`` the stop is linearly interpolated
        (``pSL_1`` -> ``pSL_2``); above ``pPF_2`` it rises one-for-one with
        profit; below ``pPF_1`` the hard stop ``pHSL`` is used. When the tiered
        stop would sit at/above the current profit a tight 1% stop is armed.
        Take-profits stay disabled (exit signals / ROI).
        """
        return SlTpConfig(
            mode="Trailing Profit Tier",
            tier_p_hsl=float(self.pHSL.value),
            tier_p_pf_1=float(self.pPF_1.value),
            tier_p_sl_1=float(self.pSL_1.value),
            tier_p_pf_2=float(self.pPF_2.value),
            tier_p_sl_2=float(self.pSL_2.value),
            enable_take_profit=False,
        )

    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
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
        risk_stake = max_stake * self.risk_per_trade / (
            self.risk_stop_distance * max(leverage, 1.0)
        )
        if min_stake is not None:
            risk_stake = max(risk_stake, min_stake)
        return min(risk_stake, max_stake)

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
        return 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # # Heikin Ashi Candles
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe["ha_open"] = heikinashi["open"]
        dataframe["ha_close"] = heikinashi["close"]
        dataframe["ha_high"] = heikinashi["high"]
        dataframe["ha_low"] = heikinashi["low"]
        # Set Up Bollinger Bands
        (mid, lower) = bollinger_bands(
            ha_typical_price(dataframe), window_size=40, num_of_std=2
        )
        dataframe["lower"] = lower
        dataframe["mid"] = mid
        dataframe["bbdelta"] = (mid - dataframe["lower"]).abs()
        dataframe["closedelta"] = (
            dataframe["ha_close"] - dataframe["ha_close"].shift()
        ).abs()
        dataframe["tail"] = (dataframe["ha_close"] - dataframe["ha_low"]).abs()
        dataframe["bb_lowerband"] = dataframe["lower"]
        dataframe["bb_middleband"] = dataframe["mid"]
        dataframe["ema_fast"] = ta.EMA(dataframe["ha_close"], timeperiod=3)
        dataframe["ema_slow"] = ta.EMA(dataframe["ha_close"], timeperiod=50)
        dataframe["volume_mean_slow"] = dataframe["volume"].rolling(window=30).mean()
        dataframe["rocr"] = ta.ROCR(dataframe["ha_close"], timeperiod=28)
        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)
        inf_tf = "1h"
        informative = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=inf_tf
        )
        inf_heikinashi = qtpylib.heikinashi(informative)
        informative["ha_close"] = inf_heikinashi["close"]
        informative["ema_50"] = ta.EMA(informative["ha_close"], timeperiod=50)
        informative["ema_200"] = ta.EMA(informative["ha_close"], timeperiod=200)
        informative["rocr"] = ta.ROCR(informative["ha_close"], timeperiod=168)
        dataframe = merge_informative_pair(
            dataframe, informative, self.timeframe, inf_tf, ffill=True
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        regime_long = (
            (dataframe["ha_close"] > dataframe["ema_200_1h"])
            & (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
        )
        entry_signal = dataframe["rocr_1h"].gt(self.rocr_1h.value) & (
            (
                dataframe["lower"].shift().gt(0)
                & dataframe["bbdelta"].gt(dataframe["ha_close"] * self.bbdelta_close.value)
                & dataframe["closedelta"].gt(
                    dataframe["ha_close"] * self.closedelta_close.value
                )
                & dataframe["tail"].lt(dataframe["bbdelta"] * self.bbdelta_tail.value)
                & dataframe["ha_close"].lt(dataframe["lower"].shift())
                & dataframe["ha_close"].le(dataframe["ha_close"].shift())
            )
            |
            (
                (dataframe["ha_close"] < dataframe["ema_slow"])
                & (
                    dataframe["ha_close"]
                    < self.close_bblower.value * dataframe["bb_lowerband"]
                )
            )
        )
        dataframe.loc[
            regime_long & entry_signal,
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["fisher"] > self.sell_fisher.value)
            & dataframe["ha_high"].le(dataframe["ha_high"].shift(1))
            & dataframe["ha_high"].shift(1).le(dataframe["ha_high"].shift(2))
            & dataframe["ha_close"].le(dataframe["ha_close"].shift(1))
            & (dataframe["ema_fast"] > dataframe["ha_close"])
            & (
                dataframe["ha_close"] * self.sell_bbmiddle_close.value
                > dataframe["bb_middleband"]
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
