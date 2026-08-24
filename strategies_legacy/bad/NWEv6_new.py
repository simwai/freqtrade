# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401

# --- Do not remove these libs ---
import numpy as np  # noqa
import pandas as pd  # noqa

pd.options.mode.chained_assignment = None  # default='warn'
from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair, informative, stoploss_from_absolute
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter
from strategy_lib.risk import SlTpConfig, TradeLevelsManager

# --------------------------------
# Add your lib to import here
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
import math
from technical.indicators import TKE
import math
import logging
from functools import reduce

from datetime import datetime, timedelta, timezone
from timeit import default_timer as timer
from datetime import timedelta
import time

logger = logging.getLogger(__name__)


def SSLChannels_ATR(dataframe, length=7):
    """
    SSL Channels with ATR: https://www.tradingview.com/script/SKHqWzql-SSL-ATR-channel/
    Credit to @JimmyNixx for python
    """
    df = dataframe.copy()

    df['ATR'] = ta.ATR(df, timeperiod=14)
    df['smaHigh'] = df['high'].rolling(length).mean() + df['ATR']
    df['smaLow'] = df['low'].rolling(length).mean() - df['ATR']
    df['hlv'] = np.where(df['close'] > df['smaHigh'], 1, np.where(df['close'] < df['smaLow'], -1, np.NAN))
    df['hlv'] = df['hlv'].ffill()
    df['sslDown'] = np.where(df['hlv'] < 0, df['smaHigh'], df['smaLow'])
    df['sslUp'] = np.where(df['hlv'] < 0, df['smaLow'], df['smaHigh'])

    return df['sslDown'], df['sslUp']


def funcNadarayaWatsonEnvelope(dtloc, source='close', bandwidth=8, window=500, mult=3):
    """
    // This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
    // Nadaraya-Watson Envelope [LUX]
      https://www.tradingview.com/script/Iko0E2kL-Nadaraya-Watson-Envelope-LUX/
     :return: up and down
     translated for freqtrade: viksal1982  viktors.s@gmail.com


     df.shape[0]
    """
    dtNWE = dtloc.copy()
    dtNWE['nwe_up'] = np.nan
    dtNWE['nwe_down'] = np.nan
    wn = np.zeros((window, window))
    for i in range(window):
        for j in range(window):
            wn[i, j] = math.exp(-(math.pow(i - j, 2) / (bandwidth * bandwidth * 2)))
    sumSCW = wn.sum(axis=1)

    def calc_nwa(dfr, init=0):
        global calc_src_value
        if init == 1:
            calc_src_value = list()
            return
        calc_src_value.append(dfr[source])
        mae = 0.0
        y2_val = 0.0
        y2_val_up = np.nan
        y2_val_down = np.nan
        if len(calc_src_value) > window:
            calc_src_value.pop(0)
        if len(calc_src_value) >= window:
            src = np.array(calc_src_value)
            sumSC = src * wn
            sumSCS = sumSC.sum(axis=1)
            y2 = sumSCS / sumSCW
            sum_e = np.absolute(src - y2)
            mae = sum_e.sum() / window * mult
            y2_val = y2[-1]
            y2_val_up = y2_val + mae
            y2_val_down = y2_val - mae
        return y2_val_up, y2_val_down

    calc_nwa(None, init=1)
    dtNWE[['nwe_up', 'nwe_down']] = dtNWE.apply(calc_nwa, axis=1, result_type='expand')
    return dtNWE[['nwe_up', 'nwe_down']]


