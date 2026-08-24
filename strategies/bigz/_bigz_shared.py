"""Shared base for the BigZ06 family of dip-buying strategies.

The four BigZ strategies (``BigZ06AtrSl``, ``BigZ06Original``, ``BigZ07Next2``,
``BigZ08``) share an identical 14-condition entry block and the 5m/1h talib
indicator setup. This module holds that shared logic exactly once; each
strategy subclass only defines its own exits, risk management, ROI/stoploss and
unique hyperopt parameters.

Source: BigZ06 by ilya (https://github.com/i1ya/freqtrade-strategies), most
inspired by iterativ (authors of the CombinedBinHAndClucV6). Entry logic is
byte-for-byte identical across the family, differing only in the signal column
name (interface v2 ``buy``/``sell`` vs interface v3 ``enter_long``/``exit_long``).
"""

import logging
from datetime import datetime
from functools import reduce
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import CategoricalParameter, DecimalParameter, merge_informative_pair
from freqtrade.strategy.interface import IStrategy


logger = logging.getLogger(__name__)


class BigZSharedBase(IStrategy):
    """Shared entry logic, indicator setup and buy hyperopt params for the BigZ06 family."""

    # The whole family targets the 5m / 1h timeframe pair.
    timeframe = "5m"
    inf_1h = "1h"

    startup_candle_count: int = 200
    process_only_new_candles = True

    # Exit / risk defaults shared by the family.
    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = (
        0.001  # it doesn't meant anything, just to guarantee there is a minimal profit.
    )
    ignore_roi_if_entry_signal = False
    use_custom_stoploss = True

    # Interface v3 signal columns by default; interface v2 subclasses override.
    entry_signal_col = "enter_long"
    exit_signal_col = "exit_long"
    # Value written to the exit signal column (v2 "sell" quirk writes 0).
    exit_signal_value = 1

    # Buy hyperspace params: all 14 conditions enabled by default.
    buy_params = {
        "buy_condition_0_enable": True,
        "buy_condition_1_enable": True,
        "buy_condition_2_enable": True,
        "buy_condition_3_enable": True,
        "buy_condition_4_enable": True,
        "buy_condition_5_enable": True,
        "buy_condition_6_enable": True,
        "buy_condition_7_enable": True,
        "buy_condition_8_enable": True,
        "buy_condition_9_enable": True,
        "buy_condition_10_enable": True,
        "buy_condition_11_enable": True,
        "buy_condition_12_enable": True,
        "buy_condition_13_enable": True,
    }

    buy_condition_0_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_1_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_2_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_3_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_4_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_5_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_6_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_7_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_8_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_9_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_10_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_11_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_12_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )
    buy_condition_13_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=True
    )

    buy_bb20_close_bblowerband_safe_1 = DecimalParameter(
        0.7, 1.1, default=0.989, space="buy", optimize=True
    )
    buy_bb20_close_bblowerband_safe_2 = DecimalParameter(
        0.7, 1.1, default=0.982, space="buy", optimize=True
    )

    buy_volume_pump_1 = DecimalParameter(
        0.1, 0.9, default=0.4, space="buy", decimals=1, optimize=True
    )
    buy_volume_drop_1 = DecimalParameter(1, 10, default=3.8, space="buy", decimals=1, optimize=True)
    buy_volume_drop_2 = DecimalParameter(1, 10, default=3, space="buy", decimals=1, optimize=True)
    buy_volume_drop_3 = DecimalParameter(1, 10, default=2.7, space="buy", decimals=1, optimize=True)

    buy_rsi_1h_1 = DecimalParameter(
        10.0, 40.0, default=16.5, space="buy", decimals=1, optimize=True
    )
    buy_rsi_1h_2 = DecimalParameter(
        10.0, 40.0, default=15.0, space="buy", decimals=1, optimize=True
    )
    buy_rsi_1h_3 = DecimalParameter(
        10.0, 40.0, default=20.0, space="buy", decimals=1, optimize=True
    )
    buy_rsi_1h_4 = DecimalParameter(
        10.0, 40.0, default=35.0, space="buy", decimals=1, optimize=True
    )
    buy_rsi_1h_5 = DecimalParameter(
        10.0, 60.0, default=39.0, space="buy", decimals=1, optimize=True
    )

    buy_rsi_1 = DecimalParameter(10.0, 40.0, default=28.0, space="buy", decimals=1, optimize=True)
    buy_rsi_2 = DecimalParameter(7.0, 40.0, default=10.0, space="buy", decimals=1, optimize=True)
    buy_rsi_3 = DecimalParameter(7.0, 40.0, default=14.2, space="buy", decimals=1, optimize=True)

    buy_macd_1 = DecimalParameter(0.01, 0.09, default=0.02, space="buy", decimals=2, optimize=True)
    buy_macd_2 = DecimalParameter(0.01, 0.09, default=0.03, space="buy", decimals=2, optimize=True)

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, "1h") for pair in pairs]
        return informative_pairs

    def informative_1h_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for multiple timeframes."
        # Get the informative pair
        informative_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=self.inf_1h)
        # EMA
        informative_1h["ema_50"] = ta.EMA(informative_1h, timeperiod=50)
        informative_1h["ema_200"] = ta.EMA(informative_1h, timeperiod=200)
        # RSI
        informative_1h["rsi"] = ta.RSI(informative_1h, timeperiod=14)

        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(informative_1h), window=20, stds=2
        )
        informative_1h["bb_lowerband"] = bollinger["lower"]
        informative_1h["bb_middleband"] = bollinger["mid"]
        informative_1h["bb_upperband"] = bollinger["upper"]

        return informative_1h

    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]

        dataframe["volume_mean_slow"] = dataframe["volume"].rolling(window=48).mean()

        # EMA
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)

        # MACD
        dataframe["macd"], dataframe["signal"], dataframe["hist"] = ta.MACD(
            dataframe["close"], fastperiod=12, slowperiod=26, signalperiod=9
        )

        # SMA
        dataframe["sma_5"] = ta.EMA(dataframe, timeperiod=5)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # Chaikin A/D Oscillator
        dataframe["mfv"] = MFV(dataframe)
        dataframe["cmf"] = (
            dataframe["mfv"].rolling(20).sum() / dataframe["volume"].rolling(20).sum()
        )

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # The indicators for the 1h informative timeframe
        informative_1h = self.informative_1h_indicators(dataframe, metadata)
        dataframe = merge_informative_pair(
            dataframe, informative_1h, self.timeframe, self.inf_1h, ffill=True
        )

        # The indicators for the normal (5m) timeframe
        dataframe = self.normal_tf_indicators(dataframe, metadata)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        conditions.append(
            self.buy_condition_13_enable.value
            & (dataframe["close"] > dataframe["ema_200_1h"])
            & (dataframe["cmf"] < -0.435)
            & (dataframe["rsi"] < 22)
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_12_enable.value
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["close"] > dataframe["ema_200_1h"])
            & (dataframe["close"] < dataframe["bb_lowerband"] * 0.993)
            & (dataframe["low"] < dataframe["bb_lowerband"] * 0.985)
            & (dataframe["close"].shift() > dataframe["bb_lowerband"])
            & (dataframe["rsi_1h"] < 72.8)
            & (dataframe["open"] > dataframe["close"])
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (
                (dataframe["open"] - dataframe["close"])
                < dataframe["bb_upperband"].shift(2) - dataframe["bb_lowerband"].shift(2)
            )
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_11_enable.value
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["hist"] > 0)
            & (dataframe["hist"].shift() > 0)
            & (dataframe["hist"].shift(2) > 0)
            & (dataframe["hist"].shift(3) > 0)
            & (dataframe["hist"].shift(5) > 0)
            & (
                dataframe["bb_middleband"] - dataframe["bb_middleband"].shift(5)
                > dataframe["close"] / 200
            )
            & (
                dataframe["bb_middleband"] - dataframe["bb_middleband"].shift(10)
                > dataframe["close"] / 100
            )
            & ((dataframe["bb_upperband"] - dataframe["bb_lowerband"]) < (dataframe["close"] * 0.1))
            & (
                (dataframe["open"].shift() - dataframe["close"].shift())
                < (dataframe["close"] * 0.018)
            )
            & (dataframe["rsi"] > 51)
            & (dataframe["open"] < dataframe["close"])
            & (dataframe["open"].shift() > dataframe["close"].shift())
            & (dataframe["close"] > dataframe["bb_middleband"])
            & (dataframe["close"].shift() < dataframe["bb_middleband"].shift())
            & (dataframe["low"].shift(2) > dataframe["bb_middleband"].shift(2))
            & (dataframe["volume"] > 0)  # Make sure Volume is not 0
        )

        conditions.append(
            self.buy_condition_0_enable.value
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["rsi"] < 30)
            & (dataframe["close"] * 1.024 < dataframe["open"].shift(3))
            & (dataframe["rsi_1h"] < 71)
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] > 0)  # Make sure Volume is not 0
        )

        conditions.append(
            self.buy_condition_1_enable.value
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["close"] > dataframe["ema_200_1h"])
            & (
                dataframe["close"]
                < dataframe["bb_lowerband"] * self.buy_bb20_close_bblowerband_safe_1.value
            )
            & (dataframe["rsi_1h"] < 69)
            & (dataframe["open"] > dataframe["close"])
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (
                (dataframe["open"] - dataframe["close"])
                < dataframe["bb_upperband"].shift(2) - dataframe["bb_lowerband"].shift(2)
            )
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_2_enable.value
            & (dataframe["close"] > dataframe["ema_200"])
            & (
                dataframe["close"]
                < dataframe["bb_lowerband"] * self.buy_bb20_close_bblowerband_safe_2.value
            )
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (
                dataframe["open"] - dataframe["close"]
                < dataframe["bb_upperband"].shift(2) - dataframe["bb_lowerband"].shift(2)
            )
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_3_enable.value
            & (dataframe["close"] > dataframe["ema_200_1h"])
            & (dataframe["close"] < dataframe["bb_lowerband"])
            & (dataframe["rsi"] < self.buy_rsi_3.value)
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_3.value))
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_4_enable.value
            & (dataframe["rsi_1h"] < self.buy_rsi_1h_1.value)
            & (dataframe["close"] < dataframe["bb_lowerband"])
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_5_enable.value
            & (dataframe["close"] > dataframe["ema_200"])
            & (dataframe["close"] > dataframe["ema_200_1h"])
            & (dataframe["ema_26"] > dataframe["ema_12"])
            & (
                (dataframe["ema_26"] - dataframe["ema_12"])
                > (dataframe["open"] * self.buy_macd_1.value)
            )
            & (
                (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                > (dataframe["open"] / 100)
            )
            & (dataframe["close"] < (dataframe["bb_lowerband"]))
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] > 0)  # Make sure Volume is not 0
        )

        conditions.append(
            self.buy_condition_6_enable.value
            & (dataframe["rsi_1h"] < self.buy_rsi_1h_5.value)
            & (dataframe["ema_26"] > dataframe["ema_12"])
            & (
                (dataframe["ema_26"] - dataframe["ema_12"])
                > (dataframe["open"] * self.buy_macd_2.value)
            )
            & (
                (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                > (dataframe["open"] / 100)
            )
            & (dataframe["close"] < (dataframe["bb_lowerband"]))
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_7_enable.value
            & (dataframe["rsi_1h"] < self.buy_rsi_1h_2.value)
            & (dataframe["ema_26"] > dataframe["ema_12"])
            & (
                (dataframe["ema_26"] - dataframe["ema_12"])
                > (dataframe["open"] * self.buy_macd_1.value)
            )
            & (
                (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                > (dataframe["open"] / 100)
            )
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_8_enable.value
            & (dataframe["rsi_1h"] < self.buy_rsi_1h_3.value)
            & (dataframe["rsi"] < self.buy_rsi_1.value)
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_9_enable.value
            & (dataframe["rsi_1h"] < self.buy_rsi_1h_4.value)
            & (dataframe["rsi"] < self.buy_rsi_2.value)
            & (dataframe["volume"] < (dataframe["volume"].shift() * self.buy_volume_drop_1.value))
            & (
                dataframe["volume_mean_slow"]
                > dataframe["volume_mean_slow"].shift(48) * self.buy_volume_pump_1.value
            )
            & (
                dataframe["volume_mean_slow"] * self.buy_volume_pump_1.value
                < dataframe["volume_mean_slow"].shift(48)
            )
            & (dataframe["volume"] > 0)
        )

        conditions.append(
            self.buy_condition_10_enable.value
            & (dataframe["rsi_1h"] < self.buy_rsi_1h_4.value)
            & (dataframe["close_1h"] < dataframe["bb_lowerband_1h"])
            & (dataframe["hist"] > 0)
            & (dataframe["hist"].shift(2) < 0)
            & (dataframe["rsi"] < 40.5)
            & (dataframe["hist"] > dataframe["close"] * 0.0012)
            & (dataframe["open"] < dataframe["close"])
            & (dataframe["volume"] > 0)
        )

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), self.entry_signal_col] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["close"] > dataframe["bb_middleband"] * 1.01)
                & (  # Don't be gready, sell fast
                    dataframe["volume"] > 0
                )  # Make sure Volume is not 0
            ),
            self.exit_signal_col,
        ] = self.exit_signal_value
        return dataframe

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

        return 5.0


# Chaikin Money Flow Volume
def MFV(dataframe):
    df = dataframe.copy()
    N = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"])
    M = N * df["volume"]
    return M
