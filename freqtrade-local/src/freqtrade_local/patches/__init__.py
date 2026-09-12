"""Runtime patches for freqtrade overlay."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def apply_backtest_heartbeat(config: dict[str, Any]) -> None:
    """
    Patch Backtesting to support heartbeat logging if the config contains
    backtest_heartbeat_interval.
    """
    interval = config.get("backtest_heartbeat_interval", 0)
    if not interval:
        return

    try:
        from freqtrade.optimize.backtesting import Backtesting

        # Install thread-based heartbeat if not already present
        if not hasattr(Backtesting, "_heartbeat_patched"):
            _install_heartbeat(Backtesting, interval)
            Backtesting._heartbeat_patched = True  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning("Failed to apply backtest heartbeat patch: %s", e)


def _install_heartbeat(Backtesting: type, interval: int) -> None:
    """
    Install a heartbeat thread on Backtesting that logs progress at the
    requested interval.
    """
    original_init = Backtesting.__init__

    def patched_init(self, config: dict[str, Any], *args, **kwargs):
        original_init(self, config, *args, **kwargs)
        self._heartbeat_interval = interval
        self._heartbeat_stop_event = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(self, self._heartbeat_stop_event, interval),
            daemon=True,
        )
        self._heartbeat_thread.start()

    Backtesting.__init__ = patched_init  # type: ignore[method-assign]

    original_cleanup = getattr(Backtesting, "cleanup", None)

    def patched_cleanup(self, *args, **kwargs):
        stop_event = getattr(self, "_heartbeat_stop_event", None)
        if stop_event is not None:
            stop_event.set()
            join_target = getattr(self, "_heartbeat_thread", None)
            if join_target is not None:
                join_target.join(timeout=5)
        if original_cleanup is not None:
            original_cleanup(self, *args, **kwargs)

    Backtesting.cleanup = patched_cleanup  # type: ignore[method-assign]


def _heartbeat_loop(
    backtesting: Any,
    stop_event: threading.Event,
    interval: int,
) -> None:
    """
    Background thread that emits heartbeat log entries while backtesting.
    """
    while not stop_event.wait(timeout=interval):
        try:
            progress = getattr(backtesting, "progress", None)
            if progress is not None:
                logger.info(
                    "Backtest heartbeat: %s",
                    progress,
                )
        except Exception as exc:  # pragma: no cover
            logger.debug("Heartbeat loop error: %s", exc)


def apply_config_schema_patch() -> None:
    """
    Patch freqtrade's config schema to accept overlay-specific keys
    before user config is validated.
    """
    try:
        from freqtrade.config_schema.config_schema import CONF_SCHEMA

        CONF_SCHEMA.setdefault("properties", {})[
            "backtest_heartbeat_interval"
        ] = {
            "description": (
                "Log backtest progress every N seconds. "
                "0 disables heartbeat logging."
            ),
            "type": "integer",
            "minimum": 0,
        }
    except Exception as e:
        logger.warning("Failed to apply config schema patch: %s", e)


def apply_all(config: dict[str, Any]) -> None:
    """Apply all runtime patches."""
    apply_config_schema_patch()
    apply_backtest_heartbeat(config)
