import logging
from typing import Any

from freqtrade import constants
from freqtrade.enums import RunMode
from freqtrade.exceptions import ConfigurationError, OperationalException


logger = logging.getLogger(__name__)


def setup_optimize_configuration(args: dict[str, Any], method: RunMode) -> dict[str, Any]:
    """
    Prepare the configuration for the Hyperopt module
    :param args: Cli args from Arguments()
    :param method: Bot running mode
    :return: Configuration
    """
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.util import fmt_coin, get_dry_run_wallet

    config = setup_utils_configuration(args, method)

    no_unlimited_runmodes = {
        RunMode.BACKTEST: "backtesting",
        RunMode.HYPEROPT: "hyperoptimization",
    }
    if method in no_unlimited_runmodes:
        wallet_size = get_dry_run_wallet(config) * config["tradable_balance_ratio"]
        # tradable_balance_ratio
        if (
            config["stake_amount"] != constants.UNLIMITED_STAKE_AMOUNT
            and config["stake_amount"] > wallet_size
        ):
            wallet = fmt_coin(wallet_size, config["stake_currency"])
            stake = fmt_coin(config["stake_amount"], config["stake_currency"])
            raise ConfigurationError(
                f"Starting balance ({wallet}) is smaller than stake_amount {stake}. "
                f"Wallet is calculated as `dry_run_wallet * tradable_balance_ratio`."
            )

    return config


def start_backtesting(args: dict[str, Any]) -> None:
    """
    Start Backtesting script
    :param args: Cli args from Arguments()
    :return: None
    """
    # Import here to avoid loading backtesting module when it's not used
    from freqtrade.optimize.backtesting import Backtesting

    # Initialize configuration
    config = setup_optimize_configuration(args, RunMode.BACKTEST)

    logger.info("Starting freqtrade in Backtesting mode")

    # Initialize backtesting object
    backtesting = Backtesting(config)
    backtesting.start()


def start_backtesting_show(args: dict[str, Any]) -> None:
    """
    Show previous backtest result
    """
    from freqtrade.configuration import setup_utils_configuration

    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)

    from freqtrade.data.btanalysis import load_backtest_stats
    from freqtrade.optimize.optimize_reports import show_backtest_results, show_sorted_pairlist

    results = load_backtest_stats(
        config["exportdirectory"] / config["exportfilename"]
        if config.get("exportfilename")
        else config["exportdirectory"]
    )

    show_backtest_results(config, results)
    show_sorted_pairlist(config, results)


def start_hyperopt(args: dict[str, Any]) -> None:
    """
    Start hyperopt script
    :param args: Cli args from Arguments()
    :return: None
    """
    # Import here to avoid loading hyperopt module when it's not used
    try:
        from filelock import FileLock, Timeout

        from freqtrade.optimize.hyperopt import FibonacciHyperopt, Hyperopt
    except ImportError as e:
        raise OperationalException(
            f"{e}. Please ensure that the hyperopt dependencies are installed."
        ) from e
    # Initialize configuration
    config = setup_optimize_configuration(args, RunMode.HYPEROPT)

    # Auto-detect Fibonacci mode: if any fibonacci arg is provided, use FibonacciHyperopt
    fibonacci_mode = any(
        args.get(key) is not None
        for key in (
            "hyperopt_fibonacci_target",
            "hyperopt_initial_points",
            "hyperopt_space_reduction",
            "hyperopt_estimator",
        )
    )

    logger.info(f"Starting freqtrade in Hyperopt mode {'(Fibonacci)' if fibonacci_mode else ''}")

    lock = FileLock(Hyperopt.get_lock_filename(config))

    try:
        with lock.acquire(timeout=1):
            # Remove noisy log messages
            logging.getLogger("hyperopt.tpe").setLevel(logging.WARNING)
            logging.getLogger("filelock").setLevel(logging.WARNING)

            # Initialize hyperopt object (Fibonacci or standard)
            hyperopt: Hyperopt | FibonacciHyperopt
            if fibonacci_mode:
                hyperopt = FibonacciHyperopt(config)
            else:
                hyperopt = Hyperopt(config)
            hyperopt.start()

    except Timeout:
        logger.info("Another running instance of freqtrade Hyperopt detected.")
        logger.info(
            "Simultaneous execution of multiple Hyperopt commands is not supported. "
            "Hyperopt module is resource hungry. Please run your Hyperopt sequentially "
            "or on separate machines."
        )
        logger.info("Quitting now.")
        # TODO: return False here in order to help freqtrade to exit
        # with non-zero exit code...
        # Same in Edge and Backtesting start() functions.


