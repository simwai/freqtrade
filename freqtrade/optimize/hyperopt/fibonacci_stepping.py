"""
Fibonacci stepping logic for multi-stage hyperopt optimization.

This module implements the Fibonacci-stepping approach for hyperparameter optimization,
where trials are allocated across multiple stages with progressively narrowing search spaces
based on Fibonacci numbers.
"""

import logging
from typing import Any

from freqtrade.constants import Config
from freqtrade.exceptions import OperationalException


# Suppress scikit-learn FutureWarnings from skopt
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=FutureWarning)
    from skopt.space import Categorical, Dimension, Integer, Real


logger = logging.getLogger(__name__)


# Minimum trials per stage to ensure meaningful optimization
MIN_STAGE1_TRIALS = 5
MIN_STAGE2_TRIALS = 5
MIN_STAGE3_TRIALS = 3

# Minimum Fibonacci target (F_9 = 34)
MIN_FIBONACCI_TARGET = 34


class FibonacciStepping:
    """
    Manages multi-stage Fibonacci trial allocation and search space reduction.

    The Fibonacci stepping approach allocates trials across stages using Fibonacci numbers:
    - Init: n_initial random trials
    - Stage 1: F_n - n_initial trials (full space)
    - Stage 2: F_{n-1} trials (reduced space from top F_{n-1} Stage 1 results)
    - Stage 3: F_{n-2} trials (further reduced space from top F_{n-2} Stage 2 results)

    Example with F_n=34, n_initial=10:
    - Init: 10 trials
    - Stage 1: 24 trials (full space)
    - Stage 2: 21 trials (reduced from top 21)
    - Stage 3: 13 trials (further reduced from top 13)
    - Total: 68 trials
    """

    def __init__(self, config: Config) -> None:
        self.fibonacci_target = config.get("hyperopt_fibonacci_target", 34)
        self.n_initial = config.get("hyperopt_initial_points", 10)
        self.space_reduction = config.get("hyperopt_space_reduction", 0.15)
        self.estimator = config.get("hyperopt_estimator", "ET")

        self._validate_config()

    def _validate_config(self) -> None:
        """Validate Fibonacci stepping configuration."""
        # Check fibonacci_target is a valid Fibonacci number >= MIN_FIBONACCI_TARGET
        fib_sequence = self._generate_fibonacci_sequence(self.fibonacci_target * 2)
        if self.fibonacci_target not in fib_sequence:
            raise OperationalException(
                f"hyperopt_fibonacci_target ({self.fibonacci_target}) must be a Fibonacci number. "
                f"Valid options >= {MIN_FIBONACCI_TARGET}: "
                f"{[f for f in fib_sequence if f >= MIN_FIBONACCI_TARGET]}"
            )

        if self.fibonacci_target < MIN_FIBONACCI_TARGET:
            raise OperationalException(
                f"hyperopt_fibonacci_target must be >= {MIN_FIBONACCI_TARGET}, "
                f"got {self.fibonacci_target}"
            )

        # Check initial points don't exceed stage 1 budget
        fib_seq = self._generate_fibonacci_sequence(self.fibonacci_target)
        fn = self.fibonacci_target
        fn_minus_1 = fib_seq[fib_seq.index(fn) - 1] if fib_seq.index(fn) > 0 else 0

        stage1_trials = fn - self.n_initial
        if stage1_trials < MIN_STAGE1_TRIALS:
            raise OperationalException(
                f"Stage 1 would have only {stage1_trials} trials (need >= {MIN_STAGE1_TRIALS}). "
                f"Reduce hyperopt_initial_points (current: {self.n_initial}) or "
                f"increase hyperopt_fibonacci_target (current: {self.fibonacci_target})."
            )

        if fn_minus_1 < MIN_STAGE2_TRIALS:
            raise OperationalException(
                f"Stage 2 would have only {fn_minus_1} trials (need >= {MIN_STAGE2_TRIALS}). "
                f"Increase hyperopt_fibonacci_target (current: {self.fibonacci_target})."
            )

        fib_seq_full = self._generate_fibonacci_sequence(fn * 2)
        fn_idx = fib_seq_full.index(fn)
        if fn_idx >= 2:
            fn_minus_2 = fib_seq_full[fn_idx - 2]
            if fn_minus_2 < MIN_STAGE3_TRIALS:
                raise OperationalException(
                    f"Stage 3 would have only {fn_minus_2} trials (need >= {MIN_STAGE3_TRIALS}). "
                    f"Increase hyperopt_fibonacci_target (current: {self.fibonacci_target})."
                )

        if not 0.01 <= self.space_reduction <= 0.5:
            raise OperationalException(
                f"hyperopt_space_reduction must be between 0.01 and 0.5, got {self.space_reduction}"
            )

        if self.estimator not in ("GP", "RF", "ET", "GBRT"):
            raise OperationalException(
                f"hyperopt_estimator must be one of GP, RF, ET, GBRT, got {self.estimator}"
            )

    def _generate_fibonacci_sequence(self, limit: int) -> list[int]:
        """Generate Fibonacci sequence up to limit."""
        fib = [1, 1]
        while fib[-1] < limit:
            fib.append(fib[-1] + fib[-2])
        return fib

    def get_fibonacci_trio(self, target: int) -> tuple[int, int, int]:
        """
        Get the Fibonacci trio (F_n, F_{n-1}, F_{n-2}) for a target F_n.

        Returns:
            Tuple of (fn, fn_minus_1, fn_minus_2)
        """
        fib_seq = self._generate_fibonacci_sequence(target * 2)
        idx = fib_seq.index(target)
        fn = fib_seq[idx]
        fn_minus_1 = fib_seq[idx - 1] if idx > 0 else 0
        fn_minus_2 = fib_seq[idx - 2] if idx > 1 else 0
        return fn, fn_minus_1, fn_minus_2

    def compute_stage_budgets(self) -> dict[str, int]:
        """
        Compute trial budgets for each stage.

        Returns:
            Dict with keys: 'init', 'stage1_full', 'stage2_reduced', 'stage3_refined', 'total'
        """
        fn, fn_minus_1, fn_minus_2 = self.get_fibonacci_trio(self.fibonacci_target)

        budgets = {
            "init": self.n_initial,
            "stage1_full": fn - self.n_initial,
            "stage2_reduced": fn_minus_1,
            "stage3_refined": fn_minus_2,
            "total": fn + fn_minus_1 + fn_minus_2,
        }

        logger.info(
            f"Fibonacci stepping budgets (F_n={fn}, n_initial={self.n_initial}): "
            f"Init={budgets['init']}, Stage1={budgets['stage1_full']}, "
            f"Stage2={budgets['stage2_reduced']}, Stage3={budgets['stage3_refined']}, "
            f"Total={budgets['total']}"
        )

        return budgets

    def reduce_space(
        self,
        dimensions: list[Dimension],
        top_trials: list[dict[str, Any]],
        k: int,
    ) -> list[Dimension]:
        """
        Narrow search space bounds based on top-K trial parameter values.

        Args:
            dimensions: Original search space dimensions
            top_trials: List of epoch result dicts, sorted by loss (best first)
            k: Number of top trials to use for space reduction

        Returns:
            New list of dimensions with narrowed bounds
        """
        if not top_trials or k <= 0:
            logger.warning("No trials provided for space reduction, keeping original space")
            return dimensions

        # Use top-k trials (or all available if fewer)
        actual_k = min(k, len(top_trials))
        top_k = top_trials[:actual_k]

        logger.info(f"Reducing search space based on top {actual_k} trials with factor {self.space_reduction}")

        new_dimensions = []
        for dim in dimensions:
            # Extract parameter values from top trials
            param_name = dim.name
            values = []
            for trial in top_k:
                if "params_dict" in trial and param_name in trial["params_dict"]:
                    values.append(trial["params_dict"][param_name])

            if not values:
                logger.debug(f"No values for parameter {param_name}, keeping original bounds")
                new_dimensions.append(dim)
                continue

            vmin = min(values)
            vmax = max(values)
            span = vmax - vmin

            # Handle different dimension types
            if isinstance(dim, Integer):
                # For integers, ensure we keep at least the original range if span is 0
                if span == 0:
                    margin = max(1, int((dim.high - dim.low) * self.space_reduction))
                else:
                    margin = max(1, int(span * self.space_reduction))

                new_low = max(dim.low, vmin - margin)
                new_high = min(dim.high, vmax + margin)

                # Ensure valid range
                if new_low >= new_high:
                    new_low = dim.low
                    new_high = dim.high

                new_dim = Integer(new_low, new_high, name=param_name)
                logger.debug(f"  {param_name}: [{dim.low}, {dim.high}] -> [{new_low}, {new_high}]")
                new_dimensions.append(new_dim)

            elif isinstance(dim, Real):
                if span == 0:
                    margin = (dim.high - dim.low) * self.space_reduction
                else:
                    margin = span * self.space_reduction

                new_low = max(dim.low, vmin - margin)
                new_high = min(dim.high, vmax + margin)

                if new_low >= new_high:
                    new_low = dim.low
                    new_high = dim.high

                new_dim = Real(new_low, new_high, name=param_name, prior=dim.prior)
                logger.debug(f"  {param_name}: [{dim.low}, {dim.high}] -> [{new_low:.4f}, {new_high:.4f}]")
                new_dimensions.append(new_dim)

            elif hasattr(dim, 'decimals'):  # SKDecimal
                # SKDecimal inherits from Integer but has decimals attribute
                decimals = getattr(dim, 'decimals', 3)
                scale = 10 ** decimals

                if span == 0:
                    margin = max(1, int((dim.high - dim.low) * scale * self.space_reduction))
                else:
                    margin = max(1, int(span * scale * self.space_reduction))

                new_low = max(dim.low, vmin - margin / scale)
                new_high = min(dim.high, vmax + margin / scale)

                if new_low >= new_high:
                    new_low = dim.low
                    new_high = dim.high

                from freqtrade.optimize.space import SKDecimal
                new_dim = SKDecimal(new_low, new_high, decimals=decimals, name=param_name)
                logger.debug(f"  {param_name}: [{dim.low}, {dim.high}] -> [{new_low:.4f}, {new_high:.4f}]")
                new_dimensions.append(new_dim)

            elif isinstance(dim, Categorical):
                # For categorical, keep only categories that appear in top-k trials
                top_categories = sorted(set(values))
                # Always keep at least 1 category, fallback to original if needed
                if not top_categories:
                    top_categories = dim.categories
                elif len(top_categories) == 1:
                    # If only one category appears, add nearby categories from original
                    original_cats = list(dim.categories)
                    idx = original_cats.index(top_categories[0])
                    # Add neighbors if available
                    if idx > 0:
                        top_categories.insert(0, original_cats[idx - 1])
                    if idx < len(original_cats) - 1:
                        top_categories.append(original_cats[idx + 1])

                new_dim = Categorical(top_categories, name=param_name)
                logger.debug(f"  {param_name}: {dim.categories} -> {top_categories}")
                new_dimensions.append(new_dim)

            else:
                # Unknown dimension type, keep as-is
                logger.warning(f"Unknown dimension type {type(dim)} for {param_name}, keeping original")
                new_dimensions.append(dim)

        return new_dimensions

    def get_stage_names(self) -> list[str]:
        """Return ordered list of stage names."""
        return ["init", "stage1_full", "stage2_reduced", "stage3_refined"]

    def get_stage_info(self, stage_name: str) -> dict[str, Any]:
        """Get information about a specific stage."""
        budgets = self.compute_stage_budgets()
        fn, fn_minus_1, fn_minus_2 = self.get_fibonacci_trio(self.fibonacci_target)

        info = {
            "init": {
                "name": "Initialization",
                "trials": budgets["init"],
                "space": "full",
                "description": "Random exploration",
            },
            "stage1_full": {
                "name": "Stage 1 (Full Space)",
                "trials": budgets["stage1_full"],
                "space": "full",
                "description": f"Bayesian optimization on full space (F_n={fn})",
            },
            "stage2_reduced": {
                "name": "Stage 2 (Reduced Space)",
                "trials": budgets["stage2_reduced"],
                "space": "reduced",
                "description": f"Bayesian optimization on reduced space (F_{{n-1}}={fn_minus_1})",
            },
            "stage3_refined": {
                "name": "Stage 3 (Refined Space)",
                "trials": budgets["stage3_refined"],
                "space": "further_reduced",
                "description": f"Bayesian optimization on further reduced space (F_{{n-2}}={fn_minus_2})",
            },
        }

        return info.get(stage_name, {})