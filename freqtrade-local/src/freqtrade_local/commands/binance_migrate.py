"""Binance futures migration command wrapper."""
import logging

from freqtrade_local.util.migrations.binance_mig import (
    migrate_binance_futures_names,  # noqa: F401
)

logger = logging.getLogger(__name__)


def start_migrate_binance_futures(args: dict) -> None:
    """Migrate Binance futures pair names in database and data files."""
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode

    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)
    migrate_binance_futures_names(config)
