"""server.py — local web app for the Strategy Lab dashboard.

Serves dashboard.html and provides a JSON API so everything can be done from
the browser instead of the CLI:

    GET   /                        -> dashboard.html
    GET   /api/jobs                -> background job status
    GET   /api/strategies          -> strategy registry
    POST  /api/strategies          -> set status / notes  {name, status, notes}
    GET   /api/data                -> dashboard payload (LAB)
    GET   /api/losses              -> known hyperopt loss functions
    POST  /api/refresh             -> ingest + rebuild report
    POST  /api/report              -> rebuild report only
    POST  /api/bench               -> run benchmark  {strategies[], timerange, timeframe}
    POST  /api/run                 -> backtest / hyperopt / walk-forward for one strategy
                                        {mode, strategy, timerange, timeframe, config?, epochs?,
                                         loss?, spaces?, train_days?, test_days?, step_days?,
                                         rebuild?}

Background jobs (ingest/benchmark) run in threads; the UI polls /api/jobs.

Usage:
    python user_data/scripts/server.py [--port 8088]
    python user_data/scripts/lab.py serve
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

SCRIPTS = Path(__file__).resolve().parent
USER_DATA = SCRIPTS.parent
ANALYSIS = USER_DATA / "analysis"
DB = ANALYSIS / "results.db"
DASHBOARD = ANALYSIS / "dashboard.html"
PYTHON = sys.executable

JOBS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()


# ---------------------------------------------------------------- background jobs

def run_command(cmd: list[str]) -> tuple[int, str]:
    """Run a subprocess, streaming output. Returns (returncode, log)."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    lines: list[str] = []
    if proc.stdout:
        for line in proc.stdout:
            lines.append(line.rstrip())
    proc.wait()
    return proc.returncode, "\n".join(lines)


def start_job(name: str, cmd: list[str]) -> str:
    return start_sequence(name, [cmd])


def start_sequence(name: str, cmds: list[list[str]]) -> str:
    """Start a sequence of commands as one background job.

    The first command is the actual run; any following commands (ingest / report)
    only execute if the previous one succeeded. Job status is visible via /api/jobs.
    """
    job_id = f"{name}-{int(time.time())}"
    with JOB_LOCK:
        JOBS[job_id] = {"name": name, "status": "running", "log": "", "created": time.time()}

    def worker():
        logs: list[str] = []
        for cmd in cmds:
            code, log = run_command(cmd)
            logs.append(log)
            if code != 0:
                with JOB_LOCK:
                    JOBS[job_id]["status"] = "error"
                    JOBS[job_id]["log"] = "\n".join(logs)
                    JOBS[job_id]["code"] = code
                    JOBS[job_id]["finished"] = time.time()
                return
        with JOB_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["log"] = "\n".join(logs)
            JOBS[job_id]["code"] = 0
            JOBS[job_id]["finished"] = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return job_id


# ---------------------------------------------------------------------- helpers

def load_lab_payload() -> dict:
    """Reuse build_report.py to produce the exact LAB payload the dashboard expects."""
    import sqlite3

    sys.path.insert(0, str(SCRIPTS))
    import build_report  # noqa: E402

    conn = sqlite3.connect(DB)
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
        "snapshot_paths": extras["snapshot_paths"],
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


