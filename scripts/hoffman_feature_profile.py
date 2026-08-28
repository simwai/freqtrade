"""Winner/loser feature diagnostic for the Hoffman IRB strategy.

Profiles the features present at each trade's setup bar against the trade's
outcome (``profit_ratio > 0``) on real backtest output, then re-checks the
candidate features on a second, out-of-sample backtest.  A feature is
considered to "separate" winners from losers only when the discovery
quintiles are roughly monotonic *and* the same direction survives the
out-of-sample backtest with adequate sample counts.

The script is intentionally additive: it does not change the strategy.  It
reads two backtest result zips (default: 2023 discovery, 2024-H1
validation), reconstructs the setup-bar feature frame per pair from the
cached feather data, and prints per-feature bucket tables and verdicts.

Usage (run from the repo root)::

    python scripts/hoffman_feature_profile.py \\
        --result user_data/backtest_results/backtest-result-2026-08-27_19-25-02.zip \\
        --result user_data/backtest_results/backtest-result-2026-08-28_13-28-41.zip \\
        --datadir user_data/data/binance

The strategy class is loaded by name from ``user_data.strategies.pattern``
(falling back to exec-ing the source snapshot stored inside the result zip),
so no behaviour change to the base strategy is required to run the
diagnostic.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from freqtrade.configuration import TimeRange
from freqtrade.data.history import load_pair_history
from freqtrade.enums import CandleType
from freqtrade.exchange import timeframe_to_seconds


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATADIR = REPO_ROOT / "user_data" / "data" / "binance"

# Per-feature thresholds: the discovery quintiles must be roughly monotonic
# (Spearman |rho| >= DISC_RHO, <= MAX_INVERSIONS sign inversions across
# buckets) with a meaningful spread between the extreme buckets, and each
# bucket must hold a minimum number of trades.  The validation bar is set
# lower because the out-of-sample window is smaller.
DISC_RHO = 0.6
DISC_SPREAD_PP = 0.04  # 4 percentage points
DISC_MIN_TOTAL = 200
DISC_MIN_BUCKET = 20
VAL_RHO = 0.4
VAL_SPREAD_PP = 0.03
VAL_MIN_TOTAL = 150
VAL_MIN_BUCKET = 15
MAX_INVERSIONS = 1  # allowed sign inversions in the bucket win-rate sequence


@dataclass(frozen=True)
class FeatureSpec:
    """One profiled feature and how to compute it from the strategy frame."""

    name: str
    description: str


# Features profiled at the setup bar.  All inputs are either confirmed-bar
# (shifted) series that the strategy already populates, or the setup
# candle's own volume derived from the raw volume column.
FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("atr_pct", "ATR as a fraction of setup-candle close"),
    FeatureSpec(
        "atr_pct_pctile_500",
        "atr_pct rank within the trailing 500 setup bars (volatility regime)",
    ),
    FeatureSpec("range_atr", "IRB range (h1-l1) normalised by ATR"),
    FeatureSpec("range_pct", "IRB range as a fraction of setup-candle close"),
    FeatureSpec("ema_slope", "Base-EMA bar-to-bar change normalised by price"),
    FeatureSpec("extension", "Distance of c1 from base EMA in ATR units"),
    FeatureSpec("htf_extension", "Distance of c1 from HTF EMA in ATR units"),
    FeatureSpec("hour", "Setup-bar hour (UTC)"),
    FeatureSpec("volume_ratio", "Setup-candle volume vs its 20-bar mean (causal)"),
    FeatureSpec("body_pos", "Setup-candle close position inside the IRB range"),
)


@dataclass
class PeriodProfile:
    """Trades, labels, and features for a single backtest period."""

    label: str
    timerange: str
    pairs: list[str]
    rows: pd.DataFrame  # one row per matched setup bar, with feature columns
    feature_names: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.rows)


@dataclass
class FeatureVerdict:
    feature: str
    passes: bool
    direction: int  # +1 higher = better, -1 lower = better, 0 unclear
    suggested_threshold: float | None
    suggested_side: str
    n_disc: int
    n_val: int
    disc_rho: float
    val_rho: float
    disc_spread_pp: float
    val_spread_pp: float
    note: str = ""


# ---------------------------------------------------------------------------
# Strategy loading
# ---------------------------------------------------------------------------
def _load_strategy_class(strategy_name: str, result_zip: zipfile.ZipFile) -> type:
    """Return the strategy class, importing by name or exec-ing the zip snapshot.

    Prefers the live import (``user_data.strategies.pattern.<name>``) so the
    diagnostic always reflects the current source.  Falls back to the source
    snapshot stored inside the result zip, which guarantees the replay
    matches the backtest exactly even if the variant file has since been
    removed.
    """
    module_path = f"user_data.strategies.pattern.{strategy_name}"
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, strategy_name)
        return cls
    except (ImportError, AttributeError):
        pass
    snapshot_name = next(
        (n for n in result_zip.namelist() if n.endswith(f"_{strategy_name}.py")),
        None,
    )
    if snapshot_name is None:
        raise SystemExit(f"strategy {strategy_name!r} not importable and no source snapshot in zip")
    source = result_zip.read(snapshot_name).decode("utf-8")
    module = ModuleType(f"hoffman_diag.{strategy_name}")
    # The snapshot is freqtrade's own copy of the strategy the user submitted
    # to the backtest; exec'ing it here guarantees the replay matches the
    # backtest even if the variant file was later removed.
    exec(compile(source, snapshot_name, "exec"), module.__dict__)  # noqa: S102
    cls = getattr(module, strategy_name)
    return cls


class _DP:
    """Minimal dataprovider stub backed by pre-loaded 15m dataframes.

    Mirrors the test's ``_FakeDP`` pattern but reads from a real
    per-pair, per-timeframe dataframe cache instead of synthetic candles.
    The base timeframe is not requested via ``get_pair_dataframe``; the
    strategy only queries the HTF (15m) for the EMA merge.
    """

    def __init__(self, htf_data: dict[str, pd.DataFrame], pairs: list[str]) -> None:
        self._htf = htf_data
        self._pairs = pairs

    def current_whitelist(self) -> list[str]:
        return list(self._pairs)

    def get_pair_dataframe(self, pair: str, timeframe: str, candle_type: str = "") -> pd.DataFrame:
        if timeframe not in self._htf:
            raise KeyError(f"no HTF cache for {timeframe}")
        return self._htf[timeframe].get(pair, pd.DataFrame()).copy()


# ---------------------------------------------------------------------------
# Result zip introspection
# ---------------------------------------------------------------------------
def _read_result_zip(path: Path) -> dict[str, Any]:
    """Read the strategy stats, config, and trades from a backtest result zip."""
    with zipfile.ZipFile(path) as z:
        result_files = [n for n in z.namelist() if n.endswith(".json")]
        if len(result_files) != 2:
            raise SystemExit(f"unexpected zip layout in {path}: {result_files}")
        config_name = next(n for n in result_files if n.endswith("_config.json"))
        result_name = next(n for n in result_files if n != config_name)
        config = json.loads(z.read(config_name))
        result = json.loads(z.read(result_name))
    strategy_name, strategy_stats = next(iter(result["strategy"].items()))
    if strategy_name != config.get("strategy_name", strategy_name):
        # The 2023 zip's config omits strategy_name; the result is authoritative.
        pass
    return {
        "strategy_name": strategy_name,
        "stats": strategy_stats,
        "config": config,
        "timerange": strategy_stats["timerange"],
        "trades": strategy_stats["trades"],
    }


# ---------------------------------------------------------------------------
# Frame replay + feature computation
# ---------------------------------------------------------------------------
def _load_base_frame(
    pair: str, timeframe: str, datadir: Path, timerange: TimeRange, startup: int
) -> pd.DataFrame:
    """Load the base-timeframe data the backtest would have used.

    Mirrors ``Backtest.load_bt_data``: subtract ``startup`` base-timeframe
    candles from the start so ``populate_indicators`` sees the same warm-up
    history the strategy had at run time.
    """
    extended = TimeRange(
        starttype=timerange.starttype,
        stoptype=timerange.stoptype,
        startts=timerange.startts,
        stopts=timerange.stopts,
    )
    extended.subtract_start(timeframe_to_seconds(timeframe) * startup)
    return load_pair_history(
        pair=pair,
        timeframe=timeframe,
        datadir=datadir,
        timerange=extended,
        candle_type=CandleType.FUTURES,
    )


def _load_htf_frame(
    pair: str,
    htf: str,
    datadir: Path,
    timerange: TimeRange,
    startup: int,
) -> pd.DataFrame:
    """Load the HTF data the backtest's dataprovider would have used.

    Matches ``DataProvider.historic_ohlcv``: subtract ``startup`` HTF candles
    from the start so the informative merge covers the full base frame.
    """
    extended = TimeRange(
        starttype=timerange.starttype,
        stoptype=timerange.stoptype,
        startts=timerange.startts,
        stopts=timerange.stopts,
    )
    extended.subtract_start(timeframe_to_seconds(htf) * startup)
    return load_pair_history(
        pair=pair,
        timeframe=htf,
        datadir=datadir,
        timerange=extended,
        candle_type=CandleType.FUTURES,
    )


def _compute_spbf(
    src: pd.Series, length1: int, length2: int, rms_length: int
) -> tuple[pd.Series, pd.Series]:
    """Ehlers Super PassBand Filter on a confirmed-bar price series.

    Two-pole high-pass ``pb`` with rolling RMS amplitude ``rms``.  Both
    series are shifted by one bar so the value at index ``i`` reflects
    the filter state at the close of bar ``i - 1``, matching the
    convention used by the strategy's ``populate_indicators``.
    """
    x = src.to_numpy(dtype=float)
    n = len(x)
    a1 = 5.0 / float(length1)
    a2 = 5.0 / float(length2)
    b0 = a1 - a2
    b1 = a2 * (1.0 - a1) - a1 * (1.0 - a2)
    a10 = (1.0 - a1) + (1.0 - a2)
    a20 = -(1.0 - a1) * (1.0 - a2)
    pb = np.zeros(n, dtype=float)
    for i in range(n):
        s0 = x[i] if np.isfinite(x[i]) else 0.0
        s1 = x[i - 1] if i >= 1 and np.isfinite(x[i - 1]) else 0.0
        p1 = pb[i - 1] if i >= 1 else 0.0
        p2 = pb[i - 2] if i >= 2 else 0.0
        pb[i] = b0 * s0 + b1 * s1 + a10 * p1 + a20 * p2
    sq = pd.Series(pb**2)
    rms = sq.rolling(window=rms_length, min_periods=rms_length).mean().pow(0.5)
    pb_series = pd.Series(pb, index=src.index).shift(1)
    rms_series = rms.shift(1)
    return pb_series, rms_series


def _add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the profiled feature columns on the (untrimmed) setup frame.

    All inputs are causal: either the strategy's confirmed-bar series
    (``h1``/``l1``/``c1``/``ema``/``atr``/``htf_ema``) or the setup candle's
    own volume derived from ``volume.shift(1)``.  ``htf_ema_slope`` was
    removed from the profile: the per-5m diff of the ffill'd HTF EMA is
    zero for most consecutive bars and carries no information.
    """
    c1 = df["c1"].to_numpy(dtype=float)
    h1 = df["h1"].to_numpy(dtype=float)
    l1 = df["l1"].to_numpy(dtype=float)
    ema = df["ema"].to_numpy(dtype=float)
    htf_ema = df["htf_ema"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    rng = h1 - l1
    safe_rng = np.where(rng > 0, rng, np.nan)
    safe_atr = np.where((atr > 0) & np.isfinite(atr), atr, np.nan)
    safe_c1 = np.where((np.abs(c1) > 0) & np.isfinite(c1), c1, np.nan)

    atr_pct = np.where(safe_c1 > 0, atr / safe_c1, np.nan)
    range_atr = np.where(safe_atr > 0, rng / safe_atr, np.nan)
    range_pct = np.where(safe_c1 > 0, rng / safe_c1, np.nan)
    ema_slope = np.where(
        safe_c1 > 0,
        ema - np.concatenate([[ema[0]], ema[:-1]]),
        np.nan,
    )
    ema_slope = ema_slope / safe_c1
    extension = np.where(safe_atr > 0, (c1 - ema) / safe_atr, np.nan)
    htf_extension = np.where(safe_atr > 0, (c1 - htf_ema) / safe_atr, np.nan)
    body_pos = np.where(safe_rng > 0, (c1 - l1) / safe_rng, np.nan)

    df = df.copy()
    df["atr_pct"] = atr_pct
    df["range_atr"] = range_atr
    df["range_pct"] = range_pct
    df["ema_slope"] = ema_slope
    df["extension"] = extension
    df["htf_extension"] = htf_extension
    df["body_pos"] = body_pos
    df["hour"] = pd.to_datetime(df["date"], utc=True).dt.hour.to_numpy(dtype=float)

    vol_setup = df["volume"].shift(1).to_numpy(dtype=float)
    vol_series = pd.Series(vol_setup, index=df.index)
    rolling_mean = vol_series.rolling(window=20, min_periods=20).mean()
    df["volume_ratio"] = (vol_series / rolling_mean).to_numpy(dtype=float)

    atr_pct_series = pd.Series(atr_pct, index=df.index)
    df["atr_pct_pctile_500"] = (
        atr_pct_series.rolling(window=500, min_periods=500).rank(pct=True).to_numpy(dtype=float)
    )

    # Ehlers Super PassBand Filter (defaults from the Pine source).
    spbf_pb, spbf_rms = _compute_spbf(df["c1"], length1=40, length2=60, rms_length=50)
    df["spbf_pb"] = spbf_pb
    df["spbf_rms"] = spbf_rms
    return df


def _match_trades_to_setups(
    trades: list[dict[str, Any]], feature_df: pd.DataFrame, max_wait: int
) -> tuple[pd.DataFrame, int]:
    """Join each trade to its setup bar and attach labels.

    Returns the joined frame and the count of trades dropped because the
    matched setup bar's date is implausible relative to the trade's
    ``open_date`` (alignment sanity check).
    """
    if "irb_tag" not in feature_df.columns:
        raise RuntimeError("strategy did not emit irb_tag; replay produced no tags")
    # First row per tag = setup bar (tag is first assigned there).
    setup_idx = feature_df.dropna(subset=["irb_tag"]).drop_duplicates(
        subset=["irb_tag"], keep="first"
    )
    # Keep date + the breakout bar's range + h1/l1 so the same-candle stopout
    # diagnostic can derive the proposed entry/stop without re-running the
    # strategy's state machine.
    setup_idx = setup_idx.set_index("irb_tag")[
        ["date", "high", "low", "h1", "l1", "spbf_pb", "spbf_rms"] + [f.name for f in FEATURES]
    ]
    base_seconds = timeframe_to_seconds("5m")
    rows: list[dict[str, Any]] = []
    dropped = 0
    for trade in trades:
        tag = str(trade.get("enter_tag") or "")
        if tag not in setup_idx.index:
            dropped += 1
            continue
        setup_date = setup_idx.loc[tag, "date"]
        open_date = pd.Timestamp(trade["open_date"])
        if pd.Timestamp(setup_date).tzinfo is None:
            setup_ts = pd.Timestamp(setup_date, tz="UTC")
        else:
            setup_ts = pd.Timestamp(setup_date)
        gap_bars = (open_date - setup_ts).total_seconds() / base_seconds
        if gap_bars < 0 or gap_bars > max_wait + 2:
            dropped += 1
            continue
        profit_ratio = float(trade["profit_ratio"])
        # Proposed entry/stop per the base strategy's state machine
        # (tick_pad = 1e-8, negligible numerically but included for fidelity).
        h1 = float(setup_idx.loc[tag, "h1"])
        l1 = float(setup_idx.loc[tag, "l1"])
        bar_high = float(setup_idx.loc[tag, "high"])
        bar_low = float(setup_idx.loc[tag, "low"])
        pad = 1e-8
        if bool(trade.get("is_short")):
            proposed_entry = l1 - pad
            proposed_stop = h1 + pad
        else:
            proposed_entry = h1 + pad
            proposed_stop = l1 - pad
        # The breakout bar would both fill at the entry and hit the stop on
        # the same candle. Mirrors the backtest's
        # ``trade_duration == 0 + exit_reason == stop_loss`` ground truth.
        long_straddle = (
            (not bool(trade.get("is_short")))
            and bar_high >= proposed_entry
            and bar_low <= proposed_stop
        )
        short_straddle = (
            bool(trade.get("is_short")) and bar_low <= proposed_entry and bar_high >= proposed_stop
        )
        would_same_candle_stop = bool(long_straddle or short_straddle)
        rows.append(
            {
                "enter_tag": tag,
                "pair": trade["pair"],
                "is_short": bool(trade["is_short"]),
                "setup_date": setup_ts,
                "open_date": open_date,
                "close_date": pd.Timestamp(trade["close_date"]),
                "gap_bars": gap_bars,
                "trade_duration": int(trade.get("trade_duration") or 0),
                "exit_reason": trade.get("exit_reason"),
                "profit_ratio": profit_ratio,
                "win": int(profit_ratio > 0),
                "same_candle_stop": int(
                    (int(trade.get("trade_duration") or 0) == 0)
                    and (str(trade.get("exit_reason") or "") == "stop_loss")
                ),
                "would_same_candle_stop": int(would_same_candle_stop),
                **{f.name: setup_idx.loc[tag, f.name] for f in FEATURES},
                "spbf_pb": setup_idx.loc[tag, "spbf_pb"],
                "spbf_rms": setup_idx.loc[tag, "spbf_rms"],
            }
        )
    return pd.DataFrame(rows), dropped


# ---------------------------------------------------------------------------
# Per-period pipeline
# ---------------------------------------------------------------------------
def _build_period_profile(
    result_path: Path, datadir: Path, config: dict[str, Any]
) -> PeriodProfile:
    """Replay the strategy for every pair in the result zip and join trades."""
    payload = _read_result_zip(result_path)
    strategy_name = payload["strategy_name"]
    timerange = TimeRange.parse_timerange(payload["timerange"])
    pairs = list(config["exchange"]["pair_whitelist"])
    with zipfile.ZipFile(result_path) as z:
        strategy_cls = _load_strategy_class(strategy_name, z)
    strategy = strategy_cls({})
    timeframe = str(strategy.timeframe)
    htf = str(strategy._param("htf"))
    startup = int(strategy.startup_candle_count)
    max_wait = int(strategy.max_wait)

    rows: list[pd.DataFrame] = []
    for pair in pairs:
        base = _load_base_frame(pair, timeframe, datadir, timerange, startup)
        if base.empty:
            print(f"  {pair:>16}: no base data for {timerange}; skipping")
            continue
        htf_df = _load_htf_frame(pair, htf, datadir, timerange, startup)
        # An empty HTF frame mirrors the backtest: the strategy's informative
        # merge catches the empty case and falls back to ``ema.shift(1)``.
        # We still need to feed the strategy an HTF cache so the fallback
        # path is taken rather than raising.
        if htf_df.empty:
            htf_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            print(
                f"  {pair:>16}: no {htf} data for {timerange}; "
                "replay uses strategy fallback (htf_ema = ema.shift(1))"
            )
        strategy.dp = _DP({htf: {pair: htf_df}}, [pair])
        # Reset the strategy's per-pair setup cache so each pair starts clean.
        strategy._setup_cache = {}
        try:
            feature_df = strategy.populate_indicators(base.copy(), {"pair": pair})
        except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError) as exc:
            # defensive continue on per-pair failure - one bad pair must not
            # abort the whole profiling run
            print(f"  {pair:>16}: populate_indicators failed: {exc}")
            continue
        feature_df = _add_features(feature_df)
        pair_trades = [t for t in payload["trades"] if t["pair"] == pair]
        joined, dropped = _match_trades_to_setups(pair_trades, feature_df, max_wait)
        if dropped:
            print(
                f"  {pair:>16}: {len(pair_trades)} trades, "
                f"{len(joined)} matched, {dropped} dropped (alignment)"
            )
        else:
            print(f"  {pair:>16}: {len(pair_trades)} trades, {len(joined)} matched")
        rows.append(joined)
    if not rows:
        label = f"{payload['stats']['backtest_start'][:10]}/{payload['stats']['backtest_end'][:10]}"
        return PeriodProfile(
            label=label,
            timerange=payload["timerange"],
            pairs=pairs,
            rows=pd.DataFrame(),
        )
    all_rows = pd.concat(rows, ignore_index=True)
    label = f"{payload['stats']['backtest_start'][:10]}/{payload['stats']['backtest_end'][:10]}"
    return PeriodProfile(
        label=label,
        timerange=payload["timerange"],
        pairs=pairs,
        rows=all_rows,
        feature_names=[f.name for f in FEATURES],
    )


