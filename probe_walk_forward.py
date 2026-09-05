import sys, json, logging
sys.dont_write_bytecode = True
logging.disable(logging.CRITICAL)

from pathlib import Path
from freqtrade.configuration import Configuration
from freqtrade.enums import CandleType, RunMode
from freqtrade.data.history import load_data
from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.commands.optimize_commands import setup_optimize_configuration

CONFIG = r"M:\Documents\Programming\Python\freqtrade\user_data\config_benchmark.json"

with open(CONFIG) as f:
    base_cfg = json.load(f)

# Simulate CLI args as parsed by freqtrade's arguments parser
args = {
    "config": [CONFIG],
    "strategy": "ScreenerDpoEveningStar",
    "timerange": "20190908-20260830",
    "train_days": 90,
    "test_days": 7,
    "step_days": 7,
    "epochs": 100,
    "hyperopt_loss": "SharpeHyperOptLossDaily",
    "spaces": ["buy", "sell", "roi", "stoploss", "trailing"],
    "job_workers": -1,
    "min_trades": 1,
    "verbosity": 2,
    "datadir": None,
    "user_data_dir": None,
    "db_url": None,
    "dry_run": True,
    "stake_currency": None,
    "stake_amount": None,
    "max_open_trades": None,
    "dataformat_ohlcv": None,
    "dataformat_trades": None,
    "exchange": None,
    "pairs": None,
    "pairs_file": None,
    "new_pairs_days": None,
    "trading_mode": None,
    "candle_types": None,
    "freqaimodel": None,
    "freqaimodel_path": None,
    "command": "walk-forward",
    "runmode": RunMode.HYPEROPT,
    "position_stacking": False,
    "enable_protections": False,
    "timeframe": None,
    "timeframe_detail": None,
    "backtest_show_pair_list": False,
    "fee": None,
    "hyperopt": None,
    "hyperopt_path": None,
    "hyperoptexportfilename": None,
    "lookahead_analysis_exportfilename": None,
    "print_json": False,
    "export_csv": False,
    "hyperopt_jobs": -1,
    "hyperopt_random_state": None,
    "hyperopt_min_trades": None,
    "analyze_per_epoch": False,
    "print_all": False,
    "recursive_strategy_search": True,
    "export": None,
    "backtest_breakdown": None,
    "backtest_cache": None,
    "disableparamexport": False,
    "freqai_backtest_live_models": False,
    "walk_forward_live": False,
    "walk_forward_run_now": False,
    "walk_forward_train_days": 90,
    "walk_forward_test_days": 7,
    "walk_forward_step_days": 7,
    "walk_forward_schedule": None,
    "walk_forward_min_trades": None,
    "walk_forward_max_drawdown": None,
    "stoploss_range": None,
    "logfile": None,
    "no_color": False,
    "lookahead_analysis_exportfilename_2": None,
}

config = setup_optimize_configuration(args, RunMode.HYPEROPT)
print("candle_type_def:", config.get("candle_type_def"))
print("trading_mode   :", config.get("trading_mode"))
print("datadir        :", config.get("datadir"))
print("pairs (set?)   :", "pairs" in config, "count:", len(config.get("pairs") or []))

# Now load data
from freqtrade.configuration import TimeRange
ddir = Path(config["datadir"])
tr = TimeRange.parse_timerange(config["timerange"])
data = load_data(
    datadir=ddir,
    pairs=config.get("pairs") or [p for p in ["DOGE/USDT:USDT", "XRP/USDT:USDT"]],
    timeframe="15m",
    timerange=tr,
    startup_candles=400,
    fail_without_data=False,
    data_format="feather",
    candle_type=config["candle_type_def"],
)
print(f"loaded {len(data)} pairs")
for p, df in list(data.items())[:3]:
    print(f"  {p}: {len(df)} rows, {df.iloc[0]['date'] if len(df) else None} -> {df.iloc[-1]['date'] if len(df) else None}")