def start_edge(args: dict[str, Any]) -> None:
    """
    Start Edge script
    :param args: Cli args from Arguments()
    :return: None
    """
    raise ConfigurationError(
        "The Edge module has been deprecated in 2023.9 and removed in 2025.6. "
        "All functionalities of edge have been removed."
    )


def start_lookahead_analysis(args: dict[str, Any]) -> None:
    """
    Start the backtest bias tester script
    :param args: Cli args from Arguments()
    :return: None
    """
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.optimize.analysis.lookahead_helpers import LookaheadAnalysisSubFunctions

    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)
    LookaheadAnalysisSubFunctions.start(config)


def start_recursive_analysis(args: dict[str, Any]) -> None:
    """
    Start the backtest recursive tester script
    :param args: Cli args from Arguments()
    :return: None
    """
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.optimize.analysis.recursive_helpers import RecursiveAnalysisSubFunctions

    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)
    RecursiveAnalysisSubFunctions.start(config)


def start_walkforward(args: dict[str, Any]) -> None:
    """
    Start walk-forward optimization script
    :param args: Cli args from Arguments()
    :return: None
    """
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.optimize.walkforward import WalkForwardHistoricalRunner

    config = setup_utils_configuration(args, RunMode.HYPEROPT)

    logger.info("Starting freqtrade in Walk-Forward Optimization mode")

    # Apply walkforward settings from CLI args to config
    if args.get("walkforward_train_days"):
        config.setdefault("walk_forward", {})["train_days"] = args["walkforward_train_days"]
    if args.get("walkforward_test_days"):
        config.setdefault("walk_forward", {})["test_days"] = args["walkforward_test_days"]
    if args.get("walkforward_step_days"):
        config.setdefault("walk_forward", {})["step_days"] = args["walkforward_step_days"]
    if args.get("walkforward_schedule"):
        config.setdefault("walk_forward", {})["schedule"] = args["walkforward_schedule"]
    if args.get("walkforward_min_trades"):
        config.setdefault("walk_forward", {})["min_trades"] = args["walkforward_min_trades"]
    if args.get("walkforward_max_drawdown") is not None:
        config.setdefault("walk_forward", {})["max_drawdown"] = args["walkforward_max_drawdown"]

    walkforward = WalkForwardHistoricalRunner(config)
    walkforward.run()


def start_lab(args: dict[str, Any]) -> None:
    """
    Start SSE log stream server (lab mode).
    :param args: Cli args from Arguments()
    :return: None
    """
    import asyncio
    import signal

    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.rpc.sse_log_stream import SSELogStream, remove_sse_logging, setup_sse_logging

    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)

    logger.info("Starting freqtrade in Lab mode (SSE log stream)")

    sse_stream = SSELogStream(config)
    handler = setup_sse_logging(config, sse_stream)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _background_tasks: set = set()

    def _signal_handler():
        logger.info("Lab mode interrupted by user")
        task = loop.create_task(sse_stream.stop())
        _background_tasks.add(task)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        loop.run_until_complete(sse_stream.start())
        logger.info(
            "Lab mode running on http://%s:%d/logs - Press Ctrl+C to stop",
            config.get("lab_host", "127.0.0.1"),
            config.get("lab_port", 8080),
        )
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Lab mode interrupted by user")
    finally:
        loop.run_until_complete(sse_stream.stop())
        loop.close()
        remove_sse_logging(handler)
        logger.info("Lab mode stopped")
