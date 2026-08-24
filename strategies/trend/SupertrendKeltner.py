# Import the required libraries and modules
import datetime
import numpy as np
from freqtrade.strategy import IStrategy, merge_informative_pair
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter
from freqtrade.persistence import Trade
from typing import Union
from pandas import DataFrame, Series

import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib


def supertrend(dataframe: DataFrame, period, multiplier):
    df = dataframe.copy()
    df["TR"] = ta.TRANGE(df)
    df["ATR"] = ta.SMA(df["TR"], period)
    st = "ST"
    stx = "STX"

    # Compute basic upper and lower bands
    df["basic_ub"] = (df["high"] + df["low"]) / 2 + multiplier * df["ATR"]
    df["basic_lb"] = (df["high"] + df["low"]) / 2 - multiplier * df["ATR"]

    # Compute final upper and lower bands
    df["final_ub"] = 0.00
    df["final_lb"] = 0.00
    for i in range(period, len(df)):
        df["final_ub"].iat[i] = (
            df["basic_ub"].iat[i]
            if df["basic_ub"].iat[i] < df["final_ub"].iat[i - 1]
            or df["close"].iat[i - 1] > df["final_ub"].iat[i - 1]
            else df["final_ub"].iat[i - 1]
        )
        df["final_lb"].iat[i] = (
            df["basic_lb"].iat[i]
            if df["basic_lb"].iat[i] > df["final_lb"].iat[i - 1]
            or df["close"].iat[i - 1] < df["final_lb"].iat[i - 1]
            else df["final_lb"].iat[i - 1]
        )

    # Set the Supertrend value
    df[st] = 0.00
    for i in range(period, len(df)):
        df[st].iat[i] = (
            df["final_ub"].iat[i]
            if df[st].iat[i - 1] == df["final_ub"].iat[i - 1]
            and df["close"].iat[i] <= df["final_ub"].iat[i]
            else df["final_lb"].iat[i]
            if df[st].iat[i - 1] == df["final_ub"].iat[i - 1]
            and df["close"].iat[i] > df["final_ub"].iat[i]
            else df["final_lb"].iat[i]
            if df[st].iat[i - 1] == df["final_lb"].iat[i - 1]
            and df["close"].iat[i] >= df["final_lb"].iat[i]
            else df["final_ub"].iat[i]
            if df[st].iat[i - 1] == df["final_lb"].iat[i - 1]
            and df["close"].iat[i] < df["final_lb"].iat[i]
            else 0.00
        )

    # Mark the trend direction up/down
    df[stx] = np.where((df[st] > 0.00), np.where((df["close"] < df[st]), -1, 1), np.NaN)

    # Remove basic and final bands from the columns
    df.drop(["basic_ub", "basic_lb", "final_ub", "final_lb"], inplace=True, axis=1)
    df.fillna(0, inplace=True)

    return df


class SupertrendKeltner(IStrategy):
    # Set strategy parameters
    stoploss = -0.05
    process_only_new_candles = False

    # Set the hyperparameters
    supertrend_period = IntParameter(10, 20, default=10, load=True, space="buy")
    supertrend_multiplier = DecimalParameter(1.5, 3.0, default=2.0, load=True, space="buy")
    keltner_period = IntParameter(20, 40, default=20, load=True, space="buy")
    keltner_multiplier = DecimalParameter(1.5, 3.0, default=2.0, load=True, space="buy")
    trailing_sl = DecimalParameter(0.01, 0.05, default=0.03, load=True, space="sell")
    trailing_tp = DecimalParameter(0.01, 0.05, default=0.03, load=True, space="sell")

    # Define the informative pairs to be used
    informative_pairs = []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Calculate Supertrend values
        supertrend_data = supertrend(
            dataframe, self.supertrend_period.value, self.supertrend_multiplier.value
        )
        dataframe["supertrend_direction"] = supertrend_data["STX"]
        dataframe["supertrend"] = supertrend_data["ST"]

        # Calculate Keltner Channel values
        keltner_channel_data = qtpylib.keltner_channel(
            dataframe, self.keltner_period.value, self.keltner_multiplier.value
        )
        dataframe["kc_upperband"] = keltner_channel_data["upper"]
        dataframe["kc_lowerband"] = keltner_channel_data["lower"]
        dataframe["kc_middleband"] = keltner_channel_data["mid"]
        return dataframe

    # Custom stoploss
    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1].squeeze()

        if trade.trade_direction == "long":
            self.stop_loss_price = last_candle["kc_lowerband"]
        elif trade.trade_direction == "short":
            self.stop_loss_price = last_candle["kc_upperband"]

        return 1

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["supertrend_direction"], 0.99)
            ),  # Supertrend is in uptrend
            "buy",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_below(dataframe["supertrend_direction"], -0.99)
            ),  # Supertrend is in downtrend
            "sell",
        ] = 1
        return dataframe