class NWEv6_new(IStrategy):
    window_buy = IntParameter(60, 1000, default=300, space='buy', optimize=True)
    bandwidth_buy = IntParameter(2, 15, default=9, space='buy', optimize=True)
    mult_buy = DecimalParameter(0.5, 20.0, default=4, space='buy', optimize=True)
    marginselldw = DecimalParameter(1.0049, 1.0200, default=1.0038, space='buy', decimals=4, optimize=True, load=True)
    # hard stoploss profit
    pHSL = DecimalParameter(-0.100, -0.040, default=-0.05, decimals=3, space='sell', load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', load=True)

    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell', load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', load=True)

    # Optimal timeframe for the strategy.
    timeframe = '3m'
    inf_timeframe = '5m'

    # These values can be overridden in the "ask_strategy" section in the config.
    use_custom_stoploss = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Number of candles the strategy requires before producing valid signals
    startup_candle_count: int = 300

    minimal_roi = {
        "0": 0.10,
        "423": 0.03,
        "751": 0.01
    }

    stoploss = -0.99
    trailing_stop = False
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.019
    trailing_only_offset_is_reached = True
    process_only_new_candles = False

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration": 120
            },
            {
                "method": "StoplossGuard",
                "lookback_period": 90,
                "trade_limit": 2,
                "stop_duration": 120,
                "only_per_pair": False
            },
            {
                "method": "StoplossGuard",
                "lookback_period": 90,
                "trade_limit": 1,
                "stop_duration": 120,
                "only_per_pair": True
            },
        ]

    # Optional order type mapping.
    order_types = {
        'entry': 'limit',
        'exit': 'limit',
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    # Optional order time in force.
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'gtc'
    }

    plot_config = {
        # Main plot indicators (Moving averages, ...)
        'main_plot': {
            'nwe_up': {'color': 'red'},
            'nwe_down': {'color': "rgba(155,150,200,2.4)"},
            'ema_100': {'color': 'blue'},
            'entry_line': {'color': 'green'},
        },
        'subplots': {
            "TREND/PCT": {
                'btctrend': {'color': 'green'},
                'highpct': {'color': 'red'},
                'lowpct': {'color': 'blue'}
            }

        }
    }

    ## Custom Trailing stoploss (credit to Perkmeister for the trailing logic)
    def _risk_config(self) -> SlTpConfig:
        """Profit-tiered trailing stop via the shared strategy_lib.risk engine."""
        return SlTpConfig(
            mode="Trailing Profit Tier",
            tier_p_hsl=float(self.pHSL.value),
            tier_p_pf_1=float(self.pPF_1.value),
            tier_p_sl_1=float(self.pSL_1.value),
            tier_p_pf_2=float(self.pPF_2.value),
            tier_p_sl_2=float(self.pSL_2.value),
            enable_take_profit=False,
        )

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
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

    @informative('3m', 'BTC/{stake}', fmt='{base}_{column}_{timeframe}')
    def populate_indicators_3m_btc(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ssldown, sslup = SSLChannels_ATR(dataframe, 25)
        dataframe['trend'] = np.where(sslup > ssldown, 1, -1)
        return dataframe

    @informative('5m')
    def populate_indicators_5m(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['ema_100'] = ta.EMA(dataframe, timeperiod=100)
        dataframe[['nwe_up', 'nwe_down']] = funcNadarayaWatsonEnvelope(dataframe, source='close',
                                                                       bandwidth=self.bandwidth_buy.value,
                                                                       window=self.window_buy.value,
                                                                       mult=self.mult_buy.value)

        dataframe["highpct"] = dataframe['nwe_down'] * dataframe['nwe_up'].pct_change(periods=24)
        dataframe["lowpct"] = dataframe['nwe_down'] * dataframe['nwe_down'].pct_change(periods=6)

        dataframe['entry_line'] = dataframe['nwe_down'] / self.marginselldw.value
        dataframe['Newentry_line'] = dataframe['nwe_down'] * dataframe["lowpct"]

        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = []

        con2 = (
                (dataframe['btc_trend_3m'] == 1) &
                (qtpylib.crossed_below(dataframe['highpct_5m'], dataframe['lowpct_5m'])) &
                (dataframe['ema_100_5m'] > dataframe['close_5m']) &
                (dataframe['nwe_up_5m'] <= (abs(dataframe['highpct_5m']) * 100)) &
                (dataframe['volume_5m'] > 0)
        )

        con3 = (
                (dataframe['close_5m'].shift() < dataframe['entry_line_5m'].shift()) &
                (dataframe['close_5m'].shift(2) < dataframe['entry_line_5m'].shift(2)) &
                (dataframe['close_5m'] > dataframe['entry_line_5m']) &
                (dataframe['ema_100_5m'] > dataframe['close_5m']) &
                #                (dataframe['ema_100_5m'] > dataframe['nwe_up_5m'] ) &
                (dataframe['volume_5m'] > 0)  # Make sure Volume is not 0
        )

        conditions.append(con2)
        conditions.append(con3)

        dataframe.loc[con2, 'entry_tag'] = " con2 "
        dataframe.loc[con3, 'entry_tag'] = " con3 "

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'enter_long'
            ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = []

        con1 = (
                (dataframe['close_5m'].shift() > dataframe['nwe_up_5m'].shift()) &
                (dataframe['close_5m'] < dataframe['nwe_up_5m'])
        )

        conditions.append(con1)
        # conditions.append(con2)

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'exit_long'
            ] = 1

        return dataframe
