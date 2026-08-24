# Components

Reusable building blocks extracted from the strategies in this folder. The goal:
build a new strategy by composing indicators, signal filters and risk
managers instead of copy-pasting whole strategy files.

Every indicator is **vectorized** (numpy/pandas rolling/EWM). Only inherently
recursive indicators (supertrend, PSAR, Ehlers IT, SMMA/EMA convergence) use a
tight numpy loop, because their output depends on prior state by definition.

## Layout

| Module | Contents |
|---|---|
| `indicators.py` | Vectorized indicators (super/PSAR, WaveTrend, Nadaraya-Watson, VIX Fix, Keltner, MFI/CMF, chop, swing detection, pump filters, adaptive regime helpers, SMMA/EMA convergence, ...) |
| `signals.py` | Cross helpers, condition combiners, volume pump/dip filters, HTF regime helpers |
| `risk.py` | `RiskMixin` + stop-loss managers, exit managers, position sizers, leverage policies, partial take-profit |
| `strategy_base.py` | `ComponentStrategy` base class with freqtrade boilerplate and HTF merge helpers |

## Indicator quick reference

All functions take a OHLCV `DataFrame` (or a `Series`) and return Series /
DataFrames aligned to the input index.

| Function | Source strategy | Notes |
|---|---|---|
| `ema`, `sma`, `rma`, `smma`, `tema`, `zema`, `t3`, `jma` | template / BigZ / BingAi | `ema`/`rma` are SMA-seeded → match `talib.EMA`/`ta.rma` exactly |
| `ma_convergence(close)` | simwai Pine (SMMA EMA Dual MA) | returns `ma_fast`, `ma_slow`, `is_long_allowed`, `is_short_allowed`, ... exact state machine port |
| `atr`, `true_range`, `hann_atr` | Octopus / TrendOMatic | `atr` matches `talib.ATR`; `hann_atr` matches Octopus Hann-window ATR |
| `supertrend(df, period, mult)` | SupertrendKeltner / TrendOMatic | canonical TV final-band logic; returns `(line, direction)` with `+1`/`-1` |
| `supertrend_simple(df, factor, atr_period)` | StrategyTemplate / SuperKeltner | single-state variant |
| `sar(df)` | Octopus | classic PSAR (matches `_classic_psar`) |
| `bollinger(series, len, mult)` | all | `ddof=0`, returns `upper/mid/lower` |
| `keltner(df, ...)` | SuperKeltner / TrendOMatic | `base` ema/sma, `range_style` atr/hann_atr/hl |
| `wavetrend(df, chlen, avg, smalen)` | MfiEmaWaveTrend | LazyBear WT; returns extended df with `wt1`, `wt2`, `wt1-wt2` |
| `mfi`, `cmf`, `mfv` | MfiEmaWaveTrend / BigZ | vectorized (no talib dependency) |
| `fisher`, `fisher_rsi` | GkdAdaptive / ClucHAnix | |
| `williams_r` | adaptive | |
| `choppiness`, `volatility_ratio` | HybridRegimeSwitcher | |
| `ewma_zscore`, `rls_mean`, `rls_slope` | HybridRegimeSwitcher | RLS adaptive mean engine |
| `ppo`, `vwap_anchor`, `prior_lows_highs` | LuxAlgo / Hybrid | 1h regime building blocks |
| `vix_fix` | TrendOMatic / GkdAdaptive | WVF |
| `swing_detection` | GkdAdaptive / academic | fractal pivots + ffill |
| `kama_slope`, `smma_ema_convergence`, `vol_index`, `extreme_vol`, `volume_zscore`, `ehlers_it`, `nadaraya_watson` | GkdAdaptive family | adaptive/regime machinery |
| `range_percent_change`, `top_percent_change`, `range_maxgap`, `range_height`, `volume_mean`, `heikin_ashi` | BigZ / Nostalgia / Cluc | pump/gap protection + HA |

## Risk management

`components.risk.RiskMixin` composes stop-loss and exit managers, position
sizing and leverage. Mix it into your `IStrategy` subclass:

```python
from components.risk import (
    RiskMixin, ATRStopManager, HighLowLookbackStopManager, TimeCutStopManager,
    DurationExitManager, RiskBasedSizer, FixedLeverage,
)

class MyStrategy(RiskMixin, ComponentStrategy):
    stop_managers = [
        ATRStopManager(atr_length=14, mult=1.5, anchor="entry"),
        HighLowLookbackStopManager(lookback=20, multiplier=0.98),
        TimeCutStopManager(minutes=240, cut=0.01),
    ]
    exit_managers = [DurationExitManager(minutes=720)]
    position_sizer = RiskBasedSizer(risk_per_trade=0.005, stop_distance=0.10)
    leverage_policy = FixedLeverage(3.0)
```

