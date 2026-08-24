from datetime import datetime, timedelta

from freqtrade.persistence import Trade

from user_data.strategies.bigz._bigz_shared import BigZSharedBase

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


class BigZ06Original(BigZSharedBase):
    INTERFACE_VERSION = 2

    # Interface v2 signal columns.
    entry_signal_col = "buy"
    exit_signal_col = "sell"
    exit_signal_value = 0

    minimal_roi = {
        "0": 0.028,  # I feel lucky!
        "10": 0.018,
        "40": 0.005,
        "180": 0.018,  # We're going up?
    }

    stoploss = -0.99  # effectively disabled.

    # Trailing stop:
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.025
    trailing_only_offset_is_reached = True

    # Optional order type mapping.
    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        sell_reason: str,
        **kwargs,
    ) -> bool:
        return True

    def custom_exit(
        self,
        pair: str,
        trade: "Trade",
        current_time: "datetime",
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1].squeeze()
        last_candle_2 = dataframe.iloc[-2].squeeze()

        if last_candle is not None:
            if (last_candle["high"] > last_candle["bb_upperband"]) & (
                last_candle["volume"] > (last_candle_2["volume"] * 1.5)
            ):
                return "sell_signal_1"

        return False

    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        # Manage losing trades and open room for better ones.

        if current_profit > 0:
            return 0.99
        else:
            trade_time_50 = trade.open_date_utc + timedelta(minutes=50)

            # Trade open more then 60 minutes. For this strategy it's means -> loss
            # Let's try to minimize the loss

            if current_time > trade_time_50:
                try:
                    number_of_candle_shift = int(
                        (current_time - trade_time_50).total_seconds() / 300
                    )
                    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                    candle = dataframe.iloc[-number_of_candle_shift].squeeze()

                    # We are at bottom. Wait...
                    if candle["rsi_1h"] < 40:
                        return 0.99

                    # Are we still sinking?
                    if candle["close"] > candle["ema_200"]:
                        if current_rate * 1.035 < candle["open"]:
                            return 0.01

                    if current_rate * 1.025 < candle["open"]:
                        return 0.01

                except IndexError:
                    # Whoops, set stoploss at 10%
                    return 0.1

        return 0.99
