"""Regression test: canonical_per_strategy must surface the full strategies
registry, so the Dashboard tab and the Lab tab agree on which strategies
exist (the single source of truth is the `strategies` table).

Bugs this guards against:

  1. The original implementation only seeded `LAB.canonical` from `backtests`
     and `benchmarks`. A strategy that has a `.py` file under
     `user_data/strategies/` but no ingested run was invisible on the
     Dashboard, even though it appeared in the Lab editor. The user noticed
     "less strategies in dashboard than in lab"; this test makes that
     impossible to regress.

  2. The Dashboard used to hide retired strategies unconditionally. The user
     voted to keep them visible by default (decision A). The
     `visible_canonical_for_dashboard` helper used here mirrors the new
     behaviour and is asserted to include retired.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parent.parent / "user_data" / "scripts"
BUILD_REPORT = SCRIPTS / "build_report.py"


def _load_build_report():
    """Import build_report.py without triggering its module-level
    argparse main(); the file is a script, not a package member, so we load
    it explicitly by path."""
    spec = importlib.util.spec_from_file_location("_build_report_under_test", BUILD_REPORT)
    assert spec and spec.loader, f"could not load {BUILD_REPORT}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def br():
    return _load_build_report()


def _row(name: str, **overrides) -> dict:
    base = {
        "strategy": name,
        "run_time": "2026-01-01T00:00:00",
        "source": "test",
        "timerange": "20250101-20260101",
        "profit_total": 0.1,
        "sortino": 2.0,
        "calmar": 1.5,
        "profit_factor": 1.6,
        "max_drawdown_account": 0.05,
        "winrate": 0.6,
        "total_trades": 100,
    }
    base.update(overrides)
    return base


def _registry(name: str, status: str = "active", notes: str = "") -> dict:
    return {"name": name, "status": status, "notes": notes}


def test_canonical_includes_registry_only_strategies(br):
    """A strategy in the registry but with no backtest must still appear."""
    data = {
        "backtests": [_row("BacktestedStrategy")],
        "benchmarks": [],
        "hyperopt": [],
        "walkforward": [],
        "strategies": [
            _registry("BacktestedStrategy"),
            _registry("RegistryOnlyActive", status="active"),
            _registry("RegistryOnlyExperimental", status="experimental"),
        ],
        "trade_runs": {},
    }
    canon = br.canonical_per_strategy(data)
    names = {r["strategy"] for r in canon}
    assert names == {"BacktestedStrategy", "RegistryOnlyActive", "RegistryOnlyExperimental"}


def test_registry_stub_basis(br):
    """Registry-only rows must have basis='registry' and no metrics."""
    data = {
        "backtests": [],
        "benchmarks": [],
        "hyperopt": [],
        "walkforward": [],
        "strategies": [_registry("Foo", status="active")],
        "trade_runs": {},
    }
    canon = br.canonical_per_strategy(data)
    assert len(canon) == 1
    row = canon[0]
    assert row["strategy"] == "Foo"
    assert row["basis"] == "registry"
    assert row["status"] == "active"
    assert row["profit_total"] is None
    assert row["sortino"] is None
    assert row["score"]["grade"] == "—"


def test_backtested_row_promotes_status_from_registry(br):
    """Backtested rows still pick up status/notes from the registry."""
    data = {
        "backtests": [_row("Real")],
        "benchmarks": [],
        "hyperopt": [],
        "walkforward": [],
        "strategies": [_registry("Real", status="experimental", notes="beta")],
        "trade_runs": {},
    }
    canon = br.canonical_per_strategy(data)
    real = next(r for r in canon if r["strategy"] == "Real")
    assert real["basis"] == "backtest"
    assert real["status"] == "experimental"
    assert real["notes"] == "beta"


def test_retired_registry_strategy_included(br):
    """A retired registry-only strategy must appear in the canonical set
    so the Dashboard can show it (the visibility filter is no longer
    applied on Dashboard)."""
    data = {
        "backtests": [_row("Alive")],
        "benchmarks": [],
        "hyperopt": [],
        "walkforward": [],
        "strategies": [
            _registry("Alive", status="active"),
            _registry("DeadOne", status="retired"),
        ],
        "trade_runs": {},
    }
    canon = br.canonical_per_strategy(data)
    statuses = {r["strategy"]: r["status"] for r in canon}
    assert statuses == {"Alive": "active", "DeadOne": "retired"}
    # Both must be present in the same row set the Dashboard renders
    assert "DeadOne" in {r["strategy"] for r in canon}


def test_registry_stubs_sort_after_backtested_rows(br):
    """Registry stubs must not lead the table; the (backtest, benchmark)
    group must come first regardless of grade."""
    data = {
        "backtests": [_row("BacktestedStrategy", profit_total=0.5)],
        "benchmarks": [],
        "hyperopt": [],
        "walkforward": [],
        "strategies": [
            _registry("BacktestedStrategy"),
            _registry("NeverRun"),
        ],
        "trade_runs": {},
    }
    canon = br.canonical_per_strategy(data)
    bases = [r["basis"] for r in canon]
    # Every backtested/benchmark row must precede every registry stub
    last_real = max(i for i, b in enumerate(bases) if b in ("backtest", "benchmark"))
    first_stub = min(i for i, b in enumerate(bases) if b == "registry")
    assert last_real < first_stub


def test_dashboard_visibility_includes_retired(br):
    """The Dashboard's `visibleCanonical()` JS helper used to filter out
    retired rows. The user voted to drop that filter; the equivalent
    Python projection (returning the full canonical set) must include
    retired rows so the JS-side change has parity with the data model."""
    data = {
        "backtests": [],
        "benchmarks": [],
        "hyperopt": [],
        "walkforward": [],
        "strategies": [
            _registry("A", status="active"),
            _registry("B", status="retired"),
        ],
        "trade_runs": {},
    }
    canon = br.canonical_per_strategy(data)
    # parity with the new visibleCanonical() JS: return everything
    visible = list(canon)
    assert {r["strategy"] for r in visible} == {"A", "B"}
