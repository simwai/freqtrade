from pandas import DataFrame
from freqtrade.strategy import IStrategy, CategoricalParameter, IntParameter, BooleanParameter
import talib.abstract as ta
import numpy as np

class WildersVolatilityBingAi(IStrategy):
    # Define the hyperoptable parameters
    ma_type = CategoricalParameter(['sma', 'ema', 'smm', 't3', 'jma'], default='sma', space='buy')
    fast_period = IntParameter(5, 50, default=12, space='buy')
    slow_period = IntParameter(30, 200, default=26, space='buy')
    highLowStopLossLookback = IntParameter(5, 100, default=14, space='buy', optimize=True, load=True)
    highLowTakeProfitLookback = IntParameter(5, 100, default=14, space='buy', optimize=True, load=True)
    enable_fir_filter = BooleanParameter(default=False, space='buy', optimize=True)
    is_aroon_sidetrend_filter_enabled = BooleanParameter(default=False, space='buy', optimize=True)
    is_aroon_sidetrend_mode_trending = BooleanParameter(default=False, space='buy', optimize=True)
    aroon_length = IntParameter(5, 50, default=14, space='buy', optimize=True, load=True)

    # Define the higher timeframe
    higher_timeframe = '4h'

    # Define the maximum risk per trade (e.g., 2% of the account balance)
    max_risk_per_trade = 0.02

    def T3(self, data, period=5, vfactor=0.7):
        EMA1 = data.ewm(span=period).mean()
        EMA2 = EMA1.ewm(span=period).mean()
        EMA3 = EMA2.ewm(span=period).mean()
        EMA4 = EMA3.ewm(span=period).mean()
        EMA5 = EMA4.ewm(span=period).mean()
        EMA6 = EMA5.ewm(span=period).mean()

        c1 = -vfactor * vfactor * vfactor
        c2 = 3 * vfactor * vfactor + 3 * vfactor * vfactor * vfactor
        c3 = -6 * vfactor * vfactor - 3 * vfactor - 3 * vfactor * vfactor * vfactor
        c4 = 1 + 3 * vfactor + vfactor * vfactor * vfactor + 3 * vfactor * vfactor

        T3 = c1 * EMA6 + c2 * EMA5 + c3 * EMA4 + c4 * EMA3
        return T3

    def JMA(self, data, period=10):
        diff = np.abs(data.diff())
        vola = diff.rolling(window=period).mean()
        ma = data.rolling(window=period).mean()
        JMA = ma + vola
        return JMA

    def informative_pairs(self):
        return [(pair, self.higher_timeframe) for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Get the higher timeframe data
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.higher_timeframe)

        # Calculate the ATR on the higher timeframe data
        informative['atr'] = ta.ATR(informative, timeperiod=14)

        # Merge the higher timeframe ATR to the current dataframe
        dataframe = dataframe.merge(informative[['date', 'atr']], on='date', how='left')

        # Forward fill the ATR values to simulate the "future" data in backtesting
        dataframe['atr'].fillna(method='ffill', inplace=True)

        # Calculate the selected moving average type for the fast MA
        if self.ma_type.value == 'sma':
            dataframe['fast_ma'] = dataframe['close'].rolling(window=self.fast_period.value).mean()
        elif self.ma_type.value == 'ema':
            dataframe['fast_ma'] = dataframe['close'].ewm(span=self.fast_period.value).mean()
        elif self.ma_type.value == 'smm':
            dataframe['fast_ma'] = dataframe['close'].rolling(window=self.fast_period.value).mean()
        elif self.ma_type.value == 't3':
            dataframe['fast_ma'] = self.T3(dataframe['close'], period=self.fast_period.value)
        elif self.ma_type.value == 'jma':
            dataframe['fast_ma'] = self.JMA(dataframe['close'], period=self.fast_period.value)

        # Calculate the selected moving average type for the slow MA
        if self.ma_type.value == 'sma':
            dataframe['slow_ma'] = dataframe['close'].rolling(window=self.slow_period.value).mean()
        elif self.ma_type.value == 'ema':
            dataframe['slow_ma'] = dataframe['close'].ewm(span=self.slow_period.value).mean()
        elif self.ma_type.value == 'smm':
            dataframe['slow_ma'] = dataframe['close'].rolling(window=self.slow_period.value).mean()
        elif self.ma_type.value == 't3':
            dataframe['slow_ma'] = self.T3(dataframe['close'], period=self.slow_period.value)
        elif self.ma_type.value == 'jma':
            dataframe['slow_ma'] = self.JMA(dataframe['close'], period=self.slow_period.value)

        # Calculate the lowest and highest prices over the lookback periods
        dataframe['highLowStopLossLowest'] = dataframe['low'].rolling(self.highLowStopLossLookback.value).min()
        dataframe['highLowStopLossHighest'] = dataframe['high'].rolling(self.highLowStopLossLookback.value).max()
        dataframe['highLowTakeProfitLowest'] = dataframe['low'].rolling(self.highLowTakeProfitLookback.value).min()
        dataframe['highLowTakeProfitHighest'] = dataframe['high'].rolling(self.highLowTakeProfitLookback.value).max()

        # Calculate the MA convergence
        dataframe['maFast_m5'] = dataframe['fast_ma'].shift(5)
        dataframe['ma1BelowMa2'] = dataframe['fast_ma'] < dataframe['slow_ma']
        dataframe['ma1AboveMa2'] = dataframe['fast_ma'] > dataframe['slow_ma']
        dataframe['isOut1ConvergingFromDown'] = (dataframe['fast_ma'] > dataframe['maFast_m5']) & dataframe['ma1BelowMa2']
        dataframe['isOut1ConvergingFromUp'] = (dataframe['fast_ma'] < dataframe['maFast_m5']) & dataframe['ma1AboveMa2']

        # Aroon sidetrend filter
        aroon_timeframe = self.dp.ticker(metadata['pair'], self.higher_timeframe)
        aroon = ta.AROON(aroon_timeframe, timeperiod=self.aroon_length.value)
        dataframe['aroon_upper'] = aroon['aroonup']
        dataframe['aroon_lower'] = aroon['aroondown']
        dataframe['aroon_upper_k'] = (dataframe['aroon_upper'].shift() - dataframe['aroon_upper']) / (dataframe.index.shift() - dataframe.index)
        dataframe['aroon_lower_k'] = (dataframe['aroon_lower'].shift() - dataframe['aroon_lower']) / (dataframe.index.shift() - dataframe.index)
        dataframe['is_sidetrend_by_aroon'] = np.where(dataframe['aroon_upper_k'] == dataframe['aroon_lower_k'], 1, 0)
        dataframe['is_trade_allowed_by_aroon_sidetrend'] = np.where(self.is_aroon_sidetrend_filter_enabled.value and ((self.is_aroon_sidetrend_mode_trending.value and not dataframe['is_sidetrend_by_aroon']) or dataframe['is_sidetrend_by_aroon']), 1, 0)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['fast_ma'] > dataframe['slow_ma']) &
                (dataframe['close'] > dataframe['highLowStopLossHighest']) &
                (~dataframe['isOut1ConvergingFromDown']) &
                (~dataframe['isOut1ConvergingFromUp']) &
                self.enable_fir_filter.value &
                dataframe['is_trade_allowed_by_aroon_sidetrend']
            ),
            'buy'] = 1

        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['fast_ma'] < dataframe['slow_ma']) &
                (dataframe['close'] < dataframe['highLowStopLossLowest']) &
                (~dataframe['isOut1ConvergingFromDown']) &
                (~dataframe['isOut1ConvergingFromUp']) &
                self.enable_fir_filter.value &
                dataframe['is_trade_allowed_by_aroon_sidetrend']
            ),
            'sell'] = 1

        return dataframe

    def custom_stake_amount(self, dataframe: DataFrame, pair: str, current_time: 'datetime', current_rate: float, proposed_stake: float, min_stake: float, max_stake: float, **kwargs) -> float:
        """
        Override this method to provide a dynamic stake amount for each trade
        """
        # Get the current ATR value for the pair
        current_atr = dataframe.loc[dataframe['date'] == current_time, 'atr'].values[0]

        # Calculate the position size based on the ATR
        position_size = self.max_risk_per_trade / current_atr

        # Make sure the position size is not less than the minimum stake amount
        position_size = max(position_size, min_stake)

        # Make sure the position size is not more than the maximum stake amount
        position_size = min(position_size, max_stake)

        return position_size