The mixin then wires `custom_stoploss` (aggregates managers, picks the tightest
valid stop), `custom_exit`, `custom_stake_amount`, `leverage` and — if you add a
`PartialTPSpec` — `adjust_trade_position` for 3-level partial take profit.

Available managers:

| Component | What it does | Source |
|---|---|---|
| `ATRStopManager` | entry/candle-anchored `± mult*ATR` | MfiEmaWaveTrend2 / LuxAlgo |
| `ATRTrailingManager` | trailing `low - mult*ATR` / `high + mult*ATR` | LuxAlgo |
| `PercentStopManager` | fixed `%` from entry | generic |
| `EntryCandleHLStopManager` | entry-candle high/low ± buffer (cached on trade) | StrategyTemplate / SuperKeltner |
| `HighLowLookbackStopManager` | trailing low/high with multiplier + backup | BigZ08 / Octopus |
| `TimeCutStopManager` | cut losers after N minutes | CombinedBinHClucAndMADV3 |
| `ProfitTieredTrailingManager` | profit-tiered trailing stop (BB_RPB_TSL) | ClucHAnix |
| `SwingStopManager` | swing low/high ± ATR buffer with TP1/TP2 state | GkdAdaptive |
| `DurationExitManager` | exit after max duration | Octopus |
| `ProfitTargetExitManager` | simple `%` take profit | generic |
| `VolumeSpikeExitManager` | exit on volume spike at top of BB | BigZ06Original |
| `PercentEquitySizer` | stake % of equity | Octopus |
| `RiskBasedSizer` | risk `risk_per_trade` / `stop_distance` | ClucHAnix / CombinedBinH |
| `VolatilitySizer` | scale stake down when volatility is high | HybridRegimeSwitcher |
| `FixedLeverage`, `MaxLeveragePolicy` | leverage policies | BigZ / Cluc |
| `PartialTPSpec` | 3-level TP 50/25/25 (ATR or swing) | GkdAdaptive / academic |

## Signal helpers

```python
from components.signals import crossed_above, crossed_below, apply_conditions, volume_pump_drop_filter
```

- `crossed_above` / `crossed_below` / `crossed` — Pine `ta.crossover` equivalents.
- `apply_conditions(df, [(mask, tag), ...])` — set `enter_long` and per-condition
  `enter_tag` in one call (the BigZ / Nostalgia pattern without the boilerplate).
- `combine(conditions, mode="OR"|"AND")` — reduce a list of masks.
- `volume_pump_drop_filter(df, pump_mult, drop_mult, lookback)` — Nostalgia volume
  regime guard for dip-buying.
- `safe_pump`, `safe_dips` — post-pump entry protection.
- `htf_bull_bear(...)` — 1h PPO/VWAP regime (LuxAlgo / Hybrid pattern).
- `suppress_same_candle_exit(df)` — clear exits on candles that also enter.

## Building a strategy (worked example)

See `ExampleComponentStrategy.py` (WaveTrend + MFI mean reversion with ATR
stop + risk sizing) and `SuperKeltnerConvergenceStrategy.py` (SuperTrend +
Keltner + SMMA/EMA convergence filter + profit-tiered trailing + partial TP).

```python
from pandas import DataFrame

from components.indicators import atr, mfi, wavetrend
from components.risk import ATRStopManager, RiskMixin, RiskBasedSizer
from components.signals import crossed_above
from components.strategy_base import ComponentStrategy


class MyStrategy(RiskMixin, ComponentStrategy):
    timeframe = "5m"
    stop_managers = [ATRStopManager(atr_length=14, mult=1.5)]
    position_sizer = RiskBasedSizer(risk_per_trade=0.005, stop_distance=0.05)

    def populate_indicators(self, dataframe, metadata):
        dataframe = wavetrend(dataframe)
        dataframe["mfi"] = mfi(dataframe, 14)
        dataframe["atr"] = atr(dataframe, 14)
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = (
            (dataframe["mfi"] < 40)
            & crossed_above(dataframe["wt1"], dataframe["wt2"])
        ).astype(int)
        return dataframe
```

Drop the strategy into `user_data/strategies/`; freqtrade's resolver adds that
folder to `sys.path`, so `from components... import ...` works out of the box
(the `components/` subpackage is never scanned as a strategy itself).
