# Strategy Analysis

Generated 2026-08-20 from the repository's Binance futures data and archived
backtest results.

## Method

- Common screen: 5m futures candles, 2023-01-01 through 2024-06-19.
- Holdout screen: 5m futures candles, 2024-01-01 through 2024-06-19.
- Requested universe: 26 pairs from the latest BigZ08 result.
- Four inactive or unavailable markets were removed by Binance, leaving 22 active pairs.
- Starting balance: 2,000 USDT.
- Maximum open trades: 6.
- Fee: 0.05% per side.
- Execution assumptions: isolated futures, static pairlist, order-book top 1, compatible market-order pricing.
- Analysis configuration: `user_data/config_analysis.json`.

## Post-Fix Common Screen

| Strategy | Trades | Return | Max drawdown | Profit factor | Sharpe | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `CombinedBinHClucAndMADV3` | 334 | +34.08% | 11.97% | 1.55 | 1.96 | Best screen result |
| `ClucHAnix_5m` | 854 | +26.73% | 13.16% | 1.26 | 2.13 | Second-best screen result |
| `BigZ06AtrSl` | 973 | +50.19% | 51.82% | 1.09 | 1.12 | Repaired, but exceeds risk limit |
| `BigZ08` | 6 | +19.43% | 0.00% | N/A | 0.51 | Too few trades to evaluate |
| `adaptive` | 120 | -4.73% | 16.70% | 0.88 | -0.20 | Fails profitability |
| `GKDAdaptiveAcademicFinal` | 1,834 | -34.49% | 34.63% | 0.54 | -12.48 | Fails profitability and risk limit |
| `BigZ06Original` | 767 | -22.37% | 73.35% | 0.94 | -0.26 | Reject |
| `BigZ07Next2` | 740 | -91.11% | 97.05% | 0.80 | -0.83 | Reject |

Results are stored in the timestamped `current-screen-*.zip` files in
`user_data/backtest_results`.

## Post-Fix Holdout Screen

| Strategy | Trades | Return | Max drawdown | Profit factor | Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| `CombinedBinHClucAndMADV3` | 110 | -1.64% | 11.97% | 0.94 | -0.29 |
| `ClucHAnix_5m` | 352 | -5.03% | 13.16% | 0.89 | -1.28 |
| `BigZ08` | 2 | +7.28% | 0.00% | N/A | 0.83 |
| `BigZ06AtrSl` | 373 | -19.18% | 51.82% | 0.88 | -2.23 |
| `BigZ06Original` | 253 | -66.48% | 73.34% | 0.46 | -3.45 |
| `BigZ07Next2` | 241 | -95.98% | 97.04% | 0.33 | -3.77 |

The market change during the holdout was -22.92%. `CombinedBinHClucAndMADV3`
and `ClucHAnix_5m` controlled losses better than the market, but neither
demonstrated positive standalone expectancy. `BigZ08` has an insignificant
sample of two trades.

## Improvement Pass

The two viable candidates were then tested with:

- A 1h EMA-50/EMA-200 regime gate applied to every entry branch.
- Profit-only exit signals.
- ROI exits no longer suppressed by a continuing entry signal.
- Explicit 1x leverage.
- Stake sizing capped at approximately 0.5% account risk for a 10% stop distance.

| Strategy | Common return / DD | Holdout return / DD | Holdout PF | Average stake |
| --- | ---: | ---: | ---: | ---: |
| `CombinedBinHClucAndMADV3` | +2.57% / 2.41% | -0.77% / 2.41% | 0.79 | 96 USDT |
| `ClucHAnix_5m` | -3.64% / 8.61% | -7.67% / 8.52% | 0.39 | 90 USDT |

The Combined strategy's holdout loss improved from -1.64% to -0.77% and its
drawdown fell from 11.97% to 2.41%. The tradeoff is much lower activity and
still-negative expectancy. The Cluc changes reduced exposure but worsened
holdout performance.

## Runtime Findings And Fixes

### BigZ06AtrSl

`BigZ06AtrSl.py:273` called `Trade.get_trades(..., is_open=False)`, but the
current persistence API accepts a trade filter instead. It now uses
`Trade.get_trades_proxy`, and the dataframe mutation that caused the warning at
the old `:376` callback was removed. A focused backtest now completes without
the API exception.

### BigZ08

`BigZ08.py:435-440` and `:452-457` passed three column names to pandas-ta
Bollinger Bands, which now produces five columns. The resulting indicator
setup left `cmf` unavailable and the run terminated at `BigZ08.py:501` with
`KeyError: 'cmf'`. Indicators now use explicit series assignments and a focused
backtest completes. The short sample generated no signals, so performance still
needs a full rerun.

BigZ08 entry candle data is now derived from each trade's open candle and stored
per trade; the shared strategy-instance state and the disabled `exit_long = 0`
signal were removed.

### Other Risks

- `CombinedBinHClucAndMADV3.py:140-183` uses legacy signal column names in an interface-v3 strategy. The current run generated trades, but this should be migrated and regression-tested.
- `GkdAdaptive.py:176-204` contains centered rolling swing detection and should not be evaluated as causal.
- `lstm_strategy.py:86-120` trains and predicts on overlapping historical data and is not a valid backtest.
- The live dry-run database contains no trades or orders, so there is no live validation.

The LSTM training path now uses a causal train/test split and a scaler fitted
only on the training segment. `GkdAdaptive.py` now uses delayed causal swing
confirmation, and its dynamic pairlist handling and custom stoploss fallback
were made framework-safe.

