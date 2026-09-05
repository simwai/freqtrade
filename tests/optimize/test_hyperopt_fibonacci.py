"""
Tests for Fibonacci stepping hyperopt functionality.
"""

from unittest.mock import patch

import pytest

from freqtrade.optimize.hyperopt.fibonacci_stepping import FibonacciStepping
from freqtrade.optimize.hyperopt.hyperopt_optimizer import HyperOptimizer


class MockConfig:
    """Mock config for testing."""

    def __init__(self, **kwargs):
        self._data = {
            "hyperopt_fibonacci_target": 34,
            "hyperopt_initial_points": 10,
            "hyperopt_space_reduction": 0.15,
            "hyperopt_estimator": "ET",
        }
        self._data.update(kwargs)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data


def test_fibonacci_sequence_generation():
    """Test Fibonacci sequence generation."""
    config = MockConfig()
    fs = FibonacciStepping(config)

    # Test sequence generation
    seq = fs._generate_fibonacci_sequence(100)
    expected = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
    assert seq == expected


def test_get_fibonacci_trio():
    """Test getting Fibonacci trio (F_n, F_{n-1}, F_{n-2})."""
    config = MockConfig(hyperopt_fibonacci_target=34)
    fs = FibonacciStepping(config)

    fn, fn_1, fn_2 = fs.get_fibonacci_trio(34)
    assert fn == 34
    assert fn_1 == 21
    assert fn_2 == 13

    # Test with 55
    config._data["hyperopt_fibonacci_target"] = 55
    fs2 = FibonacciStepping(config)
    fn, fn_1, fn_2 = fs2.get_fibonacci_trio(55)
    assert fn == 55
    assert fn_1 == 34
    assert fn_2 == 21


def test_compute_stage_budgets():
    """Test stage budget computation."""
    config = MockConfig(hyperopt_fibonacci_target=34, hyperopt_initial_points=10)
    fs = FibonacciStepping(config)

    budgets = fs.compute_stage_budgets()
    assert budgets["init"] == 10
    assert budgets["stage1_full"] == 24  # 34 - 10
    assert budgets["stage2_reduced"] == 21
    assert budgets["stage3_refined"] == 13
    assert budgets["total"] == 68  # 10 + 24 + 21 + 13


def test_compute_stage_budgets_f55():
    """Test stage budget computation with F_10=55."""
    config = MockConfig(hyperopt_fibonacci_target=55, hyperopt_initial_points=15)
    fs = FibonacciStepping(config)

    budgets = fs.compute_stage_budgets()
    assert budgets["init"] == 15
    assert budgets["stage1_full"] == 40  # 55 - 15
    assert budgets["stage2_reduced"] == 34
    assert budgets["stage3_refined"] == 21
    assert budgets["total"] == 110  # 15 + 40 + 34 + 21


def test_validate_config_success():
    """Test config validation passes for valid settings."""
    config = MockConfig(hyperopt_fibonacci_target=34, hyperopt_initial_points=10)
    FibonacciStepping(config)
    # Should not raise


def test_validate_config_invalid_fibonacci_target():
    """Test config validation fails for non-Fibonacci target."""
    config = MockConfig(hyperopt_fibonacci_target=30)  # Not a Fibonacci number
    with pytest.raises(Exception) as exc_info:
        FibonacciStepping(config)
    assert "must be a Fibonacci number" in str(exc_info.value)


def test_validate_config_target_too_small():
    """Test config validation fails for target < 34."""
    config = MockConfig(hyperopt_fibonacci_target=21)
    with pytest.raises(Exception) as exc_info:
        FibonacciStepping(config)
    assert "must be >= 34" in str(exc_info.value)


def test_validate_config_initial_points_too_large():
    """Test config validation fails when initial points too large."""
    config = MockConfig(hyperopt_fibonacci_target=34, hyperopt_initial_points=30)
    with pytest.raises(Exception) as exc_info:
        FibonacciStepping(config)
    assert "Stage 1 would have only" in str(exc_info.value)


def test_validate_config_space_reduction_out_of_range():
    """Test config validation fails for space reduction out of range."""
    config = MockConfig(hyperopt_space_reduction=0.6)
    with pytest.raises(Exception) as exc_info:
        FibonacciStepping(config)
    assert "between 0.01 and 0.5" in str(exc_info.value)


def test_validate_config_invalid_estimator():
    """Test config validation fails for invalid estimator."""
    config = MockConfig(hyperopt_estimator="INVALID")
    with pytest.raises(Exception) as exc_info:
        FibonacciStepping(config)
    assert "must be one of GP, RF, ET, GBRT" in str(exc_info.value)


