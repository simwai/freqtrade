import pandas_ta as pta
from pandas import DataFrame


class IndicatorCalculator:
    def __init__(self, dataframe: DataFrame):
        self.dataframe = dataframe

    def calculate_chaikin_volatility(self, window: int = 10) -> None:
        high_low_diff = self.dataframe["high"] - self.dataframe["low"]
        ema_high_low_diff = pta.EMA(high_low_diff, timeperiod=window)
        chaikin_vol = (
            (ema_high_low_diff - ema_high_low_diff.shift(window)) / ema_high_low_diff.shift(window)
        ) * 100
        self.dataframe["chaikin_volatility"] = chaikin_vol

    def calculate_vix_fix(self, window: int = 22, factor: float = 2.0) -> None:
        high_max = self.dataframe["high"].rolling(window=window).max()
        low_min = self.dataframe["low"].rolling(window=window).min()
        vix_fix = (high_max - self.dataframe["close"]) / (high_max - low_min) * 100
        self.dataframe["vix_fix"] = vix_fix

    def calculate_bollinger_bands(self, window: int = 20, stds: int = 2) -> None:
        vix_bollinger = pta.bbands(self.dataframe["vix_fix"], window=window, stds=stds)
        self.dataframe["vix_bb_lowerband"] = vix_bollinger["lower"]
        self.dataframe["vix_bb_middleband"] = vix_bollinger["mid"]
        self.dataframe["vix_bb_upperband"] = vix_bollinger["upper"]

    def calculate_dema(self, timeperiod: int = 9) -> None:
        self.dataframe["vix_dema"] = pta.DEMA(self.dataframe["vix_fix"], timeperiod=timeperiod)
