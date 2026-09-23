"""Edge command wrapper."""

import logging

logger = logging.getLogger(__name__)


def start_edge(args: dict) -> None:
    """
    Start Edge backtest via the re-enabled edge module.
    """
    try:
        from freqtrade.configuration import setup_utils_configuration
        from freqtrade.enums import RunMode

        from freqtrade_local.optimize.edge_cli import EdgeCli

        config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)
        cli = EdgeCli(config)
        cli.start()
    except Exception as e:
        logger.error("Edge command failed: %s", e)
        raise
