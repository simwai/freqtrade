import numpy as np
import pandas as pd

import talib.abstract as ta
from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter, merge_informative_pair


class HybridRegimeSwitcher(IStrategy):
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count: int = 250

    # --- HYPERPARAMETERS (Optimize these) ---
    # Regime thresholds
    chop_trend_threshold = IntParameter(30, 45, default=38, space="buy")
    chop_range_threshold = IntParameter(55, 70, default=62, space="buy")

    # Mean Reversion parameters
    mr_zscore = DecimalParameter(-2.5, -1.0, default=-1.5, space="buy")
    mr_mfi = IntParameter(40, 60, default=50, space="buy")

    # Trend Following parameters
    tf_rls_slope = DecimalParameter(0.2, 0.8, default=0.4, space="buy")
    tf_zscore_limit = DecimalParameter(-0.5, 0.5, default=0.0, space="buy")

    # Safety
    vol_limit = DecimalParameter(1.5, 2.0, default=1.8, space="buy")
    rls_alpha = DecimalParameter(0.90, 0.99, default=0.95, space="buy")

    # --- RISK (Shared across both modules) ---
    stoploss = -0.015
    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.006
    trailing_only_offset_is_reached = True

    minimal_roi = {
        "0": 0.02,
        "15": 0.01,
        "30": 0.005,
        "60": 0,
    }

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

    # ================================================================
    # INDICATORS (Shared Core)
    # ================================================================
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # --- 1. RLS Adaptive Mean (Core Engine) ---
        alpha = self.rls_alpha.value
        dataframe["rls_mean"] = dataframe["close"].ewm(alpha=1 - alpha, adjust=False).mean()
        dataframe["rls_slope"] = dataframe["rls_mean"] - dataframe["rls_mean"].shift(3)

        # --- 2. EWMA Z-Score (Shared Trigger) ---
        lookback = 20
        dataframe["ema_price"] = dataframe["close"].ewm(span=lookback, adjust=False).mean()
        dataframe["ema_std"] = dataframe["close"].ewm(span=lookback, adjust=False).std()
        dataframe["z_score"] = (dataframe["close"] - dataframe["ema_price"]) / (
            dataframe["ema_std"] + 1e-8
        )

        # --- 3. ATR (Volatility Safety & Choppiness) ---
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["vol_ratio"] = dataframe["atr"] / dataframe["atr"].rolling(50).mean()

        # --- 4. CHOPPINESS INDEX (The Regime Decider) ---
        atr_sum = dataframe["atr"].rolling(14).sum()
        high_low_range = dataframe["high"].rolling(14).max() - dataframe["low"].rolling(14).min()
        dataframe["chop"] = (
            100 * np.log10(atr_sum / (high_low_range + 1e-8)) / np.log10(14)
        )

        # --- 5. 1H MFI (Higher timeframe flow) ---
        if self.dp:
            informative_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
            informative_1h["mfi_1h"] = self.calc_mfi(informative_1h)

            # jdehorty-style MTF momentum: 1h PPO + signal
            ema_f = ta.EMA(informative_1h, timeperiod=12)
            ema_s = ta.EMA(informative_1h, timeperiod=26)
            informative_1h["ppo_1h"] = 100 * (ema_f - ema_s) / ema_s
            informative_1h["ppo_signal_1h"] = ta.EMA(
                informative_1h, timeperiod=9, price="ppo_1h"
            )

            # LuxAlgo VWAP anchor on 1h
            pv = informative_1h["close"] * informative_1h["volume"]
            informative_1h["vwap_1h"] = (
                pv.rolling(24).sum() / informative_1h["volume"].rolling(24).sum()
            )

            informative_1h = informative_1h[
                ["date", "mfi_1h", "ppo_1h", "ppo_signal_1h", "vwap_1h"]
            ].rename(columns={"date": "date_inf"})
            dataframe = merge_informative_pair(
                dataframe,
                informative_1h,
                self.timeframe,
                "1h",
                ffill=True,
                date_column="date_inf",
            )
            dataframe["mfi_1h"] = dataframe["mfi_1h_1h"].ffill()
            dataframe["ppo_1h"] = dataframe["ppo_1h_1h"].ffill()
            dataframe["ppo_signal_1h"] = dataframe["ppo_signal_1h_1h"].ffill()
            dataframe["vwap_1h"] = dataframe["vwap_1h_1h"].ffill()

        # --- 6. Liquidity sweep levels (algoalpha / LuxAlgo SMC) ---
        dataframe["prior_low"] = dataframe["low"].shift(1).rolling(20).min()
        dataframe["prior_high"] = dataframe["high"].shift(1).rolling(20).max()

        return dataframe

    # ================================================================
    # ENTRY LOGIC (The Regime Switch)
    # ================================================================
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # --- SAFETY OVERRIDE (Sit out chaos) ---
        safe_vol = dataframe["vol_ratio"] < self.vol_limit.value

        # --- REGIME DETECTION ---
        is_trending = dataframe["chop"] < self.chop_trend_threshold.value
        is_ranging = dataframe["chop"] > self.chop_range_threshold.value

        # --- HIGHER TIMEFRAME CONFIRMATION (jdehorty) ---
        htf_bull = (
            (dataframe["ppo_1h"] > 0)
            & (dataframe["ppo_1h"] > dataframe["ppo_signal_1h"])
            & (dataframe["close"] > dataframe["vwap_1h"])
        )
        # 1h not in freefall (used to keep MR buys off falling knives)
        htf_not_crashing = dataframe["ppo_1h"] > -4

        # --- MODULE A: MEAN REVERSION (Deployed in Ranging Markets) ---
        # Liquidity sweep of prior 20-bar low + reclaim of the RLS mean
        mr_sweep = (
            (dataframe["low"] < dataframe["prior_low"])
            & (dataframe["close"] > dataframe["rls_mean"])
        )
        mr_entry = (
            is_ranging
            & htf_not_crashing
            & (dataframe["z_score"] < self.mr_zscore.value)
            & (dataframe["mfi_1h"] > self.mr_mfi.value)
            & (dataframe["rls_slope"] > -0.1)  # Not in a severe freefall
            & (mr_sweep | (dataframe["z_score"] < self.mr_zscore.value * 1.3))
        )

        # --- MODULE B: TREND FOLLOWING (Deployed in Trending Markets) ---
        # Momentum + pullback into a rising mean, confirmed by 1h PPO/VWAP
        tf_entry = (
            is_trending
            & htf_bull
            & (dataframe["rls_slope"] > self.tf_rls_slope.value)  # Strong momentum
            & (dataframe["rls_mean"] > dataframe["rls_mean"].shift(3))  # Mean is rising
            & (dataframe["close"] > dataframe["rls_mean"])  # Above the mean
            & (dataframe["low"] <= dataframe["rls_mean"])  # Retesting the mean (pullback)
            & (dataframe["z_score"] > self.tf_zscore_limit.value)  # Not oversold
        )

        # --- NEUTRAL ZONE (38 < Chop < 62): deep oversold + sweep only ---
        neutral_entry = (
            (~is_trending)
            & (~is_ranging)
            & htf_not_crashing
            & (dataframe["low"] < dataframe["prior_low"])
            & (dataframe["close"] > dataframe["rls_mean"])
            & (dataframe["z_score"] < -2.0)  # Must be extremely oversold
            & (dataframe["mfi_1h"] > 55)
        )

        # --- FINAL ENTRY ---
        dataframe.loc[
            (safe_vol) & (mr_entry | tf_entry | neutral_entry),
            "enter_long",
        ] = 1

        return dataframe

    def calc_mfi(self, df, period=14):
        tp = (df["high"] + df["low"] + df["close"]) / 3
        raw_mf = tp * df["volume"]
        pos_flow = raw_mf.where(tp > tp.shift(1), 0).rolling(period).sum()
        neg_flow = raw_mf.where(tp < tp.shift(1), 0).rolling(period).sum()
        ratio = pos_flow / (neg_flow + 1e-8)
        return 100 - (100 / (1 + ratio))

    # ================================================================
    # EXIT LOGIC (Adaptive to Regime)
    # ================================================================
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Exit if volatility explodes (safety)
        vol_exit = dataframe["vol_ratio"] > 2.0

        # Exit if Z-Score returns to mean (mean reversion exit)
        mr_exit = dataframe["z_score"] > 0

        # Exit if trend dies (trend following exit)
        tf_exit = dataframe["rls_slope"] < 0

        # Unified exit: If price closes below RLS mean in a trending regime
        # (MR entries live below the mean by construction, so never exit them here)
        is_trending = dataframe["chop"] < self.chop_trend_threshold.value
        breakdown = (dataframe["close"] < dataframe["rls_mean"]) & is_trending

        dataframe.loc[(vol_exit) | (mr_exit) | (tf_exit) | (breakdown), "exit_long"] = 1
        # Never exit on the same candle a new entry is signalled (freqtrade would reject the entry)
        if "enter_long" in dataframe.columns:
            dataframe.loc[dataframe["enter_long"] == 1, "exit_long"] = 0
        return dataframe

    # ================================================================
    # DYNAMIC POSITION SIZING
    # ================================================================
    def custom_stake_amount(
        self,
        pair: str,
        current_time: pd.Timestamp,
        current_rate: float,
        proposed_stake: float,
        min_stake: float,
        max_stake: float,
        entry_tag: str,
        side: str,
        **kwargs,
    ) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) > 0:
            vol_ratio = dataframe["vol_ratio"].iloc[-1]
            if vol_ratio > 1.5:
                return proposed_stake * 0.5
            if vol_ratio > 1.2:
                return proposed_stake * 0.75
        return proposed_stake
