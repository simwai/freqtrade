# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401

# --- Do not remove these libs ---
import numpy as np  # noqa
import pandas as pd

from freqtrade.strategy.strategy_helper import merge_informative_pair  # noqa

pd.options.mode.chained_assignment = None  # default='warn'
from pandas import DataFrame

from freqtrade.strategy import IStrategy
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter

from user_data.strategies.components.risk import RiskMixin, TrailingATRStopManager

# --------------------------------
# Add your lib to import here
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib


def WaveTrend(dataframe, chlen=10, avg=21, smalen=4):
    """
    Computes WaveTrend Oscillator by LazyBear
    https://www.tradingview.com/script/2KE8wTuF-Indicator-WaveTrend-Oscillator-WT/

    Args:
        dataframe (pd.DataFrame): The input OHLCV DataFrame.
        chlen (int): The length of the channel.
        avg (int): The average length.
        smalen (int): The small moving average length.

    Returns:
        pd.DataFrame: The output DataFrame with 'wt1', 'wt2' and 'wt1-wt2' columns added.
    """
    df = dataframe.copy()

    # Compute necessary intermediate values
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = ta.EMA(hlc3, timeperiod=chlen)
    d = ta.EMA((hlc3 - esa).abs(), timeperiod=chlen)
    ci = (hlc3 - esa) / (0.015 * d)
    tci = ta.EMA(ci, timeperiod=avg)

    # Compute final values
    wt1 = tci
    wt2 = ta.SMA(wt1, timeperiod=smalen)
    wt_diff = wt1 - wt2

    # Add new columns to the DataFrame
    df["wt1"] = wt1
    df["wt2"] = wt2
    df["wt1-wt2"] = wt_diff

    return df


class MfiEmaWaveTrend2(RiskMixin, IStrategy):
    """
    A scalping strategy that uses MFI as a filter, EMA as a filter, and WaveTrend as a signal emitter.
    """

    # Define your hyperparameters
    # buy_mfi_threshold = IntParameter(1, 49, default=20, space="buy", optimize=True)
    # sell_mfi_threshold = IntParameter(50, 99, default=80, space="sell", optimize=True)
    buy_wt_threshold = IntParameter(-50, 65, default=53, space="buy", optimize=False)
    sell_wt_threshold = IntParameter(-65, -50, default=-53, space="sell", optimize=False)

    # mfi_length = IntParameter(2, 50, default=14, space="buy", optimize=True)

    wt_length = IntParameter(2, 200, default=21, space="buy", optimize=True)
    wt_sma_length = IntParameter(2, 200, default=4, space="buy", optimize=True)
    wt_channel_length = IntParameter(2, 200, default=10, space="buy", optimize=True)

    atr_long_multiplier = DecimalParameter(
        0.1, 12.0, default=3.0, decimals=1, space="sell", optimize=True
    )
    atr_short_multiplier = DecimalParameter(
        0.1, 12.0, default=3.0, decimals=1, space="sell", optimize=True
    )

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
    # trailing_stop_positive = 0.005
    # trailing_stop_positive_offset = 0.019
    # trailing_only_offset_is_reached = True
    process_only_new_candles = False

    # Optional order type mapping.
    order_types = {
        "entry": "limit",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # Optional order time in force.
    order_time_in_force = {"entry": "gtc", "exit": "gtc"}

    # Plot the indicators in the strategy
    plot_config = {
        "main_plot": {},
        "subplots": {
            "wt1": {"color": "purple"},
            "wt2": {"color": "cyan"},
        },
    }

    # Custom stoploss
    @property
    def stop_managers(self):
        """Trailing ATR stop (components equivalent of the strategy_lib
        "Trailing ATR" engine): ratchets ``close - atr * multiplier`` (long) /
        ``close + atr * multiplier`` (short) from the entry rate, keeping the
        separate long/short multipliers. Uses the Pine Hann-window ATR.
        """
        return [
            TrailingATRStopManager(
                atr_length=14,
                mult_long=float(self.atr_long_multiplier.value),
                mult_short=float(self.atr_short_multiplier.value),
            )
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Calculate MFI
        # dataframe["mfi"] = ta.MFI(dataframe, timeperiod=self.mfi_length.value)

        # Calculate EMA filters
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["ema"] = dataframe["ema200"]

        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)

        # Calculate ATR long SL
        dataframe["atr_long"] = ta.ATR(dataframe, timeperiod=14) * self.atr_long_multiplier.value

        # Calculate ATR short SL
        dataframe["atr_short"] = ta.ATR(dataframe, timeperiod=14) * self.atr_short_multiplier.value

        # Calculate WaveTrend oscillator
        dataframe = WaveTrend(
            dataframe, self.wt_channel_length.value, self.wt_length.value, self.wt_sma_length.value
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = (
            # (qtpylib.crossed_above(dataframe["mfi"], self.buy_mfi_threshold.value))
            (dataframe["close"] > dataframe["ema"])
            & (qtpylib.crossed_above(dataframe["wt1"], dataframe["wt2"]))
            & (dataframe["wt1"] < self.buy_wt_threshold.value)
            & (dataframe["volume"] > 0)
        )

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = (
            # (qtpylib.crossed_below(dataframe["mfi"], self.sell_mfi_threshold.value))
            (dataframe["close"] < dataframe["ema"])
            & (qtpylib.crossed_below(dataframe["wt1"], dataframe["wt2"]))
            & (dataframe["wt1"] > self.sell_wt_threshold.value)
            & (dataframe["volume"] > 0)
        )

        return dataframe