# ---------------------------------------------------------------------------
# Bucketing + verdict
# ---------------------------------------------------------------------------
def _quintile_table(rows: pd.DataFrame, feature: str, edges: list[float] | None) -> pd.DataFrame:
    """Bucket ``rows[feature]`` and report per-bucket win rate, avg profit, count.

    When ``edges`` is provided (from the discovery period) the validation
    buckets use those fixed cut points so the two periods are compared on
    the same boundaries; otherwise the bucket edges come from ``qcut``.
    """
    series = rows[feature]
    finite = series.replace([np.inf, -np.inf], np.nan).dropna()
    if edges is not None:
        labels = [f"q{i}" for i in range(len(edges) - 1)]
        bucketed = pd.cut(series, bins=edges, labels=labels, include_lowest=True)
    else:
        bucketed = pd.qcut(series, q=5, labels=False, duplicates="drop")
        bucketed = bucketed.map(lambda v: f"q{int(v)}" if pd.notna(v) else np.nan)
    out = rows.assign(_bucket=bucketed).groupby("_bucket", dropna=True, observed=True)
    table = out.agg(
        n=("win", "size"),
        wins=("win", "sum"),
        winrate=("win", "mean"),
        avg_profit=("profit_ratio", "mean"),
        stopout_rate=("same_candle_stop", "mean"),
    )
    finite_min, finite_max = float(finite.min()), float(finite.max())
    if edges is not None:
        # Bucket value range from the requested edges.
        table["feat_min"] = [edges[i] for i in range(len(table))]
        table["feat_max"] = [edges[i + 1] for i in range(len(table))]
    else:
        # Per-bucket feature min/max from the data actually placed in the bucket.
        feat_min = out[feature].min()
        feat_max = out[feature].max()
        table["feat_min"] = feat_min
        table["feat_max"] = feat_max
    table = table.dropna(subset=["n"])
    table["winrate"] = table["winrate"].fillna(0.0)
    table["stopout_rate"] = table["stopout_rate"].fillna(0.0)
    table["feat_min"] = table["feat_min"].fillna(finite_min)
    table["feat_max"] = table["feat_max"].fillna(finite_max)
    return table[["n", "wins", "winrate", "avg_profit", "stopout_rate", "feat_min", "feat_max"]]


