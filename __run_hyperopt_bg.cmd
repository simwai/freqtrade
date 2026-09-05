@echo off
REM Long, full-featured hyperopt run for VixFixMultiLab
REM Config: 180-day train, 7-day test, 7-day step on 10-pair USDC universe
REM All hyperoptable spaces (buy + sell + roi + stoploss), 200 epochs
REM Single worker (Windows joblib compatibility)

cd /d "M:\Documents\Programming\Python\freqtrade"

python -m freqtrade walk-forward ^
  --config user_data\config_vixfixmultilab_walkforward.json ^
  --strategy VixFixMultiLab ^
  --timerange 20250304-20260904 ^
  --train-days 180 ^
  --test-days 7 ^
  --step-days 7 ^
  --epochs 200 ^
  --spaces all ^
  --hyperopt-loss SharpeHyperOptLossDaily ^
  -j 1 ^
  --logfile user_data\__hyperopt_bg.log
