"""lab.py — one command to run the whole strategy-lab workflow.

Most things are now done from the browser via `lab.py serve` (dashboard + API).
The CLI commands below are convenience wrappers around the same scripts.

Usage:
    python user_data/scripts/lab.py serve [--port P]  # RUN THE WEB APP (recommended)
    python user_data/scripts/lab.py refresh           # ingest + report (CLI fallback)
    python user_data/scripts/lab.py ingest            # scan artifacts into results.db
    python user_data/scripts/lab.py report            # build dashboard.html
    python user_data/scripts/lab.py status            # list strategies + status
    python user_data/scripts/lab.py set <strategy> <active|experimental|retired> [--notes ...]
    python user_data/scripts/lab.py bench [--timerange X] [--timeframe Y] [--strategies ...]
    python user_data/scripts/lab.py open              # open dashboard.html directly (static)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
USER_DATA = SCRIPTS.parent
ANALYSIS = USER_DATA / "analysis"
DB = ANALYSIS / "results.db"
DASHBOARD = ANALYSIS / "dashboard.html"


def run(py_args: list[str]) -> int:
    return subprocess.call([sys.executable, *py_args])


def status(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """SELECT s.name, s.status, s.notes,
                  (SELECT COUNT(*) FROM backtests b WHERE b.strategy = s.name) AS bt,
                  (SELECT COUNT(*) FROM hyperopt h WHERE h.strategy = s.name) AS ho
           FROM strategies s ORDER BY s.name"""
    ).fetchall()
    print(f"{'Strategy':<32} {'Status':<14} {'Backtests':>9} {'Hyperopt':>8}  Notes")
    print("-" * 100)
    for name, st, notes, bt, ho in rows:
        print(f"{name:<32} {st:<14} {bt:>9} {ho:>8}  {notes or ''}")
    return 0


def set_status(conn: sqlite3.Connection, strategy: str, st: str, notes: str | None) -> int:
    if st not in ("active", "experimental", "retired"):
        print(f"Invalid status: {st}. Use active|experimental|retired", file=sys.stderr)
        return 1
    cur = conn.cursor()
    if notes is None:
        cur.execute("UPDATE strategies SET status=? WHERE name=?", (st, strategy))
    else:
        cur.execute("UPDATE strategies SET status=?, notes=? WHERE name=?", (st, notes, strategy))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO strategies (name, status, notes) VALUES (?,?,?)",
                    (strategy, st, notes or ""))
        print(f"Registered new strategy: {strategy}")
    conn.commit()
    print(f"{strategy} -> {st}" + (f" ({notes})" if notes else ""))
    return 0


def serve(port: int) -> int:
    """Run the Strategy Lab web app (dashboard + all controls via API)."""
    import os
    return run([str(SCRIPTS / "server.py"), "--port", str(port)])


def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy lab workflow")
    ap.add_argument("cmd", nargs="?", default="refresh",
                    choices=["ingest", "report", "refresh", "status", "set", "bench", "open", "serve"])
    ap.add_argument("strategy", nargs="?", help="strategy name for 'set'")
    ap.add_argument("status", nargs="?", help="status for 'set'")
    ap.add_argument("--notes", help="notes for 'set'")
    ap.add_argument("--strategies", nargs="*", help="strategy list for 'bench'")
    ap.add_argument("--timerange", default="20230101-20240101")
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--port", type=int, default=8088)
    args = ap.parse_args()

    if args.cmd == "serve":
        return serve(args.port)

    if args.cmd == "open":
        if DASHBOARD.is_file():
            import os
            os.startfile(DASHBOARD)  # noqa: S606
            return 0
        print("Dashboard not found. Run 'lab.py report' first.", file=sys.stderr)
        return 1

    if args.cmd == "ingest":
        return run([str(SCRIPTS / "ingest_results.py")])
    if args.cmd == "report":
        return run([str(SCRIPTS / "build_report.py")])
    if args.cmd == "refresh":
        code = run([str(SCRIPTS / "ingest_results.py")])
        if code != 0:
            return code
        code = run([str(SCRIPTS / "build_report.py")])
        if code != 0:
            return code
        print(f"\nOpen the dashboard:  python user_data/scripts/lab.py open")
        return 0
    if args.cmd == "bench":
        cmd = [str(SCRIPTS / "benchmark_runner.py"),
               "--timerange", args.timerange, "--timeframe", args.timeframe]
        if args.strategies:
            cmd += ["--strategies", *args.strategies]
        code = run(cmd)
        if code == 0:
            print("\nBenchmark done. Rebuild the report:")
            print("  python user_data/scripts/lab.py refresh")
        return code

    conn = sqlite3.connect(DB)
    try:
        if args.cmd == "status":
            return status(conn)
        if args.cmd == "set":
            if not args.strategy or not args.status:
                print("Usage: lab.py set <strategy> <active|experimental|retired> [--notes ...]",
                      file=sys.stderr)
                return 1
            return set_status(conn, args.strategy, args.status, args.notes)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
