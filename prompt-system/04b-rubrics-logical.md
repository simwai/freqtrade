# 04b-rubrics-logical

Detailed rubrics for L1-L10 (Logical Correctness Tier). Loaded when CHECKLIST file inventory contains trading/strategy/backtest/risk/signal modules. Mark L1-L10 as in-scope (`[ ]`) or out-of-scope (`[x] skip`) at checklist time.

## L1 — Mathematical/Financial Invariants

**Violation:** Code violates a mathematical or financial invariant that must always hold.

| Invariant | Violation Pattern |
|---|---|
| `risk == 0 → reward:risk == ∞` (not a finite pass) | `risk.eq(0)` combined with `risk.lt(max_mae)` lets zero-risk bars pass RR guard |
| `position_size * entry_price ≤ account_equity` | No check before order submission |
| `stop_loss < entry_price` (long) / `stop_loss > entry_price` (short) | Stop on wrong side of entry |
| `max_drawdown ≤ risk_limit` | Portfolio risk not enforced |
| `sum(weights) == 1.0` for portfolio allocation | Drifting weights unchecked |

**Detection:** Static pattern match + runtime property test on sampled data.

**Example (RR bug):**

```python
# labeling.py:35
label = ret.gt(min_ret) & risk.lt(max_mae) & (rr.gt(min_reward_risk) | risk.eq(0))
#                    ↑ risk.eq(0) makes RR infinite → always passes guard
#                    ↑ but risk.lt(max_mae) also true for risk=0 → double-counts
```

---

## L2 — Boundary Condition Handling

**Violation:** Missing or incorrect handling of zero, negative, NaN, inf, or empty inputs at domain boundaries.

| Boundary | Check |
|---|---|
| `risk == 0` (zero adverse excursion) | Explicit branch: infinite RR, not "passes finite threshold" |
| `ret == NaN` / `ret == inf` | Drop or flag, don't propagate |
| `volume == 0` | No division by volume |
| Empty DataFrame/Series | Return empty with correct dtype, not error |
| Timestamp gaps / non-monotonic index | Resample or reject |

---

## L3 — State Machine / Protocol Validity

**Violation:** Invalid state transitions in order lifecycle, position management, or strategy states.

| Valid Transitions | Invalid (L3) |
|---|---|
| `FLAT → LONG → FLAT` | `FLAT → SHORT` (no position flip) |
| `ORDER_PENDING → ORDER_FILLED` | `ORDER_FILLED → ORDER_PENDING` |
| `POSITION_OPEN → POSITION_CLOSED` | `POSITION_CLOSED → POSITION_OPEN` (same position) |

---

## L4 — Time-Series Integrity

**Violation:** Look-ahead bias, survivorship bias, or temporal leakage.

| Check | Violation |
|---|---|
| No future data in features | `shift(-1)` used in training features |
| Correct `shift(1)` for labels | Label uses `close[t+1]` but feature uses `close[t]` |
| No peeking at future bars | Rolling window includes current bar in "past" |
| Bar alignment (open/high/low/close) | Label computed on next bar's open but feature on this bar's close |

---

## L5 — Position / Portfolio Arithmetic

**Violation:** Arithmetic that doesn't conserve value or violates accounting identity.

| Identity | Violation |
|---|---|
| `PnL = (exit - entry) * size * direction` | PnL calc ignores direction or fees |
| `equity = cash + Σ(position_value)` | Equity drift from untracked fees/slippage |
| `margin_used ≤ margin_available` | Over-leverage not caught |

---

## L6 — Statistical Validity

**Violation:** Statistical method applied incorrectly or assumption violated.

| Invariant | Violation Pattern |
|---|---|
| **Stationarity** for parametric tests | ADF/KPSS not checked; rolling mean/trend in residuals ignored |
| **IID assumption** for standard errors | Autocorrelated returns → underestimated SE → false significance |
| **Multiple testing correction** | 20+ signals tested, no Bonferroni/BH/FDR → inflated Type I error |
| **p-hacking guards** | "Try until significant" loop; no pre-registration; optional stopping |
| **Sample size / power** | Backtest on < 100 trades → Sharpe confidence interval spans zero |
| **Out-of-sample validation** | Walk-forward not used; single train/test split → overfit |

