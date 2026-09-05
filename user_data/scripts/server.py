"""server.py — local web app for the Strategy Lab dashboard.

Serves dashboard.html and provides a JSON API so everything can be done from
the browser instead of the CLI:

    GET   /                        -> dashboard.html
    GET   /api/jobs                -> background job status
    GET   /api/strategies          -> strategy registry
    POST  /api/strategies          -> set status / notes  {name, status, notes}
    GET   /api/data                -> dashboard payload (LAB)
    GET   /api/losses              -> available hyperopt loss functions (autodiscovered)
    POST  /api/refresh             -> ingest + rebuild report
    POST  /api/report              -> rebuild report only
    POST  /api/bench               -> run benchmark  {strategies[], timerange, timeframe}
    POST  /api/run                 -> backtest / hyperopt / walk-forward for one strategy
                                        {mode, strategy, timerange, timeframe, config?, epochs?,
                                         loss?, spaces?, train_days?, test_days?, step_days?,
                                         rebuild?}
    GET   /api/candles             -> OHLCV candles {pair, timeframe, trading_mode?, start?, end?}

Background jobs (ingest/benchmark) run in threads; the UI polls /api/jobs.

Usage:
    python user_data/scripts/server.py [--port 8088]
    python user_data/scripts/lab.py serve
"""

from __future__ import annotations

import argparse
import collections
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

SCRIPTS = Path(__file__).resolve().parent
USER_DATA = SCRIPTS.parent
ANALYSIS = USER_DATA / "analysis"
DB = ANALYSIS / "results.db"
DASHBOARD = ANALYSIS / "dashboard.html"
PYTHON = sys.executable

# Job registry: metadata stays JSON-safe in JOBS; logs live as bounded deques in
# _LOGS (chunked so append/trim are cheap and the shared lock is never held long,
# keeping HTTP endpoints responsive while output floods). _JOB_STOP lets the
# streaming reader notice a stop without touching the lock.
JOBS: dict[str, dict] = {}  # JSON-safe metadata (compat name)
_LOGS: dict[str, collections.deque] = {}  # deque[str] tail chunks per job
_LOG_TOT: dict[str, int] = {}  # total chars ever written per job
_JOB_STOP: dict[str, threading.Event] = {}
_JOB_PROCS: dict[str, subprocess.Popen] = {}
_INDICATOR_MODULE = None
JOB_LOCK = threading.Lock()
_MAX_LOG = 180 * 1024  # tail size kept per job

_LOSSES_CACHE: list[str] | None = None
_FLUSH_LINES = 8  # stream-reader batches this many lines between lock takes
_FLUSH_BYTES = 1024  # 1 KB flush for faster streaming updates

# FIFO job queue: submitted jobs run one at a time on a single worker thread.
# Refresh/report jobs additionally take _REFRESH_LOCK so ingest+report never run
# concurrently with each other; a refresh request that arrives while one is
# running is dropped (they are triggered periodically - queuing them would only
# pile up stale rebuilds).
_JOB_QUEUE: collections.deque = collections.deque()  # (job_id, cmds, single_flight)
_QUEUE_CV = threading.Condition()
_QUEUE_THREAD: threading.Thread | None = None
_REFRESH_LOCK = threading.Lock()
_KEEP_FINISHED_JOBS = 30  # finished jobs kept in the registry before eviction


def _log_append_locked(job_id: str, text: str) -> None:
    """Append to a job's tail buffer; trim from the front while over budget."""
    dq = _LOGS[job_id]
    if text:
        dq.append(text)
        _LOG_TOT[job_id] += len(text)
        over = _LOG_TOT[job_id] - _MAX_LOG
        while over > 0 and dq:
            dropped = len(dq[0])
            over -= dropped
            _LOG_TOT[job_id] -= dropped
            dq.popleft()


def _proc_suspend(proc: subprocess.Popen) -> tuple[bool, str]:
    try:
        import psutil  # type: ignore

        psutil.Process(proc.pid).suspend()
        return True, "suspended via psutil"
    except ImportError:
        pass
    except Exception as e:
        return False, str(e)
    # fallback: SIGSTOP on POSIX
    try:
        import signal as _sig

        os.kill(proc.pid, _sig.SIGSTOP)
        return True, "SIGSTOP sent"
    except Exception as e:
        return False, f"pause not supported on this platform: {e}"


def _proc_resume(proc: subprocess.Popen) -> tuple[bool, str]:
    try:
        import psutil  # type: ignore

        psutil.Process(proc.pid).resume()
        return True, "resumed via psutil"
    except ImportError:
        pass
    except Exception as e:
        return False, str(e)
    try:
        import signal as _sig

        os.kill(proc.pid, _sig.SIGCONT)
        return True, "SIGCONT sent"
    except Exception as e:
        return False, f"resume not supported on this platform: {e}"


# ---------------------------------------------------------------- background jobs


