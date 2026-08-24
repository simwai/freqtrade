import datetime
import logging
from typing import Optional, Tuple

import numpy as np

from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
from strategy_lib.risk import SlTpConfig, TradeLevelsManager

from user_data.strategies.bigz._bigz_shared import BigZSharedBase

logger = logging.getLogger(__name__)

###########################################################################################################
##                                  BigZ06 by ilya                                                       ##
##                                                                                                       ##
##    https://github.com/i1ya/freqtrade-strategies                                                       ##
##    The stratagy most inspired by iterativ (authors of the CombinedBinHAndClucV6)                      ##
##                                                                                                       ##
###########################################################################################################
##     The main point of this strat is:                                                                  ##
##        -  make drawdown as low as possible                                                            ##
##        -  buy at dip                                                                                  ##
##        -  sell quick as fast as you can (release money for the next buy)                              ##
##        -  soft check if market if rising                                                              ##
##        -  hard check is market if fallen                                                              ##
##        -  14 buy signals                                                                              ##
##        -  stoploss function preventing from big fall                                                  ##
##        -  no sell signal. Whether ROI or stoploss =)                                                  ##
##                                                                                                       ##
###########################################################################################################
##                 GENERAL RECOMMENDATIONS                                                               ##
##                                                                                                       ##
##   For optimal performance, suggested to use between 3 and 5 open trades.                              ##
##                                                                                                       ##
##   As a pairlist you can use VolumePairlist.                                                           ##
##                                                                                                       ##
##   Ensure that you don't override any variables in your config.json. Especially                        ##
##   the timeframe (must be 5m).                                                                         ##
##                                                                                                       ##
##   sell_profit_only:                                                                                   ##
##       True - risk more (gives you higher profit and higher Drawdown)                                  ##
##       False (default) - risk less (gives you less ~10-15% profit and much lower Drawdown)             ##
##                                                                                                       ##
##    BigZ06 using market orders.                                                                        ##
##    Ensure you're familar with https://www.freqtrade.io/en/stable/configuration/#market-order-pricing  ##
##                                                                                                       ##
###########################################################################################################
##               DONATIONS 2 @iterativ (author of the original strategy)                                 ##
##                                                                                                       ##
##   Absolutely not required. However, will be accepted as a token of appreciation.                      ##
##                                                                                                       ##
##   BTC: bc1qvflsvddkmxh7eqhc4jyu5z5k6xcw3ay8jl49sk                                                     ##
##   ETH: 0x83D3cFb8001BDC5d2211cBeBB8cB3461E5f7Ec91                                                     ##
##                                                                                                       ##
###########################################################################################################


class BigZ06AtrSl(BigZSharedBase):
    INTERFACE_VERSION = 2

    # Interface v2 signal columns.
    entry_signal_col = "buy"
    exit_signal_col = "sell"
    exit_signal_value = 0

    # ROI table:
    minimal_roi = {"0": 0.259, "11": 0.088, "25": 0.04, "50": 0}

    # Stoploss:
    stoploss = -0.1

    # Trailing stop:
    trailing_stop = True
    trailing_stop_positive = 0.328
    trailing_stop_positive_offset = 0.399
    trailing_only_offset_is_reached = True

    # Optional order type mapping.
    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "ema_200_1h": {"color": "#00A398"},
                "ema_200": {"color": "#00CCBE"},
                "ema_26": {"color": "#00F5E4"},
                "ema_12": {"color": "#48FFF3"},
                "custom_stop_loss": {"color": "red"},
            },
            "subplots": {
                "MACD": {"macd": {"color": "blue"}, "signal": {"color": "violet"}},
                "RSI": {
                    "rsi": {"color": "crimson"},
                },
            },
        }

    def _should_skip_trading(self, pair: str) -> bool:
        current_date = datetime.datetime.utcnow().date()
        failed_trades_count, last_trade_date = self._get_trade_data(pair)

        if last_trade_date != current_date:
            self._reset_failed_trades_count(pair, current_date)
            failed_trades_count = 0

        return failed_trades_count >= 2

    def _increment_failed_trades_count(self, trade: Trade) -> None:
        trade_date = (trade.close_date or datetime.datetime.utcnow()).date()
        failed_trades_count, last_trade_date = self._get_trade_data(trade.pair)

        if last_trade_date != trade_date:
            self._reset_failed_trades_count(trade.pair, trade_date)
            failed_trades_count = 0

        failed_trades_count += 1
        self._set_trade_data(trade.pair, failed_trades_count, trade_date)

    def _reset_failed_trades_count(self, pair: str, current_date: datetime.date) -> None:
        self._set_trade_data(pair, 0, current_date)

    def _get_trade_data(self, pair: str) -> Tuple[int, Optional[datetime.date]]:
        trade = self._get_latest_trade(pair)
        if trade:
            failed_trades_count = trade.get_custom_data(self.failed_trades_key) or 0
            last_trade_date = trade.get_custom_data(self.last_trade_date_key)
            return failed_trades_count, last_trade_date
        return 0, None

    def _set_trade_data(
        self, pair: str, failed_trades_count: int, trade_date: datetime.date
    ) -> None:
        trade = self._get_latest_trade(pair)
        if trade:
            trade.set_custom_data(self.failed_trades_key, failed_trades_count)
            trade.set_custom_data(self.last_trade_date_key, trade_date)

    def _get_latest_trade(self, pair: str) -> Optional[Trade]:
        trades = Trade.get_trades_proxy(pair=pair, is_open=False)
        closed_trades = [trade for trade in trades if trade.close_date is not None]
        return max(closed_trades, key=lambda trade: trade.close_date, default=None)

    def confirm_trade_entry(self, pair: str, **kwargs) -> bool:
        # Check if we should skip trading for the rest of the day
        if self._should_skip_trading(pair):
            return False
        return True

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        **kwargs,
    ) -> bool:
        # Increment the counter if the trade failed (i.e., has a negative profit)
        if trade.calc_profit_ratio(rate) < 0:
            self._increment_failed_trades_count(trade)
        return True

    def _risk_config(self) -> SlTpConfig:
        """ATR stop via the shared strategy_lib.risk engine.

        Mirrors the Pine ``calculateAtrSltp`` locked mode: the stop is fixed at
        ``entry - atr * multiplier`` on the entry bar. Unlike the previous inline
        version this anchors on the entry rate rather than the entry candle low
        and uses the Pine Hann-window ATR instead of ``pta.atr`` (Wilder).
        """
        return SlTpConfig(
            mode="ATR",
            sl_size_or_atr_multiplier=1.0,
            atr_length=14,
            enable_take_profit=False,
        )

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime.datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float:
        """Custom stoploss from the shared ATR level engine."""
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
        stop_loss_ratio = stoploss_from_absolute(
            stop,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )
        logger.info(f"Using ATR-based SL {stop} for {pair}; current rate is {current_rate}.")
        return stop_loss_ratio
