from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
SCRIPTS = Path(__file__).resolve().parent
USER_DATA = SCRIPTS.parent
ANALYSIS = USER_DATA / "analysis"
LIVE_DB = ANALYSIS / "results.db"
ARCHIVED = SCRIPTS / "_archived"
BR_SCRIPT = ARCHIVED / "build_report.py"
sys.path.insert(0, str(ARCHIVED))
sys.path.insert(0, str(SCRIPTS))
import server as lab
import build_report as br
from python_compat import python_argv
lab.DB = LIVE_DB
lab.USER_DATA = USER_DATA
lab.ANALYSIS = ANALYSIS
lab.SCRIPTS = SCRIPTS
lab.db_connect.__defaults__ = (LIVE_DB,)
br.USER_DATA = USER_DATA
br.ANALYSIS_DIR = ANALYSIS
lab.ensure_lookup_indexes()
H = lab.LabHandler.__new__(lab.LabHandler)
app = FastAPI(title="Strategy Lab API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/trades", StaticFiles(directory=ANALYSIS / "trades"))
class StrategyIn(BaseModel):
    name: str
    status: str = "active"
    notes: Optional[str] = None
class BenchIn(BaseModel):
    strategies: List[str] = []
    timerange: str = "20230101-20240101"
    timeframe: str = "5m"
    mode: str = "backtest"
    epochs: Optional[int] = None
    loss: Optional[str] = None
    spaces: Optional[List[str]] = None
    jobs: Optional[int] = None
    random_state: Optional[int] = None
    train_days: Optional[int] = None
    test_days: Optional[int] = None
    step_days: Optional[int] = None
class RunIn(BaseModel):
    mode: str = "backtest"
    strategy: str = ""
    timerange: str = "20220101-20240101"
    timeframe: str = "5m"
    config: Optional[str] = None
    rebuild: bool = True
    epochs: Optional[int] = None
    loss: Optional[str] = None
    spaces: Optional[List[str]] = None
    jobs: Optional[int] = None
    random_state: Optional[int] = None
    min_trades: Optional[int] = None
    wf_min_trades: Optional[int] = None
    wf_max_drawdown: Optional[float] = None
    analyze_per_epoch: bool = False
    disable_param_export: bool = False
    print_all: bool = False
class DryrunIn(BaseModel):
    strategy: str = ""
    timerange: str = "20220101-20240101"
    timeframe: str = "5m"
    config: Optional[str] = None
    dryrun_id: Optional[str] = None


import threading


lab.JOB_LOCK = threading.RLock()


def sanitize(o):
    import math
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        out = dict()
        for k in o.keys():
            out[k] = sanitize(o[k])
        return out
    if isinstance(o, list):
        return list(map(sanitize, o))
    if isinstance(o, tuple):
        return tuple(map(sanitize, o))
    return o


app.get("/api/health")(lambda: dict(ok=True, db=LIVE_DB.exists()))
app.get("/api/jobs")(lab.summarize_jobs)
app.get("/api/strategies")(H._strategies)
def api_data():
    payload = lab.load_lab_payload()
    payload["prop_firms_spec"] = br.PROP_FIRMS
    try:
        payload["backtest_configs"] = br.extract_backtest_configs(USER_DATA, payload["backtests"])
    except Exception:
        payload["backtest_configs"] = {}
    return sanitize(payload)
app.get("/api/data")(api_data)
app.get("/api/losses")(lambda: dict(losses=lab.list_losses()))
app.get("/api/configs")(lambda: dict(configs=lab.list_configs()))
app.get("/api/freshness")(H._freshness)
app.get("/api/indicators")(H._indicator_list)
app.get("/api/hyperopt/files")(H._hyperopt_files)
from fastapi import Request
def api_hyperopt(source=None, strategy=None, limit=200):
    qs = dict()
    if source:
        qs["source"] = [source]
    if strategy:
        qs["strategy"] = [strategy]
    qs["limit"] = [str(limit)]
    return sanitize(H._hyperopt_epochs(qs))
app.get("/api/hyperopt")(api_hyperopt)
def api_walkforward(source=None, run_id=None, strategy=None):
    qs = dict()
    if source:
        qs["source"] = [source]
    if run_id:
        qs["run_id"] = [run_id]
    if strategy:
        qs["strategy"] = [strategy]
    return sanitize(H._walkforward_detail(qs))
app.get("/api/walkforward")(api_walkforward)
def api_run_meta(kind="", source=None, strategy=None):
    qs = dict(kind=[kind])
    if source:
        qs["source"] = [source]
    if strategy:
        qs["strategy"] = [strategy]
    return H._run_meta(qs)
app.get("/api/run/meta")(api_run_meta)
def api_candles(pair=None, timeframe="5m", trading_mode="", exchange="binance", start=None, end=None):
    qs = dict(pair=[pair], timeframe=[timeframe], trading_mode=[trading_mode], exchange=[exchange], start=[start], end=[end])
    return sanitize(H._candles_payload(qs))
