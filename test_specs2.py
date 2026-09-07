import sys
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\scripts')

# Force module load
import indicators_pandas_ta as mod
import inspect

# Manually build specs dict like the server does
_INDICATOR_COLUMNS = {
    "open": "open", "open_": "open", "high": "high", "low": "low",
    "close": "close", "series": "close", "volume": "volume",
}
_INDICATOR_PRICE_SCALE = {"ehlers_super_smoother"}
_INDICATOR_TITLES = {}

specs = {}
for name, fn in vars(mod).items():
    if name.startswith("_") or not inspect.isfunction(fn):
        continue
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        continue
    inputs = []
    params = []
    ok = True
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            ok = False
            break
        if p.default is p.empty:
            col = _INDICATOR_COLUMNS.get(p.name)
            if col is None:
                ok = False
                break
            inputs.append(col)
        else:
            ann_str = str(p.annotation) if p.annotation is not inspect.Parameter.empty else ""
            ann_str = ann_str.replace("typing.", "")
            default_val = p.default if isinstance(p.default, (int, float, bool, str)) else str(p.default)
            params.append({
                "name": p.name,
                "default": default_val,
                "type": ann_str,
            })
    if ok and inputs:
        specs[name] = {
            "title": _INDICATOR_TITLES.get(name, name.replace("_", " ").title()),
            "inputs": inputs,
            "scale": "price" if name in _INDICATOR_PRICE_SCALE else "own",
            "params": params,
        }

print('Total specs:', len(specs))
# Check a few
for name in ['wavetrend', 'vqzl_zscore', 'bbwp', 'cdl_engulfing', 'hurst_exponent']:
    spec = specs.get(name, {})
    print(f'{name}: inputs={spec.get("inputs")}, params_count={len(spec.get("params", []))}')
    for p in spec.get('params', []):
        print(f'  param: {p}')