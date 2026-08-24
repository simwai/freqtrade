"""Base strategy class wiring common freqtrade boilerplate.

Subclass ``ComponentStrategy`` and combine the ``components.risk.RiskMixin``
with your own entry/exit logic. ``merge_informative`` lets you attach a
higher-timeframe dataframe in one line.
"""

from __future__ import annotations

from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair


class ComponentStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    startup_candle_count: int = 300
    process_only_new_candles = True

    minimal_roi = {"0": 100.0}
    stoploss = -0.05

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    inf_1h = "1h"

    def informative_pairs(self) -> list:
        pairs = self.dp.current_whitelist()
        return [(pair, self.inf_1h) for pair in pairs]

    def merge_informative(
        self,
        dataframe: DataFrame,
        informative: DataFrame,
        timeframe: str,
        ffill: bool = True,
    ) -> DataFrame:
        """Attach a higher-timeframe dataframe with freqtrade's merge helpers."""
        return merge_informative_pair(
            dataframe, informative, self.timeframe, timeframe, ffill=ffill
        )

    def add_column_prefix(
        self, dataframe: DataFrame, prefix: str, keep: tuple[str, ...] = ()
    ) -> DataFrame:
        """Prefix all columns except the OHLCV base set (BigZ BTC-merge style)."""
        ignore = {"date", "open", "high", "low", "close", "volume", *keep}
        dataframe.rename(
            columns=lambda s: prefix + s if s not in ignore else s, inplace=True
        )
        return dataframe

    def drop_merged_base(self, dataframe: DataFrame, timeframe: str) -> DataFrame:
        drop_columns = [
            s + "_" + timeframe for s in ["date", "open", "high", "low", "close", "volume"]
        ]
        dataframe.drop(columns=dataframe.columns.intersection(drop_columns), inplace=True)
        return dataframe