app.get("/api/candles")(api_candles)
def api_tp(strategy=""):
    return H._tp_table(strategy or "")
app.get("/api/tp")(api_tp)
async def api_indicator(request: Request):
    qs = dict()
    for k, v in request.query_params.multi_items():
        qs.setdefault(k, []).append(v)
    return sanitize(H._indicator_payload(qs))
app.get("/api/indicator")(api_indicator)
def api_strategy_current(name=None):
    qs = dict()
    if name:
        qs["name"] = [name]
    return H._strategy_current(qs)
app.get("/api/strategy/current")(api_strategy_current)
def api_strategy_file(hash=None, file=None):
    import sqlite3 as sql
    if not hash:
        raise HTTPException(status_code=400, detail="hash required")
    conn = lab.db_connect()
    conn.row_factory = sql.Row
    row = conn.execute("SELECT path, source FROM strategy_snapshots WHERE hash=?", (hash,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="snapshot not found")
    main_path, main_source = row[0], row[1]
    if not file or file == main_path:
        conn.close()
        return PlainTextResponse(main_source)
    dep = conn.execute("SELECT source FROM strategy_snapshot_files WHERE hash=? AND path=?", (hash, file)).fetchone()
    conn.close()
    if not dep:
        raise HTTPException(status_code=404, detail="file not in snapshot")
    return PlainTextResponse(dep[0])
app.get("/api/strategy/file")(api_strategy_file)
def api_dryrun_status(tail=None):
    tq = dict(tail=[tail]) if tail is not None else dict()
    t = H._dryrun_tail_param(tq, lab._DRYRUN_LOG_TAIL_DEFAULT)
    ids = list(lab._DRYRUN.keys())
    metas = [m for m in (lab._dryrun_metadata(i, t) for i in ids) if m is not None]
    active = next((m for m in metas if m["alive"]), None)
    latest = sorted(metas, key=lambda m: float(m.get("started_at") or 0), reverse=True)
    return dict(active=active is not None, dryrun=active or (latest[0] if latest else None), all=metas)
app.get("/api/dryrun")(api_dryrun_status)
def api_dryrun_log(tail=None):
    ids = list(lab._DRYRUN.keys())
    active = None
    for i in ids:
        meta = lab._dryrun_metadata(i, 0)
        if meta is not None and meta["alive"]:
            active = meta
            break
    if active is None:
        raise HTTPException(status_code=404, detail="no active dry run")
    tq = dict(tail=[tail]) if tail is not None else dict()
    t = H._dryrun_tail_param(tq, None)
    raw = active.get("log_path")
    lp = Path(str(raw)) if raw else None
    if lp is None:
        return PlainTextResponse("")
    if t is not None:
        return PlainTextResponse(lab._read_dryrun_log_tail(lp, t))
    try:
        return PlainTextResponse(lp.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return PlainTextResponse("")
app.get("/api/dryrun/log")(api_dryrun_log)
def api_set_strategy(model: StrategyIn):
    if not model.name or model.status not in ("active", "experimental", "retired"):
        raise HTTPException(status_code=400, detail="name + status (active|experimental|retired) required")
    ok = H._set_strategy(model.name, model.status, model.notes)
    return dict(ok=ok, strategy=model.name, status=model.status)
app.post("/api/strategies")(api_set_strategy)
def api_refresh():
    with lab.JOB_LOCK:
        if lab._REFRESH_JOB_ACTIVE[0] or lab._REFRESH_LOCK.locked():
            return dict(skipped="report-refresh already running or queued")
        lab._REFRESH_JOB_ACTIVE[0] = True
        job_id = lab._start_sequence_locked("report-refresh", [[*python_argv(), str(SCRIPTS / "ingest_results.py")], [*python_argv(), str(BR_SCRIPT)]], single_flight=True)
        return dict(job_id=job_id)
app.post("/api/refresh")(api_refresh)
def api_report():
    with lab.JOB_LOCK:
        if lab._REFRESH_JOB_ACTIVE[0] or lab._REFRESH_LOCK.locked():
            return dict(skipped="report already running or queued")
        lab._REFRESH_JOB_ACTIVE[0] = True
        job_id = lab.start_sequence("report", [[*python_argv(), str(BR_SCRIPT)]], single_flight=True)
        return dict(job_id=job_id)
app.post("/api/report")(api_report)
def _bench_cmd(body):
    strategies = body.get("strategies") or []
    timerange = body.get("timerange", "20230101-20240101")
    timeframe = body.get("timeframe", "5m")
    mode = body.get("mode", "backtest")
    if mode not in ("backtest", "hyperopt", "walkforward"):
        raise ValueError("invalid mode " + repr(mode))
    cmd = [*python_argv(), str(SCRIPTS / "benchmark_runner.py"), "--mode", mode, "--timerange", str(timerange), "--timeframe", str(timeframe)]
    cmd.extend(H._bench_common_args(body, mode))
    cmd.extend(H._bench_walkforward_args(body))
    if strategies:
        cmd += ["--strategies", *strategies]
    return cmd
def api_bench(model: BenchIn):
    body = model.model_dump()
    try:
        cmd = _bench_cmd(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    strategies = body.get("strategies") or []
    label = ",".join(strategies) if strategies else "all"
    job_id = lab.start_job("benchmark-" + str(body.get("mode", "backtest")) + "-" + label, cmd)
    return dict(job_id=job_id, mode=body.get("mode", "backtest"))
app.post("/api/bench")(api_bench)
def api_run(model: RunIn):
    body = model.model_dump()
    try:
        cmd = lab.build_run_cmd(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not body.get("strategy"):
        raise HTTPException(status_code=400, detail="strategy required")
    mode = body.get("mode", "backtest")
    tag = mode + "-" + str(body.get("strategy", ""))
    if body.get("rebuild", True):
        job_id = lab.start_sequence(tag, [cmd, [*python_argv(), str(SCRIPTS / "ingest_results.py")], [*python_argv(), str(BR_SCRIPT)]])
    else:
        job_id = lab.start_job(tag, cmd)
    return dict(job_id=job_id)
app.post("/api/run")(api_run)
def api_job_detail(job_id: str):
    detail = lab.summarize_jobs(tail_chars=lab._MAX_LOG).get(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail="job not found")
    return detail
app.get("/api/jobs/{job_id}")(api_job_detail)
def api_job_log(job_id: str, tail: int = 0):
    log = lab.get_log(job_id, tail=tail or None)
    if not log:
        raise HTTPException(status_code=404, detail="job not found")
    return log
app.get("/api/jobs/{job_id}/log")(api_job_log)
def api_job_action(job_id: str, action: str):
    actions = dict(stop=lab.stop_job, pause=lab.pause_job, resume=lab.resume_job)
    fn = actions.get(action)
    if fn is None:
        raise HTTPException(status_code=400, detail="unknown action " + action)
    ok, msg = fn(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return dict(ok=ok, msg=msg, job_id=job_id)
app.post("/api/jobs/{job_id}/{action}")(api_job_action)
def api_dryrun_start(model: DryrunIn):
    try:
        response = lab._start_registered_dryrun(model.model_dump())
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except (OSError, RuntimeError, TimeoutError) as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    return response
app.post("/api/dryrun", status_code=201)(api_dryrun_start)
def api_dryrun_stop(model: DryrunIn):
    try:
        dryrun_id, meta = lab._find_dryrun_stop_target(str(model.dryrun_id or "").strip())
    except LookupError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    ok, msg = lab._terminate_dryrun_pid(int(meta.get("pid") or 0))
    lab._remove_dryrun_pid_file(dryrun_id)
    with lab._DRYRUN_LOCK:
        lab._DRYRUN.pop(dryrun_id, None)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return dict(ok=ok, msg=msg, dryrun_id=dryrun_id)
app.post("/api/dryrun/stop")(api_dryrun_stop)
def api_dryrun_gate(model: DryrunIn):
    strategy = str(model.strategy or "").strip()
    if not strategy:
        raise HTTPException(status_code=400, detail="strategy required")
    cmd = [*python_argv(), str(SCRIPTS / "run_strategy.py"), "gate", "--strategy", strategy]
    cmd += ["--timerange", str(model.timerange or "20220101-20240101"), "--timeframe", str(model.timeframe or "5m")]
    if model.config:
        cmd += ["--config", str(model.config)]
    job_id = lab.start_job("gate-" + strategy, cmd)
    return dict(job_id=job_id, strategy=strategy)
app.post("/api/dryrun/gate", status_code=202)(api_dryrun_gate)
def api_job_stream(job_id: str):
    def gen():
        last = 0
        while True:
            with lab.JOB_LOCK:
                text = "".join(lab._LOGS.get(job_id, ()))
            new_text = text[last:]
            if new_text:
                for line in new_text.splitlines():
                    yield "data: " + line + chr(10)
                yield chr(10)
                last = len(text)
            with lab.JOB_LOCK:
                meta_now = lab.JOBS.get(job_id)
            is_done = meta_now is not None and meta_now.get("status") in ("done", "error", "stopped", "skipped")
            if is_done and not new_text:
                break
            time.sleep(0.2)
    return StreamingResponse(gen(), media_type="text/event-stream")
app.get("/api/jobs/{job_id}/logs/stream")(api_job_stream)
def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy Lab API")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    lab._validate_indicator_modules()
    if not LIVE_DB.exists():
        print("No results.db yet - running first ingest...")
        lab.run_command([*python_argv(), str(SCRIPTS / "ingest_results.py")])
    lab.ensure_lookup_indexes()
    adopted = lab._adopt_orphan_dryruns()
    if adopted:
        print("adopted " + str(adopted) + " orphan dry runs")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