def run_command(cmd: list[str]) -> tuple[int, str]:
    """Run a subprocess, streaming output. Returns (returncode, log)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: list[str] = []
    if proc.stdout:
        for line in proc.stdout:
            lines.append(line.rstrip())
    proc.wait()
    return proc.returncode, "\n".join(lines)


def _run_command_live(job_id: str, cmd: list[str]) -> int:
    """Stream cmd output into the job log live.

    Output is buffered locally and flushed in batches so the shared JOB_LOCK is
    taken rarely even when the child spews thousands of lines; other endpoints
    only contend for milliseconds.
    """
    # PYTHONUNBUFFERED=1 so Python child processes (run_strategy.py, and the
    # freqtrade subprocess it spawns) flush stdout line-by-line into the PIPE.
    # Without this, Python block-buffers stdout to a pipe and the dashboard
    # log only updates when the child fills its buffer or exits - which makes
    # a multi-minute backtest look frozen until the very end.
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    stop_flag = _JOB_STOP.setdefault(job_id, threading.Event())
    with JOB_LOCK:
        _JOB_PROCS[job_id] = proc
        JOBS[job_id]["pid"] = proc.pid
        JOBS[job_id]["cmd"] = " ".join(cmd)
    pending: list[str] = []
    pending_bytes = 0
    try:
        if proc.stdout:
            for line in proc.stdout:
                if stop_flag.is_set():
                    break
                pending.append(line)
                pending_bytes += len(line)
                if len(pending) >= _FLUSH_LINES or pending_bytes >= _FLUSH_BYTES:
                    with JOB_LOCK:
                        _log_append_locked(job_id, "".join(pending))
                    pending.clear()
                    pending_bytes = 0
        proc.wait()
        if pending:
            with JOB_LOCK:
                _log_append_locked(job_id, "".join(pending))
        return proc.returncode if proc.returncode is not None else -1
    finally:
        with JOB_LOCK:
            _JOB_PROCS.pop(job_id, None)


def start_job(name: str, cmd: list[str]) -> str:
    return start_sequence(name, [cmd])


def _prune_jobs_locked() -> None:
    """Evict old finished jobs so JOBS/_LOGS cannot grow unbounded (must hold JOB_LOCK)."""
    finished = sorted(
        (k for k, j in JOBS.items() if j.get("status") in ("done", "error", "stopped", "skipped")),
        key=lambda k: JOBS[k].get("finished") or 0,
    )
    for k in finished[:-_KEEP_FINISHED_JOBS]:
        JOBS.pop(k, None)
        _LOGS.pop(k, None)
        _LOG_TOT.pop(k, None)
        _JOB_STOP.pop(k, None)
        _JOB_PROCS.pop(k, None)


def start_sequence(name: str, cmds: list[list[str]], single_flight: bool = False) -> str:
    """Queue a sequence of commands as one background job with live logs and control.

    Jobs run FIFO on a single worker thread. With single_flight=True the job is
    skipped at run time when a refresh/report job is already active (periodic
    triggers must not queue up). Stop aborts the remaining steps; pause/resume
    suspends the current subprocess. All shared state updates are short critical
    sections so HTTP endpoints stay responsive even while a job floods its log.
    """
    date_str = time.strftime("%Y%m%d")
    base = f"{name}-{date_str}"
    counter = 1
    with JOB_LOCK:
        max_c = 0
        for k in JOBS:
            if k.startswith(f"{base}-"):
                suffix = k[len(f"{base}-") :]
                try:
                    max_c = max(max_c, int(suffix))
                except ValueError:
                    pass
        counter = max_c + 1
    job_id = f"{base}-{counter:04d}"
    with JOB_LOCK:
        JOBS[job_id] = {
            "name": name,
            "status": "queued",
            "created": time.time(),
            "pid": None,
            "cmd": " | ".join(" ".join(c) for c in cmds),
            "paused": False,
        }
        _LOGS[job_id] = collections.deque()
        _LOG_TOT[job_id] = 0
        _JOB_STOP[job_id] = threading.Event()
        _prune_jobs_locked()
    with _QUEUE_CV:
        _JOB_QUEUE.append((job_id, cmds, single_flight))
        _QUEUE_CV.notify()
    _ensure_queue_worker()
    return job_id


def _refresh_step(cmd: list[str]) -> bool:
    """True when a step is ingest/report work - the mutually exclusive part."""
    return any(p.endswith(("ingest_results.py", "build_report.py")) for p in cmd)


def _run_sequence(job_id: str, cmds: list[list[str]], single_flight: bool) -> None:
    stop_flag = _JOB_STOP[job_id]

    def note_locked(text: str) -> None:
        _log_append_locked(job_id, text)

    holds_lock = False
    if single_flight:
        if not _REFRESH_LOCK.acquire(blocking=False):
            with JOB_LOCK:
                JOBS[job_id]["status"] = "skipped"
                JOBS[job_id]["finished"] = time.time()
            with JOB_LOCK:
                _log_append_locked(job_id, "\n-- skipped: refresh/report already running --\n")
            return
        holds_lock = True
    try:
        for idx, cmd in enumerate(cmds):
            with JOB_LOCK:
                if stop_flag.is_set() or JOBS[job_id].get("status") == "stopped":
                    note_locked(f"\n-- job stopped before step {idx + 1}/{len(cmds)} --\n")
                    JOBS[job_id]["finished"] = time.time()
                    return
                JOBS[job_id]["status"] = "running"
                JOBS[job_id]["step"] = f"{idx + 1}/{len(cmds)}"
                JOBS[job_id]["step_cmd"] = " ".join(cmd)
            # ingest/report steps of mixed sequences (e.g. run + rebuild) still
            # respect the one-at-a-time rule against dedicated refresh jobs
            step_lock = not single_flight and _refresh_step(cmd)
            if step_lock:
                _REFRESH_LOCK.acquire()
            try:
                code = _run_command_live(job_id, cmd)
            finally:
                if step_lock:
                    _REFRESH_LOCK.release()
            with JOB_LOCK:
                # stopped during this step
                if stop_flag.is_set() or JOBS[job_id].get("status") == "stopped":
                    JOBS[job_id]["code"] = code
                    JOBS[job_id]["finished"] = time.time()
                    return
                if code != 0:
                    JOBS[job_id]["status"] = "error"
                    JOBS[job_id]["code"] = code
                    JOBS[job_id]["finished"] = time.time()
                    return
        with JOB_LOCK:
            # don't overwrite a stop that raced the final return
            if JOBS[job_id].get("status") in ("running", "queued"):
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["code"] = 0
                JOBS[job_id]["finished"] = time.time()
            JOBS[job_id].pop("pid", None)
    finally:
        if holds_lock:
            _REFRESH_LOCK.release()


def _ensure_queue_worker() -> None:
    global _QUEUE_THREAD
    if _QUEUE_THREAD is not None and _QUEUE_THREAD.is_alive():
        return
    _QUEUE_THREAD = threading.Thread(target=_queue_worker, daemon=True, name="job-queue")
    _QUEUE_THREAD.start()


def _queue_worker() -> None:
    while True:
        with _QUEUE_CV:
            while not _JOB_QUEUE:
                _QUEUE_CV.wait()
            job_id, cmds, single_flight = _JOB_QUEUE.popleft()
        _run_sequence(job_id, cmds, single_flight)


def summarize_jobs(limit: int = 30, tail_chars: int = 6000) -> dict[str, dict]:
    """JSON-safe snapshot of recent jobs (shared by /api/jobs and detail views)."""
    with JOB_LOCK:
        out: dict[str, dict] = {}
        for k in sorted(JOBS.keys(), reverse=True)[:limit]:
            meta = dict(JOBS[k])
            tail = "".join(_LOGS.get(k, ()))[-tail_chars:]
            meta["log"] = tail
            meta["log_full_len"] = _LOG_TOT.get(k, 0)
            out[k] = meta
        return out


def get_log(job_id: str, tail: int | None = None) -> dict:
    """Log view payload for one job; returns {} when the job is unknown."""
    with JOB_LOCK:
        meta = JOBS.get(job_id)
        if not meta:
            return {}
        text = "".join(_LOGS.get(job_id, ()))
        if tail and len(text) > tail:
            text = text[-tail:]
        return {
            "job_id": job_id,
            "status": meta.get("status"),
            "log": text,
            "len": _LOG_TOT.get(job_id, 0),
        }


def stop_job(job_id: str) -> tuple[bool, str]:
    flag = _JOB_STOP.get(job_id)
    with JOB_LOCK:
        job = JOBS.get(job_id)
        proc = _JOB_PROCS.get(job_id)
        if not job:
            return False, "job not found"
        if job.get("status") not in ("queued", "running", "paused"):
            return False, f"job already {job.get('status')}"
        job["status"] = "stopped"
        job["paused"] = False
    # signal the streaming reader without blocking on it
    if flag is not None:
        flag.set()
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return True, "terminated"
        except Exception as e:
            return False, str(e)
    return True, "stop flagged – no live proc (between steps)"


def pause_job(job_id: str) -> tuple[bool, str]:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        proc = _JOB_PROCS.get(job_id)
        if not job:
            return False, "job not found"
        if job.get("status") != "running":
            return False, f"job not running (status={job.get('status')})"
        if not proc or proc.poll() is not None:
            return False, "no live process to pause (between steps)"
    ok, msg = _proc_suspend(proc)
    if ok:
        with JOB_LOCK:
            JOBS[job_id]["status"] = "paused"
            JOBS[job_id]["paused"] = True
    return ok, msg


def resume_job(job_id: str) -> tuple[bool, str]:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        proc = _JOB_PROCS.get(job_id)
        if not job:
            return False, "job not found"
        if job.get("status") != "paused":
            return False, f"job not paused (status={job.get('status')})"
        if not proc or proc.poll() is not None:
            # process died while paused
            job["status"] = "error"
            job["paused"] = False
            return False, "process no longer alive"
    ok, msg = _proc_resume(proc)
    if ok:
        with JOB_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["paused"] = False
    return ok, msg


# ---------------------------------------------------------------------- helpers

# WAL (set via ft_metrics.connect_wal) already keeps readers off the ingest
# writer's lock; the timeout only bounds waits for the rare WAL checkpoint or
# writer-writer contention.
_SQLITE_TIMEOUT = 5.0


def db_connect(path: Path = DB) -> sqlite3.Connection:
    from ft_metrics import connect_wal

    return connect_wal(path, timeout=_SQLITE_TIMEOUT)


# Feather OHLCV frames are re-read on every candles request; caching the parsed
# frame keyed by mtime keeps pan/zoom interaction responsive. Thread races are
# benign (worst case a duplicate parse).
_CANDLE_DF_CACHE: dict[Path, tuple[float, object]] = {}
_CANDLE_DF_CACHE_MAX = 8


def _load_candle_df(path: Path, pd: ModuleType) -> object:
    mtime = path.stat().st_mtime
    cached = _CANDLE_DF_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    df = pd.read_feather(path)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()
    if len(_CANDLE_DF_CACHE) >= _CANDLE_DF_CACHE_MAX:
        _CANDLE_DF_CACHE.clear()
    _CANDLE_DF_CACHE[path] = (mtime, df)
    return df


def load_lab_payload() -> dict:
    """Reuse build_report.py to produce the exact LAB payload the dashboard expects."""
    sys.path.insert(0, str(SCRIPTS))
    import build_report

    conn = db_connect()
    data = build_report.load_data(conn)
    canonical = build_report.canonical_per_strategy(data)
    history = build_report.history_series(data)
    extras = build_report.collect_extras(conn)
    lab = {
        "canonical": canonical,
        "latest": canonical,
        "backtests": data["backtests"],
        "history": history,
        "benchmarks": data["benchmarks"],
        "walkforward": data["walkforward"],
        "hyperopt": data["hyperopt"],
        "strategies": data["strategies"],
        "trade_runs": data["trade_runs"],
        "embedded_trades": None,
        "scorecard": build_report.SCORECARD,
        "configs": extras["configs"],
        "current_code": extras["current_code"],
        "current_code_set": extras["current_code_set"],
        "snapshot_paths": extras["snapshot_paths"],
        "snapshot_combined": extras["snapshot_combined"],
        "snapshot_files": extras["snapshot_files"],
    }
    conn.close()
    return lab


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if not length:
        return {}
    try:
        return json.loads(handler.rfile.read(length))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _int_or_none(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _validate_wf_timerange(body: dict) -> None:
    """B2: server-side guard for walk-forward timerange vs train+test.

    Mirrors the client-side check in dashboard.html (validateWfTimerange).
    Raises ValueError so the /api/run handler returns 400 with the message.
    """
    tr = str(body.get("timerange", "") or "")
    if "-" not in tr:
        return  # empty/missing timerange is left to freqtrade's own validation
    start, _, end = tr.partition("-")
    if len(start) != 8 or len(end) != 8 or not (start.isdigit() and end.isdigit()):
        return  # malformed - let freqtrade report it
    from datetime import datetime, timezone

    s = datetime(int(start[:4]), int(start[4:6]), int(start[6:8]), tzinfo=timezone.utc)
    e = datetime(int(end[:4]), int(end[4:6]), int(end[6:8]), tzinfo=timezone.utc)
    days = (e - s).days + 1
    train = int(body.get("train_days") or 90)
    test = int(body.get("test_days") or 7)
    min_days = train + test + 1
    if days < min_days:
        raise ValueError(
            f"walk-forward timerange too short: {days} day(s) for "
            f"train={train} + test={test} (need at least {min_days} days). "
            "Pick a longer timerange or reduce train/test days."
        )


def _validate_run_params(body: dict) -> None:
    """Server-side guard for common run params (timerange + timeframe).

    Mirrors the client-side check in dashboard.html (validateRunParams).
    Applies to all modes (backtest, hyperopt, walkforward). Raises ValueError
    so the /api/run handler returns 400 with the message.
    """
    import re

    tr = str(body.get("timerange", "") or "").strip()
    if not tr:
        raise ValueError("timerange is required (e.g. 20260101-20260601)")
    if "-" not in tr or len(tr.partition("-")[0]) != 8 or len(tr.partition("-")[2]) != 8:
        raise ValueError(f"timerange must be YYYYMMDD-YYYYMMDD, got {tr!r}")
    start, _, end = tr.partition("-")
    if not (start.isdigit() and end.isdigit()):
        raise ValueError(f"timerange must be YYYYMMDD-YYYYMMDD, got {tr!r}")
    from datetime import datetime, timezone

    try:
        s = datetime(int(start[:4]), int(start[4:6]), int(start[6:8]), tzinfo=timezone.utc)
        e = datetime(int(end[:4]), int(end[4:6]), int(end[6:8]), tzinfo=timezone.utc)
    except ValueError as ex:
        raise ValueError(f"timerange has an invalid date: {ex}") from None
    if e < s:
        raise ValueError(f"timerange end {end} is before start {start}")
    tf = str(body.get("timeframe", "") or "").strip()
    if not tf:
        raise ValueError("timeframe is required (e.g. 5m, 1h, 1d)")
    if not re.match(r"^[1-9]\d*[mhdw]$", tf):
        raise ValueError(f"timeframe must look like 5m / 1h / 1d / 1w, got {tf!r}")


def list_configs() -> list[dict]:  # noqa: C901
    """Discover config JSON files under user_data (for the Lab dropdown).

    Scans user_data/config*.json plus any nested config_*.json (e.g.
    strategies_legacy/nfi_configs/recommended_config.json). Returns newest-first
    with existence checks and spam filters (delisting_state*, *.meta.json, etc).
    """
    seen: set[Path] = set()
    cands: list[Path] = []
    for p in USER_DATA.glob("config*.json"):
        if p.is_file() and p not in seen:
            seen.add(p)
            cands.append(p)
    for p in USER_DATA.rglob("config_*.json"):
        if p.is_file() and p not in seen:
            seen.add(p)
            cands.append(p)
    # Also top-level *.json that looks like a config (contains exchange key) - keep noise low:
    # only add files explicitly named config*.json above; the two globs already cover
    # config_analysis.json, config_benchmark.json, etc.
    filtered: list[Path] = []
    for p in cands:
        n = p.name.lower()
        if n.startswith("delisting_state"):
            continue
        if n.endswith(".meta.json"):
            continue
        if p.stat().st_size == 0:
            continue
        filtered.append(p)
    filtered.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict] = []
    for p in filtered:
        try:
            rel = p.relative_to(USER_DATA).as_posix()
        except ValueError:
            rel = p.name
        # Strategy hint from config_<name>.json
        hint = ""
        low = p.stem.lower()
        if low.startswith("config_"):
            hint = p.stem[7:]
        elif low == "config":
            hint = "default"
        out.append(
            {
                "name": p.name,
                "path": rel,
                "hint": hint,
                "size": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            }
        )
    return out


_LOSSES_CACHE: list[str] | None = None


def _scan_losses_via_filesystem() -> list[str]:
    """Filesystem fallback: parse class names from hyperopt_loss_*.py without importing."""
    import re

    names: set[str] = set()
    pat = re.compile(r"class\s+(\w+HyperOptLoss\w*)\s*\(")
    # builtin + repo constants as seed (no hardcode)
    try:
        from freqtrade.constants import HYPEROPT_LOSS_BUILTIN as _builtin  # type: ignore

        names.update(_builtin)
        names.add("DefaultHyperOptLoss")
    except Exception:  # noqa: BLE001
        pass
    # scan builtin directory
    builtin_dir = Path(__file__).resolve().parents[2] / "freqtrade" / "optimize" / "hyperopt_loss"
    if builtin_dir.is_dir():
        for p in builtin_dir.glob("hyperopt_loss_*.py"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in pat.finditer(text):
                n = m.group(1)
                if n != "IHyperOptLoss":
                    names.add(n)
    # scan user hyperopts (custom)
    custom_dir = USER_DATA / "hyperopts"
    if custom_dir.is_dir():
        for p in custom_dir.glob("*.py"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in pat.finditer(text):
                n = m.group(1)
                if n != "IHyperOptLoss":
                    names.add(n)
    return sorted(n for n in names if n != "IHyperOptLoss")


def list_losses() -> list[str]:
    """Autodiscover available hyperopt loss functions (builtin + user_data/hyperopts).

    Mirrors `freqtrade list-hyperoptloss` via HyperOptLossResolver; falls back to
    a filesystem scan derived from HYPEROPT_LOSS_BUILTIN plus custom files. Cached
    - module imports are expensive and the set only changes on server restart.
    No hardcoded list is kept here.
    """
    global _LOSSES_CACHE
    if _LOSSES_CACHE is not None:
        return _LOSSES_CACHE
    try:
        from freqtrade.resolvers.hyperopt_resolver import HyperOptLossResolver

        objs = HyperOptLossResolver.search_all_objects(
            {"user_data_dir": USER_DATA}, enum_failed=False
        )
        losses = sorted(o["name"] for o in objs)
        if not losses:
            raise ValueError("no loss functions discovered")
    except Exception:  # noqa: BLE001
        losses = _scan_losses_via_filesystem()
    _LOSSES_CACHE = losses
    return losses


def build_run_cmd(body: dict) -> list[str]:
    """Translate an /api/run body into a run_strategy.py command."""
    mode = body.get("mode", "backtest")
    _validate_run_params(body)
    cmd = [
        PYTHON,
        str(SCRIPTS / "run_strategy.py"),
        mode,
        "--strategy",
        str(body.get("strategy", "")),
        "--timerange",
        str(body.get("timerange", "20220101-20240101")),
    ]
    timeframe = str(body.get("timeframe", "5m"))
    if mode == "backtest":
        cmd += ["--timeframe", timeframe]
    elif mode == "hyperopt":
        cmd += [
            "--timeframe",
            timeframe,
            "--epochs",
            str(body.get("epochs", 100)),
            "--loss",
            str(body.get("loss", "SharpeHyperOptLossDaily")),
        ]
        if (v := _int_or_none(body.get("jobs"))) is not None:
            cmd += ["--jobs", str(v)]
        if (v := _int_or_none(body.get("random_state"))) is not None:
            cmd += ["--random-state", str(v)]
        if (v := _int_or_none(body.get("min_trades"))) is not None:
            cmd += ["--min-trades", str(v)]
        if body.get("analyze_per_epoch"):
            cmd += ["--analyze-per-epoch"]
        if body.get("disable_param_export"):
            cmd += ["--disable-param-export"]
        if body.get("print_all"):
            cmd += ["--print-all"]
    elif mode == "walkforward":
        _validate_wf_timerange(body)
        cmd += [
            "--epochs",
            str(body.get("epochs", 50)),
            "--loss",
            str(body.get("loss", "SharpeHyperOptLossDaily")),
            "--train-days",
            str(body.get("train_days", 90)),
            "--test-days",
            str(body.get("test_days", 7)),
            "--step-days",
            str(body.get("step_days", 7)),
        ]
        if (v := _int_or_none(body.get("jobs"))) is not None:
            cmd += ["--jobs", str(v)]
        if (v := _int_or_none(body.get("random_state"))) is not None:
            cmd += ["--random-state", str(v)]
        if (v := _int_or_none(body.get("min_trades"))) is not None:
            cmd += ["--min-trades", str(v)]
        if body.get("analyze_per_epoch"):
            cmd += ["--analyze-per-epoch"]
        if (v := _int_or_none(body.get("wf_min_trades"))) is not None:
            cmd += ["--wf-min-trades", str(v)]
        if (v := _float_or_none(body.get("wf_max_drawdown"))) is not None:
            cmd += ["--wf-max-drawdown", str(v)]
    else:
        raise ValueError("mode must be backtest | hyperopt | walkforward")
    spaces = body.get("spaces")
    if spaces:
        # accept comma or space separated list
        if isinstance(spaces, str):
            parts = [s.strip() for s in spaces.replace(",", " ").split() if s.strip()]
        else:
            parts = [str(s) for s in spaces if str(s).strip()]
        if parts:
            cmd += ["--spaces", *parts]
    config = body.get("config")
    if config:
        cmd += ["--config", str(config)]
    return cmd


# ------------------------------------------------------------------ request handling


class LabHandler(BaseHTTPRequestHandler):
    server_version = "StrategyLab/1.0"

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_server_error(self, e: Exception) -> None:
        """500 with a sanitized message - details go to the server console only."""
        print(f"error handling {getattr(self, 'path', '?')}: {e!r}", file=sys.stderr)
        self._send_json({"error": f"internal error ({type(e).__name__})"}, 500)

    def _send_file(self, rel: str):
        target = (ANALYSIS / rel).resolve()
        try:
            target.relative_to(ANALYSIS.resolve())
        except ValueError:
            self._send_json({"error": "forbidden"}, 403)
            return
        if not target.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        ct = {
            ".html": "text/html; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(target.suffix.lower(), "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import parse_qs

        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/" or path == "" or path == "/dashboard.html":
            if not DASHBOARD.is_file():
                self._send_json({"error": "dashboard not built yet — POST /api/refresh"}, 503)
                return
            self._send_file("dashboard.html")
            return
        if path == "/api/jobs":
            self._send_json(summarize_jobs())
            return
        if path.startswith("/api/jobs/"):
            # GET /api/jobs/<job_id>  -> full detail incl. tail log
            # GET /api/jobs/<job_id>/log?tail=8000  -> just log tail
            import urllib.parse as _up

            parts = path.strip("/").split("/")
            # parts: ["api","jobs","<job_id>"] or ["api","jobs","<job_id>","log"]
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "jobs":
                job_id = _up.unquote(parts[2])
                detail = summarize_jobs(tail_chars=_MAX_LOG).get(job_id)
                if not detail:
                    self._send_json({"error": "job not found"}, 404)
                    return
                self._send_json(detail)
                return
            if len(parts) == 4 and parts[3] == "log":
                job_id = _up.unquote(parts[2])
                tail = int(qs.get("tail", ["0"])[0] or "0")
                log = get_log(job_id, tail=tail or None)
                if not log:
                    self._send_json({"error": "job not found"}, 404)
                    return
                self._send_json(log)
                return
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "jobs"
                and parts[3] == "logs"
                and parts[4] == "stream"
            ):
                job_id = _up.unquote(parts[2])
                self._handle_stream_log(job_id)
                return
        if path == "/api/strategies":
            try:
                self._send_json(self._strategies())
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/losses":
            try:
                self._send_json({"losses": list_losses()})
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/configs":
            try:
                self._send_json({"configs": list_configs()})
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/freshness":
            try:
                self._send_json(self._freshness())
            except Exception as e:  # noqa: BLE001
                self._send_json(
                    {"error": f"internal error ({type(e).__name__})", "stale": False}, 500
                )
            return
        if path == "/api/data":
            try:
                self._send_json(load_lab_payload())
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/hyperopt":
            # drill-down: ?source=strategy_BigZ08_....fthypt&limit=200 or ?strategy=BigZ08
            try:
                self._send_json(self._hyperopt_epochs(qs))
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/walkforward":
            try:
                self._send_json(self._walkforward_detail(qs))
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/hyperopt/files":
            self._send_json(self._hyperopt_files())
            return
        if path == "/api/run/meta":
            try:
                self._send_json(self._run_meta(qs))
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/candles":
            try:
                self._send_json(self._candles_payload(qs))
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/indicators":
            self._send_json(self._indicator_list())
            return
        if path == "/api/tp":
            try:
                self._send_json(self._tp_table(qs.get("strategy", [None])[0] or ""))
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/indicator":
            try:
                self._send_json(self._indicator_payload(qs))
            except Exception as e:  # noqa: BLE001
                self._send_server_error(e)
            return
        if path == "/api/strategy/file":
            self._strategy_file(qs)
            return
        if path == "/api/strategy/current":
            self._send_json(self._strategy_current(qs))
            return
        if path == "/api/health":
            self._send_json({"ok": True, "db": DB.exists()})
            return
        # static: trade files, etc.
        if path.startswith("/trades/"):
            self._send_file(path.lstrip("/"))
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        # job controls: /api/jobs/<id>/stop|pause|resume
        if path.startswith("/api/jobs/"):
            import urllib.parse as _up

            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "jobs":
                job_id = _up.unquote(parts[2])
                action = parts[3]
                if action == "stop":
                    ok, msg = stop_job(job_id)
                    self._send_json({"ok": ok, "msg": msg, "job_id": job_id}, 200 if ok else 400)
                    return
                if action == "pause":
                    ok, msg = pause_job(job_id)
                    self._send_json({"ok": ok, "msg": msg, "job_id": job_id}, 200 if ok else 400)
                    return
                if action == "resume":
                    ok, msg = resume_job(job_id)
                    self._send_json({"ok": ok, "msg": msg, "job_id": job_id}, 200 if ok else 400)
                    return
        if path == "/api/refresh":
            # periodic ingest+report: mutually exclusive, dropped (not queued)
            # while another refresh/report is running
            if _REFRESH_LOCK.locked():
                self._send_json({"skipped": "refresh/report already running"})
                return
            job_id = start_sequence(
                "report-refresh",
                [
                    [PYTHON, str(SCRIPTS / "ingest_results.py")],
                    [PYTHON, str(SCRIPTS / "build_report.py")],
                ],
                single_flight=True,
            )
            self._send_json({"job_id": job_id})
            return
        if path == "/api/report":
            if _REFRESH_LOCK.locked():
                self._send_json({"skipped": "refresh/report already running"})
                return
            job_id = start_sequence(
                "report",
                [
                    [PYTHON, str(SCRIPTS / "build_report.py")],
                ],
                single_flight=True,
            )
            self._send_json({"job_id": job_id})
            return
        if path == "/api/bench":
            body = read_body(self)
            strategies = body.get("strategies") or []
            timerange = body.get("timerange", "20230101-20240101")
            timeframe = body.get("timeframe", "5m")
            cmd = [
                PYTHON,
                str(SCRIPTS / "benchmark_runner.py"),
                "--timerange",
                str(timerange),
                "--timeframe",
                str(timeframe),
            ]
            if strategies:
                cmd += ["--strategies", *strategies]
            job_id = start_job(f"benchmark-{','.join(strategies) if strategies else 'all'}", cmd)
            self._send_json({"job_id": job_id})
            return
        if path == "/api/run":
            body = read_body(self)
            try:
                cmd = build_run_cmd(body)
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
                return
            if not body.get("strategy"):
                self._send_json({"error": "strategy required"}, 400)
                return
            strategy_name = body.get("strategy", "")
            mode = body.get("mode", "backtest")
            rebuild = body.get("rebuild", True)
            if rebuild:
                job_id = start_sequence(
                    f"{mode}-{strategy_name}",
                    [
                        cmd,
                        [PYTHON, str(SCRIPTS / "ingest_results.py")],
                        [PYTHON, str(SCRIPTS / "build_report.py")],
                    ],
                )
            else:
                job_id = start_job(f"{mode}-{strategy_name}", cmd)
            self._send_json({"job_id": job_id})
            return
        if path == "/api/strategies":
            body = read_body(self)
            name = body.get("name")
            status = body.get("status")
            notes = body.get("notes")
            if not name or status not in ("active", "experimental", "retired"):
                self._send_json(
                    {"error": "name + status (active|experimental|retired) required"}, 400
                )
                return
            ok = self._set_strategy(name, status, notes)
            self._send_json({"ok": ok, "strategy": name, "status": status})
            return
        self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("  %s\n" % (fmt % args))

    # ---- hyperopt / walkforward drill-down ----
    def _hyperopt_files(self) -> list[dict]:
        base = USER_DATA / "hyperopt_results"
        out: list[dict] = []
        for f in sorted(base.rglob("*.fthypt"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]:
            out.append(
                {
                    "source": f.name,
                    "path": str(f.relative_to(USER_DATA)),
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                }
            )
        return out

    def _hyperopt_epochs(self, qs: dict) -> dict:
        sys.path.insert(0, str(SCRIPTS))

        import analyze_hyperopt as ah

        limit = int(qs.get("limit", ["200"])[0]) if qs.get("limit") else 200
        limit = max(1, min(limit, 2000))
        source = qs.get("source", [None])[0] if qs.get("source") else None
        strategy = qs.get("strategy", [None])[0] if qs.get("strategy") else None
        if source:
            # allow both basename and relative path
            cand = USER_DATA / "hyperopt_results" / source
            if not cand.is_file():
                # search recursively
                found = list((USER_DATA / "hyperopt_results").rglob(source))
                cand = found[0] if found else cand
            if not cand.is_file():
                return {"error": f"not found: {source}"}
            epochs = ah.load_epochs(cand)
            return {
                "source": cand.name,
                "count": len(epochs),
                "corr": ah.epochs_corr_with_loss(epochs),
                "records": ah.epochs_to_records(epochs, limit=limit),
            }
        if strategy:
            p = ah.latest_results(strategy)
            if not p or not p.is_file():
                return {"error": f"no .fthypt for {strategy}"}
            epochs = ah.load_epochs(p)
            return {
                "source": p.name,
                "strategy": strategy,
                "count": len(epochs),
                "corr": ah.epochs_corr_with_loss(epochs),
                "records": ah.epochs_to_records(epochs, limit=limit),
            }
        return {"error": "supply ?source=... or ?strategy=..."}

    def _walkforward_detail(self, qs: dict) -> dict:
        import sqlite3 as _sql

        source = qs.get("source", [None])[0] if qs.get("source") else None
        run_id = qs.get("run_id", [None])[0] if qs.get("run_id") else None
        strategy = qs.get("strategy", [None])[0] if qs.get("strategy") else None
        conn = db_connect()
        conn.row_factory = _sql.Row
        q = "SELECT * FROM walkforward WHERE 1=1"
        params: list = []
        if source:
            q += " AND source LIKE ?"
            params.append(f"%{source}%")
        if run_id:
            q += " AND run_id=?"
            params.append(run_id)
        if strategy:
            q += " AND strategy=?"
            params.append(strategy)
        q += " ORDER BY run_time DESC LIMIT 20"
        rows = [dict(r) for r in conn.execute(q, params).fetchall()]
        for r in rows:
            if r.get("windows_json"):
                try:
                    r["windows"] = json.loads(r["windows_json"])
                except (json.JSONDecodeError, TypeError):
                    r["windows"] = []
            else:
                r["windows"] = []
        conn.close()
        return {"rows": rows}

    # ---- candles: OHLCV overlay for the trade timeline ----
    def _candle_frame(self, qs: dict, pd: ModuleType) -> tuple[object | None, dict | None]:
        """Candle feather DataFrame for pair/timeframe, sliced to start/end."""
        pair = qs.get("pair", [None])[0]
        tf = qs.get("timeframe", [None])[0] or "5m"
        mode = (qs.get("trading_mode", [""])[0] or "").lower()
        exchange = (qs.get("exchange", ["binance"])[0] or "binance").lower()
        start = _int_or_none(qs.get("start", [None])[0])
        end = _int_or_none(qs.get("end", [None])[0])
        if not pair:
            return None, {"error": "pair required"}
        safe = str(pair).replace("/", "_").replace(":", "_")
        spot = USER_DATA / "data" / exchange / f"{safe}-{tf}.feather"
        fut1 = USER_DATA / "data" / "futures" / f"{safe}-{tf}-futures.feather"
        fut2 = USER_DATA / "data" / exchange / "futures" / f"{safe}-{tf}-futures.feather"
        order = [fut1, fut2, spot] if mode == "futures" else [spot, fut1, fut2]
        path = next((c for c in order if c.is_file()), None)
        if path is None:
            return None, {"error": f"no candle file for {pair} {tf}", "candles": []}
        try:
            df = _load_candle_df(path, pd)
        except Exception as e:  # noqa: BLE001
            print(f"error loading {path.name}: {e!r}", file=sys.stderr)
            return None, {"error": f"could not read candles ({type(e).__name__})"}
        if start is not None:
            df = df[df.index >= pd.Timestamp(start, unit="ms", tz="UTC")]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end, unit="ms", tz="UTC")]
        return df, None

    def _candles_payload(self, qs: dict) -> dict:
        """OHLCV candles for one pair/timeframe, downsampled to <=3000 buckets.

        Reads the freqtrade feather files under user_data/data (spot and
        futures); buckets are merged when a range would otherwise ship too
        many candles for the browser chart.
        """
        import pandas as pd

        pair = qs.get("pair", [None])[0]
        tf = qs.get("timeframe", [None])[0] or "5m"
        df, err = self._candle_frame(qs, pd)
        if err:
            return err
        if df is None or df.empty:
            return {"pair": pair, "timeframe": tf, "candles": []}
        n = len(df)
        factor = (n + 2999) // 3000 if n > 3000 else 1
        if factor > 1:
            trim = (n // factor) * factor
            arr = df[["open", "high", "low", "close"]].to_numpy(dtype="float64")[:trim]
            arr = arr.reshape(-1, factor, 4)
            opens = arr[:, 0, 0]
            highs = arr[:, :, 1].max(axis=1)
            lows = arr[:, :, 2].min(axis=1)
            closes = arr[:, -1, 3]
            vol = df["volume"].to_numpy(dtype="float64")[:trim].reshape(-1, factor).sum(axis=1)
            idx = pd.DatetimeIndex(df.index.to_numpy()[:trim].reshape(-1, factor)[:, 0])
            tf_eff = f"{tf} x{factor}"
        else:
            opens = df["open"].to_numpy(dtype="float64")
            highs = df["high"].to_numpy(dtype="float64")
            lows = df["low"].to_numpy(dtype="float64")
            closes = df["close"].to_numpy(dtype="float64")
            vol = df["volume"].to_numpy(dtype="float64")
            idx = pd.DatetimeIndex(df.index)
            tf_eff = tf
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        ts_ms = (idx.tz_convert("UTC").asi8 // 10**6).tolist()
        candles = [
            [t, o, hi, lo, c, v]
            for t, o, hi, lo, c, v in zip(ts_ms, opens, highs, lows, closes, vol, strict=True)
        ]
        return {"pair": pair, "timeframe": tf, "effective_timeframe": tf_eff, "candles": candles}

    # ---- indicator overlays computed from the user's own library ----
    # The list is discovered from indicators_pandas_ta instead of a hardcoded
    # registry: every public function whose required parameters map to OHLCV
    # columns is offered. Functions taking a DataFrame (pattern detectors) are
    # excluded because the overlay API serves plain series.
    _INDICATOR_COLUMNS = {
        "open": "open",
        "open_": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "series": "close",
        "volume": "volume",
    }
    _INDICATOR_TITLES = {
        "wavetrend": "WaveTrend",
        "vix_fix": "VIX Fix",
        "tdfi": "TDFI",
        "chaikin_volatility": "Chaikin Volatility",
        "garman_klass_vol": "Garman-Klass Vol",
        "damiani_volatmeter": "Damiani Volatmeter",
        "woodies_cci": "Woodies CCI",
        "kairi_index": "Kairi Index",
        "kama_slope": "KAMA Slope",
        "atr_percentile": "ATR Percentile",
        "volume_percentile": "Volume Percentile",
        "generic_zscore": "Z-Score",
        "choppiness_index": "Choppiness Index",
        "linreg_forecast_return": "LinReg Forecast",
        "hurst_exponent": "Hurst Exponent",
        "bbwp": "BBWP",
        "ehlers_super_smoother": "Ehlers Super Smoother",
    }
    # functions whose output lives on the price scale instead of an own pane
    _INDICATOR_PRICE_SCALE = {"ehlers_super_smoother"}

    def _indicator_specs(self) -> dict[str, dict]:
        """Public indicator functions of indicators_pandas_ta -> {name: spec}."""
        global _INDICATOR_MODULE
        if _INDICATOR_MODULE is None:
            sys.path.insert(0, str(USER_DATA / "strategies" / "components"))
            import indicators_pandas_ta as _mod

            _INDICATOR_MODULE = _mod
        specs: dict[str, dict] = {}
        for name, fn in vars(_INDICATOR_MODULE).items():
            if name.startswith("_") or not inspect.isfunction(fn):
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            inputs: list[str] = []
            ok = True
            for p in sig.parameters.values():
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    ok = False
                    break
                if p.default is not p.empty:
                    continue
                col = self._INDICATOR_COLUMNS.get(p.name)
                if col is None:
                    ok = False
                    break
                inputs.append(col)
            if ok and inputs:
                specs[name] = {
                    "title": self._INDICATOR_TITLES.get(name, name.replace("_", " ").title()),
                    "inputs": inputs,
                    "scale": "price" if name in self._INDICATOR_PRICE_SCALE else "own",
                }
        return specs

    def _indicator_list(self) -> list:
        return [
            {"name": name, "title": spec["title"], "scale": spec["scale"]}
            for name, spec in self._indicator_specs().items()
        ]

    def _tp_table(self, name: str) -> dict:
        """Read minimal_roi from a strategy's source file.

        Returns {"found": bool, "name": str, "roi": {minutes: decimal}}.

        freqtrade's minimal_roi is keyed by minutes-from-trade-open; the value
        is the required profit (decimal, not percent). We return it as-is so
        the browser can map it to a price level.
        """
        if not name:
            return {"found": False, "name": "", "roi": {}}
        import ast
        import re

        strategies_dir = USER_DATA / "strategies"
        candidates = list(strategies_dir.rglob(f"{name}.py"))
        # fall back to a tolerant search when the filename has a different case
        # or is split across an import (rare, but cheap)
        if not candidates:
            want = name.lower()
            for p in strategies_dir.rglob("*.py"):
                if p.stem.lower() == want:
                    candidates.append(p)
        for path in candidates:
            try:
                src = path.read_text(encoding="utf-8")
            except OSError:
                continue
            # match: minimal_roi = { ... } (single line or multi-line)
            m = re.search(r"minimal_roi\s*=\s*(\{[^}]*\})", src, re.S)
            if not m:
                continue
            try:
                roi = ast.literal_eval(m.group(1))
            except (ValueError, SyntaxError):
                continue
            if isinstance(roi, dict) and roi:
                # normalise keys to int minutes, values to float
                clean: dict[str, float] = {}
                for k, v in roi.items():
                    try:
                        clean[str(int(float(k)))] = float(v)
                    except (TypeError, ValueError):
                        continue
                if clean:
                    return {"found": True, "name": name, "roi": clean}
        return {"found": False, "name": name, "roi": {}}

    def _indicator_payload(self, qs: dict) -> dict:
        """Compute one indicator from indicators_pandas_ta over candle data."""
        import pandas as pd

        name = qs.get("name", [None])[0]
        spec = self._indicator_specs().get(name or "")
        if not spec:
            return {"error": f"unknown indicator {name!r}"}
        df, err = self._candle_frame(qs, pd)
        if err:
            return err
        if df is None or df.empty:
            return {"name": name, "scale": spec["scale"], "series": []}
        fn = getattr(_INDICATOR_MODULE, name)
        cols = {inp: df[inp] for inp in spec["inputs"]}
        result = fn(**cols)
        series_list = list(result) if isinstance(result, tuple) else [result]
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        ts_ms = (idx.tz_convert("UTC").asi8 // 10**6).tolist()
        out = []
        for i, ser in enumerate(series_list):
            vals = [None if (v is None or v != v) else round(float(v), 8) for v in ser]
            out.append(
                {
                    "key": name if len(series_list) == 1 else f"{name}_{i + 1}",
                    "times": ts_ms,
                    "values": vals,
                }
            )
        return {"name": name, "title": spec["title"], "scale": spec["scale"], "series": out}

    # ---- provenance: run meta / strategy snapshots ----
    _RUN_TABLES = {
        "backtest": "backtests",
        "benchmark": "benchmarks",
        "hyperopt": "hyperopt",
        "walkforward": "walkforward",
    }

    def _run_meta(self, qs: dict) -> dict:
        import sqlite3

        kind = (qs.get("kind", [""])[0] or "").lower()
        source = qs.get("source", [None])[0]
        strategy = qs.get("strategy", [None])[0]
        table = self._RUN_TABLES.get(kind)
        if not table or not source:
            return {"error": "kind (backtest|benchmark|hyperopt|walkforward) + source required"}
        conn = db_connect()
        conn.row_factory = sqlite3.Row
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        want = [
            c
            for c in (
                "strategy",
                "source",
                "config_hash",
                "code_hash",
                "code_verified",
                "best_params",
            )
            if c in cols
        ]
        q = f"SELECT {', '.join(want)} FROM {table} WHERE source=?"
        params: list = [source]
        if strategy and "strategy" in want:
            q += " AND strategy=?"
            params.append(strategy)
        row = conn.execute(q + " LIMIT 1", params).fetchone()
        out: dict = {"kind": kind, "source": source}
        if row is None:
            conn.close()
            out["error"] = "run not found"
            return out
        out.update(dict(row))
        if out.get("config_hash"):
            cfg = conn.execute(
                "SELECT config_json, path FROM configs WHERE hash=?",
                (out["config_hash"],),
            ).fetchone()
            if cfg and cfg["config_json"]:
                try:
                    out["config"] = json.loads(cfg["config_json"])
                except json.JSONDecodeError:
                    out["config_raw"] = cfg["config_json"]
                out["config_path"] = cfg["path"]
        if out.get("code_hash"):
            snap = conn.execute(
                "SELECT path, mtime FROM strategy_snapshots WHERE hash=?",
                (out["code_hash"],),
            ).fetchone()
            if snap:
                out["snapshot"] = dict(snap)
        conn.close()
        return out

    def _send_text(self, text: str):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_stream_log(self, job_id: str) -> None:
        # Server-Sent Events endpoint for real-time log streaming.
        # Streams new chunks from the job's log buffer as they grow,
        # then closes when the job finishes and no new data appears.
        meta = None
        with JOB_LOCK:
            meta = JOBS.get(job_id)
        if not meta:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_len = 0
        try:
            # Send any existing log content first.
            with JOB_LOCK:
                text = "".join(_LOGS.get(job_id, ()))
                if text:
                    chunk = text[last_len:]
                    if chunk:
                        for line in chunk.splitlines():
                            self.wfile.write(f"data: {line}\n".encode("utf-8"))
                        self.wfile.write(b"\n")
                        self.wfile.flush()
                        last_len = len(text)
            # Poll for updates until the job finishes.
            while True:
                time.sleep(0.2)
                with JOB_LOCK:
                    meta_now = JOBS.get(job_id)
                    text = "".join(_LOGS.get(job_id, ()))
                    new_text = text[last_len:]
                    if new_text:
                        for line in new_text.splitlines():
                            self.wfile.write(f"data: {line}\n".encode("utf-8"))
                        self.wfile.write(b"\n")
                        self.wfile.flush()
                        last_len = len(text)
                is_done = meta_now is not None and meta_now.get("status") in (
                    "done",
                    "error",
                    "stopped",
                    "skipped",
                )
                if is_done and not new_text:
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected; no action needed.

    def _strategy_file(self, qs: dict) -> None:
        """Serve a stored strategy snapshot by hash.

        - ``?hash=X`` (no ``file``) returns the strategy file (strategy_snapshots.source).
        - ``?hash=X&file=<path>`` returns the file at that absolute path; resolves
          against ``strategy_snapshot_files`` (dep files) when the path is not the
          main strategy file.
        """
        h = qs.get("hash", [None])[0]
        if not h:
            self._send_json({"error": "hash required"}, 400)
            return
        file_path = qs.get("file", [None])[0]
        conn = db_connect()
        row = conn.execute(
            "SELECT path, source FROM strategy_snapshots WHERE hash=?", (h,)
        ).fetchone()
        if not row:
            conn.close()
            self._send_json({"error": "snapshot not found"}, 404)
            return
        main_path, main_source = row[0], row[1]
        if not file_path or file_path == main_path:
            conn.close()
            self._send_text(main_source)
            return
        dep = conn.execute(
            "SELECT source FROM strategy_snapshot_files WHERE hash=? AND path=?",
            (h, file_path),
        ).fetchone()
        conn.close()
        if not dep:
            self._send_json({"error": "file not in snapshot"}, 404)
            return
        self._send_text(dep[0])

    def _strategy_current(self, qs: dict) -> dict:
        from ft_metrics import find_strategy_file

        name = qs.get("name", [None])[0]
        if not name:
            return {"error": "name required"}
        f = find_strategy_file(USER_DATA, name)
        if f is None:
            return {"found": False}
        try:
            from ft_metrics import sha1_text

            return {
                "found": True,
                "path": str(f),
                "mtime": f.stat().st_mtime,
                "hash": sha1_text(f.read_text(encoding="utf-8")),
            }
        except OSError as e:
            return {"found": False, "error": f"stat failed ({type(e).__name__})"}

    # ---- db access ----
    def _freshness(self) -> dict:
        # The dashboard is considered stale when any of these source trees
        # has been modified after dashboard.html. A small fudge handles
        # sub-second clock skew between the editor and the build.
        return self._compute_freshness()

    @staticmethod
    def _walk_max_mtime(paths):
        newest = 0.0
        for p in paths:
            if not p:
                continue
            try:
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
                elif p.is_dir():
                    for child in p.rglob("*"):
                        if child.is_file():
                            try:
                                newest = max(newest, child.stat().st_mtime)
                            except OSError:
                                pass
            except OSError:
                pass
        return newest

    def _compute_freshness(self) -> dict:
        fudge = 2.0
        built_mtime = DASHBOARD.stat().st_mtime if DASHBOARD.is_file() else 0.0
        newest = self._walk_max_mtime(
            [
                USER_DATA / "backtest_results",
                USER_DATA / "strategies",
                USER_DATA / "configs",
            ]
        )
        if ANALYSIS.is_dir():
            newest = max(
                newest,
                self._walk_max_mtime(
                    [
                        p
                        for pat in ("bench_results-*.zip", "*-trades.json.gz")
                        for p in ANALYSIS.glob(pat)
                    ]
                ),
            )
        db = ANALYSIS / "results.db"
        if db.is_file():
            newest = max(
                newest,
                self._walk_max_mtime(
                    [
                        db,
                        db.with_name(db.name + "-wal"),
                        db.with_name(db.name + "-shm"),
                    ]
                ),
            )
        stale = (newest - built_mtime) > fudge
        from datetime import datetime, timezone

        ts = datetime.fromtimestamp
        return {
            "built": ts(built_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "sources": ts(newest, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if newest else "",
            "stale": bool(stale),
        }

    def _strategies(self) -> list[dict]:
        import sqlite3

        conn = db_connect()
        conn.row_factory = sqlite3.Row
        rows = [
            dict(r)
            for r in conn.execute(
                """SELECT s.name, s.status, s.notes,
                      (SELECT COUNT(*) FROM backtests b WHERE b.strategy = s.name) AS n_backtests,
                      (SELECT COUNT(*) FROM trades t WHERE t.strategy = s.name) AS n_trades
               FROM strategies s ORDER BY s.name"""
            )
        ]
        conn.close()
        return rows

    def _set_strategy(self, name: str, status: str, notes: str | None) -> bool:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM strategies WHERE name=?", (name,))
        if cur.fetchone():
            cur.execute(
                "UPDATE strategies SET status=?, notes=? WHERE name=?", (status, notes or "", name)
            )
        else:
            cur.execute(
                "INSERT INTO strategies (name, status, notes) VALUES (?,?,?)",
                (name, status, notes or ""),
            )
        conn.commit()
        conn.close()
        return True


_LOOKUP_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS ix_trades_strategy    ON trades(strategy);
CREATE INDEX IF NOT EXISTS ix_trades_run         ON trades(strategy, source);
CREATE INDEX IF NOT EXISTS ix_backtests_strategy ON backtests(strategy);
CREATE INDEX IF NOT EXISTS ix_hyperopt_strategy  ON hyperopt(strategy);
CREATE INDEX IF NOT EXISTS ix_walkforward_strategy ON walkforward(strategy);
"""


def ensure_lookup_indexes() -> None:
    """Create per-strategy lookup indexes.

    The strategy tables grow with every ingested run (trades is 500k+ rows
    locally); without these, /api/strategies correlated COUNT(*) subqueries do a
    full scan per strategy and the endpoint stalls for seconds — blocking
    regardless of whether jobs run.
    """
    try:
        conn = db_connect()
        conn.executescript(_LOOKUP_INDEX_DDL)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"warning: could not create lookup indexes: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy Lab web server")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--no-open", action="store_true", help="Don't open the browser")
    args = ap.parse_args()

    if not DB.exists():
        print("No results.db yet — running first ingest (may take a while)...")
        run_command([PYTHON, str(SCRIPTS / "ingest_results.py")])

    ensure_lookup_indexes()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), LabHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Strategy Lab running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
