# Wait for the freqtrade hyperopt lock to clear, then launch the
# VixFixMultiLab long hyperopt.

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"M:\Documents\Programming\Python\freqtrade")
log_file = REPO / "user_data" / "__hyperopt_bg.log"

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

LOCK_MESSAGE = "Another running instance of freqtrade Hyperopt detected"
ALIVE_GRACE_SECONDS = 4
POLL_SECONDS = 60
MAX_WAIT_SECONDS = 60 * 60

start = time.time()
attempt = 0
while True:
    attempt += 1
    elapsed = time.time() - start
    print(f"[{time.strftime('%H:%M:%S')}] attempt {attempt}, elapsed {elapsed:.0f}s")
    if log_file.exists():
        log_file.unlink()
    with log_file.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=f, stderr=subprocess.STDOUT)
    # The lock-rejection message is printed in ~1-2s. The real hyperopt
    # run takes far longer than 4s to either print that message or to
    # get past the strategy resolution step.
    acquired = True
    for _ in range(ALIVE_GRACE_SECONDS):
        time.sleep(1)
        with log_file.open("r", encoding="utf-8") as f2:
            content = f2.read()
        if LOCK_MESSAGE in content:
            print(f"  lock held, retrying in {POLL_SECONDS - ALIVE_GRACE_SECONDS}s")
            acquired = False
            try:
                proc.kill()
            except Exception:
                pass
            time.sleep(POLL_SECONDS - ALIVE_GRACE_SECONDS)
            break
    if not acquired:
        continue
    # Process is alive past the grace period and no lock message was found.
    if proc.poll() is not None:
        # Already exited; treat as failure.
        with log_file.open("r", encoding="utf-8") as f2:
            content = f2.read()
        if "Traceback" in content or "Fatal" in content:
            print("  fatal error, will not retry")
            print(content[-2000:])
            sys.exit(1)
    # Success
    print(f"  PID {proc.pid} running, lock acquired")
    print(f"  log: {log_file}")
    print(f"  cmd: {' '.join(cmd)}")
    sys.exit(0)
    if time.time() - start > MAX_WAIT_SECONDS:
        print(f"timed out after {MAX_WAIT_SECONDS}s waiting for the hyperopt lock")
        sys.exit(2)