`VixFixBb`, `MfiEmaWaveTrend2`, and `StrategyTemplate` now load and complete
focused framework checks. VixFix remains untestable on the bundled data because
the requested 3m futures history ends in December 2023.

## Decision

No strategy is ready for live deployment based on this evidence.

The post-fix ranking is:

1. Continue research on the improved `CombinedBinHClucAndMADV3` configuration.
2. Reject the current improved `ClucHAnix_5m` configuration until its holdout expectancy improves.
3. Keep `BigZ08` in observation only until it produces a meaningful trade sample.
4. Keep `BigZ06AtrSl`, `BigZ07Next2`, and `BigZ06Original` disabled because their holdouts lose 19% to 96% with drawdowns above 50%.

The full post-fix exports are the timestamped `postfix-common-*.zip` and
`postfix-holdout-*.zip` files in `user_data/backtest_results`.
The improvement exports are `improved-common-*.zip` and `improved-holdout-*.zip`.

Exchange, Telegram, and API credentials were previously exposed in the existing
`user_data/config_*.json` files (and repo-root `config_*.json`). They have been
scrubbed and replaced with placeholders; **rotate the originals on the exchange /
Telegram side before any live use.**

## 2026-08-23 Reorganization Notes

- `user_data/strategies/` was reorganized into family subfolders (`bigz/`,
  `cluc/`, `dip/`, `demo/`, `gkd/`, `ml/`, `pattern/`, `regime/`, `trend/`);
  `components/` is unchanged. Strategy hyperopt exports and `regime_map_academic.json`
  moved next to their strategies.
- All runnable configs now set `"recursive_strategy_search": true` (required by
  the strategy resolver to scan subfolders). Runs pass strategy names via
  `-s`/`--strategy-list` as before.
- The duplicate strategy dirs (`strategies/Bad/`, `strategies_backup/`,
  `strategies_orig_updater/`) were consolidated into `user_data/strategies_legacy/`
  (`bad/`, `backup/`, `orig_updater/`, `nfi_configs/`); byte-identical duplicates
  of active files were dropped. `BigZ06`, `NostalgiaForInfinityX*`, `NWEv6_new`,
  `turbov8`, etc. live there now.
- `strategies/commands.txt` was pruned of stale strategy references; missing
  DelistingFilter `state_file` stubs were created.
- `SuperKeltnerStratey.py` was renamed to `SuperKeltnerStrategy.py` (class name
  unchanged).

## 2026-08-24 BigZ Family Consolidation (Phase 2)

- `user_data/strategies/bigz/_bigz_shared.py` now holds the BigZ06 family's
  shared logic exactly once: the 14-condition entry block, the 5m/1h talib
  indicator setup, `populate_indicators`, the simple BB-mid exit, `leverage`,
  the `buy_params` defaults and the 31 shared buy hyperopt params
  (`BigZSharedBase`).
- `BigZ06AtrSl`, `BigZ06Original`, `BigZ07Next2`, `BigZ08` are now thin
  subclasses defining only ROI/stoploss/trailing, signal columns, their own
  exits (`custom_exit`/exit-signal overrides) and risk managers
  (`custom_stoploss`), plus their unique hyperopt params (Next2's sell ladder,
  B08's high/low + protection params).
- Signal parity was verified against the pre-refactor originals on 206k real
  5m candles: `buy`/`sell`/`enter_long`/`exit_long` columns are byte-identical
  for all four strategies.
- Behavioral notes:
  - The v2 pair writes the legacy `sell` signal with value `0` (a no-op exit)
    while the v3 pair writes `1`; this is preserved via the
    `exit_signal_col`/`exit_signal_value` attributes.
  - `BigZ06Original` now computes an extra, unused `atr` column (superset of the
    shared indicator setup); signals are unaffected.
  - `BigZ07Next2` and `BigZ08` buy params now inherit `optimize=True` (previously
    `optimize=False`). This only affects the hyperopt buy space; backtest/trading
    behavior and defaults (via each `buy_params` dict) are unchanged.
  - `BigZ08.leverage` now returns `5.0` instead of `5` (identical value).

## 2026-08-24 Framework Unification (Phase 3) — progress

- Fixed the shadowed `PercentStopManager` in `components/risk.py`: the Pine
  percentual variant is now `PinePercentStopManager`, restoring the generic
  (ratio-based) `PercentStopManager` as the public class.
- Aligned `components.TimeCutStopManager` with strategy_lib "Time Cut"
  semantics: `minutes <= 0` disables the cut, and the arming boundary uses
  `>=` to match the bar-count arming exactly.
- Migrated `MfiEmaWaveTrend` from `strategy_lib.risk` to the components
  `RiskMixin` + `TimeCutStopManager` (dynamic `stop_managers` property driven
  by the `is_timed_exit` hyperopt toggle). `custom_stoploss` parity was
  verified against the old strategy_lib path on real 5m data (long trades,
  timed + untimed, byte-identical ratios).
- **Design note for the remaining migrations:** strategy_lib's "Time Cut"
  mode arms *short* stops when `close < entry` (a bug — the `losing` flag is
  computed with the long condition for both sides). The components
  `TimeCutStopManager` arms shorts when the trade is in the red instead.
  `MfiEmaWaveTrend` is long-only, so this is moot there, but it **changes
  short behavior** for any shorting consumer (e.g. `NadarayaWatson`). Deciding
  whether to preserve such strategy_lib quirks or adopt clean component
  semantics must be settled before migrating the remaining 10 consumers.
