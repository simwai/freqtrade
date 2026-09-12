"""Walk-forward optimization command wrapper."""

import logging

logger = logging.getLogger(__name__)


def start_walkforward(args: dict) -> None:
    """
    Start walk-forward optimization.
    """
    try:
        from freqtrade.configuration import setup_utils_configuration
        from freqtrade.enums import RunMode

        from freqtrade_local.optimize.walkforward import WalkForwardHistoricalRunner

        config = setup_utils_configuration(args, RunMode.HYPEROPT)

        # Apply walkforward settings from CLI args to config
        if args.get("walkforward_train_days"):
            config.setdefault("walk_forward", {})["train_days"] = args[
                "walkforward_train_days"
            ]
        if args.get("walkforward_test_days"):
            config.setdefault("walk_forward", {})["test_days"] = args[
                "walkforward_test_days"
            ]
        if args.get("walkforward_step_days"):
            config.setdefault("walk_forward", {})["step_days"] = args[
                "walkforward_step_days"
            ]
        if args.get("walkforward_schedule"):
            config.setdefault("walk_forward", {})["schedule"] = args[
                "walkforward_schedule"
            ]
        if args.get("walkforward_min_trades"):
            config.setdefault("walk_forward", {})["min_trades"] = args[
                "walkforward_min_trades"
            ]
        if args.get("walkforward_max_drawdown") is not None:
            config.setdefault("walk_forward", {})["max_drawdown"] = args[
                "walkforward_max_drawdown"
            ]

        walkforward = WalkForwardHistoricalRunner(config)
        walkforward.run()
    except Exception as e:
        logger.error("Walk-forward optimization failed: %s", e)
        raise
