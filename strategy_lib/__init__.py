"""
strategy_lib

Reusable, strategy-agnostic components for Freqtrade strategies:

* ``strategy_lib.indicators`` - vectorized indicator primitives (Hann ATR,
  classic / adaptive PSAR, TTM squeeze bands, higher-timeframe EMA merge,
  crossing helpers, entry-index lookup).
* ``strategy_lib.risk`` - configurable structural SL/TP level engine and exit
  helpers (SlTpConfig, TradeLevelsManager, exit_cross_signal, ...).

Import from any strategy under ``user_data/strategies``::

    from strategy_lib.indicators import hann_atr, classic_psar
    from strategy_lib.risk import SlTpConfig, TradeLevelsManager

The package lives at the repository root so that hyperopt worker processes can
import it (they receive the repo root on ``sys.path``).
"""

from strategy_lib import indicators, risk


__all__ = ["indicators", "risk"]
