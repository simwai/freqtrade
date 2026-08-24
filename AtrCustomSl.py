import datetime
import logging

import pandas_ta as pta

from freqtrade.exchange.exchange_utils_timeframe import timeframe_to_prev_date
from freqtrade.persistence.trade_model import Trade


logger = logging.getLogger(__name__)


def custom_stoploss(
    self,
    pair: str,
    trade: Trade,
    current_time: datetime.datetime,
    current_rate: float,
    current_profit: float,
    **kwargs,
) -> float:
    """
    Custom stoploss function that calculates stop loss based on the low of the entry candle
    and the ATR (Average True Range) of the last candle.
    """
    entry_low_key = f"trade_{trade.id}_entry_low"
    entry_low = _get_entry_low(trade, entry_low_key, current_rate)

    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

    if entry_low == current_rate:
        entry_low = _update_entry_low_from_candle(self, trade, dataframe, entry_low_key, pair)

    atr_stop_loss = _calculate_atr_stop_loss(dataframe, entry_low)
    stop_loss_percentage = 1 - (current_rate / atr_stop_loss)

    if current_rate <= atr_stop_loss:
        logger.info(
            f"ATR-based SL triggered. Current rate: {current_rate}, SL set at {atr_stop_loss}, "
            f"which is {stop_loss_percentage}% below entry low."
        )
        return stop_loss_percentage
    else:
        logger.info(
            f"Current rate {current_rate} is above ATR-based SL {atr_stop_loss}. No SL triggered."
        )
        return 0.99  # No stop loss triggered, return a high value to keep the trade open


def _get_entry_low(trade: Trade, entry_low_key: str, current_rate: float) -> float:
    """
    Retrieve entry_low from the database if available, otherwise use current_rate.
    """
    entry_low = current_rate
    try:
        current_entry_low = trade.get_custom_data(entry_low_key)
        if current_entry_low is None:
            raise ValueError("No entry_low found in storage. Using current_rate instead.")
        else:
            logger.info(f"Using entry_low from storage: {current_entry_low}")
            entry_low = current_entry_low
    except Exception as e:
        logger.info(str(e))
    return entry_low


def _update_entry_low_from_candle(
    self, trade: Trade, dataframe, entry_low_key: str, pair: str
) -> float:
    """
    Update entry_low based on the previous candle's low.
    """
    entry_low = trade.open_rate
    try:
        trade_date = timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
        trade_candles = dataframe.loc[dataframe["date"] == trade_date]
        if trade_candles.empty:
            logger.info(f"No data found for date {trade_date} for pair {pair}.")
        else:
            entry_low = trade_candles.iloc[0]["low"]
            trade.set_custom_data(entry_low_key, entry_low)  # Store entry_low in the database
            logger.info(f"Using entry_low from previous candle: {entry_low}")
    except KeyError:
        logger.warning(
            f"No entry candle found for trade on {trade_date} for pair {pair}. Using current "
            "rate as fallback for SL calculation."
        )
    except Exception as e:
        logger.error(f"Error processing trade data: {e}")
    return entry_low


def _calculate_atr_stop_loss(dataframe, entry_low: float) -> float:
    """
    Calculate the ATR-based stop loss.
    """
    try:
        atr = pta.atr(dataframe["high"], dataframe["low"], dataframe["close"], timeperiod=14)
        last_atr = atr.iloc[-1]
        return entry_low - last_atr
    except Exception as e:
        default_sl = -0.03
        logger.error(f"Error calculating ATR. Default SL of {default_sl}% applied. Error: {e}")
        return default_sl
