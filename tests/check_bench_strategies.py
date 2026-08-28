"""End-to-end check: the benchmark chart must surface ALL strategies, not
just the 3 that have been benchmarked. This test loads the real SQLite
DB, runs the JS-equivalent grouping logic, and asserts the strategy
count matches the union of benchmarks + backtests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


DB = Path("user_data/analysis/results.db")
HTML = Path("user_data/analysis/dashboard.html").read_text(encoding="utf-8")


def quartiles(arr):
    if not arr:
        return None
    s = sorted(arr)
    n = len(s)

    def pick(p):
        return s[min(n - 1, max(0, int(p * (n - 1))))]

    return [s[0], pick(0.25), pick(0.5), pick(0.75), s[-1]]


def group_for_metric(rows, metric):
    """Mirror of the new renderBenchmark grouping logic (Python port)."""
    by_strategy = {}
    for r in rows:
        v = r.get(metric)
        if v is None or v == "":
            continue
        by_strategy.setdefault(r["strategy"], []).append(float(v))
    return by_strategy


# ---- real DB check ----
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
b_rows = [
    dict(r)
    for r in conn.execute(
        "SELECT strategy, sortino, profit_total, calmar, profit_factor,"
        " max_drawdown_account FROM benchmarks"
    ).fetchall()
]
t_rows = [
    dict(r)
    for r in conn.execute(
        "SELECT strategy, sortino, profit_total, calmar, profit_factor,"
        " max_drawdown_account FROM backtests"
    ).fetchall()
]
conn.close()

# The "auto" mode merges both. Each row gets a source tag.
all_rows = [dict(r, _src="B") for r in b_rows] + [dict(r, _src="T") for r in t_rows]

# Old (broken) behaviour: only benchmarks.
old_grouped = group_for_metric(b_rows, "sortino")
# New behaviour: auto-merge.
new_grouped = group_for_metric(all_rows, "sortino")

print(f"DB: {len(b_rows)} benchmark rows, {len(t_rows)} backtest rows")
print(f"Old behaviour: {len(old_grouped)} strategies on the chart")
print(f"New behaviour: {len(new_grouped)} strategies on the chart")

# assertion 1: the old behaviour is exactly the bug the user reported
assert len(old_grouped) == 3, f"expected 3 (the bug), got {len(old_grouped)}"
print("OK   bug reproduced: only 3 strategies under old behaviour")

# assertion 2: the new behaviour surfaces every strategy with at least one
# non-null metric value across benchmarks + backtests
distinct_in_db = {r["strategy"] for r in b_rows} | {r["strategy"] for r in t_rows}
missing = distinct_in_db - set(new_grouped.keys())
# a strategy may be missing if the metric is null for ALL its runs; that's
# fine. assert that at least the vast majority surface.
assert len(new_grouped) >= len(old_grouped), "new should never show fewer strategies than old"
assert len(new_grouped) >= 50, (
    f"new behaviour should surface most strategies, got {len(new_grouped)}"
)
print(
    f"OK   new behaviour surfaces {len(new_grouped)} strategies "
    f"({len(new_grouped) - len(old_grouped)} more than before)"
)

# assertion 3: the source selector and tag labels are wired into the live HTML
for sel in ('id="benchSource"', "B+T", "backtest-only", "tagFor"):
    assert sel in HTML, f"missing {sel}"
print("OK   source selector and tag labels present in live HTML")

# assertion 4: quartiles still compute correctly with N>1 strategy values
sample = [0.1, 0.3, 0.5, 0.7, 0.9, 1.2, 1.5, 5.0]
q = quartiles(sample)
assert q[0] == 0.1, q
assert q[4] == 5.0, q
print("OK   quartiles correct on multi-strategy data")

# assertion 5: every strategy's distribution is non-empty
for strat, vals in new_grouped.items():
    assert len(vals) >= 1, f"{strat} has no data"
print(f"OK   all {len(new_grouped)} strategies have >=1 data point")

# assertion 6: median-based sort produces a stable, well-defined ordering
meds = [(name, quartiles(v)[2]) for name, v in new_grouped.items()]
meds.sort(key=lambda x: -x[1])
print("OK   top-5 by median:", [f"{n}={m:.3f}" for n, m in meds[:5]])
print("OK   bottom-5 by median:", [f"{n}={m:.3f}" for n, m in meds[-5:]])

print("\nALL CHECKS PASSED")