def _bucket_metrics(table: pd.DataFrame) -> dict[str, float]:
    """Summarise monotonicity, spread and counts of a bucket table."""
    rates = table["winrate"].to_numpy(dtype=float)
    counts = table["n"].to_numpy(dtype=int)
    if len(rates) < 3:
        return {
            "rho": 0.0,
            "inversions": 0,
            "spread": 0.0,
            "min_bucket": int(counts.min()) if len(counts) else 0,
            "total": int(counts.sum()),
            "n_buckets": len(rates),
            "top_idx": int(np.argmax(rates)) if len(rates) else 0,
            "bottom_idx": int(np.argmin(rates)) if len(rates) else 0,
        }
    ranks = np.arange(len(rates))
    rho, _ = spearmanr(ranks, rates)
    diffs = np.diff(rates)
    inversions = int(np.sum(diffs[1:] * diffs[:-1] < 0))
    return {
        "rho": float(rho) if math.isfinite(rho) else 0.0,
        "inversions": inversions,
        "spread": float(rates.max() - rates.min()),
        "min_bucket": int(counts.min()),
        "total": int(counts.sum()),
        "n_buckets": len(rates),
        "top_idx": int(np.argmax(rates)),
        "bottom_idx": int(np.argmin(rates)),
    }


def _passes(
    metrics: dict[str, float], rho: float, spread: float, min_total: int, min_bucket: int
) -> bool:
    if metrics["n_buckets"] < 3:
        return False
    if metrics["total"] < min_total or metrics["min_bucket"] < min_bucket:
        return False
    if metrics["inversions"] > MAX_INVERSIONS:
        return False
    return abs(metrics["rho"]) >= rho and metrics["spread"] >= spread


