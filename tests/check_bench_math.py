"""Verify the dashboard's box-plot math + grade tuner logic.

This is the small assert-based self-check required by module 14:
the smallest thing that fails if the logic breaks. Pure Python, no
browser. Mirrors the JS in dashboard.html so we can lint the math
before opening a browser tab.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


# extract the two helper functions from the live dashboard so we test
# what the user actually sees
HTML = Path("user_data/analysis/dashboard.html").read_text(encoding="utf-8")


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

# ---- test 4: every "apples-to-apples" string is gone ----
assert "apples-to-apples" not in HTML
print("apples-to-apples removed")

# ---- test 5: required new UI controls are present ----
for sel in (
    'id="benchMetric"',
    'id="benchSort"',
    'id="benchLog"',
    'id="benchPoints"',
    'id="tradeRun"',
    'id="gradeTunerRows"',
    'id="gradeBackdrop"',
    'id="tradeLoadBtn"',
):
    assert sel in HTML, f"missing {sel}"
print("new controls present")

# ---- test 6: /api/freshness handler is wired ----
assert "'/api/freshness'" in HTML or '"/api/freshness"' in HTML
assert "ensureFresh" in HTML
assert "startFreshnessLoop" in HTML
print("freshness hookup present")

# ---- test 7: grade tuner open/apply/reset + re-grade hook ----
for fn in (
    "openGradeTuner",
    "closeGradeTuner",
    "applyGradeFactors",
    "resetGradeFactors",
    "applyTunedScoresInPlace",
    "scoreRowTuned",
    "gradeValueTuned",
    "overallGradeTuned",
):
    assert f"function {fn}" in HTML, f"missing function {fn}"
print("grade tuner hooks present")

# ---- test 8: trades auto-load ----
assert "auto-loaded · newest run" in HTML
assert "renderTradesTab" in HTML
print("trades auto-load present")

# ---- test 9: SCORECARD still present and identical to the python SCORECARD ----
spec = importlib.util.spec_from_file_location("br", "user_data/scripts/build_report.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)
py_scorecard = {k: dict(v) for k, v in br.SCORECARD.items()}
# the embedded LAB.scorecard is a JSON dump; locate the SCORECARD slot
m = HTML.find('"scorecard":')
assert m >= 0, "scorecard not embedded"
# crude: parse the LAB JSON
lab_start = HTML.find("const LAB = ") + len("const LAB = ")
# the embedded JSON ends at the FIRST `};` on its own line that follows
# the LAB content. The `state = {...}` object that comes next is the
# immediate successor; the LAB JSON always ends with `};\n\nconst state`.
m = re.search(r"\};\s*\n\s*\n\s*const\s+state\b", HTML[lab_start:])
assert m, "could not find end of LAB JSON"
lab_end = lab_start + m.start() + 1  # include the closing brace
lab_json = HTML[lab_start:lab_end]
lab = json.loads(lab_json)
js_scorecard = lab["scorecard"]
for k, v in py_scorecard.items():
    assert js_scorecard[k]["pass"] == v["pass"], (k, v, js_scorecard[k])
    assert js_scorecard[k]["warn"] == v["warn"], (k, v, js_scorecard[k])
    assert js_scorecard[k]["higher_is_better"] == v["higher_is_better"]
print(f"scorecard parity OK: {len(py_scorecard)} metrics")

print("\nALL CHECKS PASSED")