def build_run_cmd(body: dict) -> list[str]:
    """Translate an /api/run body into a run_strategy.py command."""
    mode = body.get("mode", "backtest")
    cmd = [PYTHON, str(SCRIPTS / "run_strategy.py"), mode,
           "--strategy", str(body.get("strategy", "")),
           "--timerange", str(body.get("timerange", "20220101-20240101"))]
    timeframe = str(body.get("timeframe", "5m"))
    if mode == "backtest":
        cmd += ["--timeframe", timeframe]
    elif mode == "hyperopt":
        cmd += ["--timeframe", timeframe,
                "--epochs", str(body.get("epochs", 100)),
                "--loss", str(body.get("loss", "SharpeHyperOptLossDaily"))]
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
        cmd += ["--epochs", str(body.get("epochs", 50)),
                "--loss", str(body.get("loss", "SharpeHyperOptLossDaily")),
                "--train-days", str(body.get("train_days", 90)),
                "--test-days", str(body.get("test_days", 7)),
                "--step-days", str(body.get("step_days", 7))]
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
            with JOB_LOCK:
                jobs = {k: dict(v, log=v["log"][-4000:]) for k, v in sorted(JOBS.items(), reverse=True)[:20]}
            self._send_json(jobs)
            return
        if path == "/api/strategies":
            self._send_json(self._strategies())
            return
        if path == "/api/losses":
            sys.path.insert(0, str(SCRIPTS))
            from run_strategy import KNOWN_LOSSES
            self._send_json({"losses": KNOWN_LOSSES})
            return
        if path == "/api/data":
            try:
                self._send_json(load_lab_payload())
            except Exception as e:  # noqa: BLE001
                self._send_json({"error": str(e)}, 500)
            return
        if path == "/api/hyperopt":
            # drill-down: ?source=strategy_BigZ08_....fthypt&limit=200 or ?strategy=BigZ08
            try:
                self._send_json(self._hyperopt_epochs(qs))
            except Exception as e:  # noqa: BLE001
                self._send_json({"error": str(e)}, 500)
            return
        if path == "/api/walkforward":
            try:
                self._send_json(self._walkforward_detail(qs))
            except Exception as e:  # noqa: BLE001
                self._send_json({"error": str(e)}, 500)
            return
        if path == "/api/hyperopt/files":
            self._send_json(self._hyperopt_files())
            return
        if path == "/api/run/meta":
            try:
                self._send_json(self._run_meta(qs))
            except Exception as e:  # noqa: BLE001
                self._send_json({"error": str(e)}, 500)
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
        if path == "/api/refresh":
            job_id = start_job("refresh", [PYTHON, str(SCRIPTS / "ingest_results.py")])
            start_job(f"report-{job_id}", [PYTHON, str(SCRIPTS / "build_report.py")])
            # return the ingest job id (report will be its sibling)
            self._send_json({"job_id": job_id})
            return
        if path == "/api/report":
            job_id = start_job("report", [PYTHON, str(SCRIPTS / "build_report.py")])
            self._send_json({"job_id": job_id})
            return
        if path == "/api/bench":
            body = read_body(self)
            strategies = body.get("strategies") or []
            timerange = body.get("timerange", "20230101-20240101")
            timeframe = body.get("timeframe", "5m")
            cmd = [PYTHON, str(SCRIPTS / "benchmark_runner.py"),
                   "--timerange", str(timerange), "--timeframe", str(timeframe)]
            if strategies:
                cmd += ["--strategies", *strategies]
            job_id = start_job("benchmark", cmd)
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
            rebuild = body.get("rebuild", True)
            if rebuild:
                job_id = start_sequence("run", [
                    cmd,
                    [PYTHON, str(SCRIPTS / "ingest_results.py")],
                    [PYTHON, str(SCRIPTS / "build_report.py")],
                ])
            else:
                job_id = start_job(f"run-{body.get('mode', 'backtest')}", cmd)
            self._send_json({"job_id": job_id})
            return
        if path == "/api/strategies":
            body = read_body(self)
            name = body.get("name")
            status = body.get("status")
            notes = body.get("notes")
            if not name or status not in ("active", "experimental", "retired"):
                self._send_json({"error": "name + status (active|experimental|retired) required"}, 400)
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
        from pathlib import Path as _P
        base = USER_DATA / "hyperopt_results"
        out: list[dict] = []
        for f in sorted(base.rglob("*.fthypt"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]:
            out.append({"source": f.name, "path": str(f.relative_to(USER_DATA)), "size": f.stat().st_size, "mtime": f.stat().st_mtime})
        return out

    def _hyperopt_epochs(self, qs: dict) -> dict:
        sys.path.insert(0, str(SCRIPTS))
        import analyze_hyperopt as ah  # noqa: E402
        from pathlib import Path as _P

        limit = int(qs.get("limit", ["200"])[0]) if qs.get("limit") else 200
        limit = max(1, min(limit, 2000))
        source = (qs.get("source", [None])[0] if qs.get("source") else None)
        strategy = (qs.get("strategy", [None])[0] if qs.get("strategy") else None)
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
            return {"source": cand.name, "count": len(epochs),
                    "corr": ah.epochs_corr_with_loss(epochs),
                    "records": ah.epochs_to_records(epochs, limit=limit)}
        if strategy:
            p = ah.latest_results(strategy)
            if not p or not p.is_file():
                return {"error": f"no .fthypt for {strategy}"}
            epochs = ah.load_epochs(p)
            return {"source": p.name, "strategy": strategy, "count": len(epochs),
                    "corr": ah.epochs_corr_with_loss(epochs),
                    "records": ah.epochs_to_records(epochs, limit=limit)}
        return {"error": "supply ?source=... or ?strategy=..."}

    def _walkforward_detail(self, qs: dict) -> dict:
        import sqlite3 as _sql
        source = (qs.get("source", [None])[0] if qs.get("source") else None)
        run_id = (qs.get("run_id", [None])[0] if qs.get("run_id") else None)
        strategy = (qs.get("strategy", [None])[0] if qs.get("strategy") else None)
        conn = _sql.connect(DB)
        conn.row_factory = _sql.Row
        q = "SELECT * FROM walkforward WHERE 1=1"
        params: list = []
        if source:
            q += " AND source LIKE ?"
            params.append(f"%{source}%")
        if run_id:
            q += " AND run_id=?"; params.append(run_id)
        if strategy:
            q += " AND strategy=?"; params.append(strategy)
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
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        want = [c for c in ("strategy", "source", "config_hash", "code_hash",
                            "code_verified", "best_params") if c in cols]
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

    def _strategy_file(self, qs: dict) -> None:
        """Serve a stored strategy snapshot by hash."""
        import sqlite3

        h = qs.get("hash", [None])[0]
        if not h:
            self._send_json({"error": "hash required"}, 400)
            return
        conn = sqlite3.connect(DB)
        row = conn.execute(
            "SELECT source FROM strategy_snapshots WHERE hash=?", (h,)
        ).fetchone()
        conn.close()
        if not row:
            self._send_json({"error": "snapshot not found"}, 404)
            return
        self._send_text(row[0])

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
            return {"found": False, "error": str(e)}

    # ---- db access ----
    def _strategies(self) -> list[dict]:
        import sqlite3

        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            """SELECT s.name, s.status, s.notes,
                      (SELECT COUNT(*) FROM backtests b WHERE b.strategy = s.name) AS n_backtests,
                      (SELECT COUNT(*) FROM trades t WHERE t.strategy = s.name) AS n_trades
               FROM strategies s ORDER BY s.name"""
        )]
        conn.close()
        return rows

    def _set_strategy(self, name: str, status: str, notes: str | None) -> bool:
        import sqlite3

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM strategies WHERE name=?", (name,))
        if cur.fetchone():
            cur.execute("UPDATE strategies SET status=?, notes=? WHERE name=?",
                        (status, notes or "", name))
        else:
            cur.execute("INSERT INTO strategies (name, status, notes) VALUES (?,?,?)",
                        (name, status, notes or ""))
        conn.commit()
        conn.close()
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy Lab web server")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--no-open", action="store_true", help="Don't open the browser")
    args = ap.parse_args()

    if not DB.exists():
        print("No results.db yet — running first ingest (may take a while)...")
        run_command([PYTHON, str(SCRIPTS / "ingest_results.py")])

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
