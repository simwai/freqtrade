"""
DrawdownConstrainedHyperOptLoss

Pareto loss: maximize total profit, penalize (linearly) any drawdown
exceeding a configurable threshold.  Default threshold 0.05 (5% of starting
balance).  Loss is returned as a negative score to minimize.

    score = -total_profit + penalty_weight * max(0, max_drawdown - threshold)

Smaller (more negative) is better.  This pushes the optimizer toward
configurations that are both profitable and respect the drawdown cap.
"""

from __future__ import annotations

from datetime import datetime

from pandas import DataFrame

from freqtrade.data.metrics import calculate_max_drawdown
from freqtrade.optimize.hyperopt import IHyperOptLoss


class DrawdownConstrainedHyperOptLoss(IHyperOptLoss):
    """
    Custom loss: profit minus a linear penalty for drawdown beyond
    ``max_drawdown_threshold`` (fraction of starting balance, default 0.05).
    Penalty weight is ``drawdown_penalty`` (default 10).  Smaller loss is better.
    """

    @staticmethod
    def hyperopt_loss_function(
        results: DataFrame,
        trade_count: int,
        min_date: datetime,
        max_date: datetime,
        config: dict,
        processed: dict,
        backtest_stats: dict,
        starting_balance: float,
        *args,
        **kwargs,
    ) -> float:
        total_profit = results["profit_abs"].sum() if not results.empty else 0.0
        try:
            dd = calculate_max_drawdown(results, value_col="profit_abs")
            max_dd_abs = dd.drawdown_abs
        except ValueError:
            return -total_profit

        starting = float(backtest_stats.get("starting_balance", starting_balance or 0.0))
        if starting > 0:
            max_dd_frac = max_dd_abs / starting
        else:
            max_dd_frac = 0.0

        threshold = float(config.get("dd_threshold", 0.05))
        penalty_weight = float(config.get("dd_penalty_weight", 10.0))
        excess = max(0.0, max_dd_frac - threshold)
        penalty = penalty_weight * starting * excess

        return -total_profit + penalty
