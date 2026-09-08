"""Stub to recover missing bt_fileutils module blocked by missing file."""
from pathlib import Path

BT_DATA_COLUMNS = []


def find_existing_backtest_stats(
    results_directory: Path,
    run_ids: dict[str, str],
    min_backtest_date,
):
    return None


def delete_backtest_result(
    results_directory: Path, strategy_name: str, result_file_name: str
) -> None:
    pass


def extract_trades_of_period(*_, **__):
    pass


def get_backtest_market_change(*_, **__):
    return 0.0


def get_backtest_result(*_, **__):
    return None


def get_backtest_resultlist(*_, **__):
    return []


def get_backtest_wallet_change(*_, **__):
    return 0.0


def get_latest_backtest_filename(*_, **__):
    return None


def get_latest_hyperopt_file(*_, **__):
    return None


def get_latest_hyperopt_filename(*_, **__):
    return None


def get_latest_optimize_filename(*_, **__):
    return None


def load_and_merge_backtest_result(*_, **__):
    pass


def load_backtest_analysis_data(*_, **__):
    pass


def load_backtest_data(*_, **__):
    pass


def load_backtest_metadata(*_, **__):
    return {}


def load_backtest_stats(*_, **__):
    return None


def load_file_from_zip(*_, **__):
    pass


def load_trades(*_, **__):
    return []


def load_trades_from_db(*_, **__):
    return []


def trade_list_to_dataframe(*_, **__):
    pass


def update_backtest_metadata(*_, **__):
    pass
