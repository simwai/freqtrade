"""GKD Adaptive Academic Final strategy.

The strategy uses a T3 price baseline, a signed KAMA slope trend detector,
causal 1h confirmation, and a regime-specific strategy variant selected from
a frozen regime map. Indicator parameters are tuned by freqtrade's built-in
walk-forward optimization.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as pta
import talib.abstract as ta
from pandas.errors import MergeError

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
)


logger = logging.getLogger(__name__)

REGIME_MAP_FILE = Path(__file__).resolve().parent / "regime_map_academic.json"


class GKDAdaptiveAcademicFinal(IStrategy):
    """T3/KAMA adaptive strategy with 12 market regimes."""

    INTERFACE_VERSION = 3
    timeframe = "15m"
    startup_candle_count = 250
    can_short = True

    # ROI is intentionally disabled. Exits are managed by the custom stop and
    # the three partial profit targets.
    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_custom_stoploss = True
    use_exit_signal = False
    position_adjustment_enable = True

    vol_mult_sl_atr = 1.5
    vol_mult_tp1_atr = 1.0
    vol_mult_tp2_atr = 2.0
    vol_mult_tp3_atr = 3.0

    regime_strategy_map: dict[int, str] = {}

    # Hyperopt parameters.
    t3_length = IntParameter(3, 20, default=5, space="buy")
    t3_factor = DecimalParameter(0.3, 0.8, default=0.618, space="buy")

    kama_slope_length = IntParameter(5, 50, default=10, space="buy")
    kama_slope_fast = IntParameter(2, 10, default=2, space="buy")
    kama_slope_slow = IntParameter(20, 50, default=30, space="buy")
    kama_slope_bars = IntParameter(2, 10, default=5, space="buy")

    fisher_length = IntParameter(9, 20, default=13, space="buy")
    rsi_period = IntParameter(2, 20, default=14, space="buy")
    mfi_period = IntParameter(10, 20, default=14, space="buy")
    wt_length = IntParameter(5, 15, default=10, space="buy")
    wt_avg_length = IntParameter(15, 30, default=21, space="buy")

    fisher_extreme = DecimalParameter(1.5, 3.5, default=2.5, space="buy")
    rsi_oversold = IntParameter(20, 35, default=30, space="buy")
    rsi_overbought = IntParameter(65, 80, default=70, space="buy")

    vol_t3_length = IntParameter(5, 20, default=14, space="buy")
    vol_t3_factor = DecimalParameter(0.3, 0.8, default=0.618, space="buy")

    vol_vol_t3_length = IntParameter(5, 20, default=14, space="buy")
    vol_vol_t3_factor = DecimalParameter(0.3, 0.8, default=0.618, space="buy")
    vol_vol_z_window = IntParameter(50, 200, default=100, space="buy")
    vol_z_threshold = DecimalParameter(0.5, 2.5, default=1.5, space="buy")

    ob_body_ratio = DecimalParameter(3.0, 7.0, default=5.0, space="buy")
    min_reward_risk = DecimalParameter(1.0, 3.0, default=1.5, space="buy")
    swing_window = IntParameter(3, 10, default=5, space="buy")

    use_htf_trend = CategoricalParameter(
        ["true", "false"],
        default="true",
        space="buy",
    )

    @staticmethod
    def _t3(close: pd.Series, length: int = 5, a: float = 0.618) -> pd.Series:
        return pta.t3(close, length=length, a=a)

    @staticmethod
    def _kama_slope(
        close: pd.Series,
        length: int = 10,
        fast: int = 2,
        slow: int = 30,
        slope_bars: int = 5,
    ) -> pd.Series:
        kama = pta.kama(close, length=length, fast=fast, slow=slow)
        atr14 = pta.atr(
            high=close * 1.0001,
            low=close * 0.9999,
            close=close,
            length=14,
        )
        denominator = (slope_bars * atr14).replace(0, np.nan)
        slope = (kama - kama.shift(slope_bars)) / denominator
        return (slope / 0.03).replace([np.inf, -np.inf], np.nan).clip(-1.0, 1.0)

    @staticmethod
    def _fisher(close: pd.Series, length: int = 13) -> pd.Series:
        high = close.rolling(length, min_periods=length).max()
        low = close.rolling(length, min_periods=length).min()
        price_range = (high - low).replace(0, np.nan)
        value = 2 * ((close - low) / price_range - 0.5)
        value = value.clip(-0.999, 0.999)
        return 0.5 * np.log((1 + value) / (1 - value))

    @staticmethod
    def _volume_zscore(
        volume: pd.Series,
        t3_length: int,
        t3_factor: float,
        z_window: int,
    ) -> pd.Series:
        t3_volume = pta.t3(volume, length=t3_length, a=t3_factor)
        mean = t3_volume.rolling(z_window, min_periods=z_window).mean()
        std = t3_volume.rolling(z_window, min_periods=z_window).std().replace(0, np.nan)
        return ((t3_volume - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    @staticmethod
    def _wavetrend(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        length: int,
        average_length: int,
    ) -> tuple[pd.Series, pd.Series]:
        """Causal WaveTrend implementation for pandas-ta versions without it."""
        average_price = (high + low + close) / 3.0
        esa = average_price.ewm(
            span=length,
            adjust=False,
            min_periods=length,
        ).mean()
        deviation = (average_price - esa).abs().ewm(
            span=length,
            adjust=False,
            min_periods=length,
        ).mean()
        channel_index = (average_price - esa) / (0.015 * deviation.replace(0, np.nan))
        wt1 = channel_index.ewm(
            span=average_length,
            adjust=False,
            min_periods=average_length,
        ).mean()
        wt2 = wt1.rolling(4, min_periods=4).mean()
        return wt1, wt2

    @staticmethod
    def _nadaraya_watson(
        close: pd.Series,
        length: int = 20,
        bandwidth: float = 3.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Causal Gaussian envelope used when pandas-ta has no NW helper."""
        offsets = np.arange(length - 1, -1, -1, dtype=float)
        weights = np.exp(-(offsets**2) / (2 * bandwidth**2))
        weights /= weights.sum()

        def weighted_average(values: np.ndarray) -> float:
            return float(np.dot(values, weights))

        center = close.rolling(length, min_periods=length).apply(weighted_average, raw=True)
        mean_absolute_error = (close - center).abs().rolling(length, min_periods=length).mean()
        upper = center + 3.0 * mean_absolute_error
        lower = center - 3.0 * mean_absolute_error
        return center, upper, lower

    @staticmethod
    def _add_swing_detection(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
        """Confirm pivots only after the right-hand candles have closed."""
        window = max(3, int(window))
        right_side = window // 2

        pivot_high = df["high"].shift(right_side)
        pivot_low = df["low"].shift(right_side)
        rolling_high = df["high"].rolling(window, min_periods=window).max()
        rolling_low = df["low"].rolling(window, min_periods=window).min()

        is_swing_high = (
            pivot_high.eq(rolling_high)
            & pivot_high.gt(df["high"].shift(right_side + 1))
            & pivot_high.gt(df["high"].shift(right_side - 1))
        ).fillna(False)
        is_swing_low = (
            pivot_low.eq(rolling_low)
            & pivot_low.lt(df["low"].shift(right_side + 1))
            & pivot_low.lt(df["low"].shift(right_side - 1))
        ).fillna(False)

        df["swing_high_price"] = pivot_high.where(is_swing_high)
        df["is_swing_high"] = is_swing_high.astype(bool)
        df["swing_low_price"] = pivot_low.where(is_swing_low)
        df["is_swing_low"] = is_swing_low.astype(bool)
        df["last_swing_high"] = df["swing_high_price"].ffill()
        df["last_swing_low"] = df["swing_low_price"].ffill()
        return df

    def detect_obs(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """Detect causal price-action order blocks without a volume filter."""
        df = dataframe.copy()
        body_ratio = self.ob_body_ratio.value

        previous_open = df["open"].shift(1)
        previous_close = df["close"].shift(1)
        current_body = df["close"] - df["open"]
        previous_red_body = previous_open - previous_close
        previous_green_body = previous_close - previous_open

        bullish_ob = (
            (previous_open > previous_close)
            & (df["open"] < df["close"])
            & (current_body > body_ratio * previous_red_body)
            & (previous_red_body > 0)
        )
        bearish_ob = (
            (previous_open < previous_close)
            & (df["open"] > df["close"])
            & ((df["open"] - df["close"]) > body_ratio * previous_green_body)
            & (previous_green_body > 0)
        )

        # An order block becomes available from the next closed candle.
        bull_top = pd.Series(
            np.where(bullish_ob, previous_open, np.nan), index=df.index
        ).shift(1)
        bull_bottom = pd.Series(
            np.where(bullish_ob, np.minimum(previous_close, df["open"]), np.nan),
            index=df.index,
        ).shift(1)
        bear_top = pd.Series(
            np.where(bearish_ob, np.maximum(df["open"], previous_close), np.nan),
            index=df.index,
        ).shift(1)
        bear_bottom = pd.Series(
            np.where(bearish_ob, previous_open, np.nan), index=df.index
        ).shift(1)

        active_bull_top: float | None = None
        active_bull_bottom: float | None = None
        active_bear_top: float | None = None
        active_bear_bottom: float | None = None
        bull_tops: list[float | None] = []
        bull_bottoms: list[float | None] = []
        bear_tops: list[float | None] = []
        bear_bottoms: list[float | None] = []

        closes = df["close"].to_numpy(dtype=float)
        for position in range(len(df)):
            if active_bull_top is not None and position >= 2:
                rejected = (
                    closes[position - 2] < active_bull_bottom
                    and closes[position - 1] > active_bull_top
                    and closes[position] > active_bull_top
                )
                if rejected:
                    active_bull_top = None
                    active_bull_bottom = None

            if active_bear_top is not None and position >= 2:
                rejected = (
                    closes[position - 2] > active_bear_top
                    and closes[position - 1] < active_bear_bottom
                    and closes[position] < active_bear_bottom
                )
                if rejected:
                    active_bear_top = None
                    active_bear_bottom = None

            if pd.notna(bull_top.iloc[position]):
                active_bull_top = float(bull_top.iloc[position])
                active_bull_bottom = float(bull_bottom.iloc[position])
            if pd.notna(bear_top.iloc[position]):
                active_bear_top = float(bear_top.iloc[position])
                active_bear_bottom = float(bear_bottom.iloc[position])

            bull_tops.append(active_bull_top)
            bull_bottoms.append(active_bull_bottom)
            bear_tops.append(active_bear_top)
            bear_bottoms.append(active_bear_bottom)

        df["bull_top"] = bull_top
        df["bull_bottom"] = bull_bottom
        df["bear_top"] = bear_top
        df["bear_bottom"] = bear_bottom
        df["ob_bull_top"] = bull_tops
        df["ob_bull_bottom"] = bull_bottoms
        df["ob_bear_top"] = bear_tops
        df["ob_bear_bottom"] = bear_bottoms
        return df

    def informative_pairs(self) -> list[tuple[str, str]]:
        pairs = self.config.get("exchange", {}).get("pair_whitelist", [])
        return [(pair, "1h") for pair in pairs]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe = dataframe.copy().sort_values("date").reset_index(drop=True)
        pair = metadata.get("pair", "")
        has_htf = False

        # The 1h candle timestamp is moved to its close before merging. This
        # prevents the still-forming 1h candle from leaking into 15m signals.
        try:
            dp = getattr(self, "dp", None)
            dataframe_1h = dp.get_pair_dataframe(pair, "1h") if dp is not None else None
            if dataframe_1h is not None and not dataframe_1h.empty:
                dataframe_1h = dataframe_1h.copy().sort_values("date")
                dataframe_1h["atr_1h"] = pta.atr(
                    dataframe_1h["high"],
                    dataframe_1h["low"],
                    dataframe_1h["close"],
                    length=14,
                )
                dataframe_1h["t3_1h"] = self._t3(
                    dataframe_1h["close"],
                    length=self.t3_length.value,
                    a=self.t3_factor.value,
                )
                dataframe_1h["t3_slope_htf"] = (
                    dataframe_1h["t3_1h"] - dataframe_1h["t3_1h"].shift(5)
                ) / (5 * dataframe_1h["atr_1h"].replace(0, np.nan))
                dataframe_1h["kama_slope_1h"] = self._kama_slope(
                    dataframe_1h["close"],
                    length=self.kama_slope_length.value,
                    fast=self.kama_slope_fast.value,
                    slow=self.kama_slope_slow.value,
                    slope_bars=self.kama_slope_bars.value,
                )
                dataframe_1h["fisher_1h"] = self._fisher(
                    dataframe_1h["close"], length=self.fisher_length.value
                )
                dataframe_1h["vol_zscore_1h"] = self._volume_zscore(
                    dataframe_1h["volume"],
                    t3_length=self.vol_vol_t3_length.value,
                    t3_factor=self.vol_vol_t3_factor.value,
                    z_window=self.vol_vol_z_window.value,
                )
                dataframe_1h = self.detect_obs(dataframe_1h)
                informative = dataframe_1h[
                    [
                        "date",
                        "t3_slope_htf",
                        "kama_slope_1h",
                        "fisher_1h",
                        "vol_zscore_1h",
                        "ob_bull_top",
                        "ob_bull_bottom",
                        "ob_bear_top",
                        "ob_bear_bottom",
                    ]
                ].copy()
                informative["date"] = informative["date"] + pd.Timedelta(hours=1)
                informative = informative.rename(columns={"date": "date_1h"})
                dataframe = pd.merge_asof(
                    dataframe.sort_values("date"),
                    informative.sort_values("date_1h"),
                    left_on="date",
                    right_on="date_1h",
                    direction="backward",
                )
                has_htf = True
        except (AttributeError, KeyError, MergeError, OSError, TypeError, ValueError) as error:
            logger.debug("Unable to load 1h data for %s: %s", pair, error)

        true_range = pta.true_range(dataframe["high"], dataframe["low"], dataframe["close"])
        dataframe["atr"] = pta.t3(
            true_range,
            length=self.vol_t3_length.value,
            a=self.vol_t3_factor.value,
        )
        dataframe["t3"] = self._t3(
            dataframe["close"], length=self.t3_length.value, a=self.t3_factor.value
        )
        dataframe["fisher"] = self._fisher(
            dataframe["close"], length=self.fisher_length.value
        )
        dataframe["trend_kama_slope"] = self._kama_slope(
            dataframe["close"],
            length=self.kama_slope_length.value,
            fast=self.kama_slope_fast.value,
            slow=self.kama_slope_slow.value,
            slope_bars=self.kama_slope_bars.value,
        )
        dataframe["volume_zscore"] = self._volume_zscore(
            dataframe["volume"],
            t3_length=self.vol_vol_t3_length.value,
            t3_factor=self.vol_vol_t3_factor.value,
            z_window=self.vol_vol_z_window.value,
        )
        dataframe["rsi"] = ta.RSI(
            dataframe["close"], timeperiod=int(self.rsi_period.value)
        )
        dataframe["mfi"] = ta.MFI(
            dataframe["high"],
            dataframe["low"],
            dataframe["close"],
            dataframe["volume"],
            timeperiod=int(self.mfi_period.value),
        )
        dataframe["wt1"], dataframe["wt2"] = self._wavetrend(
            dataframe["high"],
            dataframe["low"],
            dataframe["close"],
            length=self.wt_length.value,
            average_length=self.wt_avg_length.value,
        )
        (
            dataframe["nw_center"],
            dataframe["nw_upper"],
            dataframe["nw_lower"],
        ) = self._nadaraya_watson(dataframe["close"])
        dataframe = self._add_swing_detection(dataframe, window=self.swing_window.value)

        dataframe["t3_slope_15m"] = (
            dataframe["t3"] - dataframe["t3"].shift(5)
        ) / (5 * dataframe["atr"].replace(0, np.nan))

        if self.use_htf_trend.value == "true" and has_htf:
            dataframe["trend_slope"] = dataframe["kama_slope_1h"].combine_first(
                dataframe["trend_kama_slope"]
            )
            dataframe["t3_slope"] = dataframe["t3_slope_htf"].combine_first(
                dataframe["t3_slope_15m"]
            )
        else:
            dataframe["trend_slope"] = dataframe["trend_kama_slope"]
            dataframe["t3_slope"] = dataframe["t3_slope_15m"]

        if not has_htf:
            dataframe["fisher_1h"] = dataframe["fisher"]
            dataframe["vol_zscore_1h"] = dataframe["volume_zscore"]

        return dataframe

    def classify_regime(self, row: pd.Series) -> int:
        slope = row.get("trend_slope", row.get("t3_slope", np.nan))
        fisher_value = row.get("fisher_1h", row.get("fisher", np.nan))
        volume_zscore = row.get("vol_zscore_1h", row.get("volume_zscore", np.nan))
        rsi = row.get("rsi", np.nan)

        if any(pd.isna(value) for value in (slope, fisher_value, volume_zscore, rsi)):
            return 0

        trend = "S" if abs(slope) < 0.1 else ("U" if slope > 0 else "D")
        momentum = "E" if (
            abs(fisher_value) > self.fisher_extreme.value
            or rsi < self.rsi_oversold.value
            or rsi > self.rsi_overbought.value
        ) else "N"
        volume = "H" if volume_zscore > self.vol_z_threshold.value else "L"

        mapping = {
            ("U", "E", "L"): 1,
            ("U", "E", "H"): 2,
            ("U", "N", "L"): 3,
            ("U", "N", "H"): 4,
            ("D", "E", "L"): 5,
            ("D", "E", "H"): 6,
            ("D", "N", "L"): 7,
            ("D", "N", "H"): 8,
            ("S", "E", "L"): 9,
            ("S", "E", "H"): 10,
            ("S", "N", "L"): 11,
            ("S", "N", "H"): 12,
        }
        return mapping.get((trend, momentum, volume), 0)

    def signal_trend_fisher(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (
            (df["close"] > df["t3"])
            & (df["fisher"] > 0)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        short = (
            (df["close"] < df["t3"])
            & (df["fisher"] < 0)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        return self._apply_rr(df, long, short)

    def signal_trend_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (
            (df["close"] > df["t3"])
            & (df["rsi"] > 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        short = (
            (df["close"] < df["t3"])
            & (df["rsi"] < 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        return self._apply_rr(df, long, short)

    def signal_trend_mfi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (
            (df["close"] > df["t3"])
            & (df["mfi"] > 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        short = (
            (df["close"] < df["t3"])
            & (df["mfi"] < 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        return self._apply_rr(df, long, short)

    def signal_momentum_wt_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (
            (df["wt1"] > df["wt2"])
            & (df["wt1"].shift(1) <= df["wt2"].shift(1))
            & (df["rsi"] > 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        short = (
            (df["wt1"] < df["wt2"])
            & (df["wt1"].shift(1) >= df["wt2"].shift(1))
            & (df["rsi"] < 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        return self._apply_rr(df, long, short)

    def signal_momentum_fisher_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (
            (df["fisher"] > 0)
            & (df["rsi"] > 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        short = (
            (df["fisher"] < 0)
            & (df["rsi"] < 50)
            & (df["volume_zscore"] < self.vol_z_threshold.value)
        )
        return self._apply_rr(df, long, short)

    def signal_ob_breakout(self, df: pd.DataFrame) -> pd.DataFrame:
        if "ob_bull_top" not in df.columns:
            return self._empty_signals(df)
        long = (df["close"] > df["ob_bull_top"]) & (
            df["close"].shift(1) <= df["ob_bull_top"]
        )
        short = (df["close"] < df["ob_bear_bottom"]) & (
            df["close"].shift(1) >= df["ob_bear_bottom"]
        )
        return self._apply_rr(df, long, short)

    def signal_ob_false_breakout(self, df: pd.DataFrame) -> pd.DataFrame:
        if "ob_bull_top" not in df.columns:
            return self._empty_signals(df)
        long = (df["close"] > df["ob_bull_top"]) & (
            df["low"].shift(1) < df["ob_bull_bottom"]
        )
        short = (df["close"] < df["ob_bear_bottom"]) & (
            df["high"].shift(1) > df["ob_bear_top"]
        )
        return self._apply_rr(df, long, short)

    def signal_meanrev_nw_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (df["low"] <= df["nw_lower"]) & (df["rsi"] < self.rsi_oversold.value)
        short = (df["high"] >= df["nw_upper"]) & (df["rsi"] > self.rsi_overbought.value)
        return self._apply_rr(df, long, short)

    def signal_meanrev_nw_mfi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (df["low"] <= df["nw_lower"]) & (df["mfi"] < 20)
        short = (df["high"] >= df["nw_upper"]) & (df["mfi"] > 80)
        return self._apply_rr(df, long, short)

    def signal_scalp_meanrev_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (df["low"] <= df["nw_lower"]) & (df["rsi"] < self.rsi_oversold.value)
        short = (df["high"] >= df["nw_upper"]) & (df["rsi"] > self.rsi_overbought.value)
        return self._apply_rr(df, long, short)

    def signal_scalp_meanrev_mfi(self, df: pd.DataFrame) -> pd.DataFrame:
        long = (df["low"] <= df["nw_lower"]) & (df["mfi"] < 15)
        short = (df["high"] >= df["nw_upper"]) & (df["mfi"] > 85)
        return self._apply_rr(df, long, short)

    STRATEGY_VARIANTS = {
        "trend_fisher": signal_trend_fisher,
        "trend_rsi": signal_trend_rsi,
        "trend_mfi": signal_trend_mfi,
        "momentum_wt_rsi": signal_momentum_wt_rsi,
        "momentum_fisher_rsi": signal_momentum_fisher_rsi,
        "ob_breakout": signal_ob_breakout,
        "ob_false_breakout": signal_ob_false_breakout,
        "meanrev_nw_rsi": signal_meanrev_nw_rsi,
        "meanrev_nw_mfi": signal_meanrev_nw_mfi,
        "scalp_meanrev_rsi": signal_scalp_meanrev_rsi,
        "scalp_meanrev_mfi": signal_scalp_meanrev_mfi,
    }

    @staticmethod
    def _empty_signals(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {"enter_long": 0, "enter_short": 0},
            index=df.index,
        )

    def _apply_rr(
        self,
        df: pd.DataFrame,
        long_condition: pd.Series,
        short_condition: pd.Series,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "enter_long": self.filter_reward_risk(df, long_condition, "long").astype(int),
                "enter_short": self.filter_reward_risk(df, short_condition, "short").astype(int),
            },
            index=df.index,
        )

    def filter_reward_risk(
        self,
        df: pd.DataFrame,
        signal: pd.Series,
        direction: str,
    ) -> pd.Series:
        signal = signal.fillna(False).astype(bool)
        if not signal.any():
            return signal

        atr = df["atr"]
        swing_low = df["last_swing_low"]
        swing_high = df["last_swing_high"]
        if direction == "long":
            stop = swing_low - 0.5 * atr
            target = df["close"] + 0.5 * (swing_high - df["close"])
            risk = df["close"] - stop
            reward = target - df["close"]
            directional_levels = stop.lt(df["close"]) & target.gt(df["close"])
        else:
            stop = swing_high + 0.5 * atr
            target = df["close"] - 0.5 * (df["close"] - swing_low)
            risk = stop - df["close"]
            reward = df["close"] - target
            directional_levels = stop.gt(df["close"]) & target.lt(df["close"])

        ratio = reward.div(risk.replace(0, np.nan))
        valid = (
            directional_levels
            & ratio.ge(self.min_reward_risk.value)
        ).fillna(False)
        return signal & valid

    @staticmethod
    def _finite_float(value: object) -> float | None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if np.isfinite(value) else None

    def _trade_atr(self, pair: str, trade: Trade) -> float | None:
        atr_value = self._finite_float(trade.get_custom_data("atr_entry"))
        if atr_value is not None and atr_value > 0:
            return atr_value

        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is not None and not dataframe.empty:
                atr_value = self._finite_float(dataframe.iloc[-1].get("atr"))
        except (AttributeError, TypeError, ValueError):
            atr_value = None
        return atr_value if atr_value and atr_value > 0 else None

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        atr_value = self._trade_atr(pair, trade)
        if atr_value is None or current_rate <= 0:
            return -0.05

        swing_low = self._finite_float(trade.get_custom_data("swing_low_price"))
        swing_high = self._finite_float(trade.get_custom_data("swing_high_price"))
        atr_stop = (
            trade.open_rate + self.vol_mult_sl_atr * atr_value
            if trade.is_short
            else trade.open_rate - self.vol_mult_sl_atr * atr_value
        )
        if trade.is_short:
            stop = swing_high + 0.5 * atr_value if swing_high is not None else atr_stop
            if stop <= current_rate:
                stop = atr_stop
        else:
            stop = swing_low - 0.5 * atr_value if swing_low is not None else atr_stop
            if stop >= current_rate:
                stop = atr_stop

        if trade.get_custom_data("tp1_hit"):
            stop = trade.open_rate
        if trade.get_custom_data("tp2_hit"):
            if trade.is_short:
                tp1_move = 0.5 * (trade.open_rate - (swing_low or trade.open_rate))
                stop = trade.open_rate + tp1_move
            else:
                tp1_move = 0.5 * ((swing_high or trade.open_rate) - trade.open_rate)
                stop = trade.open_rate - tp1_move
            trail_offset = 0.5 * atr_value
            stop = (
                min(stop, current_rate + trail_offset)
                if trade.is_short
                else max(stop, current_rate - trail_offset)
            )

        is_valid = stop > current_rate if trade.is_short else stop < current_rate
        if not is_valid:
            return None
        distance = abs(1.0 - (stop / current_rate))
        return -min(distance, abs(self.stoploss))

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float | None:
        atr_value = trade.get_custom_data("atr_entry")
        if atr_value is None or not np.isfinite(atr_value):
            return None

        swing_low = trade.get_custom_data("swing_low_price")
        swing_high = trade.get_custom_data("swing_high_price")
        if swing_low is None or swing_high is None:
            tp1 = trade.open_rate + (
                self.vol_mult_tp1_atr * atr_value
                if not trade.is_short
                else -self.vol_mult_tp1_atr * atr_value
            )
            tp2 = trade.open_rate + (
                self.vol_mult_tp2_atr * atr_value
                if not trade.is_short
                else -self.vol_mult_tp2_atr * atr_value
            )
            tp3 = trade.open_rate + (
                self.vol_mult_tp3_atr * atr_value
                if not trade.is_short
                else -self.vol_mult_tp3_atr * atr_value
            )
        elif trade.is_short:
            tp1 = trade.open_rate - 0.5 * (trade.open_rate - swing_low)
            tp2 = swing_low
            tp3 = swing_low - atr_value
        else:
            tp1 = trade.open_rate + 0.5 * (swing_high - trade.open_rate)
            tp2 = swing_high
            tp3 = swing_high + atr_value

        stake_amount = float(trade.stake_amount)
        if not trade.get_custom_data("tp1_hit") and (
            (not trade.is_short and current_rate >= tp1)
            or (trade.is_short and current_rate <= tp1)
        ):
            trade.set_custom_data("tp1_hit", True)
            return -(stake_amount * 0.5)
        if trade.get_custom_data("tp1_hit") and not trade.get_custom_data("tp2_hit") and (
            (not trade.is_short and current_rate >= tp2)
            or (trade.is_short and current_rate <= tp2)
        ):
            trade.set_custom_data("tp2_hit", True)
            return -(stake_amount * 0.25)
        if trade.get_custom_data("tp2_hit") and not trade.get_custom_data("tp3_hit") and (
            (not trade.is_short and current_rate >= tp3)
            or (trade.is_short and current_rate <= tp3)
        ):
            trade.set_custom_data("tp3_hit", True)
            return -(stake_amount * 0.25)
        return None

    def custom_entry_price(
        self,
        pair: str,
        trade: Trade | None,
        current_time: datetime,
        proposed_rate: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        # Entry metadata is stored in order_filled because the initial entry
        # has no Trade object when this callback is called.
        return proposed_rate

    def order_filled(
        self,
        pair: str,
        trade: Trade,
        order: Order,
        current_time: datetime,
        **kwargs,
    ) -> None:
        if order.ft_order_side != trade.entry_side:
            return
        if trade.get_custom_data("atr_entry") is not None:
            return

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return

        candle = dataframe.iloc[-1]
        try:
            eligible = dataframe.loc[dataframe["date"] <= pd.Timestamp(current_time)]
            if not eligible.empty:
                candle = eligible.iloc[-1]
        except (TypeError, ValueError):
            pass

        atr_value = candle.get("atr")
        if pd.notna(atr_value) and float(atr_value) > 0:
            trade.set_custom_data("atr_entry", float(atr_value))
        for key in ("last_swing_low", "last_swing_high"):
            value = candle.get(key)
            if pd.notna(value):
                trade.set_custom_data(
                    "swing_low_price" if key.endswith("low") else "swing_high_price",
                    float(value),
                )

    def _default_regime_map(self) -> dict[int, str]:
        return {regime_id: "trend_fisher" for regime_id in range(1, 13)}

    def _load_regime_map(self) -> None:
        loaded: dict[int, str] = {}
        try:
            with REGIME_MAP_FILE.open(encoding="utf-8") as map_file:
                raw_map = json.load(map_file)
            loaded = {
                int(key): value
                for key, value in raw_map.items()
                if int(key) in range(1, 13) and value in self.STRATEGY_VARIANTS
            }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.info("No valid saved regime map found at %s", REGIME_MAP_FILE)

        default = self._default_regime_map()
        default.update(loaded)
        self.regime_strategy_map = default

    def bot_start(self, **kwargs) -> None:
        self._load_regime_map()

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        if not self.regime_strategy_map:
            self._load_regime_map()

        dataframe["regime"] = dataframe.apply(self.classify_regime, axis=1)
        signal_cache: dict[str, pd.DataFrame] = {}
        for regime_id, variant_name in self.regime_strategy_map.items():
            if variant_name not in self.STRATEGY_VARIANTS:
                continue
            mask = dataframe["regime"] == int(regime_id)
            if not mask.any():
                continue
            if variant_name not in signal_cache:
                signal_cache[variant_name] = self.STRATEGY_VARIANTS[variant_name](
                    self, dataframe
                )
            signals = signal_cache[variant_name]
            dataframe.loc[mask, "enter_long"] = signals.loc[mask, "enter_long"].to_numpy()
            dataframe.loc[mask, "enter_short"] = signals.loc[mask, "enter_short"].to_numpy()
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe
