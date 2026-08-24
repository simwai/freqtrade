"""SuperTrend + Keltner example with SMMA/EMA convergence filter, profit-tiered
trailing stop and partial take profits.

Reuses:
    indicators.supertrend / keltner / ma_convergence
    signals.crossed_above
    risk.RiskMixin + ProfitTieredTrailingManager + PartialTPSpec + FixedLeverage
"""

from pandas import DataFrame

from user_data.strategies.components.indicators import keltner, ma_convergence, supertrend
from user_data.strategies.components.risk import (
    FixedLeverage,
    PartialTPSpec,
    ProfitTieredTrailingManager,
    RiskMixin,
)
from user_data.strategies.components.signals import crossed_above
from user_data.strategies.components.strategy_base import ComponentStrategy


class SuperKeltnerConvergenceStrategy(RiskMixin, ComponentStrategy):
    timeframe = "1h"
    startup_candle_count = 400

    stop_managers = [
        ProfitTieredTrailingManager(
            pHSL=-0.08, pPF_1=0.011, pSL_1=0.011, pPF_2=0.064, pSL_2=0.062
        )
    ]
    leverage_policy = FixedLeverage(2.0)
    partial_tp = PartialTPSpec(mode="atr", atr_length=14, multipliers=(1.0, 2.0, 3.0))

    supertrend_period = 10
    supertrend_factor = 3.0
    keltner_length = 20
    keltner_atr_length = 10
    keltner_mult = 2.2

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        st, direction = supertrend(
            dataframe, self.supertrend_period, self.supertrend_factor
        )
        dataframe["supertrend"] = st
        dataframe["supertrend_direction"] = direction

        kc = keltner(
            dataframe,
            length=self.keltner_length,
            atr_length=self.keltner_atr_length,
            mult=self.keltner_mult,
        )
        dataframe["kc_upper"] = kc["upper"]
        dataframe["kc_mid"] = kc["mid"]
        dataframe["kc_lower"] = kc["lower"]

        convergence = ma_convergence(dataframe["close"], ema_length=15, smma_length=25)
        dataframe["is_long_allowed"] = convergence["is_long_allowed"]
        dataframe["is_short_allowed"] = convergence["is_short_allowed"]
        dataframe["atr"] = kc["upper"] - kc["mid"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = (
            (dataframe["supertrend_direction"] > 0)
            & (dataframe["supertrend_direction"].shift(1) <= 0)
            & dataframe["is_long_allowed"]
        ).astype(int)
        dataframe["enter_short"] = (
            (dataframe["supertrend_direction"] < 0)
            & (dataframe["supertrend_direction"].shift(1) >= 0)
            & dataframe["is_short_allowed"]
        ).astype(int)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = (
            (dataframe["close"] > dataframe["kc_upper"])
            & crossed_above(dataframe["close"], dataframe["kc_upper"])
        ).astype(int)
        dataframe["exit_short"] = (
            (dataframe["close"] < dataframe["kc_lower"])
            & crossed_above(dataframe["kc_lower"], dataframe["close"])
        ).astype(int)
        return dataframe
