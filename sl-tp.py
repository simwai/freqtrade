import logging

import numpy as np
from colorama import Fore, Style, init
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy


# Initialize Colorama for colored logging
init(autoreset=True)


class ColorLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def info(self, message):
        self.logger.info(Fore.GREEN + message + Style.RESET_ALL)

    def warning(self, message):
        self.logger.warning(Fore.YELLOW + message + Style.RESET_ALL)

    def error(self, message):
        self.logger.error(Fore.RED + message + Style.RESET_ALL)

    def debug(self, message):
        self.logger.debug(Fore.BLUE + message + Style.RESET_ALL)


class ATRStrategy:
    def __init__(self, strategy: IStrategy, atr_length: int, atr_multiplier: float):
        self.strategy = strategy
        self.atr_length = atr_length
        self.atr_multiplier = atr_multiplier
        self.logger = ColorLogger("ATRStrategy")

    def _calculate_atr(self, dataframe: DataFrame) -> DataFrame:
        high_low = dataframe["high"] - dataframe["low"]
        high_close = np.abs(dataframe["high"] - dataframe["close"].shift())
        low_close = np.abs(dataframe["low"] - dataframe["close"].shift())
        tr = DataFrame({"tr1": high_low, "tr2": high_close, "tr3": low_close}).max(axis=1)
        atr = tr.rolling(window=self.atr_length, min_periods=1).mean()
        return atr

    def calculate_stop_loss(self, dataframe: DataFrame, trade: Trade, current_rate: float) -> float:
        atr = self._calculate_atr(dataframe)
        entry_low_key = f"trade_{trade.id}_entry_low"
        entry_low = trade.get_custom_data(entry_low_key) or current_rate

        atr_stop_loss = entry_low - atr.iloc[-1] * self.atr_multiplier
        stop_loss_percentage = ((current_rate / atr_stop_loss) - 1) * 100

        self.logger.info(
            f"Calculated ATR-based stop loss at {atr_stop_loss}, which is {stop_loss_percentage}% below entry low."
        )
        return -stop_loss_percentage

    def calculate_take_profit(
        self, dataframe: DataFrame, trade: Trade, current_rate: float
    ) -> float:
        atr = self._calculate_atr(dataframe)
        entry_high_key = f"trade_{trade.id}_entry_high"
        entry_high = trade.get_custom_data(entry_high_key) or current_rate

        atr_take_profit = entry_high + atr.iloc[-1] * self.atr_multiplier
        take_profit_percentage = ((atr_take_profit / current_rate) - 1) * 100

        self.logger.info(
            f"Calculated ATR-based take profit at {atr_take_profit}, which is {take_profit_percentage}% above entry high."
        )
        return take_profit_percentage


class HighLowStrategy:
    def __init__(self, strategy: IStrategy, lookback_period: int):
        self.strategy = strategy
        self.lookback_period = lookback_period
        self.logger = ColorLogger("HighLowStrategy")

    def calculate_high_low_stop_loss(self, dataframe: DataFrame, is_short: bool) -> float:
        if is_short:
            high = dataframe["high"].rolling(window=self.lookback_period).max().iloc[-1]
            return high
        else:
            low = dataframe["low"].rolling(window=self.lookback_period).min().iloc[-1]
            return low

    def calculate_high_low_take_profit(self, dataframe: DataFrame, is_short: bool) -> float:
        if is_short:
            low = dataframe["low"].rolling(window=self.lookback_period).min().iloc[-1]
            return low
        else:
            high = dataframe["high"].rolling(window=self.lookback_period).max().iloc[-1]
            return high


# Example usage within a freqtrade strategy would also instantiate and use these classes.
