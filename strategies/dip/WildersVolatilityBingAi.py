from datetime import datetime
from pandas import DataFrame
from freqtrade.strategy import (
    IStrategy,
    CategoricalParameter,
    IntParameter,
    BooleanParameter,
)
import talib.abstract as ta
import numpy as np
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.strategy import merge_informative_pair


class WildersVolatilityBingAi(IStrategy):
    INTERFACE_VERSION = 3

    # Optimal timeframe for the strategy
    timeframe = "5m"

    # Minimal ROI designed for the strategy.
    minimal_roi = {"0": 0.01, "10": 0.005, "20": 0.0025, "30": 0.0010, "40": 0}

    # This attribute will be overridden if the config file contains "stoploss".
    stoploss = -0.02

    # Trailing stoploss
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    # Optimal stoploss designed for the strategy
    stoploss = -0.02

    # Run "populate_indicators()" only for new candle.
    process_only_new_candles = False

    # Number of days to keep in dataframe before using it (default: 1).
    startup_candle_count: int = 30

    # Optional order type mapping.
    order_types = {
        "entry": "limit",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # Optional order time in force.
    order_time_in_force = {
        "entry": "gtc",
        "exit": "gtc",
    }

    # Define the maximum risk per trade (e.g., 2% of the account balance)
    max_risk_per_trade = 0.02

    # Define the hyperoptable parameters
    ma_type = CategoricalParameter(
        ["sma", "ema", "smm", "t3", "jma"], default="sma", space="buy"
    )
    fast_period = IntParameter(5, 50, default=12, space="buy")
    slow_period = IntParameter(30, 200, default=26, space="buy")
    highLowStopLossLookback = IntParameter(
        5, 100, default=14, space="buy", optimize=True, load=True
    )
    highLowTakeProfitLookback = IntParameter(
        5, 100, default=14, space="buy", optimize=True, load=True
    )
    enable_fir_filter = BooleanParameter(default=False, space="buy", optimize=True)
    is_aroon_sidetrend_filter_enabled = BooleanParameter(
        default=False, space="buy", optimize=True
    )
    is_aroon_sidetrend_mode_trending = BooleanParameter(
        default=False, space="buy", optimize=True
    )
    aroon_length = IntParameter(
        5, 50, default=14, space="buy", optimize=True, load=True
    )

    higher_timeframe = CategoricalParameter(
        ["5m", "15m", "30m", "1h", "4h"], default="15m", space="buy"
    )

    def T3(self, data, period=5, vfactor=0.7):
        EMA1 = data.ewm(span=period).mean()
        EMA2 = EMA1.ewm(span=period).mean()
        EMA3 = EMA2.ewm(span=period).mean()
        EMA4 = EMA3.ewm(span=period).mean()
        EMA5 = EMA4.ewm(span=period).mean()
        EMA6 = EMA5.ewm(span=period).mean()
        c1 = -vfactor * vfactor * vfactor
        c2 = 3 * vfactor * vfactor + 3 * vfactor * vfactor * vfactor
        c3 = -6 * vfactor * vfactor - 3 * vfactor - 3 * vfactor * vfactor * vfactor
        c4 = 1 + 3 * vfactor + vfactor * vfactor * vfactor + 3 * vfactor * vfactor
        T3 = c1 * EMA6 + c2 * EMA5 + c3 * EMA4 + c4 * EMA3
        return T3

    def JMA(self, data, period=10):
        diff = np.abs(data.diff())
        vola = diff.rolling(window=period).mean()
        ma = data.rolling(window=period).mean()
        JMA = ma + vola
        return JMA

    def informative_pairs(self):
        # Use the string value directly to define informative pairs
        higher_timeframe_str = self.higher_timeframe.value
        return [(pair, higher_timeframe_str) for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        informative = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.higher_timeframe.value
        ).copy()
        # Calculate the ATR on the higher timeframe data
        informative["atr"] = ta.ATR(informative, timeperiod=14)
        aroon = ta.AROON(informative, timeperiod=self.aroon_length.value)
        informative["aroon_upper"] = aroon["aroonup"]
        informative["aroon_lower"] = aroon["aroondown"]
        dataframe = merge_informative_pair(
            dataframe,
            informative[["date", "atr", "aroon_upper", "aroon_lower"]],
            self.timeframe,
            self.higher_timeframe.value,
            ffill=True,
        )
        timeframe_suffix = f"_{self.higher_timeframe.value}"
        dataframe["atr"] = dataframe[f"atr{timeframe_suffix}"]
        dataframe["aroon_upper"] = dataframe[f"aroon_upper{timeframe_suffix}"]
        dataframe["aroon_lower"] = dataframe[f"aroon_lower{timeframe_suffix}"]
        # Calculate the selected moving average type for the fast MA
        if self.ma_type.value == "sma":
            dataframe["fast_ma"] = (
                dataframe["close"].rolling(window=self.fast_period.value).mean()
            )
        elif self.ma_type.value == "ema":
            dataframe["fast_ma"] = (
                dataframe["close"].ewm(span=self.fast_period.value).mean()
            )
        elif self.ma_type.value == "smm":
            dataframe["fast_ma"] = (
                dataframe["close"].rolling(window=self.fast_period.value).mean()
            )
        elif self.ma_type.value == "t3":
            dataframe["fast_ma"] = self.T3(
                dataframe["close"], period=self.fast_period.value
            )
        elif self.ma_type.value == "jma":
            dataframe["fast_ma"] = self.JMA(
                dataframe["close"], period=self.fast_period.value
            )
        # Calculate the selected moving average type for the slow MA
        if self.ma_type.value == "sma":
            dataframe["slow_ma"] = (
                dataframe["close"].rolling(window=self.slow_period.value).mean()
            )
        elif self.ma_type.value == "ema":
            dataframe["slow_ma"] = (
                dataframe["close"].ewm(span=self.slow_period.value).mean()
            )
        elif self.ma_type.value == "smm":
            dataframe["slow_ma"] = (
                dataframe["close"].rolling(window=self.slow_period.value).mean()
            )
        elif self.ma_type.value == "t3":
            dataframe["slow_ma"] = self.T3(
                dataframe["close"], period=self.slow_period.value
            )
        elif self.ma_type.value == "jma":
            dataframe["slow_ma"] = self.JMA(
                dataframe["close"], period=self.slow_period.value
            )
        # Calculate levels from completed candles, excluding the current candle.
        dataframe["highLowStopLossLowest"] = (
            dataframe["low"].rolling(self.highLowStopLossLookback.value).min().shift(1)
        )
        dataframe["highLowStopLossHighest"] = (
            dataframe["high"].rolling(self.highLowStopLossLookback.value).max().shift(1)
        )
        dataframe["highLowTakeProfitLowest"] = (
            dataframe["low"].rolling(self.highLowTakeProfitLookback.value).min().shift(1)
        )
        dataframe["highLowTakeProfitHighest"] = (
            dataframe["high"].rolling(self.highLowTakeProfitLookback.value).max().shift(1)
        )
        # Calculate the MA convergence
        dataframe["maFast_m5"] = dataframe["fast_ma"].shift(5)
        dataframe["ma1BelowMa2"] = dataframe["fast_ma"] < dataframe["slow_ma"]
        dataframe["ma1AboveMa2"] = dataframe["fast_ma"] > dataframe["slow_ma"]
        dataframe["isOut1ConvergingFromDown"] = (
            dataframe["fast_ma"] > dataframe["maFast_m5"]
        ) & dataframe["ma1BelowMa2"]
        dataframe["isOut1ConvergingFromUp"] = (
            dataframe["fast_ma"] < dataframe["maFast_m5"]
        ) & dataframe["ma1AboveMa2"]
        # Aroon sidetrend filter
        dataframe["aroon_upper_k"] = (
            dataframe["aroon_upper"].ffill().pct_change(fill_method=None)
        )
        dataframe["aroon_lower_k"] = (
            dataframe["aroon_lower"].ffill().pct_change(fill_method=None)
        )
        dataframe["is_sidetrend_by_aroon"] = np.where(
            dataframe["aroon_upper_k"] == dataframe["aroon_lower_k"], 1, 0
        )
        if not self.is_aroon_sidetrend_filter_enabled.value:
            dataframe["is_trade_allowed_by_aroon_sidetrend"] = 1
        elif self.is_aroon_sidetrend_mode_trending.value:
            dataframe["is_trade_allowed_by_aroon_sidetrend"] = (
                ~dataframe["is_sidetrend_by_aroon"].astype(bool)
            ).astype(int)
        else:
            dataframe["is_trade_allowed_by_aroon_sidetrend"] = dataframe[
                "is_sidetrend_by_aroon"
            ]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["fast_ma"] > dataframe["slow_ma"])
            & (dataframe["close"] > dataframe["highLowStopLossHighest"])
            & ~dataframe["isOut1ConvergingFromDown"]
            & ~dataframe["isOut1ConvergingFromUp"]
            & self.enable_fir_filter.value
            & dataframe["is_trade_allowed_by_aroon_sidetrend"],
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["fast_ma"] < dataframe["slow_ma"])
            & (dataframe["close"] < dataframe["highLowStopLossLowest"])
            & ~dataframe["isOut1ConvergingFromDown"]
            & ~dataframe["isOut1ConvergingFromUp"]
            & self.enable_fir_filter.value
            & dataframe["is_trade_allowed_by_aroon_sidetrend"],
            "exit_long",
        ] = 1
        return dataframe
