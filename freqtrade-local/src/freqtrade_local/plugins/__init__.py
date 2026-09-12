"""freqtrade-local plugins."""

from freqtrade_local.plugins.hyperopt_loss import (  # noqa: F401
    DrawdownConstrainedHyperOptLoss,
)
from freqtrade_local.plugins.pairlist import CorrelationPairList  # noqa: F401

__all__ = [
    "CorrelationPairList",
    "DrawdownConstrainedHyperOptLoss",
]
