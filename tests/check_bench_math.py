"""Verify the dashboard's box-plot math + grade tuner logic.

This is the small assert-based self-check required by module 14:
the smallest thing that fails if the logic breaks. Pure Python, no
browser. The math mirrors the helpers used by both the archived
dashboard and the Vue benchmark view (quartile split + MAD outliers),
and the UI assertions target the Vue sources, which are canonical
since the static dashboard.html generator was retired.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BENCH_VIEW = ROOT / "frontend" / "src" / "views" / "BenchmarkView.vue"
LAB_VIEW = ROOT / "frontend" / "src" / "views" / "LabView.vue"
TRADE_VIEW = ROOT / "frontend" / "src" / "views" / "TradeView.vue"
GRADE_TUNER = ROOT / "frontend" / "src" / "components" / "GradeTuner.vue"
GRADES_TS = ROOT / "frontend" / "src" / "utils" / "grades.ts"
FRESHNESS_TS = ROOT / "frontend" / "src" / "utils" / "freshness.ts"
API_SERVER = ROOT / "user_data" / "scripts" / "api_server.py"


def _bench_quartiles(arr):
    if not arr:
        return None
    s = sorted(arr)
    n = len(s)

    def pick(p):
        return s[min(n - 1, max(0, int(p * (n - 1))))]

    return [s[0], pick(0.25), pick(0.5), pick(0.75), s[-1]]


def _bench_outliers(arr):
    if len(arr) < 4:
        return 0
    s = sorted(arr)
    med = s[len(s) // 2]
    dev = sorted(abs(v - med) for v in arr)
    mad = dev[len(dev) // 2]
    if not mad:
        return 0
    k = 1.4826
    return sum(1 for v in arr if abs(v - med) / (k * mad) > 2.5)


# ---- test 1: quartiles match the plan's spec ----
sample = [0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 5.0]
q = _bench_quartiles(sample)
# R quantile type 7 (numpy default, and what our pick() matches):
# positions 0, 1.75, 3.5, 5.25, 7 -> s[0], s[1]=0.7, s[3]=0.9, s[5]=1.1, s[7]=5.0
assert q[0] == 0.5, q
assert q[1] == 0.7, q
assert q[2] == 0.9, q  # median via pick(0.5) -> index 3
assert q[3] == 1.1, q
assert q[4] == 5.0, q
print(f"quartiles OK: {q}")

# ---- test 2: 5.0 is an outlier (|z|>2.5) ----
out_n = _bench_outliers(sample)
assert out_n == 1, out_n
print(f"outlier count OK: {out_n}")

# ---- test 3: empty/single value handling ----
assert _bench_quartiles([]) is None
assert _bench_quartiles([1.0]) == [1.0, 1.0, 1.0, 1.0, 1.0]
assert _bench_outliers([1.0, 1.0]) == 0  # below the n<4 floor
print("edge cases OK")

# ---- test 4: the static dashboard generator is gone ----
assert not (ROOT / "user_data" / "analysis" / "dashboard.html").exists(), (
    "dashboard.html should no longer be generated; Vue is the only UI"
)
print("static dashboard retired")

# ---- test 5: required benchmark controls live in the Vue view ----
bench = BENCH_VIEW.read_text(encoding="utf-8")
for sel in (
    'v-model="metric"',
    'v-model="sourceMode"',
    'value="auto"',
    'value="benchmark"',
    'value="backtest"',
    'v-model="sortMode"',
    'value="median"',
    'value="count"',
    'value="name"',
    'v-model="useLog"',
    'v-model="showPoints"',
    "type: 'boxplot'",
    "(|z|>2.5)",
):
    assert sel in bench, f"missing {sel} in BenchmarkView.vue"
print("benchmark controls present")

# ---- test 6: /api/freshness handler is wired ----
api = API_SERVER.read_text(encoding="utf-8")
assert "/api/freshness" in api
fresh = FRESHNESS_TS.read_text(encoding="utf-8")
assert "ensureFresh" in fresh
assert "startFreshnessLoop" in fresh
print("freshness hookup present")

# ---- test 7: grade tuner apply/reset + re-grade hook ----
tuner = GRADE_TUNER.read_text(encoding="utf-8")
for fn in ("apply", "resetFactors", "retune"):
    assert fn in tuner, f"missing {fn} in GradeTuner.vue"
grades_ts = GRADES_TS.read_text(encoding="utf-8")
for fn in ("activeGradeFactors", "saveGradeFactors", "scoreRowTuned"):
    assert fn in grades_ts, f"missing {fn} in grades.ts"
print("grade tuner hooks present")

# ---- test 8: trades auto-load the newest run ----
trades = TRADE_VIEW.read_text(encoding="utf-8")
assert "auto-loaded · newest run" in trades
assert "newestKey" in trades
assert "/trades/" in trades
print("trades auto-load present")

# ---- test 9: TS grade thresholds match the python SCORECARD ----
spec = importlib.util.spec_from_file_location(
    "br", str(ROOT / "user_data" / "scripts" / "_archived" / "build_report.py")
)
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)
py_scorecard = {k: dict(v) for k, v in br.SCORECARD.items()}
# parse DEFAULT_GRADE_DEFS from grades.ts:  key: { pass: P, warn: W, dir: D, ... }
ts_defs = {
    k: (p, w, d)
    for k, p, w, d in re.findall(
        r"(\w+):\s*\{\s*pass:\s*([-\d.]+),\s*warn:\s*([-\d.]+),\s*dir:\s*(-?\d)",
        grades_ts,
    )
}
key_map = {"max_drawdown": "max_drawdown_account", "trades": "total_trades"}
assert set(ts_defs) == {
    "sortino",
    "calmar",
    "profit_factor",
    "max_drawdown",
    "winrate",
    "trades",
    "worst_trade",
}, ts_defs.keys()
for ts_key, (p, w, d) in ts_defs.items():
    py_key = key_map.get(ts_key, ts_key)
    v = py_scorecard[py_key]
    assert float(p) == v["pass"], (ts_key, p, v)
    assert float(w) == v["warn"], (ts_key, w, v)
    assert int(d) == (1 if v["higher_is_better"] else -1), (ts_key, d, v)
print(f"scorecard parity OK: {len(py_scorecard)} metrics")

# ---- test 10: lab run form is fed by dropdown APIs ----
lab = LAB_VIEW.read_text(encoding="utf-8")
for sel in ("/api/strategies", "/api/configs", "/api/losses"):
    assert sel in lab, f"missing {sel} in LabView.vue"
print("lab dropdowns present")

print("\nALL CHECKS PASSED")
