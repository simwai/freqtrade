import sys

sys.path.insert(0, r"M:\Documents\Programming\Python\freqtrade\user_data\scripts")
sys.path.insert(0, r"M:\Documents\Programming\Python\freqtrade\user_data\strategies\components")

import indicators_pandas_ta as mod
import inspect

_INDICATOR_COLUMNS = {
    "open": "open",
    "open_": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "series": "close",
    "volume": "volume",
}

fn = getattr(mod, "vqzl_zscore")
sig = inspect.signature(fn)
inputs = []
for p in sig.parameters.values():
    if p.default is p.empty:
        col = _INDICATOR_COLUMNS.get(p.name)
        if col is None:
            continue
        inputs.append((p.name, col))

print(f"Inputs: {inputs}")

# Now try to call the function
import pandas as pd

df = pd.DataFrame(
    {
        "open": [100.0, 101.0, 102.0] * 10,
        "high": [101.0, 102.0, 103.0] * 10,
        "low": [99.0, 100.0, 101.0] * 10,
        "close": [100.5, 101.5, 102.5] * 10,
    }
)
kwargs = {pname: df[col] for pname, col in inputs}
print(f"Kwargs keys: {list(kwargs.keys())}")

result = fn(**kwargs)
print(f"Result type: {type(result)}")
print(f"Result length: {len(result)}")
