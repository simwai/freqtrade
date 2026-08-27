"""Screener rank 1 - auto-generated from walk-forward screening.

Combo      : dpo_20
             · vqzl_zscore · evening_star
             · fvg_distance · bayes_sigma_down
             · breakout_up_prob
Score      : 6.4473
Metrics    : Calmar 326.17, Sortino 4.23, F1 0.742, \
trades 188, win rate 89.36%, max losing streak 3
CV F1      : 0.651
FDR status : passed BH-FDR at alpha=0.05

Do not edit thresholds by hand - regenerate via screener rule extraction.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pandas_ta as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter
from freqtrade.strategy.interface import IStrategy
from strategy_lib.risk import SlTpConfig, TradeLevelsManager, exit_cross_signal, levels_at


class ScreenerDpoEveningStar(IStrategy):
    """Long-only signal strategy distilled from the screened combination."""

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 400

    # hold_bars mirrors the screener's labeling horizon (H=5) and stays outside the space
    hold_bars = 5
    minimal_roi = {"0": 100}
    # loose catastrophic floor - structural exits come from the level engine below
    stoploss = -0.05
    trailing_stop = False

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._manager: TradeLevelsManager | None = None

    # Hyperopt space - structural risk management (sell space)
    sl_mode = CategoricalParameter(
        ["Highest Lowest", "Time Cut"], default="Highest Lowest", space="sell"
    )
    high_low_stop_loss_lookback = IntParameter(10, 60, default=20, space="sell")
    high_low_stop_loss_multiplier = DecimalParameter(
        0.90, 1.00, default=0.98, decimals=2, space="sell"
    )
    my_backup_multiplier = DecimalParameter(1.00, 1.20, default=1.10, decimals=2, space="sell")
    time_cut_minutes = IntParameter(low=15, high=75, default=45, space="sell")
    time_cut_percent = DecimalParameter(0.002, 0.02, default=0.01, decimals=3, space="sell")
    risk_reward_ratio = DecimalParameter(0.75, 3.00, default=1.05, decimals=2, space="sell")

    def _sltp_config(self) -> SlTpConfig:
        """Snapshot of the current SL/TP hyperopt parameters."""
        return SlTpConfig(
            mode=self.sl_mode.value,
            sl_size_or_atr_multiplier=2.0,
            risk_reward_ratio=float(self.risk_reward_ratio.value),
            high_low_stop_loss_lookback=int(self.high_low_stop_loss_lookback.value),
            high_low_stop_loss_multiplier=float(self.high_low_stop_loss_multiplier.value),
            my_backup_multiplier=float(self.my_backup_multiplier.value),
            enable_take_profit=True,
            time_cut_minutes=int(self.time_cut_minutes.value),
            time_cut_percent=float(self.time_cut_percent.value),
        )

    def _levels_manager(self) -> TradeLevelsManager:
        # Reassigning config lets _ensure_signature flush stale level caches between epochs
        if self._manager is None:
            self._manager = TradeLevelsManager(self._sltp_config())
        else:
            self._manager.config = self._sltp_config()
        return self._manager

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: dt.datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        # structural SL/TP crosses first, then the labeling-horizon timeout
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is not None and not dataframe.empty:
            levels = self._levels_manager().cached_trade_level_series(
                pair, dataframe, trade, self.timeframe
            )
            if levels is not None:
                cur_idx = len(dataframe) - 1
                prev_idx = max(cur_idx - 1, int(levels["entry_index"][0]))
                tag = exit_cross_signal(
                    float(dataframe["close"].iloc[prev_idx]),
                    float(dataframe["close"].iloc[cur_idx]),
                    levels_at(levels, prev_idx),
                    levels_at(levels, cur_idx),
                    trade.is_short,
                )
                if tag is not None:
                    return "structural_tp" if "TP" in tag else "structural_sl"
        if current_time - trade.open_date_utc >= dt.timedelta(minutes=15 * self.hold_bars):
            return "h_bar_timeout"
        return None

    @staticmethod
    def _scale(base: int, limit: int) -> int:
        """Warm-up aware scaling - 10k->0.5x, 70k->1.0x, <3k->0.4x to keep <5% warm-up."""
        if limit >= 50000:
            factor = 1.0
        elif limit >= 10000 or limit >= 5000:
            factor = 0.5
        else:
            factor = 0.4
        return max(5, int(base * factor))

    @staticmethod
    def _col(out, prefix: str) -> pd.Series:
        """Pick first column whose name starts with prefix - robust to scaled lengths."""
        if isinstance(out, pd.Series):
            return out
        for c in out.columns:
            if str(c).startswith(prefix):
                return out[c]
        return out.iloc[:, 0]

    @staticmethod
    def _bayesian_bbsma(
        df: pd.DataFrame, bb_length: int = 20, bb_mult: float = 2.5, bayes_period: int = 20
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        close = df["close"]
        basis = ta.sma(close, length=bb_length)
        std = close.rolling(bb_length).std()
        bb_upper = basis + bb_mult * std

        prob_bb_upper_up = (close > bb_upper).rolling(bayes_period).sum() / bayes_period
        prob_bb_upper_down = (close < bb_upper).rolling(bayes_period).sum() / bayes_period
        prob_up_bb_upper = prob_bb_upper_up / (prob_bb_upper_up + prob_bb_upper_down)

        prob_bb_basis_up = (close > basis).rolling(bayes_period).sum() / bayes_period
        prob_bb_basis_down = (close < basis).rolling(bayes_period).sum() / bayes_period
        prob_up_bb_basis = prob_bb_basis_up / (prob_bb_basis_up + prob_bb_basis_down)

        prob_sma_up = (close > basis).rolling(bayes_period).sum() / bayes_period
        prob_sma_down = (close < basis).rolling(bayes_period).sum() / bayes_period
        prob_up_sma = prob_sma_up / (prob_sma_up + prob_sma_down)

        product_up = prob_up_bb_upper * prob_up_bb_basis * prob_up_sma
        product_down = (1 - prob_up_bb_upper) * (1 - prob_up_bb_basis) * (1 - prob_up_sma)
        sigma_down = product_up / (product_up + product_down)

        prob_down_bb_upper = prob_bb_upper_down / (prob_bb_upper_down + prob_bb_upper_up)
        prob_down_bb_basis = prob_bb_basis_down / (prob_bb_basis_down + prob_bb_basis_up)
        prob_down_sma = prob_sma_down / (prob_sma_down + prob_sma_up)
        product_down2 = prob_down_bb_upper * prob_down_bb_basis * prob_down_sma
        product_up2 = (1 - prob_down_bb_upper) * (1 - prob_down_bb_basis) * (1 - prob_down_sma)
        sigma_up = product_down2 / (product_down2 + product_up2)

        prob_prime = (
            sigma_down * sigma_up / (sigma_down * sigma_up + (1 - sigma_down) * (1 - sigma_up))
        )

        return sigma_down, sigma_up, prob_prime

    @staticmethod
    def _breakout_probability(
        df: pd.DataFrame, perc: float = 1.0, lookback: int = 1000
    ) -> tuple[pd.Series, pd.Series]:
        h = df["high"]
        lo = df["low"]
        c = df["close"]
        o = df["open"]

        step = c.shift(1) * (perc / 100)
        green = c.shift(1) > o.shift(1)
        red = c.shift(1) < o.shift(1)

        up_target = h.shift(1) + step
        down_target = lo.shift(1) - step

        hit_up = h >= up_target
        hit_down = lo <= down_target

        green_total = green.rolling(lookback, min_periods=1).sum()
        red_total = red.rolling(lookback, min_periods=1).sum()

        green_up_hits = (green & hit_up).rolling(lookback, min_periods=1).sum()
        green_down_hits = (green & hit_down).rolling(lookback, min_periods=1).sum()
        red_up_hits = (red & hit_up).rolling(lookback, min_periods=1).sum()
        red_down_hits = (red & hit_down).rolling(lookback, min_periods=1).sum()

        up_prob = pd.Series(np.nan, index=df.index)
        down_prob = pd.Series(np.nan, index=df.index)

        up_prob[green] = green_up_hits[green] / green_total[green]
        up_prob[red] = red_up_hits[red] / red_total[red]
        down_prob[green] = green_down_hits[green] / green_total[green]
        down_prob[red] = red_down_hits[red] / red_total[red]

        return up_prob, down_prob

    @staticmethod
    def _cdl_evening_star(open_, high, low, close) -> pd.Series:
        big_bull = (close.shift(2) > open_.shift(2)) & (
            (close.shift(2) - open_.shift(2)).abs() > (close.shift(3) - open_.shift(3)).abs() * 0.8
        )
        small_mid = (open_.shift(1) - close.shift(1)).abs() <= (
            close.shift(2) - open_.shift(2)
        ).abs() * 0.5
        bear_close = (close < open_) & (close < (open_.shift(2) + close.shift(2)) / 2)
        es = big_bull & small_mid & bear_close
        return es.fillna(False).astype(int)

    @staticmethod
    def _detect_fvg(df: pd.DataFrame, min_gap: float = 0.0001) -> pd.DataFrame:
        high = df["high"]
        low = df["low"]
        close = df["close"]

        fvg_bull = (low.shift(2) > high).astype(int)
        fvg_bear = (high.shift(2) < low).astype(int)

        fvg_bull_size = (low.shift(2) - high) / high
        fvg_bear_size = (low - high.shift(2)) / high.shift(2)
        fvg_size = fvg_bull_size.where(fvg_bull == 1, fvg_bear_size.where(fvg_bear == 1, 0.0))

        active_fvgs: list[tuple[float, float, str, int]] = []
        unfilled = pd.Series(0, index=df.index)
        distance = pd.Series(np.nan, index=df.index)

        for i in range(len(df)):
            still_active = []
            for top, bottom, direction, _ in active_fvgs:
                if direction == "bull":
                    if low.iloc[i] <= top:
                        continue
                else:
                    if high.iloc[i] >= bottom:
                        continue
                still_active.append((top, bottom, direction, _))
            active_fvgs = still_active

            if i >= 2:
                if fvg_bull.iloc[i] == 1 and fvg_bull_size.iloc[i] >= min_gap:
                    top = low.iloc[i - 2]
                    bottom = high.iloc[i]
                    active_fvgs.append((top, bottom, "bull", i))
                if fvg_bear.iloc[i] == 1 and fvg_bear_size.iloc[i] >= min_gap:
                    top = low.iloc[i]
                    bottom = high.iloc[i - 2]
                    active_fvgs.append((top, bottom, "bear", i))

            if active_fvgs:
                dists = []
                for top, bottom, direction, _ in active_fvgs:
                    if direction == "bull":
                        d = (close.iloc[i] - bottom) / close.iloc[i]
                    else:
                        d = (top - close.iloc[i]) / close.iloc[i]
                    dists.append(d)
                idx_min = np.argmin(np.abs(dists))
                distance.iloc[i] = dists[idx_min]
                unfilled.iloc[i] = 1

        return pd.DataFrame(
            {
                "fvg_bull_flag": fvg_bull,
                "fvg_bear_flag": fvg_bear,
                "fvg_size": fvg_size,
                "fvg_unfilled": unfilled,
                "fvg_distance": distance,
            }
        )

    @staticmethod
    def _vqzl_zscore(
        open_: pd.Series,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        price_smoothing: int = 15,
        zlength: int = 100,
    ) -> pd.Series:
        cHigh = high.ewm(span=price_smoothing, adjust=False).mean()
        cLow = low.ewm(span=price_smoothing, adjust=False).mean()
        cOpen = open_.ewm(span=price_smoothing, adjust=False).mean()
        cClose = close.ewm(span=price_smoothing, adjust=False).mean()
        pClose = cClose.shift(1)

        true_range = np.maximum(cHigh, cClose) - np.minimum(cLow, pClose)
        rrange = cHigh - cLow

        vqi = ((cClose - pClose) / true_range + (cClose - cOpen) / rrange) * 0.5
        vqi_abs = np.abs(vqi) * (cClose - pClose + cClose - cOpen) * 0.5
        sum_vqi = vqi_abs.where(np.abs(vqi_abs) > 1, vqi_abs * 10)

        zscore = (sum_vqi - sum_vqi.rolling(zlength).mean()) / sum_vqi.rolling(zlength).std()
        return zscore

    # Indicator functions
    def _f_dpo_20(self, df):
        return ta.dpo(df["close"], length=max(10, self._scale(20, 2000)))

    def _f_vqzl_zscore(self, df):
        return self._vqzl_zscore(df["open"], df["high"], df["low"], df["close"])

    def _f_evening_star(self, df):
        return self._cdl_evening_star(df["open"], df["high"], df["low"], df["close"])

    def _f_fvg_distance(self, df):
        return self._detect_fvg(df)["fvg_distance"]

    def _f_bayes_sigma_down(self, df):
        return self._bayesian_bbsma(df)[0]

    def _f_breakout_up_prob(self, df):
        return self._breakout_probability(df)[0]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe
        dataframe["dpo_20"] = self._f_dpo_20(df)
        dataframe["vqzl_zscore"] = self._f_vqzl_zscore(df)
        dataframe["evening_star"] = self._f_evening_star(df)
        dataframe["fvg_distance"] = self._f_fvg_distance(df)
        dataframe["bayes_sigma_down"] = self._f_bayes_sigma_down(df)
        dataframe["breakout_up_prob"] = self._f_breakout_up_prob(df)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe
        enter_long = (
            (df["dpo_20"] <= -47.6724987)
            & (df["dpo_20"] <= -81.02750015)
            & (df["dpo_20"] > -715.506012)
        ) | (
            (df["dpo_20"] <= -47.6724987)
            & (df["dpo_20"] > -81.02750015)
            & (df["vqzl_zscore"] > 0.9667899311)
        )
        dataframe.loc[enter_long, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # exits are handled by minimal_roi / stoploss / h_bar_timeout
        return dataframe
