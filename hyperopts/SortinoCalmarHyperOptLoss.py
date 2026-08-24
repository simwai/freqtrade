"""
SortinoCalmarHyperOptLoss

A risk-adjusted, capital-efficiency-aware loss for the Octopus Nest strategy.

The score is a *multiplicative* combination of factors, each scaled to roughly
[0.5, 6] so no single term dominates and a catastrophic drawdown collapses the
whole score. Components are read from freqtrade's ``backtest_stats`` where
possible (they are already computed consistently by the framework) and from the
trade list (``results``) for MAE / MFE.

Default score:

    score = (1 + sortino)                          risk-adjusted return
          * (1 + calmar)                           return / max drawdown
          * (1 + 0.25 * (profit_factor - 1))       gross win / gross loss
          * (1 + 0.10 * sqn)                       consistency * trade count
          * (1 + 0.30 * exit_efficiency)           MFE capture (holds winners)
          * (1 + 3.00 * annualized_return)         capital efficiency ("short but decent")
          / (1 + 2.00 * mae_ratio)                 penalizes deep adverse excursions

``loss = -score`` (smaller is better for skopt).

Weights are class attributes - set any of them to 0.0 to disable the
component. Mind the interaction between ``mae_ratio`` and the SL width: a wider
stop mechanically produces a larger MAE, so a heavy MAE penalty biases the
search toward narrow stops. ``exit_efficiency`` (profit relative to MFE) is the
more robust "hold the winners" signal and is safe to keep.

Note: annualized return is the statistically sound version of "shorter trades
are better, as long as profit holds" - it rewards freeing capital for re-use
without penalizing long-but-profitable winners.
"""

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.optimize.hyperopt_loss.hyperopt_loss_interface import IHyperOptLoss


# Component multipliers (set to 0.0 to disable a term)
MULT_SORTINO = 1.0
MULT_CALMAR = 1.0
MULT_PROFIT_FACTOR = 0.25
MULT_SQN = 0.10
MULT_EXIT_EFFICIENCY = 0.30
MULT_ANNUALIZED = 3.0

# MAE penalty (0.0 disables)
DIV_MAE = 2.0

# Annualized return is clamped so short test windows can't dominate the score.
ANNUALIZED_MIN = -0.999
ANNUALIZED_CAP = 1.5

# Floor for factors that can legitimately go negative (sortino, calmar, sqn,
# annualized). Avoids sign flips in the multiplicative score.
FLOOR = 1e-4

# Sentinel for "no trades" / degenerate results. Freqtrade already assigns
# MAX_LOSS below --min-trades, this is a defensive backstop.
MAX_LOSS = 100000.0


class SortinoCalmarHyperOptLoss(IHyperOptLoss):
    """
    Defines the loss function for hyperopt.
    """

    @staticmethod
    def _clamped(value: float, floor: float = FLOOR) -> float:
        return max(float(value), floor)

    @classmethod
    def hyperopt_loss_function(
        cls,
        *,
        results: DataFrame,
        trade_count: int,
        min_date,
        max_date,
        config,
        processed,
        backtest_stats,
        starting_balance: float,
        **kwargs,
    ) -> float:
        """
        Objective function, returns smaller number for better results.
        """
        if trade_count == 0 or results is None or results.empty:
            return MAX_LOSS

        sortino = backtest_stats.get("sortino") or 0.0
        calmar = backtest_stats.get("calmar") or 0.0
        profit_factor = backtest_stats.get("profit_factor") or 0.0
        sqn = backtest_stats.get("sqn") or 0.0

        days = (max_date - min_date).total_seconds() / 86400.0
        total_profit = float(results["profit_abs"].sum())
        if days > 0 and starting_balance > 0:
            annualized = (1.0 + total_profit / starting_balance) ** (365.0 / days) - 1.0
        else:
            annualized = 0.0
        annualized = min(max(annualized, ANNUALIZED_MIN), ANNUALIZED_CAP)

        mae_ratio, exit_efficiency = cls._excursion_metrics(results)

        score = (
            cls._clamped(1.0 + MULT_SORTINO * sortino)
            * cls._clamped(1.0 + MULT_CALMAR * calmar)
            * cls._clamped(1.0 + MULT_PROFIT_FACTOR * (profit_factor - 1.0))
            * cls._clamped(1.0 + MULT_SQN * sqn)
            * cls._clamped(1.0 + MULT_EXIT_EFFICIENCY * exit_efficiency)
            * cls._clamped(1.0 + MULT_ANNUALIZED * annualized)
            / cls._clamped(1.0 + DIV_MAE * mae_ratio)
        )
        return -float(score)

    @staticmethod
    def _excursion_metrics(results: DataFrame) -> tuple[float, float]:
        """
        Compute average MAE and MFE-capture (exit efficiency) from trade OHLC.

        MAE / MFE are relative to the entry price, sign-corrected for shorts.
        Exit efficiency is profit_ratio / MFE clipped to [0, 1]: 1.0 means the
        exit captured the entire favorable excursion.
        """
        open_rate = results["open_rate"].astype(float)
        min_rate = results["min_rate"].astype(float)
        max_rate = results["max_rate"].astype(float)
        profit_ratio = results["profit_ratio"].astype(float)
        is_short = (
            results.get("is_short", pd.Series(False, index=results.index)).astype(bool).to_numpy()
        )

        long_mfe = (max_rate - open_rate) / open_rate.replace(0, np.nan)
        long_mae = (open_rate - min_rate) / open_rate.replace(0, np.nan)
        short_mfe = (open_rate - min_rate) / open_rate.replace(0, np.nan)
        short_mae = (min_rate - open_rate) / open_rate.replace(0, np.nan)

        mfe = np.where(is_short, short_mfe, long_mfe)
        mae = np.where(is_short, short_mae, long_mae)
        mfe = np.clip(mfe, 0.0, None)
        mae = np.clip(mae, 0.0, None)

        with np.errstate(divide="ignore", invalid="ignore"):
            efficiency = np.divide(profit_ratio.to_numpy(), mfe)
        efficiency = np.nan_to_num(efficiency, nan=0.0, posinf=1.0, neginf=0.0)
        efficiency = np.clip(efficiency, 0.0, 1.0)

        mae_ratio = float(np.mean(mae)) if len(mae) else 0.0
        exit_efficiency = float(np.mean(efficiency)) if len(efficiency) else 0.0
        return mae_ratio, exit_efficiency
