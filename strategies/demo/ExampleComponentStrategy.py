"""Example strategy built entirely from components.

Reuses:
    indicators.wavetrend / mfi / atr / volume_mean
    signals.crossed_above / volume_pump_drop_filter
    risk.RiskMixin + ATRStopManager + TimeCutStopManager + DurationExitManager
        + RiskBasedSizer + FixedLeverage

Drop this file into user_data/strategies and run with:
    freqtrade backtesting --strategy ExampleComponentStrategy --config <your-config>
"""

from pandas import DataFrame

from user_data.strategies.components.indicators import atr, mfi, volume_mean, wavetrend
from user_data.strategies.components.risk import (
    ATRStopManager,
    DurationExitManager,
    FixedLeverage,
    RiskBasedSizer,
    RiskMixin,
    TimeCutStopManager,
)
from user_data.strategies.components.signals import (
    crossed_above,
    crossed_below,
    volume_pump_drop_filter,
)
from user_data.strategies.components.strategy_base import ComponentStrategy


class ExampleComponentStrategy(RiskMixin, ComponentStrategy):
    timeframe = "5m"
    startup_candle_count = 300

    stop_managers = [
        ATRStopManager(atr_length=14, mult=1.5, anchor="entry"),
        TimeCutStopManager(minutes=240, cut=0.01),
    ]
    exit_managers = [DurationExitManager(minutes=720)]
    position_sizer = RiskBasedSizer(risk_per_trade=0.005, stop_distance=0.05)
    leverage_policy = FixedLeverage(3.0)

    buy_wt = 0.75
    sell_wt = -0.75
    buy_mfi = 40.0
    sell_mfi = 65.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = wavetrend(dataframe, channel_length=10, avg_length=21, sma_length=4)
        dataframe["mfi"] = mfi(dataframe, 14)
        dataframe["atr"] = atr(dataframe, 14)
        dataframe["volume_ma"] = volume_mean(dataframe, 30)
        pump_ok, _ = volume_pump_drop_filter(dataframe, pump_mult=0.4, drop_mult=3.8)
        dataframe["pump_ok"] = pump_ok
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = (
            (dataframe["mfi"] < self.buy_mfi)
            & (dataframe["close"] > dataframe["close"].rolling(200).mean())
            & crossed_above(dataframe["wt1"], dataframe["wt2"])
            & (dataframe["wt1"] < self.buy_wt)
            & (dataframe["volume"] > dataframe["volume_ma"])
            & dataframe["pump_ok"]
        ).astype(int)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = (
            (dataframe["mfi"] > self.sell_mfi)
            & crossed_below(dataframe["wt1"], dataframe["wt2"])
            & (dataframe["wt1"] > self.sell_wt)
        ).astype(int)
        return dataframe
