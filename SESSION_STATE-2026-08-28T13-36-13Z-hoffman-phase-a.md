# SESSION STATE
<!-- Auto-written by active persona. Do not edit manually. -->

## Meta
session_id: 2026-08-28T13-36-13Z-hoffman-phase-a
active_persona: BabaDev
current_phase: CLOSED
prior_phase: PATCH
planning_mode: NONE
execution_mode: DIRECT
mode_reason: phase A-G diagnostic + hyperopt walk-forward + multi-TF multi-pair OOS basket
mode_override: none
session_start: 2026-08-28T13:25:00Z(approx)
last_updated: 2026-09-01T01:35:00Z
session_end: 2026-09-01T01:35:00Z (closed by user request)

## Target
repo: M:\Documents\Programming\Python\freqtrade
scope: Hoffman IRB winner/loser feature diagnostic (Phase A) + vol-regime filter (Phase B) + trade-level diagnostics (Phase C-1) + attempted lockout (Phase C-2, abandoned) + Ehlers Super PassBand Filter (Phase C-3)
language: Python (3.11)

## Current Task
target: scripts/hoffman_feature_profile.py + base strategy + variants + 2x2 backtest matrix + hyperopt walk-forward
size: L
definition_of_done:
- [x] Phase A: diagnostic script, 1383/1644 trade reproduction
- [x] Phase B: vol_regime_pctile_min attribute, state-machine gate, 5 new tests, 5mFeeVolRegime variant, 2x2 backtest matrix (vol-regime: -89% -> -33% on 2024-H1)
- [x] Phase C-1: same-candle impact + consecutive-loss clustering + lockout simulation in profiler
- [x] Phase C-1: same-candle guard removed (weak, ~7pp, check would need fill bar not setup bar)
- [x] Phase C-2: lockout attributes + helpers added (state tracking correct in isolation), enforcement abandoned (freqtrade backtest architecture incompatible)
- [x] Phase C-3: Ehlers Super PassBand Filter (SPBF) attribute set + indicator + state-machine gate + 7 new tests + 5mFeeVRSPBF variant + 2x2 backtest matrix
- [x] Phase C-4: dual-convergence gate tried (diagnostic + backtest negative), removed; Chaikin Volatility gate (5/34, >0) added, then removed (redundant with SPBF)
- [x] Phase C-5: EMA pullback confirmation (user idea) — attributes + helper + 7 tests + VRPB / VRSPBFPB variants + 4-cell matrix
- [x] 48/48 tests pass; ruff clean on all touched files

## Findings

