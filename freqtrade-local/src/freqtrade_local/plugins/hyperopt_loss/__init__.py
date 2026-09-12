"""Custom hyperopt loss plugins."""

from freqtrade_local.plugins.hyperopt_loss.hyperopt_loss_dd_constrained import (  # noqa: F401
    DrawdownConstrainedHyperOptLoss,
)

__all__ = ["DrawdownConstrainedHyperOptLoss"]