**Detection:** Static pattern (missing `adfuller`, `acf`, `multipletests`) + property test on synthetic data.

---

## L7 — Backtesting Integrity

**Violation:** Backtest result not reproducible or inflated by leakage.

| Check | Violation |
|---|---|
| **No look-ahead** | Feature at `t` uses `close[t+1]` or `shift(-1)` |
| **Survivorship bias** | Universe = current S&P 500 constituents only |
| **Transaction costs** | Zero fees/slippage; or fixed bps not scaled by volatility/volume |
| **Execution realism** | Market orders fill at `open`/`close`; no partial fills; no latency |
| **Position limits** | Unlimited leverage; no margin; no max position / sector caps |
| **Rolling rebalance** | Rebalance uses future weights; no `shift(1)` on signal |
| **Path dependence** | Vectorized backtest ignores intra-bar path (e.g., stop hit before target) |

---

## L8 — Risk / Position Sizing Logic

**Violation:** Sizing or risk math doesn't conserve capital or violates Kelly/optimal-f.

| Invariant | Violation |
|---|---|
| `position_size ≤ max_risk_per_trade * equity / (entry - stop)` | Fixed dollar size ignores stop distance → risk varies wildly |
| `portfolio_risk = Σ(position_risk) ≤ portfolio_risk_limit` | Sum of individual risks > portfolio limit (no correlation adjustment) |
| **Kelly fraction** `f* = (p*win - q*loss) / win` | `f* > 1` or negative not clamped; overbet/underbet not flagged |
| **Max drawdown control** | No drawdown-based position scaling (e.g., halve size at 50% DD) |
| **Correlation-aware sizing** | `Σ w_i * w_j * ρ_ij` ignored → concentrated risk |

---

## L9 — Performance Metric Correctness

**Violation:** Metric computed wrong or interpreted incorrectly.

| Metric | Common Bug |
|---|---|
| **Sharpe** | `mean(daily_ret) / std(daily_ret) * √252` — but `std` uses `ddof=0` (population) not `ddof=1` (sample) |
| **Sortino** | Downside deviation uses `min(ret, 0)` not `min(ret - MAR, 0)` |
| **Calmar** | `max_drawdown` computed on equity curve with `expanding().max()` but reset not handled |
| **Win rate** | `winning_trades / total_trades` — but breakeven trades counted as losers |
| **Profit factor** | `Σ wins / Σ losses` — but `losses = 0` → `inf` not handled |
| **Annualized return** | `(1 + total_ret)^(252/n) - 1` but `n` = trading days not calendar days |

---

## L10 — Strategy Logic / State Machine

**Violation:** Strategy enters invalid state or generates contradictory signals.

| Check | Violation |
|---|---|
| **Signal mutual exclusion** | `long_signal & short_signal` both true at same bar |
| **Position flip guard** | `FLAT → LONG → SHORT` same bar (no flat in between) |
| **Pyramiding limit** | `current_units < max_units` not checked before add |
| **Stop/target OCO** | Stop and target both active; fill of one doesn't cancel other |
| **Time-based exit** | `bars_held > max_hold` not enforced |
| **Regime filter** | `volatility_regime == high` but position size not reduced |

---

## Usage (Logical Tier)

- Apply all L1-L10 to every chunk when trading/statistical files are in scope, unless explicitly excluded in the checklist.
- Flag all applicable L-items in the REVIEW phase. L-items are hard-tier: a confirmed violation blocks PLAN until accepted or excluded with justification in the REVIEW decision section.
- L-items appear in REVIEW findings as `L1`, `L2`, etc. with the same format as H/S items.
- Mitigations block uses the standard 2-3 option format with recommended option first as `**A. option**`.