### Phase A diagnostic
- 1 of 10 features clears discovery+validation bars: atr_pct_pctile_500 (vol-regime, >=0.872)
- htf_ema_slope degenerate (per-5m diff of ffill'd HTF EMA ≈ 0)

### Phase B matrix (vol-regime)

| variant                | period   | n   | winrate | PnL %  | profit_factor | max DD % |
|------------------------|----------|-----|---------|--------|---------------|----------|
| unfiltered base 5m     | 2023     |1450 | 22.8%   | -89.9% | 0.32          | 89.9%    |
| 5mFee (fee guard)      | 2023     |1383 | 27.3%   | -89.9% | 0.40          | 89.9%    |
| 5mFee + vol-regime     | 2023     |1465 | 29.9%   | -89.9% | 0.49          | 89.9%    |
| unfiltered base 5m     | 2024-H1  |1714 | 28.9%   | -89.9% | 0.36          | 89.9%    |
| 5mFee (fee guard)      | 2024-H1  |1644 | 32.7%   | -88.9% | 0.44          | 89.0%    |
| 5mFee + vol-regime     | 2024-H1  | 352 | 34.4%   | -33.1% | 0.58          | 33.2%    |

### Phase C-1 trade-level diagnostics
- Same-candle stopout guard: weak (10% of trades, 9.9% of losses, ~7pp PnL); not built
- Consecutive-loss clustering: mean reversion after streaks (35.1% winrate on 2024-H1 longs after 3 losses vs 30.3% baseline). Lockout simulator said +40% PnL improvement but couldn't be built (see C-2)
- Lockout state tracking helpers kept for future live use; enforcement abandoned

### Phase C-5: Chaikin removed + EMA pullback confirmation (new, user idea)

**Chaikin Volatility gate removed** (attributes, indicator, helper, tests, profiler section,
ChV variants deleted) — it was redundant with SPBF (OOS per-trade decay -0.000875 vs -0.000883).

**EMA pullback confirmation** (user idea): the IRB setup candle must touch the base EMA —
longs `l1 <= ema + tol*atr`, shorts `h1 >= ema - tol*atr` (combined with the existing
``c1 > ema`` trend requirement this selects "pullback to EMA and rejection" continuations).
Attributes: ``pullback_ema_touch`` (bool, off) + ``pullback_ema_atr_tol`` (float, 0).
Diagnostic: winrate +2.1pp / +2.2pp touched-vs-no-touch on both periods; avg_pnl flips
(worse 2023, 21% better OOS); touch rate 12-17%.

Backtest matrix (per-trade decay):

| variant     | period  | n    | win    | PnL     | PF   | decay      |
|-------------|---------|------|--------|---------|------|------------|
| VR          | 2023    | 1465 | 29.9%  | -89.9%  | 0.49 | -0.001567  |
| VR+SPBF     | 2023    | 1155 | 29.9%  | -83.5%  | 0.52 | -0.001559  |
| VR+PB       | 2023    | 120  | 36.7%  | -12.3%  | 0.60 | -0.001091  |
| VR          | 2024-H1 | 352  | 34.4%  | -33.1%  | 0.58 | -0.001141  |
| VR+SPBF     | 2024-H1 | 205  | 37.6%  | -16.6%  | 0.66 | -0.000883  |
| VR+PB       | 2024-H1 |  54  | 33.3%  |  -6.4%  | 0.53 | -0.001225  |
| VR+SPBF+PB  | 2023    |  44  | 25.0%  |  -8.9%  | 0.32 | -0.002116  |
| VR+SPBF+PB  | 2024-H1 |  10  | 30.0%  |  -1.5%  | 0.42 | -0.001473  |

Reading:
- VR+PB is the FIRST filter with real per-trade edge IN-SAMPLE: 2023 decay 30% better than VR
  (-0.001091 vs -0.001567), winrate 36.7% (closest yet to the 40% break-even)
- VR+PB OOS: best absolute PnL so far (-6.4%) but n=54 is small and decay -0.001225 is slightly
  worse than VR's -0.001141 — OOS the PnL gain is partly activity reduction
- VR+SPBF+PB is over-filtered (SPBF high-vol regime and EMA pullback are anti-correlated:
  pullbacks happen in quieter conditions); samples die (44/10 trades), decay collapses
- Open follow-ups: PB with ATR tolerance (0.25/0.5) to raise the 12-17% touch rate; PB as the
  primary filter instead of SPBF

### Phase C-6: pullback sweep (tolerance + vol-regime relaxation + control)

| variant        | period  | n    | win    | PnL     | PF   | decay      |
|----------------|---------|------|--------|---------|------|------------|
| VR (baseline)  | 2023    | 1465 | 29.9%  | -89.9%  | 0.49 | -0.001567  |
| VR+PB tol 0    | 2023    | 120  | 36.7%  | -12.3%  | 0.60 | -0.001091  |
| VR+PB tol 0.25 | 2023    | 294  | 32.7%  | -31.9%  | 0.50 | -0.001305  |
| VR+PB tol 0.5  | 2023    | 507  | 32.2%  | -48.7%  | 0.50 | -0.001316  |
| VR50+PB tol 0  | 2023    | 451  | 33.0%  | -45.3%  | 0.49 | -0.001339  |
| 5mFee+PB tol 0 | 2023    | 835  | 31.3%  | -70.8%  | 0.41 | -0.001475  |
| VR (baseline)  | 2024-H1 | 352  | 34.4%  | -33.1%  | 0.58 | -0.001141  |
| VR+PB tol 0    | 2024-H1 | 54   | 33.3%  | -6.4%   | 0.53 | -0.001225  |
| VR+PB tol 0.25 | 2024-H1 | 100  | 33.0%  | -11.2%  | 0.54 | -0.001183  |
| VR+PB tol 0.5  | 2024-H1 | 142  | 35.9%  | -11.6%  | 0.66 | -0.000867  |
| VR50+PB tol 0  | 2024-H1 | 177  | 35.6%  | -17.5%  | 0.54 | -0.001086  |
| 5mFee+PB tol 0 | 2024-H1 | 322  | 33.9%  | -32.4%  | 0.47 | -0.001217  |

Reading:
- DOSE-RESPONSE in-sample: loosening the tolerance degrades 2023 per-trade decay monotonically
  (-0.001091 -> -0.001305 -> -0.001316 vs baseline -0.001567). The exact touch carries the edge;
  a random filter would not degrade monotonically with strictness. This is the strongest
  evidence yet that the pullback signal is real.
- Control (5mFee+PB, no VR): decay improves 11%/9% over the 5mFee baseline on both periods —
  the pullback gate adds edge independent of the vol-regime filter.
- Relaxing vol-regime to 0.5 hurts 2023 decay (-0.001339 vs -0.001091) but has the second-best
  OOS decay (-0.001086). Mixed; strict VR remains preferable in-sample.
- OOS: tol 0.5 posts the best OOS decay of ANY config (-0.000867, edging VR+SPBF's -0.000883)
  but OOS samples are small (54-142) and in-sample vs OOS prefer different tolerances —
  tolerance is a curve-fit risk; keep tol 0 (no tuned parameter) as the default.
- Variants kept: HoffmanIRBStrategy5mFeeVRPB25 / VRPB50 / VR50PB / 5mFeePB (all untracked).

### Phase C-7: BTC regime gate (rejected) + touch depth -> negative tolerance sweep

**BTC market-regime gate (BTC close vs EMA(20)): REJECTED — inverted signal.** Longs in
BTC-bear outperform longs in BTC-bull on BOTH periods (win 34.6%/35.7% vs 27.8%/32.3%;
avg_pnl 6x better in-sample). Short-in-bull OOS is n=11, meaningless. Trading the inversion
would be overfit bait on n=78. Not built.

**Touch depth (within touched subset): CONFIRMED both periods.** Deep pierces beat shallow:
win 34.1% vs 24.1% (2023), 35.9% vs 33.1% (OOS). The existing ``pullback_ema_atr_tol``
attribute encodes depth via NEGATIVE tolerance (``l1 <= ema - 0.1*atr`` = require a pierce).

**Negative-tolerance sweep (dose-response extension):**

| variant        | period  | n   | win    | PnL    | PF   | decay      |
|----------------|---------|-----|--------|--------|------|------------|
| VR+PB tol -0.1 | 2023    | 65  | 43.1%  | -3.9%  | 0.79 | -0.000608  |
| VR+PB tol -0.1 | 2024-H1 | 36  | 30.6%  | -5.2%  | 0.47 | -0.001476  |
| VR+PB tol -0.15| 2023    | 45  | 37.8%  | -3.8%  | 0.73 | -0.000861  |
| VR+PB tol -0.15| 2024-H1 | 25  | 32.0%  | -4.0%  | 0.46 | -0.001635  |

Full 2023 tolerance dose-response: +0.5 -> -0.001316, +0.25 -> -0.001305, 0 -> -0.001091,
-0.1 -> -0.000608 (winrate 43.1%, FIRST config above the 40% break-even), -0.15 -> -0.000861.
In-sample optimum: tol -0.1. OOS optimum: tol +0.5 (-0.000867). IS and OOS prefer different
tolerances = classic curve-fit signature on the parameter. The PB FAMILY is validated (every
PB cell massively beats its baseline on absolute PnL); the tolerance value is NOT resolvable
with this data. Ship tol 0 (parameter-free) or leave tolerance to walk-forward hyperopt.
Variants kept: HoffmanIRBStrategy5mFeeVRPBN10 / VRPBN15 (untracked).

### Phase D: TRUE out-of-sample validation on XRP (2024-07 -> 2026-08)

XRP/USDT:USDT 5m+15m+funding data runs to 2026-08-27 locally — no filter decision in this
session ever touched that window. Ran the PB family on XRP alone (config
``user_data/config_hoffman_irb_xrp.json``), timerange 20240701-20260828 (~2 years):

| variant          | n    | win    | PnL     | PF   | decay      |
|------------------|------|--------|---------|------|------------|
| VR (control)     | 1296 | 30.2%  | -89.9%  | 0.55 | -0.001769  |
| VR+PB tol 0      | 170  | 36.5%  | -16.8%  | 0.64 | -0.001084  |
| VR+PB tol -0.1   | 107  | 37.4%  | -9.8%   | 0.67 | -0.000965  |
| VR+PB tol +0.5   | 587  | 33.4%  | -55.3%  | 0.55 | -0.001372  |

Verdict:
1. PB edge HOLDS on fresh data: tol 0 decay 39% better than control, tol -0.1 45% better;
   winrate +6-7pp. Three independent datasets (2023, 2024-H1, XRP 2y) now agree.
2. Tolerance question RESOLVED: in-sample optimum (-0.1) is ALSO the fresh-data optimum
   (-0.000965 best of all cells). The earlier IS/OOS disagreement was the 5.5-month window
   being underpowered. Dose-response ordering (+0.5 worst, 0 middle, -0.1 best) replicates.
3. Best config: **VR + pullback(tol -0.1)** = -9.8% over 2 years vs -89.9% control.
4. Still not profitable: OOS winrate 37.4% < 40% break-even, PF 0.67. Remaining gap is the
   1.5R geometry (break-even rr at 37.4% winrate = 1.67 > 1.5 cap).
Caveats: single pair, n=107, specific market regime. Ship candidate:
``HoffmanIRBStrategy5mFeeVRPBN10`` (fee + vol-regime 0.872 + pullback tol -0.1).

### Phase C-4: dual-convergence (tried, removed) + Chaikin Volatility (removed)

**SMMA EMA dual-convergence gate** (`ma_convergence` component, 15/25/5): diagnostic was
consistently NEGATIVE (allowed subset winrate 26.7% vs blocked 29.5% on 2023; 32.1% vs 33.8%
OOS — the gate keeps the worse trades). Backtest confirmed: VR+DC 2023 decay -0.001633 vs
VR's -0.001567 (per-trade quality got WORSE); OOS decay -0.001118 vs -0.001141 (neutral).
Removed from base strategy, variants deleted. The negative diagnostic was accurate.

**Chaikin Volatility gate** (user spec: length=5, roc=34; > 0 allows trades, direction-agnostic;
uses the repo component `chaikin_volatility`, shift(1) confirmed-bar): diagnostic quality-neutral
in 2023 (27.3% vs 27.2%), positive OOS (33.5% vs 31.7%). Backtest matrix (per-trade decay):

| variant          | period  | n    | win    | PnL     | PF   | decay      |
|------------------|---------|------|--------|---------|------|------------|
| VR               | 2023    | 1465 | 29.9%  | -89.9%  | 0.49 | -0.001567  |
| VR+SPBF          | 2023    | 1155 | 29.9%  | -83.5%  | 0.52 | -0.001559  |
| VR+ChV           | 2023    | 1267 | 30.5%  | -86.7%  | 0.49 | -0.001591  |
| VR+SPBF+ChV      | 2023    | 1047 | 29.8%  | -81.8%  | 0.50 | -0.001625  |
| VR               | 2024-H1 | 352  | 34.4%  | -33.1%  | 0.58 | -0.001141  |
| VR+SPBF          | 2024-H1 | 205  | 37.6%  | -16.6%  | 0.66 | -0.000883  |
| VR+ChV           | 2024-H1 | 260  | 35.4%  | -22.8%  | 0.64 | -0.000993  |
| VR+SPBF+ChV      | 2024-H1 | 187  | 36.9%  | -15.1%  | 0.67 | -0.000875  |

Reading:
- ChV on top of VR alone: real OOS per-trade edge (-0.001141 -> -0.000993, 13% better)
- ChV on top of VR+SPBF: per-trade decay a wash (-0.000883 -> -0.000875) — SPBF already
  captures that edge; ChV is largely redundant with SPBF (both are volatility-regime gates)
- Best OOS per-trade decay: VR+SPBF (-0.000883); best absolute OOS PnL: VR+SPBF+ChV (-15.1%)
- In 2023 every combo still bleeds ~-0.0016/trade: geometry + fees ceiling stands

### Phase C-3 SPBF

**Diagnostic (5mFee trades bucketed by SPBF band-crossing at the setup bar):**
- Discovery (2023, n=1383): agree n=609 (44%, winrate 25.0%, avg_pnl -0.00200), silent n=760 (55%, winrate 29.1%, avg_pnl -0.00163), oppose n=14 (1%)
- Validation (2024-H1, n=1644): agree n=593 (36%, winrate 33.9%, avg_pnl -0.00121), silent n=990 (60%, winrate 31.8%, avg_pnl -0.00146), oppose n=61 (3.7%)
- Standalone diagnostic is mixed: agree has lower winrate on 2023 but better avg_pnl on 2024-H1

**Backtest matrix (5mFeeVRSPBF = fee + vol-regime + SPBF):**

| variant            | period   | n   | winrate | PnL %  | profit_factor | max DD % |
|--------------------|----------|-----|---------|--------|---------------|----------|
| 5mFee + vol-regime | 2023     |1465 | 29.9%   | -89.9% | 0.49          | 89.9%    |
| 5mFee + vol + SPBF | 2023     |1155 | 29.9%   | -83.5% | 0.52          | 83.9%    |
| 5mFee + vol-regime | 2024-H1  | 352 | 34.4%   | -33.1% | 0.58          | 33.2%    |
| 5mFee + vol + SPBF | 2024-H1  | 205 | 37.6%   | -16.6% | 0.66          | 16.6%    |

The SPBF filter looks like an improvement on top of vol-regime:
- 2023 PnL: -89.9% -> -83.5% (see CORRECTION below: activity reduction, not edge)
- 2024-H1 PnL: -33.1% -> -16.6% (halved), winrate 34.4% -> 37.6%, max DD 33.2% -> 16.6%
- Trade count drops 21% (2023) and 42% (2024-H1)

**CORRECTION (per-trade decay analysis, user challenged the identical winrate):**
The 2023 "improvement" is NOT edge — it is pure activity reduction. Per-trade geometric
decay (risk_pct sizing => PnL ~ exp(decay*n)):
- VR 2023:        n=1465, winrate 29.90%, decay -0.001567/trade
- VR+SPBF 2023:   n=1155, winrate 29.87%, decay -0.001559/trade  (identical)
- Removed subset 2023: 310 trades, 93 wins = 30.0% winrate = exactly population average
- VR 2024H1:      n=352,  winrate 34.38%, decay -0.001141/trade
- VR+SPBF 2024H1: n=205,  winrate 37.56%, decay -0.000883/trade  (22% better)
- Removed subset 2024H1: 147 trades, 44 wins = 29.9% vs 34.4% average (below-average => real edge)
Verdict: SPBF is quality-neutral in 2023 (removes an average subset; identical winrate is the
signature) and genuinely edge-positive OOS 2024-H1. Also visible: in 2023 ALL filter combos
(base/5mFee/VR/VR+SPBF) bleed at ~-0.0016/trade despite winrate going 22.8% -> 29.9% — the
1.5R-target/Hoffman-stop geometry (40% break-even winrate) absorbs winrate gains via payoff
degradation. The 2023 ceiling is geometry + fees, not signal quality; only a geometry change
can move it.

### Phase E: walk-forward hyperopt with custom dd-constrained loss

**Custom loss** `freqtrade/optimize/hyperopt_loss/hyperopt_loss_dd_constrained.py`:
``score = -total_profit + dd_penalty_weight * starting_balance * max(0, dd - dd_threshold)``.
Reads ``dd_threshold`` (default 0.05) and ``dd_penalty_weight`` (default 10) from config.

**Strategy fix:** ``strategy_lib`` package was deleted in commit 626f719e8 but stale
``__pycache__`` masked the import failure. The ``DirectionalLossStreakLock`` mixin was NOT
active in any of today's prior backtests. Inlined the lock as a module-level function
``_directional_loss_streak_locks(trade_obj)`` in ``HoffmanIRBStrategy.py`` with try/except
guards so tests and backtests without a DB work. Re-ran the static grid:
``VRPBN10_rr0_5`` 2023 = 27 trades, 59.3% win, -2.57%, 5.04% dd (matches earlier number; lock
was a no-op on this period — no 4-loss run on either side).

**Hyperopt variant** ``HoffmanIRBStrategy5mFeeVRPBN10Hyp``: hyperopt over
``rr`` (0.5-3.0) and ``pullback_ema_atr_tol`` (-0.3 to 0.5), everything else frozen.

**30-epoch run, 2023 BTC/ETH/SOL, dd_penalty_weight=80:** All 30 trials cluster in three
bands of identical trade counts (65) and very similar results. Best by loss (ep3..ep30,
loss=11380) is ``rr=0.7-2.6, tol=-0.3 to +0.39`` with -3.88% / 6.22% dd. The dd-constraint is
*structurally violated*: with this selectivity level (65 trades) the per-trade decay
(-0.0006) and trade count give a floor of ~6% cumulative dd.

**Walk-forward OOS validation** (best 2023 epoch, ``rr=1.6, tol=0.17``, on untouched XRP
2024-07 -> 2026-08): **309 trades, 34.3% win, -29.75% profit, 30.62% dd, PF 0.63**.
Massive overfit. The hyperopt's apparent Pareto improvement over the static grid is
entirely a 2023-window illusion.

**Final Pareto frontier (XRP 2024-07 -> 2026-08, untouched):**

| variant                          | trades | win    | PnL     | dd      | decay      |
|----------------------------------|--------|--------|---------|---------|------------|
| VR (control)                     | 1296   | 30.2%  | -89.9%  | 89.9%   | -0.001769  |
| VR+PB tol 0                      | 170    | 36.5%  | -16.8%  | 17.8%   | -0.001084  |
| VR+PB tol -0.1                   | 107    | 37.4%  |  -9.8%  | 10.2%   | -0.000965  |
| **VR+PB tol -0.1 + low-risk**     | **45** | **73.3%** | **-2.91%** | **4.96%** | **-0.000655** |
| hyperopt winner (rr=1.6, tol=0.17) | 309    | 34.3%  | -29.75% | 30.62%  | -0.001143  |

The best meeting ``max_drawdown <= 5%`` on untouched data is ``VR+PB tol -0.1 + low-risk``:
-2.91% PnL / 4.96% dd / 73.3% win / 0.67 PF / decay -0.000655. This is the static grid's
finding, not the hyperopt's.

Variants kept: ``HoffmanIRBStrategy5mFeeVRPBN10Hyp`` (hyperopt variant), ``HoffmanIRBStrategy5mFeeVRPBN10WF``
(frozen WF best), ``HoffmanIRBStrategy5mFeeVRPBN10_lowrisk`` (half-risk sizing, all untracked).

### Phase F: multi-pair basket OOS (2024-07 -> 2026-08)

User's challenge: the prior single-pair XRP result (n=45) is underpowered. 40 pairs have
BOTH 5m+15m data through 2026-08; the 12-pair basket of majors (XRP, LTC, ATOM, ALGO,
DOGE, DOT, CRV, ENJ, GRT, SAND, MANA, APE) provides 5m+HTF coverage for honest OOS.

**12-pair basket (``config_hoffman_irb_basket.json``): 1304 trades, 26.4% win, -86.87% PnL,
86.91% dd.** Outlier analysis: CRV alone produced 402 trades at 13.4% winrate / -49.9% PnL /
49.98% dd -- i.e. CRV accounts for 60% of all losses with the filter misfiring
catastrophically. Every other pair has winrate 26-41% but a per-trade decay of
-0.0003 to -0.0011.

**11-pair basket (excl CRV): 953 trades, 32.4% win, -64.64% PnL, 65.26% dd.** Each pair
shows a small negative avg_pnl (SAND -0.00109, APE -0.00026, XRP -0.00040, LTC -0.00051).
The filter is not working on any single pair -- each pair bleeds at roughly the same
-0.0006/trade rate the hyperopt and static-grid 2023 tests have consistently shown.

**Final verdict:** the single-pair XRP -2.91% / 73% win / 4.96% dd was a small-n outlier.
The multi-pair truth: with n=953 across 11 independent pairs, the filter does not beat
the unfiltered baseline. The 1.5R geometry (40% break-even winrate) plus 0.05% taker fee
still costs more than the pullback/vol-regime combination earns at 30-37% winrate. The
walk-forward experiment demonstrates this is not a curve-fit issue: 11 independent pairs,
n=953, consistent negative per-trade edge.

**Variants added:** ``HoffmanIRBStrategy5mFeeVolRegime_basket.py`` (unfiltered baseline, untracked).

### Phase G: higher-TF + BTC-regime (30m, 1h)

User's suggestion: 197 pairs have BOTH 5m+1h through 2026-08; 30m also widely
available.  New variants:
``HoffmanIRBStrategy30mVRPBN10_lowrisk`` and ``HoffmanIRBStrategy1hVRPBN10_lowrisk``
(same fee + VR + PB tol -0.1 + low-risk as 5m).  Configs:
``user_data/config_hoffman_irb_basket_1h.json`` (timeframe=1h) and
``user_data/config_hoffman_irb_basket_30m.json`` (timeframe=30m); reused the 11-pair
basket from Phase F (no CRV).

**30m basket OOS (2024-07 -> 2026-08): 127 trades, 29.1% win, -12.26% PnL, 12.26% dd.**
Lower absolute loss than 5m/1h, but smaller sample.  Per-trade PnL is *worse* at
30m than 5m (avg ~-0.97% vs ~-0.07%).  Most pairs show 1-15 trades; 30m is
too coarse to generate enough setups for statistical power.

**1h basket OOS (2024-07 -> 2026-08): 86 trades, 26.7% win, -7.58% PnL, 7.83% dd.**
Smallest absolute PnL loss.  3 of 11 pairs positive (LTC, MANA, GRT, each
n<10) but n too small for significance.  Real signal remains absent.

**1h BTC-regime diagnostic (n=86, true 1h backtest):**

| bucket         | n  | win    | decay     |
|----------------|----|--------|-----------|
| long BTC-bull  | 23 | 21.7%  | -0.00908  |
| **long BTC-bear** | **13** | **38.5%** | **+0.00555** |
| short BTC-bull | 15 | 26.7%  | -0.00180  |
| short BTC-bear | 35 | 25.7%  | -0.00999  |

Longs-in-BTC-bear is the only positive bucket.  n=13 still underpowered.
The 5m result (longs in BTC-bear > BTC-bull, n=78 single-pair) and the 1h result
are *directionally consistent* on longs (BTC-bear preferred either way) but
contradict on shorts.  This is a TF-dependent, low-n signal that does not survive
curve-fit discipline.

**Variants added:** ``HoffmanIRBStrategy30mVRPBN10_lowrisk.py``,
``HoffmanIRBStrategy1hVRPBN10_lowrisk.py``, configs ``basket_30m.json`` and
``basket_1h.json`` (all untracked).

**Final multi-TF verdict:** the strategy bleeds at every TF tested.  Across 5m, 30m,
1h and 11 pairs the filter is negative on every configuration.  The 1h direction
shows the smallest PnL loss AND has a single positive small-n bucket
(long-BTC-bear, n=13) -- but n is too small to be statistically significant.
The honest conclusion stands: the filter does not have an edge at this
geometry/fee combination.

## Phase Skips
- STRUCTURED phases: user pre-specified the plan; DIRECT execution

## Verification
diff_inspected: true
checks_run: [
  "python -m py_compile user_data/strategies/pattern/HoffmanIRBStrategy.py -> OK",
  "python -m py_compile freqtrade/optimize/hyperopt_loss/hyperopt_loss_dd_constrained.py -> OK",
  "ruff check (all touched files) -> All checks passed",
  "pytest tests/strategy/test_hoffman_irb_strategy.py -> 48 passed (7 SPBF + 5 vol-regime + 5 lockout + 7 pullback + 24 base)",
  "profiler end-to-end: discovery n=1383, validation n=1644, 0 alignment drops, SPBF + Chaikin + depth coverage included",
  "backtest matrix: 5mFeeVRSPBF 2023 = -83.5% PnL; 2024-H1 = -16.6% PnL",
  "hyperopt 30 epochs with dd-constrained loss -> best 2023 = -3.88% / 6.22% dd (penalty=80)",
  "walk-forward OOS on XRP 2024-07 -> 2026-08: hyperopt winner = -29.75% (overfit); static grid best = -2.91% / 4.96% dd"
]
results: PASS (with the note that hyperopt overfit to the 2023 window; static grid result is the honest ship candidate)

## Edited Files
- scripts/hoffman_feature_profile.py (Phase A + C-1 + C-7 diagnostics; SPBF + Chaikin + touch-depth coverage sections; DC coverage removed)
- user_data/strategies/pattern/HoffmanIRBStrategy.py (vol-regime guard, lockout helpers now inlined, SPBF guard, Chaikin Volatility guard, _setup_valid helper; DC gate removed; rr cap raised to 3.0; loss-streak lock inlined as module function)
- tests/strategy/test_hoffman_irb_strategy.py (7 SPBF + 5 vol-regime + 5 lockout + 7 pullback = 24 new tests; 48/48 pass)
- freqtrade/optimize/hyperopt_loss/hyperopt_loss_dd_constrained.py (NEW; custom Pareto loss: -profit + dd_penalty_weight * starting_balance * max(0, dd - dd_threshold))
- user_data/strategies/pattern/HoffmanIRBStrategy5mFee.py (unchanged; untracked under user_data/)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVolRegime.py (unchanged; untracked)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRSPBF.py (unchanged this phase; untracked)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRPB.py (NEW; untracked; fee + vol-regime + pullback touch)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRSPBFPB.py (NEW; untracked; fee + vol-regime + SPBF + pullback)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRDC.py, HoffmanIRBStrategy5mFeeVRSPBFDC.py, HoffmanIRBStrategy5mFeeVRChV.py, HoffmanIRBStrategy5mFeeVRSPBFChV.py (CREATED then DELETED; untracked)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRPBN10Hyp.py (NEW; untracked; hyperoptable rr + tol)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRPBN10WF.py (NEW; untracked; frozen WF best, rr=1.6 tol=0.17)
- user_data/strategies/pattern/HoffmanIRBStrategy5mFeeVRPBN10_lowrisk.py (NEW; untracked; risk=0.5% sizing)
- user_data/config_hoffman_irb.json (added dd_threshold=0.05, dd_penalty_weight=80.0)
- user_data/backtest_results/*.zip (multiple new zips; all untracked under user_data/)

## Commit/Push Gate
decision: pending user answer
stageable (TRACKED, ready to commit):
  - scripts/hoffman_feature_profile.py
  - user_data/strategies/pattern/HoffmanIRBStrategy.py
  - tests/strategy/test_hoffman_irb_strategy.py
  - freqtrade/optimize/hyperopt_loss/hyperopt_loss_dd_constrained.py
untracked/ignored (not stageable):
  - user_data/strategies/pattern/HoffmanIRBStrategy5mFee*.py
  - user_data/backtest_results/*2026-08-2*.zip
  - user_data/config_hoffman_irb.json (under user_data/, gitignored)

Note: 4 stageable files this leg (was 3). The new entry is the custom loss
class in freqtrade/optimize/hyperopt_loss/. The base-strategy diff includes
inlining the loss-streak lock (a behavior change to the base strategy).

## Final Session Summary (Phases A-G)

**Final multi-TF OOS verdict (all on untouched 2024-07 -> 2026-08 data,
11-pair basket, n ranges 86-1304):**

| TF   | trades | win  | PnL     | dd      | per-pair decay        | edges?  |
|------|--------|------|---------|---------|------------------------|---------|
| 5m   | 953    | 32%  | -64.6%  | 65.3%   | -0.0005 to -0.0011     | 0/11    |
| 30m  | 127    | 29%  | -12.3%  | 12.3%   | lower n, low power     | 0/11    |
| 1h   |  86    | 27%  |  -7.6%  |  7.8%   | mixed; longs in BTC-bear positive (n=13) | 3/11 (n<10 each) |

**BTC regime at 1h (n=86):** longs in BTC-bear = +0.00555/decay, 38.5% win (n=13).
**BTC regime at 5m (n=78 single-pair earlier):** longs in BTC-bear > BTC-bull.
**Conflict:** 5m and 1h agree on longs, disagree on shorts. The 1h n=13 positive
bucket is TF-dependent and underpowered for shipping.

**Conclusion across all phases:** the strategy's pullback + vol-regime + fee
guard + size-halving combination cannot consistently beat the 1.5R geometry
break-even (40% winrate) at 0.05% taker fees on 5m/30m/1h. The hyperopt
walk-forward overfit to the 2023 in-sample window; multi-pair OOS on 2 years
of fresh data confirms the filter is negative on every TF and 11/11 pairs at 5m.

**Ship candidate: NONE.** Diagnostic conclusion stands: the Hoffman IRB edge does not
survive 5m futures fees at 1.5R target geometry, regardless of selectivity filters
tested (vol-regime, SPBF, Chaikin, dual-convergence, pullback-touch, BTC-regime)
or timeframe (5m, 30m, 1h). The best single signal (longs-in-BTC-bear at 1h, n=13)
is a tantalizing low-n result that curve-fit discipline says to not ship.

**Untracked file inventory in user_data/strategies/pattern/ (~50 files, all ruff-clean
at session close):**
VRPB family (tol 0, 0.25, 0.5, -0.1, -0.15), SPBF and SPBF+PB, dual-convergence (deleted),
Chaikin (deleted), RR sweep 0.5..3.0 for tol 0 and tol -0.1, N10 low-risk, 15mVRPB,
1hVRPB, 30mVRPB, VRPBN10Hyp, VRPBN10WF, 5mFeeVolRegime_basket.
