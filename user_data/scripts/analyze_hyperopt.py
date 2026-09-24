"""
analyze_hyperopt

Read a freqtrade hyperopt results file (``.fthypt``) and produce a
component-level ranking of every epoch. This is the "maintainer guardrail" for
the SortinoCalmarHyperOptLoss: the loss ranks candidates, but you should also
confirm the ranking is sensible across each component separately (sortino,
calmar, profit factor, SQN, drawdown, MAE, exit efficiency) before trusting it
out of sample.

Usage:
    python user_data/scripts/analyze_hyperopt.py [--results PATH] [--top N] [--best-params N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rapidjson


EPOCH_KEYS = {
    "epoch": "current_epoch",
    "loss": "loss",
    "is_best": "is_best",
    "is_initial": "is_initial_point",
    "trades": ("results_metrics", "total_trades"),
    "profit_total": ("results_metrics", "profit_total"),
    "profit_abs": ("results_metrics", "profit_total_abs"),
    "winrate": ("results_metrics", "winrate"),
    "sortino": ("results_metrics", "sortino"),
    "calmar": ("results_metrics", "calmar"),
    "sharpe": ("results_metrics", "sharpe"),
    "sqn": ("results_metrics", "sqn"),
    "profit_factor": ("results_metrics", "profit_factor"),
    "max_drawdown": ("results_metrics", "max_drawdown_account"),
    "holding_avg_s": ("results_metrics", "holding_avg_s"),
}

# Public API for reuse by build_report / server (D)
__all__ = [
    "EPOCH_KEYS", "_dig", "_get", "_excursion_metrics",
    "latest_results", "load_epochs", "build_frame",
    "epochs_to_records", "epochs_corr_with_loss", "top_epochs",
]


def _dig(obj: dict, path) -> float | None:
    """Safely walk a nested dict path."""
    if isinstance(path, tuple):
        cur = obj
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur
    return obj.get(path)


def _get(row: dict, name: str) -> float | None:
    val = _dig(row, EPOCH_KEYS[name])
    if val is None:
        return None
    if isinstance(val, (int, float, np.number)):
        return float(val)
    if isinstance(val, str) and val != "":
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _excursion_metrics(trades: list[dict]) -> tuple[float, float]:
    """MAE and MFE-capture (exit efficiency) from embedded trade data."""
    mfe, mae, eff = [], [], []
    for t in trades:
        open_rate = float(t.get("open_rate") or 0.0)
        min_rate = float(t.get("min_rate") or 0.0)
        max_rate = float(t.get("max_rate") or 0.0)
        profit = float(t.get("profit_ratio") or 0.0)
        if open_rate <= 0:
            continue
        is_short = bool(t.get("is_short", False))
        if is_short:
            t_mfe = (open_rate - min_rate) / open_rate
            t_mae = (min_rate - open_rate) / open_rate
        else:
            t_mfe = (max_rate - open_rate) / open_rate
            t_mae = (open_rate - min_rate) / open_rate
        t_mfe = max(t_mfe, 0.0)
        t_mae = max(t_mae, 0.0)
        mfe.append(t_mfe)
        mae.append(t_mae)
        if t_mfe > 0:
            eff.append(min(max(profit / t_mfe, 0.0), 1.0))
        else:
            eff.append(0.0)
    if not mfe:
        return 0.0, 0.0
    return float(np.mean(mae)), float(np.mean(eff))


def latest_results(strategy: str = "") -> Path | None:
    candidates = sorted(
        Path("user_data/hyperopt_results").glob(f"*{strategy}*.fthypt"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def load_epochs(results: Path) -> list[dict]:
    epochs = []
    with results.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            epochs.append(
                rapidjson.loads(line, number_mode=rapidjson.NM_NATIVE | rapidjson.NM_NAN)
            )
    return epochs


def build_frame(epochs: list[dict]) -> pd.DataFrame:
    rows = []
    for row in epochs:
        trades = row.get("results_metrics", {}).get("trades", []) or []
        mae, eff = _excursion_metrics(trades)
        buy = row.get("params_dict", {}).get("buy", {})
        sell = row.get("params_dict", {}).get("sell", {})
        params_dict = row.get("params_dict", {}) or {}
        rows.append(
            {
                "epoch": _get(row, "epoch"),
                "loss": _get(row, "loss"),
                "best": bool(row.get("is_best", False)),
                "init": bool(row.get("is_initial_point", False)),
                "trades": _get(row, "trades"),
                "profit_total": _get(row, "profit_total"),
                "winrate": _get(row, "winrate"),
                "sortino": _get(row, "sortino"),
                "calmar": _get(row, "calmar"),
                "sharpe": _get(row, "sharpe"),
                "sqn": _get(row, "sqn"),
                "profit_factor": _get(row, "profit_factor"),
                "max_drawdown": _get(row, "max_drawdown"),
                "holding_days": (
                    (_get(row, "holding_avg_s") or 0.0) / 86400.0
                    if _get(row, "holding_avg_s")
                    else None
                ),
                "mae": mae,
                "exit_eff": eff,
                "ema_length": buy.get("ema_length"),
                "length_kc": buy.get("length_kc"),
                "sl_mult": sell.get("sl_size_or_atr_multiplier"),
                "rr": sell.get("risk_reward_ratio"),
                "max_days": sell.get("max_trade_duration_days"),
                "params_dict": params_dict,
            }
        )
    return pd.DataFrame(rows)


def epochs_to_records(epochs: list[dict], limit: int = 200) -> list[dict]:
    """Lightweight JSON-serializable view for the dashboard/server (no pandas needed)."""
    df = build_frame(epochs)
    # sort by loss asc
    if not df.empty and "loss" in df:
        df = df.sort_values("loss", na_position="last")
    out: list[dict] = []
    for _, r in df.head(limit).iterrows():
        rec = {k: (None if pd.isna(v) else v) for k, v in r.to_dict().items()}
        # params_dict is already serializable, ensure it survives pd.isna handling
        if isinstance(rec.get("params_dict"), float) and np.isnan(rec["params_dict"]):
            rec["params_dict"] = {}
        out.append(rec)
    return out


def epochs_corr_with_loss(epochs: list[dict]) -> dict[str, float]:
    """Correlation of each component with loss – mirrors CLI printout."""
    df = build_frame(epochs)
    comps = ["sortino", "calmar", "profit_factor", "sqn", "exit_eff", "mae", "max_drawdown"]
    if df.empty or "loss" not in df:
        return {}
    cols = [c for c in ["loss", *comps] if c in df.columns]
    corr = df[cols].corr(numeric_only=True)["loss"].drop("loss", errors="ignore")
    return {k: float(v) for k, v in corr.items() if pd.notna(v)}


def top_epochs(epochs: list[dict], n: int = 15, column: str = "loss", ascending: bool = True) -> list[dict]:
    df = build_frame(epochs)
    if df.empty or column not in df.columns:
        return []
    sub = df.sort_values(column, ascending=ascending).head(n)
    out: list[dict] = []
    for _, r in sub.iterrows():
        rec = {k: (None if pd.isna(v) else v) for k, v in r.to_dict().items()}
        out.append(rec)
    return out


def _print_top(df: pd.DataFrame, column: str, n: int, ascending: bool, label: str) -> None:
    if df[column].isna().all():
        return
    sub = df.sort_values(column, ascending=ascending).head(n)
    print(f"\nTop {n} by {label}:")
    cols = [
        c
        for c in [
            "epoch",
            column,
            "loss",
            "trades",
            "profit_total",
            "max_drawdown",
            "exit_eff",
            "mae",
        ]
        if c in sub
    ]
    cols = list(dict.fromkeys(cols))  # avoid duplicating the sort column
    print(sub[cols].to_string(index=False, float_format=lambda v: f"{v:.4g}"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--results", help="Path to .fthypt file (default: latest for OctopusNestStrategy)"
    )
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--best-params", type=int, default=0, help="Dump top-N parameter sets to JSON")
    args = ap.parse_args()

    results = Path(args.results) if args.results else latest_results("OctopusNestStrategy")
    if not results or not results.is_file():
        print("No results file found.", file=sys.stderr)
        return 1
    print(f"Reading {results.name} ({results.stat().st_size / 1e6:.1f} MB)")

    epochs = load_epochs(results)
    df = build_frame(epochs)
    print(f"{len(df)} epochs")

    _print_top(df, "loss", args.top, ascending=True, label="SortinoCalmar loss (lower = better)")
    _print_top(df, "sortino", 5, ascending=False, label="sortino")
    _print_top(df, "calmar", 5, ascending=False, label="calmar")
    _print_top(df, "profit_factor", 5, ascending=False, label="profit factor")
    _print_top(df, "sqn", 5, ascending=False, label="SQN")
    _print_top(df, "exit_eff", 5, ascending=False, label="exit efficiency")
    _print_top(df, "max_drawdown", 5, ascending=True, label="lowest drawdown")

    print("\nComponent correlation with loss (all epochs):")
    comps = ["sortino", "calmar", "profit_factor", "sqn", "exit_eff", "mae", "max_drawdown"]
    corr = df[["loss", *comps]].corr()["loss"].drop("loss")
    print(corr.to_string(float_format=lambda v: f"{v:+.2f}"))

    if args.best_params > 0:
        top = df.sort_values("loss").head(args.best_params)
        params = []
        for _, r in top.iterrows():
            row = epochs[int(r["epoch"]) - 1] if r["epoch"] else {}
            params.append(
                {
                    "epoch": int(r["epoch"]) if pd.notna(r["epoch"]) else None,
                    "loss": float(r["loss"]) if pd.notna(r["loss"]) else None,
                    "params_dict": row.get("params_dict", {}),
                }
            )
        out = Path(f"user_data/top{args.best_params}_params.json")
        out.write_text(json.dumps(params, indent=2), encoding="utf-8")
        print(f"\nTop {args.best_params} parameter sets written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
