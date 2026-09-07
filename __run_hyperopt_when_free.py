# Wait for the freqtrade hyperopt lock to clear, then launch the
# VixFixMultiLab long hyperopt.
#
# The lock check has a race: the freqtrade child prints the lock-rejection
# message in ~1s, then exits in another ~0.5s. Reading the log file at
# 1-second intervals can miss the message if the read lands between the
# print and the close. The reliable fix is: open the log with line
# buffering on the freqtrade side, and poll the log file by stat
# (size) - if the size stops growing, the process is done.

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"M:\Documents\Programming\Python\freqtrade")
log_file = REPO / "user_data" / "__hyperopt_bg.log"
waiter_log = REPO / "user_data" / "__hyperopt_waiter.log"

cmd = [
    sys.executable, "-u", "-m", "freqtrade", "walk-forward",
    "--config", "user_data/config_vixfixmultilab_walkforward.json",
    "--strategy", "VixFixMultiLab",
    "--timerange", "20240104-20260904",
    "--train-days", "180",
    "--test-days", "7",
    "--step-days", "7",
    "--epochs", "200",
    "--spaces", "buy", "sell", "roi", "stoploss", "trailing",
    "--hyperopt-loss", "SharpeHyperOptLossDaily",
    "-j", "1",
    "--logfile", str(log_file),
]

LOCK_MESSAGE = "Another running instance of freqtrade Hyperopt detected"
POLL_SECONDS = 60
MAX_WAIT_SECONDS = 60 * 60
GRACE_SECONDS = 5  # min time a healthy hyperopt child stays alive after launch


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with waiter_log.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


log("waiter started")
start = time.time()
attempt = 0
while True:
    attempt += 1
    elapsed = time.time() - start
    log(f"attempt {attempt}, elapsed {elapsed:.0f}s")
    if log_file.exists():
        log_file.unlink()
    # Open with -u (unbuffered) so lines hit disk promptly.
    with log_file.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=f, stderr=subprocess.STDOUT)
    pid = proc.pid
    # Wait GRACE_SECONDS for either the lock message or a stable alive child.
    lock_seen = False
    for tick in range(GRACE_SECONDS):
        time.sleep(1)
        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            content = ""
        if LOCK_MESSAGE in content:
            log("  lock held")
            lock_seen = True
            break
    if lock_seen:
        try:
            proc.kill()
        except Exception:
            pass
        proc.wait(timeout=5)
        if time.time() - start > MAX_WAIT_SECONDS:
            log(f"timed out after {MAX_WAIT_SECONDS}s")
            sys.exit(2)
        time.sleep(POLL_SECONDS - GRACE_SECONDS)
        continue
    # No lock message after grace. Verify the child is still alive.
    if proc.poll() is not None:
        # Exited unexpectedly.
        content = log_file.read_text(encoding="utf-8", errors="replace")
        log(f"  process exited rc={proc.returncode}")
        log("--- last 2000 chars of log ---")
        log(content[-2000:])
        if "Traceback" in content or "Fatal" in content:
            log("fatal error, not retrying")
            sys.exit(1)
        # Maybe a benign early exit; retry after a short wait.
        time.sleep(10)
        continue
    log(f"  PID {pid} alive past grace; lock acquired")
    log(f"  log: {log_file}")
    sys.exit(0)
