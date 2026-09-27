# Indicator Causality Test Results

*Truncation test: remove last 100 bars, compare overlapping prefix*
*Data: 1000-bar random walk, seed=42*

*Main indicators tested: 61*
*Control test cases: 3 (1 parameterized test function)*
*Registry smoke test: 1*
*Total pytest test IDs collected: 63*

## Control Tests (Harness Validation)

*These control tests verify the test methodology itself. They are a single parameterized test function with 3 cases.*

**⚠️ Reading the controls:** In pytest output, these tests show `PASSED` when the harness **correctly detects bias** — i.e., when the known-biased indicator fails the causality check. Do not read control `PASSED` as "this indicator is causal." `CONTROL.dpo_centered PASSED` means the truncation test flagged the centered DPO as non-causal (the intended outcome).

- **CONTROL.dpo_centered**: ❌ FAIL (expected FAIL) ✓
- **CONTROL.shifted_close**: ❌ FAIL (expected FAIL) ✓
- **CONTROL.dpo_causal**: ✅ PASS (expected PASS) ✓

All 3 control cases behaved as expected, confirming the harness correctly 
detects future-referencing bias (centered DPO, shifted close) and passes 
causal indicators (causal DPO).

## TREND

- ta.ADX: ✅ PASS
- ta.AROON.down: ✅ PASS
- ta.AROON.up: ✅ PASS
- ta.AROONOSC: ✅ PASS
- ta.CCI: ✅ PASS
- ta.MINUS_DI: ✅ PASS
- ta.MINUS_DM: ✅ PASS
- ta.PLUS_DI: ✅ PASS
- ta.PLUS_DM: ✅ PASS
- ta.ROC: ✅ PASS
- ta.SAR: ✅ PASS
- ta.ULTOSC: ✅ PASS

## MOMENTUM

- ta.MACD.macd: ✅ PASS
- ta.MACD.macdhist: ✅ PASS
- ta.MACD.macdsignal: ✅ PASS
- ta.MFI: ✅ PASS
- ta.RSI: ✅ PASS
- ta.STOCH.slowd: ✅ PASS
- ta.STOCH.slowk: ✅ PASS
- ta.STOCHF.fastd: ✅ PASS
- ta.STOCHF.fastk: ✅ PASS
- ta.STOCHRSI.fastd: ✅ PASS
- ta.STOCHRSI.fastk: ✅ PASS

## MA

- ta.EMA.10: ✅ PASS
- ta.EMA.100: ✅ PASS
- ta.EMA.21: ✅ PASS
- ta.EMA.3: ✅ PASS
- ta.EMA.5: ✅ PASS
- ta.EMA.50: ✅ PASS
- ta.SMA.10: ✅ PASS
- ta.SMA.100: ✅ PASS
- ta.SMA.21: ✅ PASS
- ta.SMA.3: ✅ PASS
- ta.SMA.5: ✅ PASS
- ta.SMA.50: ✅ PASS
- ta.TEMA: ✅ PASS

## CYCLE

- ta.HT_SINE.leadsine: ✅ PASS
- ta.HT_SINE.sine: ✅ PASS

## CANDLESTICK

- ta.CDL3INSIDE: ✅ PASS
- ta.CDL3LINESTRIKE: ✅ PASS
- ta.CDL3OUTSIDE: ✅ PASS
- ta.CDL3WHITESOLDIERS: ✅ PASS
- ta.CDLDARKCLOUDCOVER: ✅ PASS
- ta.CDLDRAGONFLYDOJI: ✅ PASS
- ta.CDLENGULFING: ✅ PASS
- ta.CDLEVENINGDOJISTAR: ✅ PASS
- ta.CDLEVENINGSTAR: ✅ PASS
- ta.CDLGRAVESTONEDOJI: ✅ PASS
- ta.CDLHAMMER: ✅ PASS
- ta.CDLHANGINGMAN: ✅ PASS
- ta.CDLHARAMI: ✅ PASS
- ta.CDLINVERTEDHAMMER: ✅ PASS
- ta.CDLMORNINGSTAR: ✅ PASS
- ta.CDLPIERCING: ✅ PASS
- ta.CDLSHOOTINGSTAR: ✅ PASS
- ta.CDLSPINNINGTOP: ✅ PASS

## VOLATILITY

- qtpylib.bb.lower: ✅ PASS
- qtpylib.bb.mid: ✅ PASS
- qtpylib.bb.upper: ✅ PASS
- qtpylib.typical_price: ✅ PASS

## CROSSOVER

- qtpylib.crossed_above: ✅ PASS

---

## What This Test Proves

No indicator in freqtrade's main codebase reads future bars through 
the standard truncation criterion. The harness is validated against 
known-biased controls (centered DPO, shifted close), which it correctly flags.

## What This Test Does NOT Cover

1. **pandas_ta indicators** used in user strategies — the registry is extensible 
   but not yet populated.
2. **Repainting / intrabar dependency** — a causal indicator can still 
   repaint if it depends on the current bar's incomplete state.
3. **Shift-by-one bugs in user strategy code** — e.g., accidentally using 
   `close.shift(-1)` in a strategy.
4. **Timeframe-resampling interactions** — a causal 1h indicator can still 
   repaint on a 5m chart if resampling is naive (lookahead via 
   future 5m bars that complete the current 1h bar).
