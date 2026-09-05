# Long, full-featured hyperopt run for VixFixMultiLab
# Config: 180-day train, 7-day test, 7-day step on 10-pair USDC universe
# All hyperoptable spaces (buy + sell + roi + stoploss), 200 epochs
# Single worker (Windows joblib compatibility)

import subprocess
import sys
from pathlib import Path

REPO = Path(r"M:\Documents\Programming\Python\freqtrade")
log_file = REPO / "user_data" / "__hyperopt_bg.log"

# Long timerange: 180 days x 4 windows = 720 days coverage.
# 2024-01-04 (earliest data) to 2026-09-04 is ~974 days, plenty.
cmd = [
    sys.executable, "-m", "freqtrade", "walk-forward",
    "--config", "user_data/config_vixfixmultilab_walkforward.json",
    "--strategy", "VixFixMultiLab",
    "--timerange", "20240104-20260904",
    "--train-days", "180",
    "--test-days", "7",
    "--step-days", "7",
    "--epochs", "200",
    "--spaces", "all",
    "--hyperopt-loss", "SharpeHyperOptLossDaily",
    "-j", "1",
    "--logfile", str(log_file),
]

print(f"Launching hyperopt: {' '.join(cmd)}")
with log_file.open("w", encoding="utf-8") as f:
    proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=f, stderr=subprocess.STDOUT)
print(f"Started PID {proc.pid}, log -> {log_file}")
