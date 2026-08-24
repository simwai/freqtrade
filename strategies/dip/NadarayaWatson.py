# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401

# --- Do not remove these libs ---
import numpy as np  # noqa
import pandas as pd  # noqa

pd.options.mode.chained_assignment = None  # default='warn'
from pandas import DataFrame

from freqtrade.strategy import IStrategy
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter

from user_data.strategies.components.risk import RiskMixin, TimeCutStopManager

# --------------------------------
# Add your lib to import here
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import math
from technical.indicators import atr
import logging
from functools import reduce

logger = logging.getLogger(__name__)


def funcNadarayaWatsonEnvelope(dtloc, source="close", bandwidth=8, window=500, mult=3):
    """
    // This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
    // Nadaraya-Watson Envelope [LUX]
      https://www.tradingview.com/script/Iko0E2kL-Nadaraya-Watson-Envelope-LUX/
     :return: up and down
     translated for freqtrade: viksal1982  viktors.s@gmail.com

     df.shape[0]
    """
    dtNWE = dtloc.copy()
    dtNWE["nwe_center"] = np.nan
    dtNWE["nwe_up"] = np.nan
    dtNWE["nwe_down"] = np.nan
    wn = np.zeros((window, window))
    for i in range(window):
        for j in range(window):
            wn[i, j] = math.exp(-(math.pow(i - j, 2) / (bandwidth * bandwidth * 2)))
    sumSCW = wn.sum(axis=1)

    def calc_nwa(dfr, init=0):
        global calc_src_value
        if init == 1:
            calc_src_value = list()
            return
        calc_src_value.append(dfr[source])
        mae = 0.0
        y2_val = 0.0
        y2_val_up = np.nan
        y2_val_down = np.nan
        if len(calc_src_value) > window:
            calc_src_value.pop(0)
        if len(calc_src_value) >= window:
            src = np.array(calc_src_value)
            sumSC = src * wn
            sumSCS = sumSC.sum(axis=1)
            y2 = sumSCS / sumSCW
            sum_e = np.absolute(src - y2)
            mae = sum_e.sum() / window * mult
            y2_val = y2[-1]
            y2_val_up = y2_val + mae
            y2_val_down = y2_val - mae
        return y2_val, y2_val_up, y2_val_down

    calc_nwa(None, init=1)
    dtNWE[["nwe_center", "nwe_up", "nwe_down"]] = dtNWE.apply(
        calc_nwa, axis=1, result_type="expand"
    )
    return dtNWE[["nwe_center", "nwe_up", "nwe_down"]]


class NadarayaWatson(RiskMixin, IStrategy):
    # Optimal timeframe for the strategy.
    timeframe = "5m"

    # These values can be overridden in the "ask_strategy" section in the config.
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    can_short = True

    # Number of candles the strategy requires before producing valid signals
    startup_candle_count: int = 300

    minimal_roi = {"0": 100}

    stoploss = -0.05
    trailing_stop = False
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.019
    trailing_only_offset_is_reached = True
    process_only_new_candles = False

    # @property
    # def protections(self):
    #     return [
    #         {"method": "CooldownPeriod", "stop_duration": 120},
    #         {
    #             "method": "StoplossGuard",
    #             "lookback_period": 90,
    #             "trade_limit": 2,
    #             "stop_duration": 120,
    #             "only_per_pair": False,
    #         },
    #         {
    #             "method": "StoplossGuard",
    #             "lookback_period": 90,
    #             "trade_limit": 1,
    #             "stop_duration": 120,
    #             "only_per_pair": True,
    #         },
    #     ]

    # Optional order type mapping.
    order_types = {
        "entry": "limit",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # Optional order time in force.
    order_time_in_force = {"entry": "gtc", "exit": "gtc"}

    plot_config = {
        # Main plot indicators (Moving averages, ...)
        "main_plot": {
            "nwe_center": {"color": "orange"},
            "nwe_up": {"color": "red"},
            "nwe_down": {"color": "rgba(155,150,200,2.4)"},
            "atr_long": {"color": "purple"},
            "atr_short": {"color": "blue"},
        }
    }

    # Hyeropt
    atr_length = IntParameter(2, 200, default=5, space="sell", optimize=True)
    window_buy = IntParameter(60, 1000, default=300, space="buy", optimize=True)
    bandwidth_buy = IntParameter(2, 15, default=8, space="buy", optimize=True)
    mult_buy = DecimalParameter(0.5, 20.0, default=4, decimals=1, space="buy", optimize=True)
    atr_long_exit_multiplier = DecimalParameter(
        1.5, 20.0, default=3, decimals=1, space="sell", optimize=True
    )
    atr_short_exit_multiplier = DecimalParameter(
        1.5, 20.0, default=3, decimals=1, space="sell", optimize=True
    )
    is_timed_exit = CategoricalParameter([True, False], default=True, space="sell", optimize=True)

    ## Custom stoploss
    @property
    def stop_managers(self):
        """Time-cut stop (components equivalent of the strategy_lib "Time Cut"
        engine): once the trade has been open ``time_cut_minutes`` and is in
        the red, a tight 1% stop is armed; otherwise ``self.stoploss`` (-0.05)
        acts as the hard loss floor. ``is_timed_exit`` disables the cut.

        Note: the components manager arms *short* stops when the short is
        losing (price above entry). strategy_lib armed short cuts while the
        short was *profitable* (a bug); this migration adopts the clean
        semantics.
        """
        minutes = 120 if self.is_timed_exit.value else 0
        return [TimeCutStopManager(minutes=minutes, cut=0.01)]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe[["nwe_center", "nwe_up", "nwe_down"]] = funcNadarayaWatsonEnvelope(
            dataframe,
            source="close",
            bandwidth=self.bandwidth_buy.value,
            window=self.window_buy.value,
            mult=self.mult_buy.value,
        )

        myAtr = atr(dataframe, self.atr_length.value)
        dataframe["atr_long"] = (
            dataframe["nwe_center"] + myAtr * self.atr_long_exit_multiplier.value
        )
        dataframe["atr_short"] = (
            dataframe["nwe_center"] - myAtr * self.atr_short_exit_multiplier.value
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        con1 = (
            qtpylib.crossed_below(dataframe["close"], dataframe["nwe_up"]) & dataframe["volume"] > 0
        )
        con1_short = (
            qtpylib.crossed_above(dataframe["close"], dataframe["nwe_down"]) & dataframe["volume"]
            > 0
        )

        conditions.append(con1)
        conditions.append(con1_short)

        dataframe.loc[con1, "enter_short"] = 1
        dataframe.loc[con1_short, "enter_long"] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_conditions = []
        short_conditions = []

        con1_long = qtpylib.crossed_above(dataframe["close"], dataframe["nwe_center"])
        con2_long = qtpylib.crossed_above(dataframe["close"], dataframe["atr_long"])

        con1_short = qtpylib.crossed_below(dataframe["close"], dataframe["nwe_center"])
        con2_short = qtpylib.crossed_below(dataframe["close"], dataframe["atr_short"])

        long_conditions.append(con1_long)
        long_conditions.append(con2_long)

        short_conditions.append(con1_short)
        short_conditions.append(con2_short)

        dataframe.loc[reduce(lambda x, y: x & y, long_conditions), "exit_long"] = 1
        dataframe.loc[reduce(lambda x, y: x & y, short_conditions), "exit_short"] = 1

        return dataframe
