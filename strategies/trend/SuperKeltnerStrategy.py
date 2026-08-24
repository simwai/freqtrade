import logging
from datetime import datetime
from functools import reduce
from typing import Optional, Tuple

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence.trade_model import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute
from strategy_lib.risk import SlTpConfig, TradeLevelsManager


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class SuperKeltnerStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # ROI table:
    minimal_roi = {"0": 0.1, "10": 0.05, "20": 0.02, "30": 0}

    # Stoploss:
    stoploss = -0.1

    # Trailing stop:
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    timeframe = "1h"

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    use_custom_stoploss = True
    process_only_new_candles = True
    startup_candle_count: int = 200

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }

    # Keltner Channel parameters
    keltner_length = 20
    keltner_mult_add = 1.0
    keltner_mult_tp = 2.2
    keltner_atr_length = 10
    keltner_use_exp = True

    # SuperTrend parameters
    supertrend_atr_period = 10
    supertrend_factor = 3

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "keltner_ma": {"color": "#2962FF"},
                "keltner_upper_add": {"color": "#2962FF"},
                "keltner_lower_add": {"color": "#2962FF"},
                "keltner_upper_tp": {"color": "#2962FF"},
                "keltner_lower_tp": {"color": "#2962FF"},
                "supertrend": {"color": "green"},
            },
        }

    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Keltner Channels
        ma = (
            ta.EMA(dataframe, timeperiod=self.keltner_length)
            if self.keltner_use_exp
            else ta.SMA(dataframe, timeperiod=self.keltner_length)
        )
        atr = ta.ATR(dataframe, timeperiod=self.keltner_atr_length)
        dataframe["keltner_ma"] = ma
        dataframe["keltner_upper_add"] = ma + atr * self.keltner_mult_add
        dataframe["keltner_lower_add"] = ma - atr * self.keltner_mult_add
        dataframe["keltner_upper_tp"] = ma + atr * self.keltner_mult_tp
        dataframe["keltner_lower_tp"] = ma - atr * self.keltner_mult_tp

        # SuperTrend
        dataframe["supertrend"], dataframe["supertrend_direction"] = self.supertrend(
            dataframe, self.supertrend_factor, self.supertrend_atr_period
        )

        return dataframe

    def supertrend(
        self, dataframe: DataFrame, factor: float, atr_period: int
    ) -> Tuple[DataFrame, DataFrame]:
        atr = ta.ATR(dataframe, timeperiod=atr_period)
        hl2 = (dataframe["high"] + dataframe["low"]) / 2
        upperband = hl2 + (factor * atr)
        lowerband = hl2 - (factor * atr)
        supertrend = [0] * len(dataframe)
        supertrend_direction = [0] * len(dataframe)

        trend = 1
        for i in range(1, len(dataframe)):
            if dataframe["close"][i] > upperband[i - 1]:
                trend = 1
            elif dataframe["close"][i] < lowerband[i - 1]:
                trend = -1

            if trend == 1:
                supertrend[i] = lowerband[i]
            else:
                supertrend[i] = upperband[i]

            supertrend_direction[i] = trend

        return DataFrame(supertrend, index=dataframe.index), DataFrame(
            supertrend_direction, index=dataframe.index
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.normal_tf_indicators(dataframe, metadata)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        # Buy condition based on SuperTrend and Keltner Channels
        conditions.append(
            (dataframe["supertrend_direction"] < 0)
            & (dataframe["supertrend_direction"].shift(1) > 0)
        )

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "enter_long"] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        # Sell condition based on SuperTrend and Keltner Channels
        conditions.append(
            (dataframe["supertrend_direction"] > 0)
            & (dataframe["supertrend_direction"].shift(1) < 0)
        )

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "exit_long"] = 1

        return dataframe

    def _risk_config(self) -> SlTpConfig:
        """Entry-candle high/low stop via the shared strategy_lib.risk engine.

        NOTE: the previous implementation returned a *percentage* (-2.04) from
        ``custom_stoploss`` where freqtrade expects a ratio, so in practice the
        stop was a no-op (static ``-0.10`` + native trailing governed). The
        ``Entry Candle High Low`` mode implements the intended 2% stop: the
        tighter of ``entry_low * 0.98`` / ``close * 0.98`` (long), floored at
        the entry candle level.
        """
        return SlTpConfig(
            mode="Entry Candle High Low",
            entry_candle_buffer=0.02,
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

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Customize leverage for each new trade. This method is only called in futures mode.
        :param pair: Pair that's currently analyzed
        :param current_time: datetime object, containing the current datetime
        :param current_rate: Rate, calculated based on pricing settings in exit_pricing.
        :param proposed_leverage: A leverage proposed by the bot.
        :param max_leverage: Max leverage allowed on this pair
        :param entry_tag: Optional entry_tag (entry_tag) if provided with the buy signal.
        :param side: 'long' or 'short' - indicating the direction of the proposed trade
        :return: A leverage amount, which is between 1.0 and max_leverage.
        """
        return 3.0
