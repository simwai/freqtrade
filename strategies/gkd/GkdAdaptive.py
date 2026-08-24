# strategy_gkd_adaptive_24_final.py
"""
GKD Adaptive Strategy – BTC/USDT 15m (Final Version)
24 market regimes: Trend (U/D/S) × Momentum (Extreme/Normal) × Volatility (H/L) × Volume (H/L).
Uses higher‑timeframe (1h) indicators for regime detection, entries remain on 15m.
Strategy pool: Trend, Momentum, Breakout, Mean Reversion (NW & Extreme), Scalp Mean Rev.
SL/TP: selectable between ATR‑based and swing‑based modes, with minimum reward/risk filter.
All indicator parameters, including RSI timeperiod, are hyperopt‑ready.
"""

import numpy as np
import pandas as pd
import talib.abstract as ta
import pandas_ta as pta
from freqtrade.strategy import (
    CategoricalParameter,
    DecimalParameter,
    IStrategy,
    IntParameter,
    stoploss_from_absolute,
)
import logging

logger = logging.getLogger(__name__)


class GKDAdaptive24Final(IStrategy):
    timeframe = '15m'
    can_short = True
    stoploss = -0.99          # managed dynamically
    use_custom_stoploss = True
    position_adjustment_enable = True

    # ------------------------------------------------------------------
    # Fixed risk multipliers for ATR mode (fallback)
    vol_mult_sl_atr = 1.5
    vol_mult_tp1_atr = 1.0
    vol_mult_tp2_atr = 2.0
    vol_mult_tp3_atr = 3.0

    # Optimizer settings
    optimization_interval = 100   # 15m candles
    backtest_window = 500

    # Mapping regime_id -> {'baseline': name, 'trend_detector': name, 'strategy': name}
    regime_strategy_map = {}
    last_optimization_bar = None

    # ------------------------------------------------------------------
    # Hyperopt‑capable parameters
    # Baseline
    kama_length = IntParameter(5, 50, default=10, space='buy')
    kama_fast = IntParameter(2, 10, default=2, space='buy')
    kama_slow = IntParameter(20, 50, default=30, space='buy')
    t3_length = IntParameter(3, 20, default=5, space='buy')
    t3_factor = DecimalParameter(0.3, 0.8, default=0.618, space='buy')
    ehlers_alpha = DecimalParameter(0.01, 0.2, default=0.07, space='buy')

    # Trend detector
    kama_slope_bars = IntParameter(2, 10, default=5, space='buy')
    smma_len = IntParameter(3, 15, default=7, space='buy')
    ema_fast_len = IntParameter(5, 30, default=10, space='buy')
    ema_mid_len = IntParameter(10, 50, default=20, space='buy')
    ema_slow_len = IntParameter(20, 100, default=50, space='buy')

    # Fisher Transform
    fisher_length = IntParameter(9, 20, default=13, space='buy')

    # RSI
    rsi_period = IntParameter(2, 20, default=14, space='buy')

    # WaveTrend (for momentum strategy)
    wt_length = IntParameter(5, 15, default=10, space='buy')
    wt_avg_length = IntParameter(15, 30, default=21, space='buy')

    # Volatility index (T3 ATR Percentile/Std)
    vola_t3_length = IntParameter(5, 20, default=14, space='buy')
    vola_t3_factor = DecimalParameter(0.3, 0.8, default=0.618, space='buy')
    vola_percentile_window = IntParameter(50, 200, default=100, space='buy')
    vola_std_window = IntParameter(10, 50, default=20, space='buy')
    vol_threshold = DecimalParameter(0.3, 0.7, default=0.5, space='buy')

    # Volume extreme (T3 Volume Percentile/Std)
    vol_length = IntParameter(10, 30, default=20, space='buy')
    vol_t3_factor = DecimalParameter(0.3, 0.8, default=0.618, space='buy')
    vol_percentile_window = IntParameter(50, 200, default=100, space='buy')
    vol_std_window = IntParameter(10, 50, default=20, space='buy')
    extreme_vol_threshold = DecimalParameter(0.4, 0.9, default=0.6, space='buy')

    # Momentum extreme detection
    fisher_extreme = DecimalParameter(1.5, 3.5, default=2.5, space='buy')
    rsi_oversold = IntParameter(20, 35, default=30, space='buy')
    rsi_overbought = IntParameter(65, 80, default=70, space='buy')

    # Breakout
    breakout_window = IntParameter(10, 30, default=20, space='buy')

    # SL/TP mode and risk filter
    sl_tp_mode = CategoricalParameter(['atr', 'swing'], default='swing', space='buy')
    min_reward_risk = DecimalParameter(1.0, 3.0, default=1.5, space='buy')

    # Swing detection
    swing_window = IntParameter(3, 10, default=5, space='buy')

    # ------------------------------------------------------------------
    # Indicator factories (static methods)
    @staticmethod
    def _kama(close, length=10, fast=2, slow=30):
        return pta.kama(close, length=length, fast=fast, slow=slow)

    @staticmethod
    def _t3(close, length=5, a=0.618):
        return pta.t3(close, length=length, a=a)

    @staticmethod
    def _ehlers_it(close, alpha=0.07):
        it = close.copy()
        for i in range(2, len(it)):
            it.iloc[i] = (alpha - (alpha**2)/4) * close.iloc[i] + \
                         ((alpha**2)/2) * close.iloc[i-1] - \
                         (alpha - 3*(alpha**2)/4) * it.iloc[i-1] - \
                         ((alpha**2)/4) * it.iloc[i-2]
        return it

    BASELINES = {
        'kama': _kama.__func__,
        't3': _t3.__func__,
        'ehlers_it': _ehlers_it.__func__,
    }

    @staticmethod
    def _kama_slope(close, length=10, fast=2, slow=30, slope_bars=5):
        kama = pta.kama(close, length=length, fast=fast, slow=slow)
        atr14 = pta.atr(high=close*1.0001, low=close*0.9999, close=close, length=14)
        slope = (kama - kama.shift(slope_bars)) / (slope_bars * atr14)
        return np.clip(np.abs(slope) / 0.03, 0, 1)

    @staticmethod
    def _smma_ema_convergence(close, smma_len=7, ema_lens=(10,20,50)):
        smma = close.copy()
        alpha = 1.0 / smma_len
        for i in range(1, len(smma)):
            smma.iloc[i] = alpha * close.iloc[i] + (1 - alpha) * smma.iloc[i-1]
        emas = [ta.EMA(close, l) for l in ema_lens]
        all_mas = pd.DataFrame({'smma': smma, **{f'ema_{l}': e for l, e in zip(ema_lens, emas)}})
        spread = all_mas.std(axis=1)
        eff = 1 - (spread / spread.rolling(50).max())
        return np.clip(eff, 0, 1)

    TREND_DETECTORS = {
        'kama_slope': _kama_slope.__func__,
        'smma_ema_convergence': _smma_ema_convergence.__func__,
    }

    @staticmethod
    def _vol_index(high, low, close, t3_length=14, t3_factor=0.618,
                   percentile_window=100, std_window=20):
        tr = pta.true_range(high, low, close)
        t3 = pta.t3(tr, length=t3_length, a=t3_factor)
        rank = t3.rolling(percentile_window).rank(pct=True)
        std = t3.rolling(std_window).std()
        norm_std = std / (std.rolling(200).max() + 1e-10)
        return (rank * norm_std).fillna(0.5)

    @staticmethod
    def _extreme_vol(volume, length=20, t3_factor=0.618, percentile_window=100, std_window=20):
        t3_vol = pta.t3(volume, length=length, a=t3_factor)
        rank = t3_vol.rolling(percentile_window).rank(pct=True)
        std = t3_vol.rolling(std_window).std()
        norm_std = std / (std.rolling(200).max() + 1e-10)
        return (rank * norm_std).fillna(0)

    @staticmethod
    def _fisher_transform(close, length=13):
        high = close.rolling(length).max()
        low = close.rolling(length).min()
        val = 2 * ((close - low) / (high - low) - 0.5)
        val = np.clip(val, -0.999, 0.999)
        return 0.5 * np.log((1 + val) / (1 - val))

    @staticmethod
    def _add_swing_detection(df, window=5):
        window = max(3, int(window))
        right_side = window // 2
        pivot_high = df['high'].shift(right_side)
        pivot_low = df['low'].shift(right_side)
        rolling_high = df['high'].rolling(window, min_periods=window).max()
        rolling_low = df['low'].rolling(window, min_periods=window).min()

        df['swing_high_price'] = pivot_high
        df['is_swing_high'] = (
            pivot_high.eq(rolling_high)
            & pivot_high.gt(df['high'].shift(right_side + 1))
            & pivot_high.gt(df['high'].shift(right_side - 1))
        ).fillna(False)
        df['swing_low_price'] = pivot_low
        df['is_swing_low'] = (
            pivot_low.eq(rolling_low)
            & pivot_low.lt(df['low'].shift(right_side + 1))
            & pivot_low.lt(df['low'].shift(right_side - 1))
        ).fillna(False)
        # forward fill last swing prices
        last_high = None
        last_low = None
        vals_high = []
        vals_low = []
        for i in range(len(df)):
            if df.iloc[i]['is_swing_high']:
                last_high = df.iloc[i]['swing_high_price']
            if df.iloc[i]['is_swing_low']:
                last_low = df.iloc[i]['swing_low_price']
            vals_high.append(last_high)
            vals_low.append(last_low)
        df['last_swing_high'] = vals_high
        df['last_swing_low'] = vals_low
        df['last_swing'] = None
        last = None
        for i in range(len(df)):
            if df.iloc[i]['is_swing_high']:
                last = 'high'
            elif df.iloc[i]['is_swing_low']:
                last = 'low'
            df.iloc[i, df.columns.get_loc('last_swing')] = last
        df['last_swing'] = df['last_swing'].ffill()
        return df[['last_swing', 'last_swing_high', 'last_swing_low']]

    # ------------------------------------------------------------------
    # Populate Indicators (with higher‑timeframe data)
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata['pair']

        # -- 1h Data (HTF) --
        try:
            df_1h = self.dp.get_pair_dataframe(pair, '1h')
            if df_1h is not None and not df_1h.empty:
                df_1h['atr_1h'] = pta.atr(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
                for name, func in {
                    'kama': lambda close: self._kama(close, length=self.kama_length.value,
                                                     fast=self.kama_fast.value,
                                                     slow=self.kama_slow.value),
                    't3': lambda close: self._t3(close, length=self.t3_length.value,
                                                a=self.t3_factor.value),
                    'ehlers_it': lambda close: self._ehlers_it(close, alpha=self.ehlers_alpha.value)
                }.items():
                    df_1h[f'baseline_{name}_1h'] = func(df_1h['close'])
                    slope = (df_1h[f'baseline_{name}_1h'] - df_1h[f'baseline_{name}_1h'].shift(5)) / (5 * df_1h['atr_1h'])
                    df_1h[f'baseline_{name}_1h_slope'] = slope
                df_1h['fisher_1h'] = self._fisher_transform(df_1h['close'], length=self.fisher_length.value)
                cols = ['date'] + [f'baseline_{n}_1h_slope' for n in self.BASELINES] + ['fisher_1h']
                df_1h = df_1h[cols].rename(columns={'date': 'date_1h'})
                dataframe = pd.merge_asof(
                    dataframe.sort_values('date'),
                    df_1h.sort_values('date_1h'),
                    left_on='date', right_on='date_1h', direction='backward'
                )
                has_1h = True
            else:
                has_1h = False
        except Exception:
            has_1h = False

        # -- 15m Indicators --
        dataframe['atr'] = pta.atr(dataframe['high'], dataframe['low'], dataframe['close'], length=14)

        # Baseline lines & slopes on 15m (for entry signals; regime uses HTF if available)
        for name, func in {
            'kama': lambda close: self._kama(close, length=self.kama_length.value,
                                             fast=self.kama_fast.value,
                                             slow=self.kama_slow.value),
            't3': lambda close: self._t3(close, length=self.t3_length.value,
                                        a=self.t3_factor.value),
            'ehlers_it': lambda close: self._ehlers_it(close, alpha=self.ehlers_alpha.value)
        }.items():
            dataframe[f'baseline_{name}'] = func(dataframe['close'])
            slope = (dataframe[f'baseline_{name}'] - dataframe[f'baseline_{name}'].shift(5)) / (5 * dataframe['atr'])
            if has_1h:
                col_1h = f'baseline_{name}_1h_slope'
                if col_1h in dataframe.columns:
                    dataframe[f'baseline_{name}_slope'] = dataframe[col_1h]
                else:
                    dataframe[f'baseline_{name}_slope'] = slope
            else:
                dataframe[f'baseline_{name}_slope'] = slope

        # Fisher: regime uses HTF if available
        dataframe['fisher'] = self._fisher_transform(dataframe['close'], length=self.fisher_length.value)
        if has_1h and 'fisher_1h' in dataframe.columns:
            dataframe['fisher_regime'] = dataframe['fisher_1h']
        else:
            dataframe['fisher_regime'] = dataframe['fisher']

        # Trend detectors on 15m
        dataframe['trend_kama_slope'] = self._kama_slope(
            dataframe['close'],
            length=self.kama_length.value,
            fast=self.kama_fast.value,
            slow=self.kama_slow.value,
            slope_bars=self.kama_slope_bars.value
        )
        dataframe['trend_smma_ema_convergence'] = self._smma_ema_convergence(
            dataframe['close'],
            smma_len=self.smma_len.value,
            ema_lens=(self.ema_fast_len.value, self.ema_mid_len.value, self.ema_slow_len.value)
        )

        # Volatility index
        dataframe['vol_index'] = self._vol_index(
            dataframe['high'], dataframe['low'], dataframe['close'],
            t3_length=self.vola_t3_length.value,
            t3_factor=self.vola_t3_factor.value,
            percentile_window=self.vola_percentile_window.value,
            std_window=self.vola_std_window.value
        )

        # Extreme volume
        dataframe['extreme_vol'] = self._extreme_vol(
            dataframe['volume'],
            length=self.vol_length.value,
            t3_factor=self.vol_t3_factor.value,
            percentile_window=self.vol_percentile_window.value,
            std_window=self.vol_std_window.value
        )

        # RSI, MFI, WaveTrend
        dataframe['rsi'] = ta.RSI(dataframe['close'], timeperiod=self.rsi_period.value)
        dataframe['mfi'] = ta.MFI(dataframe['high'], dataframe['low'], dataframe['close'],
                                  dataframe['volume'], timeperiod=14)
        wt = pta.wavetrend(dataframe['high'], dataframe['low'], dataframe['close'],
                           length=self.wt_length.value, average_length=self.wt_avg_length.value)
        dataframe['wt1'] = wt['WT_1']
        dataframe['wt2'] = wt['WT_2']

        # Nadaraya‑Watson envelope (for mean reversion)
        nw = pta.nadaraya_watson(dataframe['high'], dataframe['low'], dataframe['close'],
                                 length=20, bandwidth=3.0)
        dataframe['nw_upper'] = nw['NW_UPPER']
        dataframe['nw_lower'] = nw['NW_LOWER']

        # VIX Fix + Bollinger Bands
        dataframe['vix_fix'] = 100 * (dataframe['close'].rolling(14).max() - dataframe['low']) / \
                               dataframe['close'].rolling(14).max()
        bb = pta.bbands(dataframe['vix_fix'], length=20, std=2)
        dataframe['vix_bb_upper'] = bb['BBU_20_2.0']
        dataframe['vix_bb_lower'] = bb['BBL_20_2.0']

        # Swing detection
        swing_df = self._add_swing_detection(dataframe, window=self.swing_window.value)
        dataframe['last_swing'] = swing_df['last_swing']
        dataframe['swing_high_price'] = swing_df['last_swing_high']
        dataframe['swing_low_price'] = swing_df['last_swing_low']

        return dataframe

    # ------------------------------------------------------------------
    # Regime Classification (24 regimes)
    def classify_regime(self, row, baseline_name):
        slope = row[f'baseline_{baseline_name}_slope']
        if abs(slope) < 0.1:
            trend = 'S'
        elif slope > 0:
            trend = 'U'
        else:
            trend = 'D'

        fisher_val = row.get('fisher_regime', row['fisher'])
        fisher_ext = abs(fisher_val) > self.fisher_extreme.value
        rsi_ext = (row['rsi'] < self.rsi_oversold.value) | (row['rsi'] > self.rsi_overbought.value)
        momentum = 'E' if (fisher_ext or rsi_ext) else 'N'

        volatility = 'H' if row['vol_index'] > self.vol_threshold.value else 'L'
        volume = 'H' if row['extreme_vol'] > self.extreme_vol_threshold.value else 'L'

        mapping = {
            ('U','E','L','L'):1, ('U','E','L','H'):2, ('U','E','H','L'):3, ('U','E','H','H'):4,
            ('U','N','L','L'):5, ('U','N','L','H'):6, ('U','N','H','L'):7, ('U','N','H','H'):8,
            ('D','E','L','L'):9, ('D','E','L','H'):10, ('D','E','H','L'):11, ('D','E','H','H'):12,
            ('D','N','L','L'):13, ('D','N','L','H'):14, ('D','N','H','L'):15, ('D','N','H','H'):16,
            ('S','E','L','L'):17, ('S','E','L','H'):18, ('S','E','H','L'):19, ('S','E','H','H'):20,
            ('S','N','L','L'):21, ('S','N','L','H'):22, ('S','N','H','L'):23, ('S','N','H','H'):24,
        }
        return mapping.get((trend, momentum, volatility, volume), 0)

    # ------------------------------------------------------------------
    # Strategy Pool – all six strategies
    @staticmethod
    def generate_signals_trend(df, params, strategy_obj):
        long_raw = (df['close'] > df['baseline']) & (df['fisher'] > 0) & (df['extreme_vol'] < 0.8)
        short_raw = (df['close'] < df['baseline']) & (df['fisher'] < 0) & (df['extreme_vol'] < 0.8)
        long = strategy_obj.filter_by_reward_risk(df, long_raw, 'long')
        short = strategy_obj.filter_by_reward_risk(df, short_raw, 'short')
        return pd.DataFrame({'enter_long': long.astype(int), 'enter_short': short.astype(int)})

    @staticmethod
    def generate_signals_momentum(df, params, strategy_obj):
        wt1 = df['wt1']; wt2 = df['wt2']; rsi = df['rsi']
        long_raw = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1)) & (rsi > 50)
        short_raw = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1)) & (rsi < 50)
        long_raw &= (df['extreme_vol'] < 0.8)
        short_raw &= (df['extreme_vol'] < 0.8)
        long = strategy_obj.filter_by_reward_risk(df, long_raw, 'long')
        short = strategy_obj.filter_by_reward_risk(df, short_raw, 'short')
        return pd.DataFrame({'enter_long': long.astype(int), 'enter_short': short.astype(int)})

    @staticmethod
    def generate_signals_breakout(df, params, strategy_obj):
        hh = df['high'].rolling(strategy_obj.breakout_window.value).max()
        ll = df['low'].rolling(strategy_obj.breakout_window.value).min()
        vol_ok = df['extreme_vol'] > 0.6
        vix_rising = df['vix_fix'] > df['vix_fix'].shift(5)
        long_raw = (df['close'] > hh.shift(1)) & vol_ok & vix_rising
        short_raw = (df['close'] < ll.shift(1)) & vol_ok & vix_rising
        long = strategy_obj.filter_by_reward_risk(df, long_raw, 'long')
        short = strategy_obj.filter_by_reward_risk(df, short_raw, 'short')
        return pd.DataFrame({'enter_long': long.astype(int), 'enter_short': short.astype(int)})

    @staticmethod
    def generate_signals_meanrev_nw(df, params, strategy_obj):
        upper = df['nw_upper']; lower = df['nw_lower']
        rsi = df['rsi']; mfi = df['mfi']
        long_raw = (df['low'] <= lower) & (rsi < strategy_obj.rsi_oversold.value) & (mfi < 20)
        short_raw = (df['high'] >= upper) & (rsi > strategy_obj.rsi_overbought.value) & (mfi > 80)
        long = strategy_obj.filter_by_reward_risk(df, long_raw, 'long')
        short = strategy_obj.filter_by_reward_risk(df, short_raw, 'short')
        return pd.DataFrame({'enter_long': long.astype(int), 'enter_short': short.astype(int)})

    @staticmethod
    def generate_signals_meanrev_extreme(df, params, strategy_obj):
        vix = df['vix_fix']; vix_upper = df['vix_bb_upper']; vix_lower = df['vix_bb_lower']
        cross_under = (vix < vix_upper) & (vix.shift(1) >= vix_upper.shift(1))
        cross_over = (vix > vix_lower) & (vix.shift(1) <= vix_lower.shift(1))
        extreme_vol = df['extreme_vol'] > 0.8
        reversal = cross_under | cross_over | extreme_vol
        last_swing = df['last_swing']
        long_raw = reversal & (last_swing == 'low')
        short_raw = reversal & (last_swing == 'high')
        long = strategy_obj.filter_by_reward_risk(df, long_raw, 'long')
        short = strategy_obj.filter_by_reward_risk(df, short_raw, 'short')
        return pd.DataFrame({'enter_long': long.astype(int), 'enter_short': short.astype(int)})

    @staticmethod
    def generate_signals_scalp_meanrev(df, params, strategy_obj):
        upper = df['nw_upper']; lower = df['nw_lower']; mfi = df['mfi']
        long_raw = (df['low'] <= lower) & (mfi < 15)
        short_raw = (df['high'] >= upper) & (mfi > 85)
        long = strategy_obj.filter_by_reward_risk(df, long_raw, 'long')
        short = strategy_obj.filter_by_reward_risk(df, short_raw, 'short')
        return pd.DataFrame({'enter_long': long.astype(int), 'enter_short': short.astype(int)})

    STRATEGIES = {
        'trend': generate_signals_trend,
        'momentum': generate_signals_momentum,
        'breakout': generate_signals_breakout,
        'meanrev_nw': generate_signals_meanrev_nw,
        'meanrev_extreme': generate_signals_meanrev_extreme,
        'scalp_meanrev': generate_signals_scalp_meanrev,
    }

    # ------------------------------------------------------------------
    # Reward/Risk filter
    def filter_by_reward_risk(self, df, signal, direction):
        if not signal.any():
            return signal
        mode = self.sl_tp_mode.value
        if mode == 'atr':
            atr = df['atr']
            risk = self.vol_mult_sl_atr * atr
            reward = self.vol_mult_tp1_atr * atr if direction == 'long' else self.vol_mult_tp1_atr * atr
            ratio = reward / risk
            valid = ratio >= self.min_reward_risk.value
        else:  # swing
            swing_low = df['swing_low_price']; swing_high = df['swing_high_price']
            atr = df['atr']
            if direction == 'long':
                sl = swing_low - 0.5 * atr
                tp = df['close'] + 0.5 * (swing_high - df['close'])
                risk = df['close'] - sl
                reward = tp - df['close']
            else:
                sl = swing_high + 0.5 * atr
                tp = df['close'] - 0.5 * (df['close'] - swing_low)
                risk = sl - df['close']
                reward = df['close'] - tp
            ratio = np.where(risk > 0, reward / risk, 0)
            valid = ratio >= self.min_reward_risk.value
        return signal & valid

    # ------------------------------------------------------------------
    # Money Management
    def custom_stoploss(self, pair: str, trade, current_time, current_rate, current_profit, **kwargs):
        atr_val = trade.get_custom_data('atr_entry')
        if atr_val is None:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                return 0.05
            atr_val = dataframe.iloc[-1].get('atr')
            if atr_val is None or pd.isna(atr_val):
                return 0.05
            trade.set_custom_data('atr_entry', atr_val)
        mode = self.sl_tp_mode.value
        if mode == 'swing':
            swing_low = trade.get_custom_data('swing_low_price')
            swing_high = trade.get_custom_data('swing_high_price')
            if swing_low is None or swing_high is None:
                mode = 'atr'
        entry = trade.open_rate
        if mode == 'atr':
            sl_dist = self.vol_mult_sl_atr * atr_val
            sl = entry + sl_dist if trade.is_short else entry - sl_dist
        else:
            if trade.is_short:
                sl = swing_high + 0.5 * atr_val
            else:
                sl = swing_low - 0.5 * atr_val

        if trade.get_custom_data('tp1_hit'):
            sl = entry
        if trade.get_custom_data('tp2_hit'):
            tp1_move = self._get_tp1_move(trade, atr_val, mode)
            sl = entry + (1 if trade.is_short else -1) * tp1_move
        if trade.get_custom_data('tp2_hit'):
            trail_off = 0.5 * atr_val
            if trade.is_short:
                sl = min(sl, current_rate + trail_off)
            else:
                sl = max(sl, current_rate - trail_off)
        return stoploss_from_absolute(
            sl,
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def _get_tp1_move(self, trade, atr_val, mode):
        if mode == 'atr':
            return self.vol_mult_tp1_atr * atr_val
        else:
            swing_low = trade.get_custom_data('swing_low_price')
            swing_high = trade.get_custom_data('swing_high_price')
            if trade.is_short:
                return trade.open_rate - (trade.open_rate - 0.5 * (trade.open_rate - swing_low))
            else:
                return (trade.open_rate + 0.5 * (swing_high - trade.open_rate)) - trade.open_rate

    def adjust_trade_position(self, trade, current_time, current_rate, current_profit, **kwargs):
        atr_val = trade.get_custom_data('atr_entry')
        if atr_val is None:
            return None
        mode = self.sl_tp_mode.value
        if mode == 'swing':
            swing_low = trade.get_custom_data('swing_low_price')
            swing_high = trade.get_custom_data('swing_high_price')
            if swing_low is None or swing_high is None:
                mode = 'atr'

        entry = trade.open_rate
        if mode == 'atr':
            tp1 = entry + (self.vol_mult_tp1_atr * atr_val if not trade.is_short else -self.vol_mult_tp1_atr * atr_val)
            tp2 = entry + (self.vol_mult_tp2_atr * atr_val if not trade.is_short else -self.vol_mult_tp2_atr * atr_val)
            tp3 = entry + (self.vol_mult_tp3_atr * atr_val if not trade.is_short else -self.vol_mult_tp3_atr * atr_val)
        else:
            if trade.is_short:
                tp1 = entry - 0.5 * (entry - swing_low)
                tp2 = swing_low
                tp3 = swing_low - 1.0 * atr_val
            else:
                tp1 = entry + 0.5 * (swing_high - entry)
                tp2 = swing_high
                tp3 = swing_high + 1.0 * atr_val

        if not trade.get_custom_data('tp1_hit') and \
           ((not trade.is_short and current_rate >= tp1) or (trade.is_short and current_rate <= tp1)):
            trade.set_custom_data('tp1_hit', True)
            return - (trade.stake_amount * 0.5)
        elif trade.get_custom_data('tp1_hit') and not trade.get_custom_data('tp2_hit') and \
             ((not trade.is_short and current_rate >= tp2) or (trade.is_short and current_rate <= tp2)):
            trade.set_custom_data('tp2_hit', True)
            return - (trade.stake_amount * 0.25)
        elif trade.get_custom_data('tp2_hit') and not trade.get_custom_data('tp3_hit') and \
             ((not trade.is_short and current_rate >= tp3) or (trade.is_short and current_rate <= tp3)):
            trade.set_custom_data('tp3_hit', True)
            return - (trade.stake_amount * 0.25)
        return None

    def custom_entry_price(self, pair, current_time, proposal, **kwargs):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is not None and not dataframe.empty:
            trade = kwargs.get('trade', None)
            if trade:
                last_row = dataframe.iloc[-1]
                trade.set_custom_data('atr_entry', last_row['atr'])
                trade.set_custom_data('swing_low_price', last_row.get('swing_low_price'))
                trade.set_custom_data('swing_high_price', last_row.get('swing_high_price'))
        return proposal

    # ------------------------------------------------------------------
    # Walk‑Forward Optimizer
    def optimize(self, dataframe: pd.DataFrame) -> None:
        df = dataframe.iloc[-self.backtest_window:].copy()
        if len(df) < 200:
            return
        best_map = {}
        for b_name in self.BASELINES.keys():
            baseline_col = f'baseline_{b_name}'
            df['baseline'] = df[baseline_col]
            df['temp_regime'] = df.apply(lambda r: self.classify_regime(r, b_name), axis=1)
            for t_name in self.TREND_DETECTORS.keys():
                trend_col = f'trend_{t_name}'
                df['trend_strength'] = df[trend_col]
                for s_name in self.STRATEGIES.keys():
                    strat_func = self.STRATEGIES[s_name]
                    for regime_id in range(1, 25):
                        mask = df['temp_regime'] == regime_id
                        regime_df = df[mask]
                        if len(regime_df) < 30:
                            continue
                        pf = self._backtest_strategy(regime_df, strat_func)
                        key = (regime_id, b_name, t_name, s_name)
                        if pf > best_map.get(regime_id, (-1,))[0]:
                            best_map[regime_id] = (pf, b_name, t_name, s_name)

        new_map = {}
        for regime_id, (pf, b_name, t_name, s_name) in best_map.items():
            new_map[regime_id] = {
                'baseline': b_name,
                'trend_detector': t_name,
                'strategy': s_name,
                'profit_factor': pf
            }
            logger.info(f"Regime {regime_id}: best={b_name}/{t_name}/{s_name}, PF={pf:.2f}")
        self.regime_strategy_map = new_map

    def _backtest_strategy(self, df, strat_func, params=None):
        signals = strat_func(df, params, self)
        profit = 0.0
        loss = 0.0
        for idx in df.index[signals['enter_long'] | signals['enter_short']]:
            if signals.at[idx, 'enter_long']:
                tp = df.at[idx, 'close'] + df.at[idx, 'atr'] * self.vol_mult_tp1_atr
                sl = df.at[idx, 'close'] - df.at[idx, 'atr'] * self.vol_mult_sl_atr
                future = df.loc[idx+1:idx+10]
                if future.empty: continue
                if any(future['high'] >= tp):
                    profit += df.at[idx, 'atr'] * self.vol_mult_tp1_atr
                elif any(future['low'] <= sl):
                    loss += df.at[idx, 'atr'] * self.vol_mult_sl_atr
            elif signals.at[idx, 'enter_short']:
                tp = df.at[idx, 'close'] - df.at[idx, 'atr'] * self.vol_mult_tp1_atr
                sl = df.at[idx, 'close'] + df.at[idx, 'atr'] * self.vol_mult_sl_atr
                future = df.loc[idx+1:idx+10]
                if future.empty: continue
                if any(future['low'] <= tp):
                    profit += df.at[idx, 'atr'] * self.vol_mult_tp1_atr
                elif any(future['high'] >= sl):
                    loss += df.at[idx, 'atr'] * self.vol_mult_sl_atr
        if loss == 0:
            return 99.0 if profit > 0 else 0.0
        return profit / loss

    def bot_loop_start(self, **kwargs) -> None:
        if self.dp is None:
            return
        pairs = self.dp.current_whitelist()
        if not pairs:
            return
        pair = pairs[0]
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return
        last_date = dataframe.iloc[-1]['date']
        if self.last_optimization_bar is not None:
            elapsed = len(dataframe[dataframe['date'] >= self.last_optimization_bar])
        else:
            elapsed = len(dataframe)
        if elapsed >= self.optimization_interval:
            self.last_optimization_bar = last_date
            self.optimize(dataframe)

    # ------------------------------------------------------------------
    # Entry Signal Generation
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0

        if not self.regime_strategy_map:
            default = {'baseline': 'kama', 'trend_detector': 'kama_slope', 'strategy': 'trend'}
            for rid in range(1, 25):
                self.regime_strategy_map[rid] = default

        for regime_id, mapping in self.regime_strategy_map.items():
            mask = self._get_regime_mask(dataframe, regime_id, mapping)
            if not mask.any():
                continue
            strat_name = mapping['strategy']
            strat_func = self.STRATEGIES[strat_name]
            sub_df = dataframe.loc[mask].copy()
            sub_df['baseline'] = sub_df[f"baseline_{mapping['baseline']}"]
            signals = strat_func(sub_df, None, self)
            dataframe.loc[mask, 'enter_long'] = signals['enter_long'].values
            dataframe.loc[mask, 'enter_short'] = signals['enter_short'].values
        return dataframe

    def _get_regime_mask(self, df, regime_id, mapping):
        baseline_name = mapping['baseline']
        regime_series = df.apply(lambda r: self.classify_regime(r, baseline_name), axis=1)
        return regime_series == regime_id