def _disc_edges(rows: pd.DataFrame, feature: str) -> list[float] | None:
    """Discovery quintile edges (inclusive) for use on the validation period.

    Returns ``None`` when there are not enough unique values to form three or
    more distinct buckets; the verdict then treats the validation as having
    insufficient evidence.
    """
    series = rows[feature].replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return None
    quantiles = series.quantile([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]).to_numpy(dtype=float)
    unique = np.unique(quantiles)
    if unique.size < 3:
        quantiles = series.quantile([0.0, 0.25, 0.5, 0.75, 1.0]).to_numpy(dtype=float)
        unique = np.unique(quantiles)
    if unique.size < 3:
        return None
    return [float(q) for q in unique]


def _verdict_for_feature(feature: str, disc: PeriodProfile, val: PeriodProfile) -> FeatureVerdict:
    """Combine the discovery and validation bucket tables into a verdict."""
    edges = _disc_edges(disc.rows, feature)
    disc_table = _quintile_table(disc.rows, feature, edges=None)
    val_table = _quintile_table(val.rows, feature, edges=edges)
    disc_m = _bucket_metrics(disc_table)
    val_m = _bucket_metrics(val_table)

    disc_ok = _passes(disc_m, DISC_RHO, DISC_SPREAD_PP, DISC_MIN_TOTAL, DISC_MIN_BUCKET)
    val_ok = _passes(val_m, VAL_RHO, VAL_SPREAD_PP, VAL_MIN_TOTAL, VAL_MIN_BUCKET)
    direction = 0
    threshold = None
    side = "n/a"
    note = ""
    if disc_ok and val_ok and (disc_m["rho"] * val_m["rho"] > 0):
        direction = 1 if disc_m["rho"] > 0 else -1
        # Trade in the "good" direction only: highest quintile for positive
        # features, lowest quintile for negative ones.  The threshold is the
        # discovery-period edge that separates the kept bucket from the rest.
        if direction > 0:
            target_idx = disc_m["top_idx"]
            edge_idx = int(target_idx)  # 0..4 -> edge at index+1 (0..4)
        else:
            target_idx = disc_m["bottom_idx"]
            edge_idx = int(target_idx)  # bottom bucket starts at edges[0]
        if edges is not None and 0 <= edge_idx < len(edges) - 1:
            threshold = float(edges[edge_idx + 1] if direction > 0 else edges[edge_idx])
        side = ">= " if direction > 0 else "<= "
    elif disc_ok and not val_ok:
        note = "discovery OK, validation failed (likely overfit)"
    elif not disc_ok:
        note = "discovery failed"

    return FeatureVerdict(
        feature=feature,
        passes=bool(disc_ok and val_ok and direction != 0),
        direction=direction,
        suggested_threshold=threshold,
        suggested_side=side,
        n_disc=int(disc_m["total"]),
        n_val=int(val_m["total"]),
        disc_rho=disc_m["rho"],
        val_rho=val_m["rho"],
        disc_spread_pp=disc_m["spread"],
        val_spread_pp=val_m["spread"],
        note=note,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _format_table(name: str, period: str, table: pd.DataFrame) -> str:
    header = f"  {name}  ({period}, n={int(table['n'].sum())})"
    if table.empty:
        return header + "\n    (no buckets)\n"
    rows = []
    for bucket, row in table.iterrows():
        rows.append(
            "    {bucket:>3}  n={n:>4}  winrate={wr:6.1%}  "
            "avg_pnl={ap:+.4f}  stopout={so:5.1%}  "
            "range=[{lo:.4g}, {hi:.4g}]".format(
                bucket=bucket,
                n=int(row["n"]),
                wr=float(row["winrate"]),
                ap=float(row["avg_profit"]),
                so=float(row["stopout_rate"]),
                lo=float(row["feat_min"]),
                hi=float(row["feat_max"]),
            )
        )
    return header + "\n" + "\n".join(rows) + "\n"


def _format_verdict(v: FeatureVerdict) -> str:
    if v.passes:
        sign = "+" if v.direction > 0 else "-"
        if v.suggested_threshold is None:
            th = "n/a"
        else:
            th = f"{v.suggested_side}{v.suggested_threshold:.4g}"
        return (
            f"  PASS  {v.feature:>20s}  direction={sign}  threshold={th}  "
            f"(disc n={v.n_disc}, rho={v.disc_rho:+.2f}, spread={v.disc_spread_pp:.1%}; "
            f"val n={v.n_val}, rho={v.val_rho:+.2f}, spread={v.val_spread_pp:.1%})"
        )
    return (
        f"  FAIL  {v.feature:>20s}  {v.note:>40s}  "
        f"(disc n={v.n_disc}, rho={v.disc_rho:+.2f}, spread={v.disc_spread_pp:.1%}; "
        f"val n={v.n_val}, rho={v.val_rho:+.2f}, spread={v.val_spread_pp:.1%})"
    )


def _print_report(
    disc: PeriodProfile,
    val: PeriodProfile,
    verdicts: list[FeatureVerdict],
) -> None:
    print("=" * 78)
    print("HOFFMAN IRB FEATURE DIAGNOSTIC")
    print(f"  discovery: {disc.label}  timerange={disc.timerange}  n={disc.n}")
    print(f"  validation: {val.label}  timerange={val.timerange}  n={val.n}")
    print("=" * 78)

    passes = [v for v in verdicts if v.passes]
    print()
    print(f"PASSING FEATURES ({len(passes)}):")
    if not passes:
        print("  (none — see per-feature tables below)")
    for v in passes:
        print(_format_verdict(v))

    print()
    print("PER-FEATURE BUCKET TABLES")
    for spec in FEATURES:
        edges = _disc_edges(disc.rows, spec.name)
        disc_table = _quintile_table(disc.rows, spec.name, edges=None)
        val_table = _quintile_table(val.rows, spec.name, edges=edges)
        print()
        print(f"[{spec.name}]  {spec.description}")
        if edges is not None and len(edges) > 1:
            edge_str = ", ".join(f"{e:.4g}" for e in edges)
            print(f"  discovery edges: [{edge_str}]")
        print(_format_table(spec.name, "discovery", disc_table), end="")
        print(_format_table(spec.name, "validation", val_table), end="")
        print("  " + _format_verdict(next(v for v in verdicts if v.feature == spec.name)).strip())

    _print_trade_diagnostics(disc, val)


# ---------------------------------------------------------------------------
# Trade-level diagnostics (Phase C-1)
# ---------------------------------------------------------------------------
def _same_candle_impact(rows: pd.DataFrame) -> dict[str, float]:
    """Estimate the effect of rejecting would-same-candle-stop setups.

    Compares the observed PnL to the simulated PnL with those setups dropped.
    Reports winrate, n, total profit, and the fraction of losses caught.
    """
    if rows.empty or "would_same_candle_stop" not in rows.columns:
        return {}
    drop = rows["would_same_candle_stop"].astype(bool)
    kept = rows[~drop]
    n_total = len(rows)
    n_kept = len(kept)
    n_dropped = int(drop.sum())
    losses_total = int((rows["profit_ratio"] < 0).sum())
    losses_caught = int(((rows["profit_ratio"] < 0) & drop).sum())
    pnl_observed = float(rows["profit_ratio"].sum())
    pnl_kept = float(kept["profit_ratio"].sum()) if n_kept else 0.0
    return {
        "n_total": n_total,
        "n_kept": n_kept,
        "n_dropped": n_dropped,
        "kept_pct": (n_kept / n_total) if n_total else 0.0,
        "losses_total": losses_total,
        "losses_caught": losses_caught,
        "losses_caught_pct": (losses_caught / losses_total) if losses_total else 0.0,
        "winrate_observed": float(rows["win"].mean()) if n_total else 0.0,
        "winrate_kept": float(kept["win"].mean()) if n_kept else 0.0,
        "pnl_observed": pnl_observed,
        "pnl_kept": pnl_kept,
        "avg_pnl_observed": (pnl_observed / n_total) if n_total else 0.0,
        "avg_pnl_kept": (pnl_kept / n_kept) if n_kept else 0.0,
    }


def _consecutive_loss_clusters(rows: pd.DataFrame) -> pd.DataFrame:
    """Per-side table of winrate bucketed by prior same-side loss count.

    ``prior_same_side_losses`` counts the losses on this side that
    immediately preceded the current trade (so 0 = last same-side trade was
    a win, 1 = last same-side trade was a loss, 2 = two losses in a row,
    3+ = three or more). The first trade on each side has no prior, so it
    is excluded.
    """
    if rows.empty:
        return pd.DataFrame()
    sorted_rows = rows.sort_values("open_date").reset_index(drop=True)
    out_rows: list[dict[str, Any]] = []
    for side_label, is_short in (("long", False), ("short", True)):
        side_rows = sorted_rows[sorted_rows["is_short"] == is_short].reset_index(drop=True)
        prior_loss = 0
        for _, r in side_rows.iterrows():
            n = prior_loss
            bucket = "3+" if n >= 3 else f"{n}"
            out_rows.append(
                {
                    "side": side_label,
                    "prior_losses": bucket,
                    "prior_n": n,
                    "win": int(r["win"]),
                    "profit_ratio": float(r["profit_ratio"]),
                }
            )
            prior_loss = prior_loss + 1 if r["win"] == 0 else 0
    if not out_rows:
        return pd.DataFrame()
    df = pd.DataFrame(out_rows)
    grouped = df.groupby(["side", "prior_losses"], observed=True).agg(
        n=("win", "size"),
        wins=("win", "sum"),
        winrate=("win", "mean"),
        avg_pnl=("profit_ratio", "mean"),
        total_pnl=("profit_ratio", "sum"),
    )
    return grouped


def _simulate_loss_streak_lockout(
    rows: pd.DataFrame, threshold: int, cooldown_minutes: int
) -> dict[str, float]:
    """Simulate the consecutive-loss lockout on observed trades.

    Per side, after ``threshold`` consecutive losses (inclusive of the
    current one), no further trades on that side are admitted until the
    cooldown wall-clock has elapsed since the close of the Nth loss. The
    opposite side is unaffected. A winning trade clears the streak and
    does not engage the lockout.
    """
    if rows.empty or "close_date" not in rows.columns:
        return {}
    sorted_rows = rows.sort_values("open_date").reset_index(drop=True)
    cooldown = pd.Timedelta(minutes=cooldown_minutes)
    kept_mask: list[bool] = []
    streak_long = 0
    streak_short = 0
    lock_long_until: pd.Timestamp | None = None
    lock_short_until: pd.Timestamp | None = None
    for _, r in sorted_rows.iterrows():
        is_short = bool(r["is_short"])
        open_dt = pd.Timestamp(r["open_date"])
        close_dt = pd.Timestamp(r["close_date"])
        lockout_until = lock_short_until if is_short else lock_long_until
        if lockout_until is not None and open_dt < lockout_until:
            kept_mask.append(False)
            # Streak continues: the dropped trade doesn't break the run.
            if is_short:
                streak_short += 1
            else:
                streak_long += 1
            continue
        kept_mask.append(True)
        won = int(r["win"]) == 1
        if is_short:
            if won:
                streak_short = 0
                lock_short_until = None
            else:
                streak_short += 1
                if streak_short >= threshold:
                    lock_short_until = close_dt + cooldown
        else:
            if won:
                streak_long = 0
                lock_long_until = None
            else:
                streak_long += 1
                if streak_long >= threshold:
                    lock_long_until = close_dt + cooldown
    kept = sorted_rows[kept_mask]
    n_total = len(sorted_rows)
    n_kept = len(kept)
    pnl_observed = float(sorted_rows["profit_ratio"].sum())
    pnl_kept = float(kept["profit_ratio"].sum()) if n_kept else 0.0
    return {
        "threshold": threshold,
        "cooldown_minutes": cooldown_minutes,
        "n_total": n_total,
        "n_kept": n_kept,
        "kept_pct": (n_kept / n_total) if n_total else 0.0,
        "winrate_observed": float(sorted_rows["win"].mean()) if n_total else 0.0,
        "winrate_kept": float(kept["win"].mean()) if n_kept else 0.0,
        "pnl_observed": pnl_observed,
        "pnl_kept": pnl_kept,
        "avg_pnl_observed": (pnl_observed / n_total) if n_total else 0.0,
        "avg_pnl_kept": (pnl_kept / n_kept) if n_kept else 0.0,
    }


def _format_pct(x: float) -> str:
    return f"{x:6.1%}" if not math.isnan(x) else "  n/a "


def _print_trade_diagnostics(  # noqa: C901
    disc: PeriodProfile, val: PeriodProfile
) -> None:
    print()
    print("=" * 78)
    print("TRADE-LEVEL DIAGNOSTICS (Phase C-1)")
    print("=" * 78)

    for label, period in (("discovery", disc), ("validation", val)):
        rows = period.rows
        print()
        print(f"[{label}]  same-candle stopout impact")
        impact = _same_candle_impact(rows)
        if not impact:
            print("    (no rows)")
            continue
        print(
            f"    n_total={impact['n_total']}  would_same_candle_stop={impact['n_dropped']} "
            f"({impact['n_dropped'] / max(impact['n_total'], 1):.1%})  "
            f"losses_caught={impact['losses_caught']}/{impact['losses_total']} "
            f"({impact['losses_caught_pct']:.1%})"
        )
        print(
            f"    observed:   winrate={_format_pct(impact['winrate_observed'])}  "
            f"avg_pnl={impact['avg_pnl_observed']:+.5f}  total_pnl={impact['pnl_observed']:+.4f}"
        )
        print(
            f"    with guard: winrate={_format_pct(impact['winrate_kept'])}  "
            f"avg_pnl={impact['avg_pnl_kept']:+.5f}  total_pnl={impact['pnl_kept']:+.4f}  "
            f"kept={impact['kept_pct']:.1%}"
        )

    for label, period in (("discovery", disc), ("validation", val)):
        rows = period.rows
        print()
        print(f"[{label}]  consecutive same-side losses -> winrate / avg pnl")
        clusters = _consecutive_loss_clusters(rows)
        if clusters.empty:
            print("    (no rows)")
            continue
        for side_label in ("long", "short"):
            sides = clusters.index.get_level_values("side")
            if side_label not in sides:
                continue
            side_clusters = clusters.xs(side_label, level="side")
            print(f"    {side_label}:")
            for bucket, row in side_clusters.iterrows():
                print(
                    f"      prior_losses={bucket:>3}  n={int(row['n']):>4}  "
                    f"winrate={_format_pct(float(row['winrate']))}  "
                    f"avg_pnl={float(row['avg_pnl']):+.5f}  "
                    f"total_pnl={float(row['total_pnl']):+.4f}"
                )

    for label, period in (("discovery", disc), ("validation", val)):
        rows = period.rows
        print()
        print(f"[{label}]  simulated loss-streak lockout (per spec: 3 losses, 240min cooldown)")
        for threshold, cooldown in ((3, 240), (4, 240)):
            sim = _simulate_loss_streak_lockout(rows, threshold, cooldown)
            if not sim:
                continue
            print(
                f"    threshold={sim['threshold']} cooldown={sim['cooldown_minutes']}min  "
                f"kept={sim['kept_pct']:.1%} ({sim['n_kept']}/{sim['n_total']})"
            )
            print(
                f"      observed:   winrate={_format_pct(sim['winrate_observed'])}  "
                f"avg_pnl={sim['avg_pnl_observed']:+.5f}  total_pnl={sim['pnl_observed']:+.4f}"
            )
            print(
                f"      with lock: winrate={_format_pct(sim['winrate_kept'])}  "
                f"avg_pnl={sim['avg_pnl_kept']:+.5f}  total_pnl={sim['pnl_kept']:+.4f}"
            )

    for label, period in (("discovery", disc), ("validation", val)):
        rows = period.rows
        if rows.empty or "spbf_pb" not in rows.columns or "spbf_rms" not in rows.columns:
            continue
        print()
        print(f"[{label}]  Ehlers Super PassBand Filter coverage at the setup bar")
        groups: dict[str, list] = {"agree": [], "silent": [], "oppose": []}
        for _, r in rows.iterrows():
            pb = r["spbf_pb"]
            rms = r["spbf_rms"]
            if not (np.isfinite(pb) and np.isfinite(rms)) or rms <= 0:
                groups["silent"].append(r)
                continue
            is_long = not bool(r["is_short"])
            if (is_long and pb > rms) or (not is_long and pb < -rms):
                groups["agree"].append(r)
            elif abs(pb) <= rms:
                groups["silent"].append(r)
            else:
                groups["oppose"].append(r)
        n_total = len(rows)
        for group_name in ("agree", "silent", "oppose"):
            grp = groups[group_name]
            n = len(grp)
            pct = n / n_total if n_total else 0.0
            if n:
                winrate = sum(g["win"] for g in grp) / n
                avg_pnl = sum(g["profit_ratio"] for g in grp) / n
                total_pnl = sum(g["profit_ratio"] for g in grp)
            else:
                winrate = avg_pnl = total_pnl = 0.0
            print(
                f"    {group_name:>6}: n={n:>4} ({pct:5.1%})  "
                f"winrate={_format_pct(winrate)}  "
                f"avg_pnl={avg_pnl:+.5f}  total_pnl={total_pnl:+.4f}"
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile Hoffman IRB setup-bar features against trade outcomes.",
    )
    parser.add_argument(
        "--result",
        action="append",
        required=True,
        type=Path,
        help="backtest result zip (pass twice; earlier timerange = discovery, later = validation)",
    )
    parser.add_argument(
        "--datadir",
        type=Path,
        default=DEFAULT_DATADIR,
        help=f"freqtrade feather datadir (default: {DEFAULT_DATADIR})",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if len(args.result) < 2:
        print("need at least two --result zips (discovery + validation)", file=sys.stderr)
        return 2
    if not args.datadir.exists():
        print(f"datadir not found: {args.datadir}", file=sys.stderr)
        return 2

    # Read the backtest configs (whitelists) in zip order; the first zip's
    # whitelist is used for both periods to keep pair coverage identical.
    payloads = [_read_result_zip(p) for p in args.result]
    payloads.sort(key=lambda p: p["stats"]["backtest_start_ts"])
    base_config = payloads[0]["config"]
    if any(
        p["config"]["exchange"]["pair_whitelist"] != base_config["exchange"]["pair_whitelist"]
        for p in payloads[1:]
    ):
        print(
            "WARNING: pair whitelist differs between zips; using first zip's list",
            file=sys.stderr,
        )

    print("Building discovery profile...")
    disc = _build_period_profile(args.result[0], args.datadir, base_config)
    print()
    print("Building validation profile...")
    val = _build_period_profile(args.result[1], args.datadir, base_config)
    print()

    verdicts = [_verdict_for_feature(spec.name, disc, val) for spec in FEATURES]
    _print_report(disc, val, verdicts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
