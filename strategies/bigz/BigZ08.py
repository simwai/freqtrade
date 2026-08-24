import logging
from datetime import datetime
from typing import Optional

import numpy as np
from pandas import DataFrame
import pandas_ta as pta

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    stoploss_from_absolute,
)
from freqtrade.strategy.parameters import BooleanParameter
from strategy_lib import risk as sl_risk
from strategy_lib.risk import SlTpConfig, TradeLevelsManager

from user_data.strategies.bigz._bigz_shared import BigZSharedBase


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class BigZ08(BigZSharedBase):
    INTERFACE_VERSION = 3

    # minimal_roi = {"0": 0.028, "10": 0.018, "40": 0.005, "180": 0.018}
    stoploss = -0.99  # effectively disabled.

    timeframe = "5m"
    inf_1h = "1h"

    use_exit_signal = True
    use_custom_exit = True
    use_custom_stoploss = True
    process_only_new_candles = True
    startup_candle_count: int = 200

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }

    buy_params = {
        "buy_condition_0_enable": False,
        "buy_condition_1_enable": False,
        "buy_condition_2_enable": False,
        "buy_condition_3_enable": False,
        "buy_condition_4_enable": False,
        "buy_condition_5_enable": True,
        "buy_condition_6_enable": True,
        "buy_condition_7_enable": False,
        "buy_condition_8_enable": False,
        "buy_condition_9_enable": False,
        "buy_condition_10_enable": False,
        "buy_condition_11_enable": False,
        "buy_condition_12_enable": False,
        "buy_condition_13_enable": False,
    }


    high_low_stop_loss_lookback = DecimalParameter(
        1, 200, decimals=0, default=50, space="buy", optimize=True
    )
    high_low_stop_loss_multiplier = DecimalParameter(
        0.8, 1.0, default=0.84, decimals=2, space="buy", optimize=True
    )
    high_low_stop_loss_backup_multiplier = DecimalParameter(
        0.8, 1.0, default=1, decimals=2, space="buy", optimize=True
    )
    automatic_high_low_take_profit_ratio = DecimalParameter(
        0.85, 1.5, default=1.28, decimals=2, space="buy", optimize=True
    )

    cooldown_lookback = DecimalParameter(
        2, 300, default=205, space="protection", optimize=True, decimals=0
    )
    use_stop_protection = BooleanParameter(default=True, space="protection", optimize=False)

    max_drawdown_lookback = DecimalParameter(
        2, 300, default=141, space="protection", optimize=True, decimals=0
    )
    max_drawdown_trade_limit = DecimalParameter(
        1, 5, default=3, space="protection", optimize=True, decimals=0
    )
    max_drawdown_stop_duration = DecimalParameter(
        1, 100, default=60, space="protection", optimize=True, decimals=0
    )
    max_allowed_drawdown = DecimalParameter(
        0.1, 0.3, default=0.19, space="protection", optimize=True, decimals=2
    )

    stop_loss_guard_lookback = DecimalParameter(
        1, 300, default=243, space="protection", optimize=False, decimals=0
    )
    stop_loss_guard_trade_limit = DecimalParameter(
        1, 10, default=3, space="protection", optimize=False, decimals=0
    )
    stop_loss_guard_stop_duration = DecimalParameter(
        1, 100, default=11, space="protection", optimize=True, decimals=0
    )
    required_profit_stoploss_guard = DecimalParameter(
        0.0, 0.2, default=0.07, space="protection", optimize=True, decimals=2
    )

    low_profit_pairs_lookback = DecimalParameter(
        1, 300, default=199, space="protection", optimize=True, decimals=0
    )
    low_profit_pairs_trade_limit = DecimalParameter(
        1, 10, default=1, space="protection", optimize=False, decimals=0
    )
    low_profit_pairs_stop_duration = DecimalParameter(
        1, 100, default=40, space="protection", optimize=False, decimals=0
    )
    required_profit_low_profit_pairs = DecimalParameter(
        0.01, 0.1, default=0.1, space="protection", optimize=True, decimals=2
    )

    @property
    def protections(self):  # type: ignore
        prot = []

        if self.use_stop_protection.value:
            prot.append(
                {"method": "CooldownPeriod", "stop_duration_candles": self.cooldown_lookback.value}
            )
            prot.append(
                {
                    "method": "MaxDrawdown",
                    "lookback_period_candles": self.max_drawdown_lookback.value,
                    "trade_limit": self.max_drawdown_trade_limit.value,
                    "stop_duration_candles": self.max_drawdown_stop_duration.value,
                    "max_allowed_drawdown": self.max_allowed_drawdown.value,
                    "only_per_pair": False,
                    "only_per_side": False,
                }
            )
            prot.append(
                {
                    "method": "StoplossGuard",
                    "lookback_period_candles": self.stop_loss_guard_lookback.value,
                    "trade_limit": self.stop_loss_guard_trade_limit.value,
                    "stop_duration_candles": self.stop_loss_guard_stop_duration.value,
                    "required_profit": self.required_profit_stoploss_guard.value,
                    "only_per_pair": False,
                    "only_per_side": False,
                }
            )
            prot.append(
                {
                    "method": "LowProfitPairs",
                    "lookback_period_candles": self.low_profit_pairs_lookback.value,
                    "trade_limit": self.low_profit_pairs_trade_limit.value,
                    "stop_duration_candles": self.low_profit_pairs_stop_duration.value,
                    "required_profit": self.required_profit_low_profit_pairs.value,
                    "only_per_pair": True,
                    "only_per_side": False,
                }
            )

        return prot

    @property
    def plot_config(self):  # type: ignore
        return {
            "main_plot": {
                "ema_200_1h": {"color": "#00A398"},
                "ema_200": {"color": "#00CCBE"},
                "ema_26": {"color": "#00F5E4"},
                "ema_12": {"color": "#48FFF3"},
                "stop_loss": {"color": "red"},
                "take_profit": {"color": "green"},
            },
            "subplots": {
                "MACD": {"macd": {"color": "blue"}, "signal": {"color": "violet"}},
                "RSI": {
                    "rsi": {"color": "crimson"},
                },
            },
        }

    def _risk_config(self) -> SlTpConfig:
        """SL/TP levels via the shared strategy_lib.risk engine (Highest Lowest mode).

        The engine mirrors the Pine ``calculateHighLowSltp`` behaviour: the stop
        is captured once at entry from the lookback low/high (with a backup
        multiplier when the entry candle is itself the lookback extreme) and the
        take-profit is locked at entry from the entry-to-stop risk * R:R.
        """
        return SlTpConfig(
            mode="Highest Lowest",
            risk_reward_ratio=float(self.automatic_high_low_take_profit_ratio.value),
            my_backup_multiplier=float(self.high_low_stop_loss_backup_multiplier.value),
            high_low_stop_loss_lookback=int(self.high_low_stop_loss_lookback.value),
            high_low_stop_loss_multiplier=float(self.high_low_stop_loss_multiplier.value),
            enable_take_profit=True,
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        """Take-profit / stop-loss candle-cross exits from the shared level engine."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 2:
            return None

        current_index = len(dataframe) - 1
        previous_index = current_index - 1
        config = self._risk_config()
        manager = getattr(self, "_risk_manager", None)
        if manager is None:
            manager = TradeLevelsManager(config)
            self._risk_manager = manager
        else:
            manager.config = config
        levels = manager.cached_trade_level_series(pair, dataframe, trade, self.timeframe)
        if levels is None:
            return None
        entry_index = int(levels["entry_index"][0])
        if current_index <= entry_index:
            return None
        previous_levels = sl_risk.levels_at(levels, previous_index)
        current_levels = sl_risk.levels_at(levels, current_index)

        previous_close = float(dataframe["close"].iloc[previous_index])
        current_close = float(dataframe["close"].iloc[current_index])
        signal = sl_risk.exit_cross_signal(
            previous_close,
            current_close,
            previous_levels,
            current_levels,
            trade.is_short,
        )
        if signal:
            logging.info(
                f"{signal} on {pair}. Current rate: {current_rate:.4f}, "
                f"SL: {current_levels['long_stop' if not trade.is_short else 'short_stop']:.4f}, "
                f"TP: {current_levels['long_tp' if not trade.is_short else 'short_tp']:.4f}."
            )
            return signal
        return None

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        """Hard stop from the same shared level series."""
        config = self._risk_config()
        manager = getattr(self, "_risk_manager", None)
        if manager is None:
            manager = TradeLevelsManager(config)
            self._risk_manager = manager
        else:
            manager.config = config
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        levels = manager.current_trade_levels(pair, dataframe, trade, self.timeframe)
        if levels is None:
            return self.stoploss
        stop = levels["short_stop"] if trade.is_short else levels["long_stop"]
        if not np.isfinite(stop) or stop <= 0.0:
            return self.stoploss
        return stoploss_from_absolute(
            stop, current_rate, is_short=trade.is_short, leverage=trade.leverage
        )


    def informative_1h_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if not self.dp:
            raise ValueError("DataProvider is required for multiple timeframes.")

        # Get the informative pair
        informative_1h = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.inf_1h
        ).copy()

        # EMA
        informative_1h["ema_50"] = pta.ema(informative_1h["close"], length=50)
        informative_1h["ema_200"] = pta.ema(informative_1h["close"], length=200)

        # RSI
        informative_1h["rsi"] = pta.rsi(informative_1h["close"], length=14)

        # Bollinger Bands
        bbands = pta.bbands(informative_1h["close"], length=20, std=2)
        informative_1h["bb_lowerband"] = bbands.iloc[:, 0]
        informative_1h["bb_middleband"] = bbands.iloc[:, 1]
        informative_1h["bb_upperband"] = bbands.iloc[:, 2]

        # Aroon
        aroon = pta.aroon(
            high=informative_1h["high"], low=informative_1h["low"], length=10
        )
        informative_1h["aroon_down"] = aroon.iloc[:, 0]
        informative_1h["aroon_up"] = aroon.iloc[:, 1]

        return informative_1h

    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Bollinger Bands
        bbands = pta.bbands(dataframe["close"], length=20, std=2)
        dataframe["bb_lowerband"] = bbands.iloc[:, 0]
        dataframe["bb_middleband"] = bbands.iloc[:, 1]
        dataframe["bb_upperband"] = bbands.iloc[:, 2]

        # Volume Mean
        dataframe["volume_mean_slow"] = pta.sma(dataframe["volume"], length=48)

        # EMAs
        dataframe["ema_200"] = pta.ema(dataframe["close"], length=200)
        dataframe["ema_26"] = pta.ema(dataframe["close"], length=26)
        dataframe["ema_12"] = pta.ema(dataframe["close"], length=12)

        # MACD
        macd = pta.macd(dataframe["close"], fast=12, slow=26, signal=9)
        dataframe["macd"] = macd.iloc[:, 0]
        dataframe["signal"] = macd.iloc[:, 1]
        dataframe["hist"] = macd.iloc[:, 2]

        # RSI
        dataframe["rsi"] = pta.rsi(dataframe["close"], length=14)

        # Chaikin Money Flow
        dataframe["cmf"] = pta.cmf(
            high=dataframe["high"],
            low=dataframe["low"],
            close=dataframe["close"],
            volume=dataframe["volume"],
            length=20,
        )

        # ATR
        dataframe["atr"] = pta.atr(
            high=dataframe["high"],
            low=dataframe["low"],
            close=dataframe["close"],
            length=5,
        )

        return dataframe