def test_reduce_space_integer():
    """Test space reduction for Integer dimensions."""
    config = MockConfig()
    fs = FibonacciStepping(config)

    from skopt.space import Integer

    dimensions = [Integer(0, 100, name="test_param")]

    # Top trials with values around 50
    top_trials = [
        {"params_dict": {"test_param": 48}},
        {"params_dict": {"test_param": 52}},
        {"params_dict": {"test_param": 50}},
    ]

    new_dims = fs.reduce_space(dimensions, top_trials, k=3)
    assert len(new_dims) == 1
    assert isinstance(new_dims[0], Integer)
    # With 15% reduction: span=4, margin=1 (min 1)
    # Bounds should be ~[47, 53] clipped to [0, 100]
    assert new_dims[0].low >= 0
    assert new_dims[0].high <= 100


def test_reduce_space_categorical():
    """Test space reduction for Categorical dimensions."""
    config = MockConfig()
    fs = FibonacciStepping(config)

    from skopt.space import Categorical

    dimensions = [Categorical(["a", "b", "c", "d", "e"], name="cat_param")]

    # Top trials only use 'b' and 'c'
    top_trials = [
        {"params_dict": {"cat_param": "b"}},
        {"params_dict": {"cat_param": "c"}},
        {"params_dict": {"cat_param": "b"}},
    ]

    new_dims = fs.reduce_space(dimensions, top_trials, k=3)
    assert len(new_dims) == 1
    assert isinstance(new_dims[0], Categorical)
    # Should keep 'b' and 'c' and their neighbors 'a' and 'd'
    categories = set(new_dims[0].categories)
    assert "b" in categories
    assert "c" in categories
    # Neighbors may be added


def test_reduce_space_skdecimal():
    """Test space reduction for SKDecimal dimensions."""
    config = MockConfig()
    fs = FibonacciStepping(config)

    from freqtrade.optimize.space import SKDecimal

    dimensions = [SKDecimal(0.0, 1.0, decimals=3, name="decimal_param")]

    # Top trials around 0.5
    top_trials = [
        {"params_dict": {"decimal_param": 0.48}},
        {"params_dict": {"decimal_param": 0.52}},
        {"params_dict": {"decimal_param": 0.50}},
    ]

    new_dims = fs.reduce_space(dimensions, top_trials, k=3)
    assert len(new_dims) == 1
    assert isinstance(new_dims[0], SKDecimal)
    # SKDecimal stores values as scaled integers internally
    # Use low_orig/high_orig for original float bounds
    assert new_dims[0].low_orig >= 0.0
    assert new_dims[0].high_orig <= 1.0


def test_get_stage_info():
    """Test stage info retrieval."""
    config = MockConfig(hyperopt_fibonacci_target=34, hyperopt_initial_points=10)
    fs = FibonacciStepping(config)

    info = fs.get_stage_info("stage1_full")
    assert info["name"] == "Stage 1 (Full Space)"
    assert info["trials"] == 24
    assert info["space"] == "full"


def test_get_stage_names():
    """Test stage names list."""
    config = MockConfig()
    fs = FibonacciStepping(config)

    names = fs.get_stage_names()
    assert names == ["init", "stage1_full", "stage2_reduced", "stage3_refined"]


class TestHyperOptimizerReset:
    """Tests for HyperOptimizer.reset_optimizer method."""

    @patch(
        "freqtrade.optimize.hyperopt.hyperopt_optimizer.HyperOptimizer.__init__",
        return_value=None,
    )
    def test_reset_optimizer_basic(self, mock_init):
        """Test basic optimizer reset functionality."""
        optimizer = HyperOptimizer.__new__(HyperOptimizer)
        optimizer.dimensions = []
        optimizer.buy_space = []
        optimizer.sell_space = []
        optimizer.protection_space = []
        optimizer.roi_space = []
        optimizer.stoploss_space = []
        optimizer.trailing_space = []
        optimizer.max_open_trades_space = []

        from skopt.space import Integer

        new_dims = [Integer(0, 10, name="buy_test"), Integer(0, 5, name="sell_test")]

        optimizer.reset_optimizer(new_dims)

        assert len(optimizer.dimensions) == 2
        assert len(optimizer.buy_space) == 1
        assert len(optimizer.sell_space) == 1
        assert optimizer.buy_space[0].name == "buy_test"
        assert optimizer.sell_space[0].name == "sell_test"


def test_fibonacci_stepping_stage_budgets_edge_cases():
    """Test edge cases for stage budgets."""
    # Test with minimal valid config (F_9=34, n_initial=10 gives Stage1=24)
    # n_initial=29 gives Stage1=5 (minimum), so n_initial=30 should fail
    config = MockConfig(hyperopt_fibonacci_target=34, hyperopt_initial_points=30)
    with pytest.raises(Exception) as exc_info:
        FibonacciStepping(config)
    assert "Stage 1 would have only 4 trials" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
